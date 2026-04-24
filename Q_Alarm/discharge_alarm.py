"""
StAGE Discharge Alarm Script
==============================
Queries AQUARIUS for instantaneous discharge at monitored gages and sends a
daily email alert when any of the following conditions are met:

  - No data reported (timestamp is null or value is zero)
  - Current discharge exceeds a configured high-flow threshold
  - 24-hour discharge increase exceeds a configured delta threshold

Inputs
------
q_list.csv : Site list with columns:
    index     – AQUARIUS TimeSeriesUniqueId
    SiteName  – Human-readable station name
    LowAlarm  – Low-flow alarm threshold (cfs) [not currently evaluated]
    HighAlarm – High-flow alarm threshold (cfs)
    Delta     – 24-hour delta alarm threshold (cfs)
    Publish   – Boolean; True = include in alarm evaluation

Outputs
-------
Instant_Discharge.csv       – Full snapshot of all queried sites
Instant_Discharge_Alarms.csv – Subset of sites that triggered an alarm

Email
-----
Sent via SMTP (mail.mt.gov:25) with the alarm CSV attached. The email body
lists triggered sites grouped by alarm type, including the current discharge
value for each site.

Notes
-----
- Timestamps are pulled from the AQUARIUS Publish API at 15-minute intervals;
  indices -1, -4, and -96 correspond to ~current, ~1-hour ago, ~24-hours ago.
- Timestamps are adjusted from UTC to Mountain Time (MST: UTC-7, MDT: UTC-6).
- Negative or zero discharge values are treated as no-data and trigger a
  missing-data alarm rather than a flow alarm.
"""

import datetime as dt
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from tqdm import tqdm
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =============================================================================
# CONFIG
# =============================================================================
# SERVER_NAME = 'dnrhln6386.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'
USER_NAME   = 'DNRC'
PASSWORD    = 'DNRC'

DIRECTORY   = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Q_Alarm')
SITE_LIST   = DIRECTORY / 'q_list.csv'
OUTPUT_ALL  = DIRECTORY / 'Instant_Discharge.csv'
OUTPUT_ALARMS = DIRECTORY / 'Instant_Discharge_Alarms.csv'

SMTP_HOST   = 'mail.mt.gov'
SMTP_PORT   = 25
EMAIL_FROM  = 'StAGE_Alarm@dnrc.mt.gov'
RECIPIENTS  = [
    'David.Saba@mt.gov',
    'MNorberg@mt.gov',
    'diane.wagner@mt.gov',
    'Ryan.Koehnlein2@mt.gov',
    'Christopher.Basden@mt.gov',
    'b.grigsby@mt.gov',
    'luke.lutz2@mt.gov',
    'raeya.gordon@mt.gov',
]
# RECIPIENTS  = ['David.Saba@mt.gov']

# AQUARIUS time window: 1680 min = 28 hours (covers 24-hr lookback + buffer)
LOOKBACK_MINUTES = 1680
REQUEST_TIMEOUT  = 60

# Point indices from end of returned series (15-min data):
#   -1  → most recent reading
#   -4  → ~1 hour ago
#   -96 → ~24 hours ago
IDX_NOW  = -1
IDX_1HR  = -4
IDX_DAY  = -96

# =============================================================================
# HELPERS
# =============================================================================
def build_session() -> requests.Session:
    """HTTP session with automatic retry on transient server errors."""
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET'],
    )
    session = requests.Session()
    session.mount('http://', HTTPAdapter(max_retries=retry))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.auth = (USER_NAME, PASSWORD)
    return session


def format_timestamp(ts: str) -> str:
    """
    Convert an AQUARIUS ISO-8601 timestamp string to 'Mon-DD HH:MM' in
    Mountain Time. Returns 'null' if the input is 'null'.

    AQUARIUS returns timestamps with UTC offsets; we subtract additional hours
    to account for offset ambiguity between MST (UTC-7) and MDT (UTC-6).
    """
    if ts == 'null':
        return 'null'
    try:
        fmt = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f0%z")
        return (fmt - dt.timedelta(hours=6)).strftime("%b-%d %H:%M")
    except ValueError:
        # Handle edge-case where minute digit causes parse failure
        ts_fixed = ts[:12] + '3' + ts[13:]
        fmt = dt.datetime.strptime(ts_fixed, "%Y-%m-%dT%H:%M:%S.%f0%z")
        return (fmt - dt.timedelta(hours=5)).strftime("%b-%d %H:%M")


def safe_value(points: list, idx: int):
    """Return integer discharge value at list index, or 'null' on IndexError."""
    try:
        return int(points[idx]['Value']['Numeric'])
    except (IndexError, KeyError, TypeError):
        return 'null'


def safe_timestamp(points: list, idx: int) -> str:
    """Return formatted timestamp at list index, or 'null' on IndexError."""
    try:
        return format_timestamp(points[idx]['Timestamp'])
    except (IndexError, KeyError):
        return 'null'


def delta_24hr(now, day_ago) -> int:
    """Return the 24-hour discharge change, or 0 if either value is missing."""
    if now == 'null' or day_ago == 'null':
        return 0
    return int(now) - int(day_ago)


def fetch_site_data(session: requests.Session, ts_uid: str, site_meta: pd.Series,
                    query_from: str, query_to: str) -> dict:
    """
    Query AQUARIUS for corrected discharge data at a single time series and
    return a dictionary of current, 1-hour, and 24-hour values.
    """
    resp = session.get(
        url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
        params={'TimeSeriesUniqueId': ts_uid, 'QueryFrom': query_from, 'QueryTo': query_to},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    points = payload.get('Points', [])

    return {
        'UniqueId':          payload['UniqueId'],
        'LocationIdentifier': payload['LocationIdentifier'],
        'SiteName':          site_meta['SiteName'],
        'Parameter':         payload['Parameter'],
        'Unit':              payload['Unit'],
        'Timestamp':         safe_timestamp(points, IDX_NOW),
        'Value':             safe_value(points, IDX_NOW),
        'Timestamp_1hr':     safe_timestamp(points, IDX_1HR),
        'Value_1hr':         safe_value(points, IDX_1HR),
        'Timestamp_day':     safe_timestamp(points, IDX_DAY),
        'Value_day':         safe_value(points, IDX_DAY),
        'Delta_Day':         '',
        'Alarm_Type':        '',
        'LowAlarm':          site_meta['LowAlarm'],
        'HighAlarm':         site_meta['HighAlarm'],
        'DeltaAlarm':        site_meta['Delta'],
        'Publish':           site_meta['Publish'],
    }


def format_alarm_lines(alarm_list: list) -> str:
    """
    Format a list of alarm dicts into readable email lines.

    Each dict contains:
        location_id – Station ID
        site_name   – Station name
        value       – Current discharge (cfs)
        unit        – Unit string from AQUARIUS

    Returns '  None' if the list is empty.
    """
    if not alarm_list:
        return '  None'
    lines = []
    for entry in alarm_list:
        val = entry['value']
        val_str = f'{val} {entry["unit"]}' if val != 'null' else 'no data'
        lines.append(f'  - {entry["location_id"]}  {entry["site_name"]}  ({val_str})')
    return '\n'.join(lines)


# =============================================================================
# MAIN
# =============================================================================
def main():
    # Time window
    utc_now  = dt.datetime.utcnow()
    query_to = utc_now.strftime('%Y-%m-%dT%H:%M:%SZ')
    query_from = (utc_now - dt.timedelta(minutes=LOOKBACK_MINUTES)).strftime('%Y-%m-%dT%H:%M:%SZ')
    date_label = dt.datetime.now().strftime('%b %d, %Y')

    # Load site list
    sl_df = pd.read_csv(SITE_LIST, index_col=0, skip_blank_lines=True)
    session = build_session()

    # Query AQUARIUS
    print('Acquiring discharge data...')
    records = []
    for ts_uid in tqdm(sl_df.index, desc="Sites", unit="site"):
        try:
            record = fetch_site_data(session, str(ts_uid).strip(), sl_df.loc[ts_uid], query_from, query_to)
            records.append(record)
        except Exception as exc:
            tqdm.write(f"  [SKIP] {ts_uid}: {exc}")

    today_df = pd.DataFrame(records)
    today_df.to_csv(OUTPUT_ALL, index=False)

    # Evaluate alarms
    no_data_alarms  = []   # null timestamp or zero value
    high_flow_alarms = []  # exceeds HighAlarm threshold
    delta_alarms    = []   # 24-hr increase exceeds DeltaAlarm threshold

    alarm_rows = []
    for _, row in today_df.iterrows():
        if not row['Publish']:
            continue

        row = row.copy()
        row['Delta_Day'] = delta_24hr(row['Value'], row['Value_day'])

        entry = {
            'location_id': row['LocationIdentifier'],
            'site_name':   row['SiteName'],
            'value':       row['Value'],
            'unit':        'cfs',
        }

        if row['Timestamp'] == 'null' or row['Value'] == 0:
            row['Alarm_Type'] = 'NoData'
            no_data_alarms.append(entry)
            alarm_rows.append(row)

        elif row['Value'] > row['HighAlarm']:
            row['Alarm_Type'] = 'HighAlarm'
            high_flow_alarms.append(entry)
            alarm_rows.append(row)

        elif row["Delta_Day"] > row["DeltaAlarm"]:
            row["Alarm_Type"] = "DeltaAlarm"
            delta_alarms.append(
                {
                    "location_id": row["LocationIdentifier"],
                    "site_name": row["SiteName"],
                    "value": row["Delta_Day"],  # show the delta, not the current reading
                    "unit": "cfs increase",
                }
            )
            alarm_rows.append(row)

    error_df = pd.DataFrame(alarm_rows)
    error_df.to_csv(OUTPUT_ALARMS, index=False)

    print(f'  {len(high_flow_alarms)} site(s) reporting high flow')
    print(f'  {len(delta_alarms)} site(s) reporting significant 24-hr increase')
    print(f'  {len(no_data_alarms)} site(s) missing data')

    # Build email
    body_text = (
        f'Discharge Alarm — {date_label}\n'
        f'{"=" * 50}\n\n'
        f'Missing / No Data:\n'
        f'{format_alarm_lines(no_data_alarms)}\n\n'
        f'High Discharge:\n'
        f'{format_alarm_lines(high_flow_alarms)}\n\n'
        f'Significant 24-hr Increase:\n'
        f'{format_alarm_lines(delta_alarms)}\n\n'
        f'See attached CSV for full details.\n'
    )

    msg = MIMEMultipart()
    msg['Subject'] = f'StAGE Discharge Alarm — {date_label}'
    msg['From']    = EMAIL_FROM
    msg['To']      = ', '.join(RECIPIENTS)
    msg.attach(MIMEText(body_text))

    attachment = MIMEBase('application', 'octet-stream')
    attachment.set_payload(OUTPUT_ALARMS.read_bytes())
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', 'attachment',
                          filename=OUTPUT_ALARMS.name)
    msg.attach(attachment)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)

    print('Email sent.')


if __name__ == '__main__':
    main()
