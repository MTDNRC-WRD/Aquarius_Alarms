"""
Gold Creek Irrigation Pump Alarm
================================
Checks recent discharge at the Gold Creek gage and emails the pump operators
when to shut pumps down (flow at or below ALARM_LOW) or turn them back on
(flow at or above ALARM_HIGH).

Rules
-----
- An alarm is sent only when it differs from the last alarm sent (low -> high
  or high -> low). Flow between the two thresholds changes nothing.
- If AQUARIUS returns an error, no data, or data older than
  MAX_DATA_AGE_MINUTES, one "broken" email is sent. The flag clears
  automatically when good data returns.
- Any unexpected crash emails the traceback to FAILURE_RECIPIENTS.

Credentials are read from creds.txt next to this script:
    AQUARIUS_USER=your_username
    AQUARIUS_PASSWORD=your_password

State is kept in alarm_state.json in DIRECTORY.
"""

import datetime as dt
import json
import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, NamedTuple, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =============================================================================
# CONFIG
# =============================================================================
# SERVER_NAME = 'dnrhln6386.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'

SCRIPT_DIR = Path(__file__).resolve().parent
CRED_FILE = SCRIPT_DIR / 'creds.txt'

DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Gage_Alarms\GoldCreek')
STATE_FILE = DIRECTORY / 'core' / 'alarm_state.json'

Q_ID = '9c276f5ebcdf4a758e1a9dc93f891f87'
GAGE = '76G 05850'
GAGE_NAME = 'Gold Creek near Gold Creek, MT'

ALARM_LOW = 6.0      # cfs; at or below -> shut pumps down
ALARM_HIGH = 8.0     # cfs; at or above -> turn pumps back on

LOOKBACK_MINUTES = 1440
CHECK_POINTS = 8             # newest readings examined each run
MAX_DATA_AGE_MINUTES = 150   # older than this counts as "broken"
REQUEST_TIMEOUT = 60
LOCAL_TZ = 'America/Denver'

SEND_RECOVERY_EMAIL = False  # email when data returns after a broken period
DRY_RUN = False              # True = print emails, do not send or save state

SMTP_HOST = 'mail.mt.gov'
SMTP_PORT = 25
EMAIL_FROM = 'Alarm@dnrc.mt.gov'
FAILURE_EMAIL_FROM = 'Alarm_Failure@dnrc.mt.gov'
SUBJECT = 'Gold Creek Discharge Warning'

EMAIL_RECIPIENTS = [
    'bruce@thomasherefords.com',
    'John.Lunzer@mt.gov',
    'David.Saba@mt.gov',
]
# Carrier email-to-text gateways are being shut down; test these regularly.
SMS_RECIPIENTS = [
    '4065441536@vtext.com',
    '4069169738@tmomail.net',
]
RECIPIENTS = EMAIL_RECIPIENTS + SMS_RECIPIENTS
FAILURE_RECIPIENTS = ['David.Saba@mt.gov']

ALARM_MESSAGES = {
    'high': 'TURN THEM PUMPS BACK ON BOYS!',
    'low': 'SHUT THEM PUMPS DOWN BOYS!',
}


class Reading(NamedTuple):
    """One discharge measurement."""
    time: pd.Timestamp   # timezone-aware, local time
    value: float         # cfs


# =============================================================================
# CREDENTIALS AND SESSION
# =============================================================================
def load_credentials(path: Path) -> dict[str, str]:
    """Read key=value lines from a text file, skipping blanks and # comments."""
    if not path.exists():
        raise FileNotFoundError(f'Credentials file not found: {path}')
    creds: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        creds[key.strip()] = value.strip()
    return creds


def build_session() -> requests.Session:
    """HTTP session with creds.txt login and retries on transient errors."""
    creds = load_credentials(CRED_FILE)
    retry = Retry(total=5, backoff_factor=1,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=['GET'])
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=retry))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.auth = (creds['AQUARIUS_USER'], creds['AQUARIUS_PASSWORD'])
    return session


# =============================================================================
# DATA ACCESS AND CHECKS
# =============================================================================
def parse_timestamp(ts: str) -> pd.Timestamp:
    """Parse an AQUARIUS ISO-8601 timestamp into a local-time Timestamp."""
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize('UTC')
    return stamp.tz_convert(LOCAL_TZ)


def fetch_readings(session: requests.Session) -> list[Reading]:
    """
    Get the newest CHECK_POINTS discharge readings, oldest first.

    Raises:
        requests.RequestException: On HTTP or network failure.
        KeyError, ValueError, TypeError: If the response is malformed.
    """
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    utc_now = dt.datetime.now(dt.timezone.utc)
    resp = session.get(
        f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
        params={
            'TimeSeriesUniqueId': Q_ID,
            'QueryFrom': (utc_now - dt.timedelta(minutes=LOOKBACK_MINUTES)).strftime(fmt),
            'QueryTo': utc_now.strftime(fmt),
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    readings = []
    for point in resp.json().get('Points') or []:
        numeric = (point.get('Value') or {}).get('Numeric')
        if numeric is None:
            continue
        readings.append(Reading(parse_timestamp(point['Timestamp']), float(numeric)))
    return readings[-CHECK_POINTS:]


def fmt_time(ts: pd.Timestamp) -> str:
    """Format a timestamp like 'Nov-05 3:15 PM'."""
    return f"{ts:%b-%d} {ts.hour % 12 or 12}:{ts.minute:02d} {'AM' if ts.hour < 12 else 'PM'}"


def find_data_problem(readings: list[Reading]) -> Optional[str]:
    """
    Describe why the data can't be trusted, or return None if it looks fine.

    Checks for an empty result and for a newest reading older than
    MAX_DATA_AGE_MINUTES.
    """
    if not readings:
        return f'AQUARIUS returned no discharge data in the last {LOOKBACK_MINUTES} minutes.'
    age = pd.Timestamp.now(tz=LOCAL_TZ) - readings[-1].time
    if age > pd.Timedelta(minutes=MAX_DATA_AGE_MINUTES):
        hours = age.total_seconds() / 3600
        return (f'Newest reading is {hours:.1f} hours old '
                f'({fmt_time(readings[-1].time)}).')
    return None


def find_alarm(readings: list[Reading]) -> Optional[tuple[str, Reading]]:
    """
    Return ('low' or 'high', reading) for the newest reading in alarm, or None.
    """
    for reading in reversed(readings):
        if reading.value <= ALARM_LOW:
            return 'low', reading
        if reading.value >= ALARM_HIGH:
            return 'high', reading
    return None


# =============================================================================
# STATE
# =============================================================================
def load_state() -> dict[str, Any]:
    """Load saved state; a missing or unreadable file means 'no history'."""
    default = {'last_alarm': None, 'broken': False}
    if not STATE_FILE.exists():
        return default
    try:
        return {**default, **json.loads(STATE_FILE.read_text(encoding='utf-8'))}
    except json.JSONDecodeError:
        return default


def save_state(state: dict[str, Any]) -> None:
    """Write state to disk (skipped in dry-run mode)."""
    if DRY_RUN:
        print(f'[DRY RUN] would save state: {state}')
        return
    state['updated'] = dt.datetime.now().isoformat(timespec='seconds')
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


# =============================================================================
# EMAIL
# =============================================================================
def send_email(subject: str, body: str, recipients: list[str], from_addr: str) -> None:
    """Send a plain-text email (or just print it in dry-run mode)."""
    if DRY_RUN:
        print(f'[DRY RUN] To: {recipients}\nSubject: {subject}\n{body}\n')
        return
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)


def send_failure_email() -> None:
    """Email the current exception's traceback to FAILURE_RECIPIENTS."""
    stamp = dt.datetime.now().strftime('%b %d, %Y %H:%M')
    body = (
        'The Gold Creek pump alarm script crashed.\n\n'
        f'Time: {stamp}\nServer: {SERVER_NAME}\nGage: {GAGE} {GAGE_NAME}\n\n'
        f'Traceback:\n{"=" * 80}\n{traceback.format_exc()}'
    )
    send_email(f'Gold Creek Pump Alarm FAILED — {stamp}', body,
               FAILURE_RECIPIENTS, FAILURE_EMAIL_FROM)


# =============================================================================
# ACTIONS
# =============================================================================
def handle_problem(state: dict[str, Any], problem: str) -> None:
    """Send a single 'broken' email the first time data goes bad."""
    print(f'Data problem: {problem}')
    if state['broken']:
        print('Already notified; not sending again.')
        return
    body = ('Something is broken.\n'
            'Go find Dave and tell him to fix it!\n\n'
            f'Details: {problem}')
    send_email(SUBJECT, body, RECIPIENTS, EMAIL_FROM)
    state['broken'] = True
    save_state(state)
    print('broken email sent')


def handle_recovery(state: dict[str, Any]) -> None:
    """Clear the broken flag once good data returns."""
    if not state['broken']:
        return
    state['broken'] = False
    save_state(state)
    print('Data restored; broken flag cleared.')
    if SEND_RECOVERY_EMAIL:
        send_email(SUBJECT, 'Gold Creek data is reporting again.', RECIPIENTS, EMAIL_FROM)


def handle_alarm(state: dict[str, Any], kind: str, reading: Reading) -> None:
    """Send the alarm email unless the same alarm was already the last one sent."""
    if state['last_alarm'] == kind:
        print(f'{kind} alarm already sent; nothing to do.')
        return
    body = f'\n{fmt_time(reading.time)}: {reading.value:.1f} cfs\n\n{ALARM_MESSAGES[kind]}\n'
    send_email(SUBJECT, body, RECIPIENTS, EMAIL_FROM)
    state['last_alarm'] = kind          # saved only after a successful send
    save_state(state)
    print(f'{kind} alarm email sent')


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    """Check the gage and send whichever notification is needed."""
    if ALARM_LOW >= ALARM_HIGH:
        raise ValueError('ALARM_LOW must be less than ALARM_HIGH')

    session = build_session()
    state = load_state()

    print('Acquiring StAGE data...')
    try:
        readings = fetch_readings(session)
        problem = find_data_problem(readings)
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        readings, problem = [], f"Can't retrieve data: {exc}"

    if problem:
        handle_problem(state, problem)
        return

    handle_recovery(state)
    latest = readings[-1]
    print(f'Latest: {fmt_time(latest.time)}  {latest.value:.1f} cfs')

    alarm = find_alarm(readings)
    if alarm:
        handle_alarm(state, *alarm)
    else:
        print('Flow is between thresholds; no alarm.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        try:
            send_failure_email()
        except Exception:
            pass
        raise