"""
StAGE Discharge Alarm Script
==============================
Queries AQUARIUS for instantaneous discharge at monitored gages and sends a
daily email alert when any of the following conditions are met:

  - No data reported (timestamp is null or value is zero)
  - Current discharge falls below a configured low-flow threshold
  - Current discharge exceeds a configured high-flow threshold
  - 24-hour discharge increase exceeds a configured delta threshold

Inputs
------
creds.txt: Aquarius login credentials
    Aquarius_Username=''
    Aquarius_Password=''

Qlist.xlsx : Site list with columns:
    index     – AQUARIUS TimeSeriesUniqueId
    SiteName  – Human-readable station name
    LowAlarm  – Low-flow alarm threshold (cfs)
    HighAlarm – High-flow alarm threshold (cfs)
    DeltaAlarm– 24-hour delta alarm threshold (cfs)
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
import traceback
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from tqdm import tqdm
import pandas as pd
import shutil
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional
import html as html_lib

# =============================================================================
# CONFIG
# =============================================================================
# SERVER_NAME = 'dnrhln6386.state.mt.ads'
# SERVER_NAME = 'ENTDNR0101.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'

CRED_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\creds.txt')

DIRECTORY   = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Discharge_Alarms')
SITE_LIST   = DIRECTORY / 'Qlist.xlsx'
SITE_SHEET  = 'q_list'
OUTPUT_ALL  = DIRECTORY / 'outputs' / 'Instant_Discharge.csv'
OUTPUT_ALARMS = DIRECTORY / 'outputs' / 'Instant_Discharge_Alarms.csv'

SMTP_HOST   = 'mail.mt.gov'
SMTP_PORT   = 25
EMAIL_FROM = 'StAGE_Alarm@dnrc.mt.gov'
FAILURE_EMAIL_FROM = 'StAGE_Alarm_Failure@dnrc.mt.gov'

RECIPIENTS  = [
    'David.Saba@mt.gov',
    'MNorberg@mt.gov',
    'diane.wagner@mt.gov',
    'Ryan.Koehnlein2@mt.gov',
    'Christopher.Basden@mt.gov',
    'b.grigsby@mt.gov',
    'luke.lutz2@mt.gov',
    'raeya.gordon@mt.gov',
    'Jack.Poole@mt.gov'
]

FAILURE_RECIPIENTS = ['David.Saba@mt.gov', 'Jack.Poole@mt.gov']
# RECIPIENTS = ['David.Saba@mt.gov']

LOOKBACK_MINUTES = 1680
REQUEST_TIMEOUT  = 60

IDX_NOW  = -1
IDX_1HR  = -4
IDX_DAY  = -96

REQUIRED_COLS = ['SiteName', 'LowAlarm', 'HighAlarm', 'DeltaAlarm', 'Publish']

HTML_MAX_WIDTH = 640     # px; the table is 100% wide up to this
HTML_ID_COL_PX = 92      # ID column width
HTML_VALUE_COL_PX = 96   # discharge column width; Site Name gets the rest
HTML_TINT = 0.85         # how far each header color is mixed toward white for banding

SECTION_STYLES = {       # section title -> header color
    'High Discharge':             '#b42318',
    'Significant 24-hr Increase': '#b54708',
    'Low Discharge':              '#175cd3',
    'Missing / No Data':          '#475467',
}

_CELL = ('padding:6px 8px;border-bottom:1px solid #e4e7ec;font-size:14px;'
         'font-family:Arial,Helvetica,sans-serif;vertical-align:top;')
_NAME_CELL = _CELL + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'


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
    Read the discharge alarm site list from Excel.

    Structural problems (missing file or columns) raise an error. Row-level
    problems (blank/non-numeric thresholds, duplicate IDs) do not stop the
    run; they are returned as warnings and the bad check is skipped.

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

    df['Publish'] = df['Publish'].fillna(False).astype(bool)

    dupes = df.index[df.index.duplicated()]
    if len(dupes):
        warnings.append(f'Duplicate UniqueIds (first row kept): {sorted(set(dupes))}')
        df = df[~df.index.duplicated(keep='first')]

    for col in ["LowAlarm", "HighAlarm", "DeltaAlarm"]:
        raw = df[col]
        df[col] = pd.to_numeric(raw, errors="coerce")
        bad = df[df["Publish"] & df[col].isna()]
        for uid, row in bad.iterrows():
            warnings.append(
                f"{row['SiteName']} ({uid}): {col} is blank or not a number " f"({raw[uid]!r}); {col} check skipped"
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


def format_timestamp(ts: str) -> str:
    """
    Convert an AQUARIUS ISO-8601 timestamp string to 'Mon-DD HH:MM' in
    Mountain Time. Returns 'null' if the input is 'null'.
    """
    if ts == 'null':
        return 'null'
    try:
        fmt = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f0%z")
        return (fmt - dt.timedelta(hours=6)).strftime("%b-%d %H:%M")
    except ValueError:
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
        'UniqueId':            payload['UniqueId'],
        'LocationIdentifier':  payload['LocationIdentifier'],
        'SiteName':            site_meta['SiteName'],
        'Parameter':           payload['Parameter'],
        'Unit':                payload['Unit'],
        'Timestamp':           safe_timestamp(points, IDX_NOW),
        'Value':               safe_value(points, IDX_NOW),
        'Timestamp_1hr':       safe_timestamp(points, IDX_1HR),
        'Value_1hr':           safe_value(points, IDX_1HR),
        'Timestamp_day':       safe_timestamp(points, IDX_DAY),
        'Value_day':           safe_value(points, IDX_DAY),
        'Delta_Day':           '',
        'Alarm_Type':          '',
        'LowAlarm':            site_meta['LowAlarm'],
        'HighAlarm':           site_meta['HighAlarm'],
        'DeltaAlarm':          site_meta['DeltaAlarm'],
        'Publish':             site_meta['Publish'],
    }


def format_alarm_lines(alarm_list: list) -> str:
    """Format a list of alarm dicts into readable email lines."""
    if not alarm_list:
        return '  None'
    lines = []
    for entry in alarm_list:
        val = entry['value']
        val_str = f'{val} {entry["unit"]}' if val != 'null' else 'no data'
        lines.append(f'  - {entry["location_id"]}  {entry["site_name"]}  ({val_str})')
    return '\n'.join(lines)

def tint(hex_color: str, amount: float = HTML_TINT) -> str:
    """Mix a '#rrggbb' color toward white; amount=0 keeps it, 1 gives white."""
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c + (255 - c) * amount)
    return f'#{mix(r):02x}{mix(g):02x}{mix(b):02x}'


def format_value_html(entry: dict, signed: bool = False) -> str:
    """Format an alarm entry's value (e.g. '1,250 cfs', '+520 cfs', 'no data')."""
    val = entry['value']
    if val == 'null' or (val == 0 and not signed):
        return 'no data'
    try:
        num = int(val)
    except (TypeError, ValueError):
        return html_lib.escape(str(val))
    return f'{num:+,} cfs' if signed else f'{num:,} cfs'


def build_alarm_table(title: str, alarm_list: list, value_header: str,
                      signed: bool = False) -> str:
    """One alarm section as a 3-column table: ID | Site Name | Discharge.

    Fixed layout: ID and value columns have set widths and Site Name takes the
    rest, cut off with an ellipsis on narrow screens. Rows alternate between a
    light tint of the header color and no color.
    """
    color = SECTION_STYLES.get(title, '#475467')
    band = tint(color)
    head = (f'<p style="margin:18px 0 6px 0;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:16px;font-weight:bold;color:{color};">'
            f'{html_lib.escape(title)} ({len(alarm_list)})</p>')

    if not alarm_list:
        return head + ('<p style="margin:0;font-family:Arial,Helvetica,sans-serif;'
                       'font-size:14px;font-weight:bold;color:#667085;">None</p>')

    th = (
        f"padding:6px 8px;background:{color};color:#ffffff;font-size:13px;"
        f"border-bottom:1px solid #e4e7ec;"
        "font-family:Arial,Helvetica,sans-serif;text-align:left;"
    )
    rows = [
        '<tr>'
        f'<th bgcolor="{color}" style="{th}width:{HTML_ID_COL_PX}px;">ID</th>'
        f'<th bgcolor="{color}" style="{th}">Site Name</th>'
        f'<th bgcolor="{color}" style="{th}width:{HTML_VALUE_COL_PX}px;text-align:right;">'
        f'{html_lib.escape(value_header)}</th>'
        '</tr>'
    ]
    for i, entry in enumerate(alarm_list):
        loc = html_lib.escape(str(entry['location_id']))
        name = html_lib.escape(str(entry['site_name']))
        value = format_value_html(entry, signed=signed)
        bg = f' bgcolor="{band}"' if i % 2 == 0 else ''
        bg_css = f'background-color:{band};' if i % 2 == 0 else ''
        rows.append(
            '<tr>'
            f'<td{bg} style="{_CELL}{bg_css}white-space:nowrap;">{loc}</td>'
            f'<td{bg} style="{_NAME_CELL}{bg_css}" title="{name}">{name}</td>'
            f'<td{bg} style="{_CELL}{bg_css}text-align:right;white-space:nowrap;">{value}</td>'
            '</tr>'
        )

    table = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="table-layout:fixed;width:100%;max-width:{HTML_MAX_WIDTH}px;'
        f'border-collapse:collapse;">' + ''.join(rows) + '</table>'
    )
    return head + table


def build_html_body(date_label: str, high: list, delta: list,
                    low: list, no_data: list) -> str:
    """Full HTML email body with one table per alarm type."""
    sections = (
        build_alarm_table('High Discharge', high, 'Discharge')
        + build_alarm_table('Significant 24-hr Increase', delta, '24-hr Change', signed=True)
        + build_alarm_table('Low Discharge', low, 'Discharge')
        + build_alarm_table('Missing / No Data', no_data, 'Discharge')
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '</head><body style="margin:0;padding:12px;">'
        f'<div style="max-width:{HTML_MAX_WIDTH}px;">'
        '<p style="margin:0 0 4px 0;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:20px;font-weight:bold;">Discharge Alarm &mdash; {html_lib.escape(date_label)}</p>'
        + sections +
        '<p style="margin:18px 0 0 0;font-family:Arial,Helvetica,sans-serif;'
        'font-size:13px;color:#667085;">See attached CSV for full details.</p>'
        '</div></body></html>'
    )

def send_email(subject, body, recipients, from_addr,
               attachment_path=None, html_body=None):
    """Send an email via SMTP; optional HTML alternative and attachment."""
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = ', '.join(recipients)

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(body, 'plain'))
    if html_body:
        alt.attach(MIMEText(html_body, 'html'))   # last part is preferred by clients
    msg.attach(alt)

    if attachment_path and attachment_path.exists():
        attachment = MIMEBase('application', 'octet-stream')
        attachment.set_payload(attachment_path.read_bytes())
        encoders.encode_base64(attachment)
        attachment.add_header('Content-Disposition', 'attachment',
                              filename=attachment_path.name)
        msg.attach(attachment)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)


def send_failure_email() -> None:
    """
    Send a failure notification email with the full traceback.
    """
    timestamp = dt.datetime.now().strftime('%b %d, %Y %H:%M')
    error_text = traceback.format_exc()

    subject = f'StAGE Discharge Alarm FAILED — {timestamp}'
    body = (
        'The StAGE Discharge Alarm script failed to execute.\n\n'
        f'Time: {timestamp}\n'
        f'Server: {SERVER_NAME}\n'
        f'Site list: {SITE_LIST}\n\n'
        'Traceback:\n'
        f'{"=" * 80}\n'
        f'{error_text}'
    )

    send_email(subject=subject, body=body, recipients=FAILURE_RECIPIENTS, from_addr=FAILURE_EMAIL_FROM)

# =============================================================================
# MAIN
# =============================================================================
def main():
    utc_now = dt.datetime.utcnow()
    query_to = utc_now.strftime('%Y-%m-%dT%H:%M:%SZ')
    query_from = (utc_now - dt.timedelta(minutes=LOOKBACK_MINUTES)).strftime('%Y-%m-%dT%H:%M:%SZ')
    date_label = dt.datetime.now().strftime('%b %d, %Y')

    sl_df, list_warnings = load_site_list(SITE_LIST, SITE_SHEET)
    sl_df = sl_df[sl_df["Publish"]]   # will save on API calls, but won't give you everything in the output csv
    session = build_session()

    print('Acquiring discharge data...')
    records = []
    for ts_uid in tqdm(sl_df.index, desc="Sites", unit="site"):
        try:
            record = fetch_site_data(
                session,
                str(ts_uid).strip(),
                sl_df.loc[ts_uid],
                query_from,
                query_to
            )
            records.append(record)
        except Exception as exc:
            tqdm.write(f"  [SKIP] {ts_uid}: {exc}")

    today_df = pd.DataFrame(records)
    today_df.to_csv(OUTPUT_ALL, index=False)

    no_data_alarms = []
    low_flow_alarms = []
    high_flow_alarms = []
    delta_alarms = []
    alarm_rows = []

    for _, row in today_df.iterrows():
        if not row['Publish']:
            continue

        row = row.copy()
        row['Delta_Day'] = delta_24hr(row['Value'], row['Value_day'])

        entry = {
            'location_id': row['LocationIdentifier'],
            'site_name': row['SiteName'],
            'value': row['Value'],
            'unit': 'cfs',
        }

        if row["Timestamp"] == "null" or row["Value"] == 0:
            row["Alarm_Type"] = "NoData"
            no_data_alarms.append(entry)
            alarm_rows.append(row)

        elif row["Value"] < row["LowAlarm"]:
            row["Alarm_Type"] = "LowAlarm"
            low_flow_alarms.append(entry)
            alarm_rows.append(row)

        elif row["Value"] > row["HighAlarm"]:
            row["Alarm_Type"] = "HighAlarm"
            high_flow_alarms.append(entry)
            alarm_rows.append(row)

        elif row['Delta_Day'] > row['DeltaAlarm']:
            row['Alarm_Type'] = 'DeltaAlarm'
            delta_alarms.append({
                'location_id': row['LocationIdentifier'],
                'site_name': row['SiteName'],
                'value': row['Delta_Day'],
                'unit': 'cfs increase',
            })
            alarm_rows.append(row)

    error_df = pd.DataFrame(alarm_rows)
    error_df.to_csv(OUTPUT_ALARMS, index=False)

    print(f"  {len(low_flow_alarms)} site(s) reporting low flow")
    print(f"  {len(high_flow_alarms)} site(s) reporting high flow")
    print(f'  {len(delta_alarms)} site(s) reporting significant 24-hr increase')
    print(f'  {len(no_data_alarms)} site(s) missing data')

    body_text = (
        f"Discharge Alarm — {date_label}\n"
        f'{"=" * 50}\n\n'
        f"High Discharge:\n"
        f"{format_alarm_lines(high_flow_alarms)}\n\n"        
        f"Significant 24-hr Increase:\n"
        f"{format_alarm_lines(delta_alarms)}\n\n"        
        f"Low Discharge:\n"
        f"{format_alarm_lines(low_flow_alarms)}\n\n"        
        f"Missing / No Data:\n"
        f"{format_alarm_lines(no_data_alarms)}\n\n"  
        "See attached CSV for full details.\n"
    )

    html_text = build_html_body(
        date_label, high_flow_alarms, delta_alarms, low_flow_alarms, no_data_alarms
    )

    send_email(
        subject=f'StAGE Discharge Alarm — {date_label}',
        body=body_text,
        recipients=RECIPIENTS,
        from_addr=EMAIL_FROM,
        attachment_path=OUTPUT_ALARMS,
        html_body=html_text,
    )

    if list_warnings:
        print(f'  {len(list_warnings)} site list warning(s)')
        send_email(
            subject=f'StAGE Discharge Alarm site list warnings — {date_label}',
            body=(
                'The alarm ran, but these rows in the site list need fixing:\n\n'
                + '\n'.join(f'  - {w}' for w in list_warnings)
            ),
            recipients=FAILURE_RECIPIENTS,
            from_addr=FAILURE_EMAIL_FROM,
        )

    print('Email sent.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        try:
            send_failure_email()
        except Exception:
            pass
        raise
