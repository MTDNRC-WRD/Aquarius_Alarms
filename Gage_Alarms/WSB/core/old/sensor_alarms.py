"""
StAGE Sensor Alarm Script
==========================
Queries AQUARIUS for the most recent sensor readings across all monitored
sites and sends a daily email alert when any of the following conditions
are met:

  - No data reported in the past 24 hours (timestamp is 0 / missing)
  - Battery voltage is outside the configured alarm band
  - Any other parameter is outside its configured low/high alarm band

Two emails may be sent per run:
  1. General alarm email   -> all RECIPIENTS
  2. Paradise Valley email -> PARADISE_RECIPIENTS, sent only if one or more
     Paradise Valley sites appear in the alarm list

Failure email:
  - If the script crashes for any reason, a failure email is sent to
    FAILURE_RECIPIENTS using FAILURE_EMAIL_FROM, with the full traceback.

Inputs
------
creds.txt: Aquarius login credentials
    Aquarius_Username=''
    Aquarius_Password=''

SensorList.xlsx : Site list with columns:
    index                – AQUARIUS TimeSeriesUniqueId
    LocationIdentifier   – location ID
    SiteName             – Human-readable station name
    Parameter            – stage, voltage, temp, storage, etc.
    Unit                 – parameter units, e.g. cfs
    LowAlarm             – Low alarm threshold
    HighAlarm            – High alarm threshold
    Publish              – Boolean; True = include in alarm evaluation

Outputs
-------
todays_data.csv   – Full snapshot of all queried sites
STAGE_Alarms.csv – Subset of sites that triggered an alarm

Email
-----
Sent via SMTP (mail.mt.gov:25) with the alarm CSV attached. The body
lists triggered sites grouped by alarm type, including the current value
and unit for each site. Closes with a randomly selected pleasantry.

Notes
-----
- Only the most recent point is evaluated (index -1).
- Timestamps are adjusted from UTC to Mountain Time (MST: UTC-7, MDT: UTC-6).
- Sites reporting in volts (Unit == 'V') are grouped separately from other
  parameter anomalies for easier triage.
"""

import datetime as dt
import random
import smtplib
import traceback
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import shutil
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry
from typing import Optional

# =============================================================================
# CONFIG
# =============================================================================
# SERVER_NAME = 'dnrhln6386.state.mt.ads'
# SERVER_NAME = 'ENTDNR0101.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'
CRED_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\creds.txt')

DIRECTORY     = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Gage_Alarms\WSB')
SITE_LIST   = DIRECTORY / 'SensorList.xlsx'
SITE_SHEET  = 'sensor_list'
OUTPUT_ALL    = DIRECTORY / 'outputs' / 'todays_data.csv'
OUTPUT_ALARMS = DIRECTORY / 'outputs' / 'STAGE_Alarms.csv'

SMTP_HOST = 'mail.mt.gov'
SMTP_PORT = 25

EMAIL_FROM         = 'StAGE_Alarm@dnrc.mt.gov'
FAILURE_EMAIL_FROM = 'StAGE_Alarm_Failure@dnrc.mt.gov'

RECIPIENTS = [
    'MNorberg@mt.gov',
    'Ryan.Koehnlein2@mt.gov',
    'luke.lutz2@mt.gov',
    'Christopher.Basden@mt.gov',
    'b.grigsby@mt.gov',
    'David.Saba@mt.gov',
    'Jack.Poole@mt.gov'
]
# RECIPIENTS = ['David.Saba@mt.gov']

PARADISE_RECIPIENTS = [
    'John.Lunzer@mt.gov',
    'Raeya.Gordon@mt.gov',
    'Madeline.McKeefry@mt.gov',
    'David.Saba@mt.gov',
]

FAILURE_RECIPIENTS = ['David.Saba@mt.gov', 'Jack.Poole@mt.gov']

# Sites that trigger a secondary Paradise Valley email if in alarm
PARADISE_SITES = {'43B 05990', '43B 10000', '43B 05000', '43B 04000', '76G 05850'}

LOOKBACK_MINUTES = 1440   # 24 hours
REQUEST_TIMEOUT  = 60

# =============================================================================
# PLEASANTRIES
# =============================================================================
PLEASANTRIES = [
    'agreeable', 'amiable', 'amusing', 'sublime', 'charming', 'cheerful',
    'congenial', 'cool', 'cordial', 'delightful', 'engaging', 'enjoyable',
    'fun', 'homey', 'likable', 'lovely', 'mild', 'pleasing', 'pleasurable',
    'refreshing', 'satisfying', 'sweet', 'affable', 'civil', 'civilized',
    'copacetic', 'delectable', 'diplomatic', 'enchanting', 'fine',
    'fine and dandy', 'admissible', 'all right', 'cooking with gas',
    'delightful', 'hunky-dory', 'kosher', 'okay', 'peachy keen', 'right on',
    'swell', 'trendy', 'A-OK', 'dandy', 'genial', 'good-humored',
    'gratifying', 'jolly', 'jovial', 'kindly', 'mild-mannered', 'nice',
    'obliging', 'social', 'urbane', 'cultured', 'suave', 'cosmopolitan',
    'elegant', 'genteel', 'mannerly', 'astonishing', 'astounding',
    'breathtaking', 'fabulous', 'fantastic', 'marvelous', 'mind-blowing',
    'miraculous', 'monumental', 'phenomenal', 'prodigious', 'smashing',
    'spectacular', 'stunning', 'superb', 'terrific', 'tremendous',
    'wondrous', 'punctual', 'scrupulous', 'meticulous', 'punctilious',
]


def random_valediction():
    """Return a randomized closing like 'Have a delightful day!'"""
    adj = random.choice(PLEASANTRIES)
    article = 'an' if adj[0].lower() in 'aeiou' else 'a'
    return f'Have {article} {adj} day!'


REQUIRED_COLS = ['LocationIdentifier', 'SiteName', 'Parameter', 'Unit',
                 'LowAlarm', 'HighAlarm', 'Publish']


def get_site_list_copy(source: Path, cache_dir: Path) -> tuple[Path, Optional[str]]:
    """
    Copy the site list into cache_dir and return the path to read from.

    If the copy fails (e.g. the workbook is open and locked), fall back to
    the copy from the last successful run. Raises only if no cached copy
    exists.

    Returns:
        (path to read, warning message or None)
    """
    if not source.exists():
        raise FileNotFoundError(f'Site list not found: {source}')

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / source.name

    try:
        shutil.copy2(source, cached)
        return cached, None
    except (PermissionError, OSError) as exc:
        if cached.exists():
            age_hours = (dt.datetime.now().timestamp() - cached.stat().st_mtime) / 3600
            warning = (
                f'Could not copy {source.name} ({exc}); using cached copy '
                f'last updated {age_hours:.1f} hours ago. The file may be open in Excel.'
            )
            print(f'  [WARN] {warning}')
            return cached, warning
        raise PermissionError(
            f'Could not copy {source.name} and no cached copy exists: {exc}'
        ) from exc


def load_site_list(path: Path, sheet: str) -> tuple[pd.DataFrame, list[str]]:
    """
    Read the sensor alarm site list from Excel.

    Structural problems (missing file or columns) raise an error. Row-level
    problems (blank/non-numeric thresholds, duplicate IDs) do not stop the
    run; they are returned as warning strings so the bad check is skipped
    and the problem can be reported.

    Returns:
        (site DataFrame indexed by UniqueId, list of warning messages)
    """
    warnings: list[str] = []

    read_path, copy_warning = get_site_list_copy(path, path.parent / "cache")
    if copy_warning:
        warnings.append(copy_warning)

    df = pd.read_excel(read_path, sheet_name=sheet, index_col=0, engine="openpyxl")
    df = df.dropna(how="all")
    df.index = df.index.astype(str).str.strip()

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Site list is missing columns: {missing}")

    # Blank Publish cells would read as NaN, which Python treats as True
    df['Publish'] = df['Publish'].fillna(False).astype(bool)

    dupes = df.index[df.index.duplicated()]
    if len(dupes):
        warnings.append(f'Duplicate UniqueIds (first row kept): {sorted(set(dupes))}')
        df = df[~df.index.duplicated(keep='first')]

    for col in ['LowAlarm', 'HighAlarm']:
        raw = df[col]
        df[col] = pd.to_numeric(raw, errors='coerce')
        bad = df[df['Publish'] & df[col].isna()]
        for uid, row in bad.iterrows():
            warnings.append(
                f"{row['LocationIdentifier']} {row['Parameter']} ({uid}): "
                f"{col} is blank or not a number ({raw[uid]!r}); {col} check skipped"
            )

    return df, warnings


def load_credentials(path: Path) -> dict:
    """Read key=value lines from a text file; skip blanks and # comments."""
    if not path.exists():
        raise FileNotFoundError(f'Credentials file not found: {path}')
    creds = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        creds[key.strip()] = value.strip()
    return creds


def build_session() -> requests.Session:
    """HTTP session with automatic retry on transient server errors."""
    creds = load_credentials(CRED_FILE)

    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET'],
    )
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=retry))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.auth = (creds['AQUARIUS_USER'], creds['AQUARIUS_PASSWORD'])
    return session


def format_timestamp(ts):
    """
    Convert an AQUARIUS ISO-8601 timestamp to 'Mon-DD HH:MM' Mountain Time.
    Returns 0 if input is 0 (no data sentinel).
    """
    if ts == 0:
        return 0
    try:
        fmt = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f0%z")
        return (fmt - dt.timedelta(hours=6)).strftime("%b-%d %H:%M")
    except ValueError:
        ts_fixed = ts[:12] + '3' + ts[13:]
        fmt = dt.datetime.strptime(ts_fixed, "%Y-%m-%dT%H:%M:%S.%f0%z")
        return (fmt - dt.timedelta(hours=5)).strftime("%b-%d %H:%M")


def fetch_site_record(session, ts_uid, site_meta, query_from, query_to):
    """
    Query AQUARIUS for the most recent corrected reading at one time series.
    Returns a dict with site metadata, current value, and alarm thresholds.
    """
    resp = session.get(
        url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
        params={'TimeSeriesUniqueId': ts_uid, 'QueryFrom': query_from, 'QueryTo': query_to},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    points = payload.get('Points', [])

    try:
        timestamp = format_timestamp(points[-1]['Timestamp'])
        value = points[-1]['Value']['Numeric']
    except (IndexError, KeyError):
        timestamp = 0
        value = 0

    return {
        'UniqueId':           payload['UniqueId'],
        'LocationIdentifier': payload['LocationIdentifier'],
        'SiteName':           site_meta['SiteName'],
        'Parameter':          payload['Parameter'],
        'Timestamp':          timestamp,
        'Value':              value,
        'Unit':               payload['Unit'],
        'LowAlarm':           site_meta['LowAlarm'],
        'HighAlarm':          site_meta['HighAlarm'],
        'Publish':            site_meta['Publish'],
    }


def format_alarm_lines(alarm_list: list[dict], decimals: int = 2) -> str:
    """
    Format a list of alarm dicts into readable email lines.

    Each dict must contain: location_id, site_name, value, unit.
    Values are rounded to `decimals` places; 0 is shown as 'no data'.
    Returns '  None' if the list is empty.
    """
    if not alarm_list:
        return '  None'
    lines = []
    for entry in alarm_list:
        val = entry['value']
        if val == 0:
            val_str = 'no data'
        else:
            try:
                val_str = f'{float(val):.{decimals}f} {entry["unit"]}'
            except (TypeError, ValueError):
                val_str = f'{val} {entry["unit"]}'
        lines.append(f'  - {entry["location_id"]}  {entry["site_name"]}  ({val_str})')
    return '\n'.join(lines)


def send_email(subject,
               body,
               recipients,
               from_addr,
               attachment_path=None):
    """
    Send an email using the configured SMTP server.
    """
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(body, 'plain'))

    if attachment_path and attachment_path.exists():
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment_path.read_bytes())
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            'attachment',
            filename=attachment_path.name
        )
        msg.attach(part)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)


def send_failure_email():
    """
    Send a failure notification email with the full traceback.
    """
    timestamp = dt.datetime.now().strftime('%b %d, %Y %H:%M')
    error_text = traceback.format_exc()

    subject = f'StAGE Sensor Alarm FAILED — {timestamp}'
    body = (
        'The StAGE Sensor Alarm script failed to execute.\n\n'
        f'Time: {timestamp}\n'
        f'Server: {SERVER_NAME}\n'
        f'Site list: {SITE_LIST}\n'
        f'Output all: {OUTPUT_ALL}\n'
        f'Output alarms: {OUTPUT_ALARMS}\n\n'
        'Traceback:\n'
        f'{"=" * 80}\n'
        f'{error_text}'
    )

    send_email(
        subject=subject,
        body=body,
        recipients=FAILURE_RECIPIENTS,
        from_addr=FAILURE_EMAIL_FROM
    )


# =============================================================================
# MAIN
# =============================================================================
def main():
    utc_now = dt.datetime.utcnow()
    query_to = utc_now.strftime('%Y-%m-%dT%H:%M:%SZ')
    query_from = (utc_now - dt.timedelta(minutes=LOOKBACK_MINUTES)).strftime('%Y-%m-%dT%H:%M:%SZ')
    date_label = dt.datetime.now().strftime('%b %d, %Y')

    sl_df, list_warnings = load_site_list(SITE_LIST, SITE_SHEET)
    # sl_df = sl_df[sl_df["Publish"]]   # will save on API calls, but won't give you everything in the output csv
    session = build_session()

    # Query AQUARIUS
    print('Acquiring StAGE data...')
    records = []
    for ts_uid in tqdm(sl_df.index, desc='Sites', unit='site'):
        try:
            record = fetch_site_record(
                session, str(ts_uid).strip(), sl_df.loc[ts_uid], query_from, query_to
            )
            records.append(record)
        except Exception as exc:
            tqdm.write(f'  [SKIP] {ts_uid}: {exc}')

    today_df = pd.DataFrame(records)
    today_df["Value"] = pd.to_numeric(today_df["Value"], errors="coerce").round(2)
    today_df.to_csv(OUTPUT_ALL, index=False)

    # Evaluate alarms
    no_report_alarms = []
    voltage_alarms = []
    data_alarms = []

    seen_no_report = set()
    seen_voltage = set()
    seen_data = set()

    alarm_rows = []
    for _, row in today_df.iterrows():
        if not row['Publish']:
            continue

        loc = row['LocationIdentifier']
        entry = {
            'location_id': loc,
            'site_name': row['SiteName'],
            'value': row['Value'],
            'unit': row['Unit'],
        }

        if row['Timestamp'] == 0:
            if loc not in seen_no_report:
                no_report_alarms.append(entry)
                seen_no_report.add(loc)
                alarm_rows.append(row)

        elif row['LowAlarm'] > row['Value'] or row['HighAlarm'] < row['Value']:
            if row['Unit'] == 'V':
                if loc not in seen_voltage:
                    voltage_alarms.append(entry)
                    seen_voltage.add(loc)
                    alarm_rows.append(row)
            else:
                if loc not in seen_data and loc not in seen_no_report:
                    data_alarms.append(entry)
                    seen_data.add(loc)
                    alarm_rows.append(row)

    error_df = pd.DataFrame(alarm_rows)
    error_df["Value"] = pd.to_numeric(error_df["Value"], errors="coerce").round(2)
    error_df.to_csv(OUTPUT_ALARMS, index=False)

    total_alarms = len(no_report_alarms) + len(voltage_alarms) + len(data_alarms)
    print(f'  {total_alarms} site(s) reporting anomalies')

    # Build shared email body
    valediction = random_valediction()
    body_text = (
        f'Daily Alarm Summary — {date_label}\n'
        f'{"=" * 50}\n\n'
        f'Sites Not Reporting:\n'
        f'{format_alarm_lines(no_report_alarms)}\n\n'
        f'Sites Reporting Irregular Voltage:\n'
        f'{format_alarm_lines(voltage_alarms)}\n\n'
        f'Sites Reporting Irregular Data:\n'
        f'{format_alarm_lines(data_alarms)}\n\n'
        f'{valediction}'
    )
    subject = f'StAGE Alarms — {date_label}'

    # Send general email
    send_email(
        subject=subject,
        body=body_text,
        recipients=RECIPIENTS,
        from_addr=EMAIL_FROM,
        attachment_path=OUTPUT_ALARMS
    )
    print('General alarm email sent.')

    # Send Paradise Valley email if any Paradise sites are in alarm
    alarmed_locations = set(error_df['LocationIdentifier']) if not error_df.empty else set()
    if PARADISE_SITES & alarmed_locations:
        send_email(
            subject=subject,
            body=body_text,
            recipients=PARADISE_RECIPIENTS,
            from_addr=EMAIL_FROM,
            attachment_path=OUTPUT_ALARMS
        )
        print('Paradise Valley alarm email sent.')

    # Missing values warning
    if list_warnings:
        print(f'  {len(list_warnings)} site list warning(s)')
        send_email(
            subject=f'StAGE Sensor Alarm site list warnings — {date_label}',
            body=(
                'The alarm ran, but these rows in Sensor_List.xlsx need fixing:\n\n'
                + '\n'.join(f'  - {w}' for w in list_warnings)
            ),
            recipients=FAILURE_RECIPIENTS,
            from_addr=FAILURE_EMAIL_FROM,
        )

if __name__ == '__main__':
    try:
        main()
    except Exception:
        try:
            send_failure_email()
        except Exception:
            pass
        raise
