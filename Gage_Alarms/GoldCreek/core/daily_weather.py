"""
Gold Creek Daily Weather Summary
================================
Pulls the last ~30 hours of weather-station data from AQUARIUS and emails a
daily summary: a one-line headline, an optional colored weather banner,
current/overnight conditions, yesterday's conditions, and year-to-date
precipitation. The email is sent as HTML with a plain-text fallback.

Inputs
------
sensor_list.xlsx (sheet 'sensor_list') with at least these columns:
    UniqueId  – AQUARIUS TimeSeriesUniqueId
    Publish   – Boolean; True = pull this time series

Expected AQUARIUS parameters among the published series:
    'Air Temp', 'Precip Cumul', 'Wind Dir', 'Wind Vel'

Credentials are read from creds.txt next to this script:
    AQUARIUS_USER=your_username
    AQUARIUS_PASSWORD=your_password

Outputs
-------
today_data.csv – Long-format snapshot of every point pulled
"""

import datetime as dt
import random
import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from typing import NamedTuple, Optional

import numpy as np
import pandas as pd
import requests

# =============================================================================
# CONFIG
# =============================================================================
# SERVER_NAME = 'dnrhln6386.state.mt.ads'
# SERVER_NAME = 'ENTDNR0101'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'

CRED_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\creds.txt')

DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Gage_Alarms\GoldCreek')
SITE_LIST = DIRECTORY / 'SensorList.xlsx'
SITE_SHEET = 'sensor_list'
OUTPUT_DATA = DIRECTORY / 'outputs' / 'today_data.csv'

SMTP_HOST = 'mail.mt.gov'
SMTP_PORT = 25
EMAIL_FROM = 'WeatherStation@dnrc.mt.gov'
FAILURE_EMAIL_FROM = 'WeatherStation_Failure@dnrc.mt.gov'

RECIPIENTS = [
    'bruce@thomasherefords.com',
    'David.Saba@mt.gov',
    'Hannah.Haugen@mt.gov',
]

FAILURE_RECIPIENTS = ['David.Saba@mt.gov']

LOCAL_TZ = 'America/Denver'
LOOKBACK_MINUTES = 1820     # must reach back past midnight yesterday
REQUEST_TIMEOUT = 60
PRECIP_DISPLAY_UNIT = 'in'  # label shown in the email for precipitation

P_TEMP = 'Air Temp'
P_PRECIP = 'Precip Cumul'
P_WDIR = 'Wind Dir'
P_WVEL = 'Wind Vel'

# Banner thresholds (in the sensor's own units, same as the original script)
COLD_BELOW = 0
HOT_AT_OR_ABOVE = 95
WET_AT_OR_ABOVE = 1

# Maps AQUARIUS unit strings to display labels (anything not listed is shown as-is)
UNIT_LABELS = {
    'degF': '°F',
    'degC': '°C',
    'deg F': '°F',
    'deg C': '°C',
    'ft^3/s': 'cfs',
    'deg': '°',
}

# kind -> (message, background color, text/border color)
BANNERS = {
    'cold': ("Don't Forget to Put Your Long Johns On!", '#dbeafe', '#1e40af'),
    'hot':  ("WOOOOOOEEEEEE It's Hot", '#fee2e2', '#991b1b'),
    'wet':  ("Don't Forget to Blow Dry The Cows", '#ccfbf1', '#115e59'),
}

COMPASS = ['North', 'NorthEast', 'East', 'SouthEast',
           'South', 'SouthWest', 'West', 'NorthWest']

PLEASANTRIES = list(dict.fromkeys([   # dict.fromkeys drops duplicates
    'agreeable', 'amiable', 'amusing', 'sublime', 'charming', 'cheerful',
    'congenial', 'cool', 'cordial', 'delightful', 'engaging', 'enjoyable',
    'fun', 'homey', 'likable', 'lovely', 'mild', 'pleasing', 'pleasurable',
    'refreshing', 'satisfying', 'sweet', 'affable', 'civil', 'civilized',
    'copacetic', 'delectable', 'diplomatic', 'enchanting', 'fine',
    'fine and dandy', 'admissible', 'all right', 'average', 'big',
    'cooking with gas', 'hep', 'hip', 'hunky-dory', 'in the swim', 'kosher',
    'large', 'okay', 'on the ball', 'passable', 'peachy keen', 'right on',
    'standard', 'swell', 'trendy', 'unexceptional', 'unobjectionable',
    'up to code', 'up to snuff', 'A-OK', 'dandy', 'genial', 'good-humored',
    'gratifying', 'jolly', 'jovial', 'kindly', 'mild-mannered', 'nice',
    'obliging', 'social', 'urbane', 'cultured', 'suave', 'cosmopolitan',
    'elegant', 'genteel', 'metropolitan', 'mannerly', 'astonishing',
    'astounding', 'breathtaking', 'colossal', 'dynamite', 'fab', 'fabulous',
    'fantastic', 'fat', 'gigantic', 'great', 'huge', 'marvelous',
    'mind-blowing', 'mind-boggling', 'miraculous', 'monster', 'monumental',
    'phenomenal', 'prodigious', 'radical', 'smashing', 'spectacular',
    'staggering', 'stunning', 'super', 'superb', 'surprising', 'terrific',
    'titanic', 'tremendous', 'unreal', 'utmost', 'wondrous', 'punctual',
    'scrupulous', 'heedful', 'upright', 'meticulous', 'punctilious',
]))


# =============================================================================
# CREDENTIALS, SITE LIST, SESSION
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
    """Create a requests session authenticated with creds.txt credentials."""
    creds = load_credentials(CRED_FILE)
    session = requests.Session()
    session.auth = (creds['AQUARIUS_USER'], creds['AQUARIUS_PASSWORD'])
    return session


def load_site_list(path: Path, sheet: str) -> pd.DataFrame:
    """
    Read the sensor list from Excel and return only the published rows.

    Raises:
        FileNotFoundError: If the workbook does not exist.
        ValueError: If 'UniqueId' or 'Publish' columns are missing.
    """
    if not path.exists():
        raise FileNotFoundError(f'Site list not found: {path}')
    df = pd.read_excel(path, sheet_name=sheet, engine='openpyxl')
    df = df.dropna(how='all')

    missing = [c for c in ('UniqueId', 'Publish') if c not in df.columns]
    if missing:
        raise ValueError(f'Site list is missing columns: {missing}')

    df['UniqueId'] = df['UniqueId'].astype(str).str.strip()
    df['Publish'] = df['Publish'].fillna(False).astype(bool)
    return df[df['Publish']].reset_index(drop=True)


# =============================================================================
# AQUARIUS ACCESS
# =============================================================================
def parse_timestamp(ts: str) -> pd.Timestamp:
    """Parse an AQUARIUS ISO-8601 timestamp into a Mountain Time Timestamp."""
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize('UTC')
    return stamp.tz_convert(LOCAL_TZ)


def fetch_series(session: requests.Session, tsid: str,
                 query_from: str, query_to: str) -> tuple[str, str, pd.Series]:
    """
    Get corrected data for one time series.

    Returns:
        (parameter name, unit, Series of float values indexed by local time)
    """
    resp = session.get(
        f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
        params={'TimeSeriesUniqueId': tsid, 'QueryFrom': query_from, 'QueryTo': query_to},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    times, values = [], []
    for point in payload.get('Points') or []:
        numeric = (point.get('Value') or {}).get('Numeric')
        if numeric is None:
            continue
        times.append(parse_timestamp(point['Timestamp']))
        values.append(float(numeric))

    series = pd.Series(values, index=pd.DatetimeIndex(times), dtype=float).sort_index()
    series = series[~series.index.duplicated(keep='last')]
    return payload['Parameter'], payload['Unit'], series


def collect_data(session: requests.Session, tsids: list[str], query_from: str,
                 query_to: str) -> tuple[dict[str, pd.Series], dict[str, str], pd.DataFrame]:
    """
    Pull every time series and organize the results by parameter.

    Returns:
        series_by_param: {parameter: Series indexed by local time}
        units: {parameter: unit}
        long_df: all points as Parameter/Unit/Time/Value rows (for the CSV)
    """
    series_by_param: dict[str, pd.Series] = {}
    units: dict[str, str] = {}
    frames = []

    for tsid in tsids:
        param, unit, series = fetch_series(session, tsid, query_from, query_to)
        if param in series_by_param:
            series = pd.concat([series_by_param[param], series]).sort_index()
            series = series[~series.index.duplicated(keep='last')]
        series_by_param[param] = series
        units[param] = unit
        frames.append(pd.DataFrame({
            'Parameter': param, 'Unit': unit,
            'Time': series.index.strftime('%Y-%m-%d %H:%M'), 'Value': series.values,
        }))

    long_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return series_by_param, units, long_df


# =============================================================================
# CALCULATIONS
# =============================================================================
Result = Optional[tuple[float, pd.Timestamp]]   # (value, time) or None
Row = tuple[str, str, str]                      # (label, value text, time text)


def compass_direction(deg: float) -> str:
    """Convert degrees (0-360) to one of eight compass names."""
    return COMPASS[int(((deg % 360) + 22.5) // 45) % 8]


def circular_mean_deg(degrees: pd.Series) -> float:
    """Average compass bearings correctly (e.g. 350 and 10 average to 0)."""
    rad = np.radians(degrees.to_numpy())
    return float(np.degrees(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360)


def on_date(series: pd.Series, day: dt.date) -> pd.Series:
    """Return the part of a series that falls on a local calendar date."""
    return series[series.index.date == day]


def latest(series: pd.Series) -> Result:
    """Most recent (value, time) in a series, or None if empty."""
    if series.empty:
        return None
    return float(series.iloc[-1]), series.index[-1]


def extreme(series: pd.Series, kind: str) -> Result:
    """Max or min (value, time) of a series; kind is 'max' or 'min'."""
    if series.empty:
        return None
    idx = series.idxmax() if kind == 'max' else series.idxmin()
    return float(series[idx]), idx


def change(series: pd.Series) -> Optional[float]:
    """Last minus first value (for a cumulative series), or None if empty."""
    if series.empty:
        return None
    return float(series.iloc[-1] - series.iloc[0])


# =============================================================================
# REPORT BUILDING
# =============================================================================
class Report(NamedTuple):
    """Everything needed to render the email."""
    summary: str
    banner: Optional[str]                 # key into BANNERS, or None
    sections: dict[str, list[Row]]


def fmt_time(ts: pd.Timestamp) -> str:
    """Format a timestamp as 12-hour time, e.g. '7:15 AM' (no leading zero)."""
    return f"{ts.hour % 12 or 12}:{ts.minute:02d} {'AM' if ts.hour < 12 else 'PM'}"


def pretty_unit(unit: str) -> str:
    """Return a display label for an AQUARIUS unit string."""
    return UNIT_LABELS.get(unit, unit)


def stat_row(label: str, result: Result, unit: str, decimals: int = 0) -> Row:
    """Row of (label, 'value unit', 'HH:MM'), or 'no data' if result is None."""
    if result is None:
        return label, 'no data', ''
    value, when = result
    return label, f'{value:.{decimals}f} {unit}', fmt_time(when)


def value_row(label: str, value: Optional[float], unit: str, decimals: int = 0) -> Row:
    """Row of (label, 'value unit', ''), or 'no data' if value is None."""
    if value is None:
        return label, 'no data', ''
    return label, f'{value:.{decimals}f} {unit}', ''


def direction_row(label: str, deg: Optional[float], unit: str) -> Row:
    """Row of (label, 'North (355 deg)', ''), or 'no data' if deg is None."""
    if deg is None:
        return label, 'no data', ''
    return label, f'{compass_direction(deg)} ({deg:.0f}{unit})', ''


def random_valediction() -> str:
    """Return a randomized closing such as 'Have a delightful day!'."""
    adj = random.choice(PLEASANTRIES)
    article = 'an' if adj[0].lower() in 'aeiou' else 'a'
    return f'Have {article} {adj} day!'


def pick_banner(current_temp: Optional[float], yesterday_max: Optional[float],
                daily_precip: Optional[float]) -> Optional[str]:
    """
    Choose the weather banner key ('cold', 'hot', 'wet') or None.

    Later conditions override earlier ones: wet > hot > cold.
    """
    banner = None
    if current_temp is not None and current_temp < COLD_BELOW:
        banner = 'cold'
    if yesterday_max is not None and yesterday_max >= HOT_AT_OR_ABOVE:
        banner = 'hot'
    if daily_precip is not None and daily_precip >= WET_AT_OR_ABOVE:
        banner = 'wet'
    return banner


def build_summary(cur_temp: Result, cur_wvel: Result, cur_wdir: Result,
                  low: Result, overnight_precip: Optional[float],
                  u_temp: str, u_wvel: str, u_precip: str) -> str:
    """Write the one-line headline shown at the top of the email."""
    now_parts = []
    if cur_temp:
        now_parts.append(f'{cur_temp[0]:.0f} {u_temp}')
    if cur_wdir and cur_wvel:
        now_parts.append(f'{compass_direction(cur_wdir[0])} wind at {cur_wvel[0]:.0f} {u_wvel}')
    elif cur_wvel:
        now_parts.append(f'wind {cur_wvel[0]:.0f} {u_wvel}')

    sentences = []
    if now_parts:
        sentences.append('Now: ' + ', '.join(now_parts) + '.')
    later = []
    if low:
        later.append(f'overnight low {low[0]:.0f} {u_temp}')
    if overnight_precip is not None:
        later.append(f'{overnight_precip:.2f} {u_precip} precipitation overnight')
    if later:
        text = '; '.join(later)
        sentences.append(text[0].upper() + text[1:] + '.')
    return ' '.join(sentences) if sentences else 'No current data available.'


def build_report(data: dict[str, pd.Series], units: dict[str, str],
                 today: dt.date) -> Report:
    """Compute all statistics and assemble them into a Report."""
    yesterday = today - dt.timedelta(days=1)
    empty = pd.Series(dtype=float)
    temp, precip = data.get(P_TEMP, empty), data.get(P_PRECIP, empty)
    wdir, wvel = data.get(P_WDIR, empty), data.get(P_WVEL, empty)
    u_temp = pretty_unit(units.get(P_TEMP, ""))
    u_wvel = pretty_unit(units.get(P_WVEL, ""))
    u_wdir = pretty_unit(units.get(P_WDIR, ""))
    u_precip = PRECIP_DISPLAY_UNIT

    # --- This morning ---------------------------------------------------
    cur_temp, cur_wvel, cur_wdir = latest(temp), latest(wvel), latest(wdir)
    t_today, p_today, w_today = on_date(temp, today), on_date(precip, today), on_date(wvel, today)
    overnight_low = extreme(t_today, 'min')
    overnight_precip = change(p_today)

    morning = [
        stat_row('Current Temp', cur_temp, u_temp),
        stat_row('Overnight Low', overnight_low, u_temp),
        value_row('Overnight Precip', overnight_precip, u_precip, 2),
        stat_row('Current Wind', cur_wvel, u_wvel),
        direction_row('Current Wind Dir', cur_wdir[0] if cur_wdir else None, u_wdir),
        stat_row('Overnight Max Wind', extreme(w_today, 'max'), u_wvel),
    ]

    # --- Yesterday ------------------------------------------------------
    t_yes, p_yes = on_date(temp, yesterday), on_date(precip, yesterday)
    w_yes, d_yes = on_date(wvel, yesterday), on_date(wdir, yesterday)
    max_temp = extreme(t_yes, 'max')
    daily_precip = change(p_yes)
    avg_dir = circular_mean_deg(d_yes) if not d_yes.empty else None
    avg_wvel = float(w_yes.mean()) if not w_yes.empty else None

    yesterday_rows = [
        stat_row('High Temp', max_temp, u_temp),
        stat_row('Low Temp', extreme(t_yes, 'min'), u_temp),
        value_row('Precip', daily_precip, u_precip, 2),
        stat_row('Max Wind', extreme(w_yes, 'max'), u_wvel),
        value_row('Ave Wind', avg_wvel, u_wvel),
        direction_row('Ave Wind Dir', avg_dir, u_wdir),
    ]

    # --- Year to date ---------------------------------------------------
    ytd = latest(precip)
    ytd_rows = [value_row('YTD precipitation', ytd[0] if ytd else None, u_precip, 2)]

    summary = build_summary(cur_temp, cur_wvel, cur_wdir, overnight_low,
                            overnight_precip, u_temp, u_wvel, u_precip)
    banner = pick_banner(
        cur_temp[0] if cur_temp else None,
        max_temp[0] if max_temp else None,
        daily_precip,
    )
    sections = {
        f'This Morning ({today:%a, %b-%d})': morning,
        f'Yesterday ({yesterday:%a, %b-%d})': yesterday_rows,
        'Year to Date': ytd_rows,
    }
    return Report(summary, banner, sections)


# =============================================================================
# RENDERING
# =============================================================================
def render_text(title: str, report: Report, closing: str) -> str:
    """Render the report as plain text (fallback for non-HTML mail clients)."""
    out = [title, '=' * len(title), '', report.summary, '']
    if report.banner:
        out += [f'*** {BANNERS[report.banner][0]} ***', '']
    for heading, rows in report.sections.items():
        out += [heading, '-' * len(heading)]
        for label, value, when in rows:
            out.append(f'{label}: {value}' + (f' ({when})' if when else ''))
        out.append('')
    out.append(closing)
    return '\n'.join(out)


def render_html(title: str, report: Report, closing: str) -> str:
    """Render the report as an HTML email with a banner and one table per section."""
    font = 'font-family:Calibri,Arial,sans-serif'
    parts = [
        f'<div style="{font};max-width:560px">',
        f'<h2 style="margin-bottom:6px">{escape(title)}</h2>',
        f'<p style="font-size:16px;margin-top:0">{escape(report.summary)}</p>',
    ]
    if report.banner:
        message, bg, fg = BANNERS[report.banner]
        parts.append(
            f'<div style="background:{bg};color:{fg};border-left:6px solid {fg};'
            f'padding:10px 14px;font-weight:bold;font-size:16px;margin:12px 0">'
            f'{escape(message)}</div>'
        )
    for heading, rows in report.sections.items():
        parts.append(f'<h3 style="margin:18px 0 4px">{escape(heading)}</h3>')
        parts.append('<table style="border-collapse:collapse;width:100%">')
        for i, (label, value, when) in enumerate(rows):
            bg = '#f2f6fa' if i % 2 else '#ffffff'
            parts.append(
                f'<tr style="background:{bg}">'
                f'<td style="padding:4px 14px 4px 6px">{escape(label)}</td>'
                f'<td style="padding:4px 14px"><b>{escape(value)}</b></td>'
                f'<td style="padding:4px 6px;color:#666;text-align:right">{escape(when)}</td>'
                f'</tr>'
            )
        parts.append('</table>')
    parts.append(f'<p style="margin-top:18px">{escape(closing)}</p></div>')
    return '\n'.join(parts)


# =============================================================================
# EMAIL
# =============================================================================
def send_email(subject: str, body: str, recipients: list[str], from_addr: str,
               html: Optional[str] = None) -> None:
    """
    Send an email through the configured SMTP server.

    Args:
        subject: Subject line.
        body: Plain-text body (also the fallback when html is given).
        recipients: List of recipient addresses.
        from_addr: Sender address.
        html: Optional HTML body; mail clients prefer it over the plain text.
    """
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    if html:
        msg.attach(MIMEText(html, 'html', 'utf-8'))   # last part is the preferred one

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)


def send_failure_email() -> None:
    """Email the full traceback of the current exception to FAILURE_RECIPIENTS."""
    stamp = dt.datetime.now().strftime('%b %d, %Y %H:%M')
    body = (
        'The Gold Creek weather summary script failed.\n\n'
        f'Time: {stamp}\nServer: {SERVER_NAME}\nSite list: {SITE_LIST}\n\n'
        f'Traceback:\n{"=" * 80}\n{traceback.format_exc()}'
    )
    send_email(f'Gold Creek Weather Summary FAILED — {stamp}', body,
               FAILURE_RECIPIENTS, FAILURE_EMAIL_FROM)


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    """Pull station data, write the CSV snapshot, and send the daily email."""
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    utc_now = dt.datetime.now(dt.timezone.utc)
    query_to = utc_now.strftime(fmt)
    query_from = (utc_now - dt.timedelta(minutes=LOOKBACK_MINUTES)).strftime(fmt)
    today = pd.Timestamp.now(tz=LOCAL_TZ).date()

    sites = load_site_list(SITE_LIST, SITE_SHEET)
    session = build_session()

    print('Acquiring StAGE data...')
    data, units, long_df = collect_data(session, sites['UniqueId'].tolist(),
                                        query_from, query_to)
    OUTPUT_DATA.parent.mkdir(parents=True, exist_ok=True)
    long_df.to_csv(OUTPUT_DATA, index=False)

    report = build_report(data, units, today)
    title = f'Daily Weather Summary, {today:%a %b %d}'
    closing = random_valediction()
    text_body = render_text(title, report, closing)
    print(text_body)

    send_email(f'Daily Weather Summary {today:%b %d, %Y}', text_body,
               RECIPIENTS, EMAIL_FROM, html=render_html(title, report, closing))
    print('email sent')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        try:
            send_failure_email()
        except Exception:
            pass
        raise
