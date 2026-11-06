"""
AQUARIUS time-series snapshot tool
==================================
Pulls the latest value for a set of AQUARIUS time series and writes them to a
CSV. The time series can come from either:

  1. LOCATION_IDS – a list of location identifiers; every time series at each
     location is looked up automatically.
  2. TSID_CSV     – a CSV with a 'UniqueId' column (optional 'SiteName').

Set USE_TSID_CSV to choose the source. Set FETCH_METADATA = True to also write
the full time-series description metadata to a second CSV.

Credentials are read from creds.txt (next to this script):
    AQUARIUS_USER=your_username
    AQUARIUS_PASSWORD=your_password
"""

import datetime as dt
from pathlib import Path

import pandas as pd
import requests

# =============================================================================
# CONFIG
# =============================================================================
# SERVER_NAME = 'dnrhln6386.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'

SCRIPT_DIR = Path(__file__).resolve().parent
CRED_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\creds.txt')

# --- Source of time series -------------------------------------------------
# Edit this list to add or remove locations (search by location ID).
LOCATION_IDS: list[str] = [
    '76HB 09500',
    '76HB 09600'
]

# Set True to use a CSV of time series IDs instead of LOCATION_IDS.
USE_TSID_CSV = True
TSID_CSV = SCRIPT_DIR / 'all_ids.csv'   # needs a 'UniqueId' column
TSID_COLUMN = 'ID'

# --- Options ---------------------------------------------------------------
LOOKBACK_MINUTES = 1500
REQUEST_TIMEOUT = 60
FETCH_METADATA = False                      # also save full TS descriptions

OUTPUT_DATA = SCRIPT_DIR / 'output_tsid.csv'
OUTPUT_METADATA = SCRIPT_DIR / 'output_metadata.csv'

BASE_URL = f'http://{SERVER_NAME}/AQUARIUS/Publish/v2'
TIME_FMT = '%Y-%m-%dT%H:%M:%SZ'


# =============================================================================
# HELPERS
# =============================================================================
def load_credentials(path: Path) -> dict[str, str]:
    """Read key=value lines from a text file, skipping blanks and # comments.

    Args:
        path: Location of the credentials file.

    Returns:
        Dictionary of credential names to values.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
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


def get_json(session: requests.Session, endpoint: str, params: dict) -> dict:
    """GET an AQUARIUS Publish endpoint and return the parsed JSON.

    Args:
        session: Authenticated requests session.
        endpoint: Endpoint name, e.g. 'GetTimeSeriesCorrectedData'.
        params: Query-string parameters.

    Returns:
        Decoded JSON response.
    """
    resp = session.get(f'{BASE_URL}/{endpoint}', params=params, timeout=REQUEST_TIMEOUT)
    # print(f"GET {resp.url}  ->  {resp.status_code}")
    resp.raise_for_status()
    return resp.json()


def get_tsids_for_location(session: requests.Session, location_id: str) -> list[str]:
    """Return all time series unique IDs at a location.

    Args:
        session: Authenticated requests session.
        location_id: AQUARIUS location identifier, e.g. '76F 03100'.
    """
    data = get_json(session, 'GetTimeSeriesUniqueIdList',
                    {'LocationIdentifier': location_id})
    return [item['UniqueId'] for item in data.get('TimeSeriesUniqueIds', [])]


def read_gage_csv(path: Path, column: str = TSID_COLUMN) -> pd.DataFrame:
    """Read gage (location) IDs and optional SiteName from a CSV."""
    df = pd.read_csv(path, skip_blank_lines=True, encoding='utf-8-sig', dtype=str)
    df.columns = df.columns.str.strip()
    if column not in df.columns:
        raise ValueError(f"'{column}' column not found in {path}. Columns: {list(df.columns)}")
    df = df.rename(columns={column: 'LocationIdentifier'})
    df = df.dropna(subset=['LocationIdentifier'])
    df['LocationIdentifier'] = df['LocationIdentifier'].str.strip()
    df = df[df['LocationIdentifier'] != '']
    if 'SiteName' not in df.columns:
        df['SiteName'] = ''
    return df[['LocationIdentifier', 'SiteName']].drop_duplicates('LocationIdentifier')


def collect_tsids(session: requests.Session) -> pd.DataFrame:
    """Look up every time series UniqueId for each gage ID (CSV or LOCATION_IDS)."""
    if USE_TSID_CSV:
        gages = read_gage_csv(TSID_CSV)
    else:
        gages = pd.DataFrame({'LocationIdentifier': LOCATION_IDS, 'SiteName': ''})

    rows = []
    for gage in gages.itertuples(index=False):
        try:
            tsids = get_tsids_for_location(session, gage.LocationIdentifier)
        except requests.RequestException as exc:
            print(f'  [SKIP] {gage.LocationIdentifier}: {exc}')
            continue
        print(f'{gage.LocationIdentifier}: {len(tsids)} time series')
        rows.extend({'UniqueId': t, 'SiteName': gage.SiteName} for t in tsids)
    return pd.DataFrame(rows, columns=['UniqueId', 'SiteName']).drop_duplicates('UniqueId')


def fetch_latest_point(session: requests.Session, tsid: str, site_name: str,
                       query_from: str, query_to: str) -> dict:
    """Get the most recent corrected data point for one time series.

    Args:
        session: Authenticated requests session.
        tsid: Time series unique ID.
        site_name: Display name to include in the output row.
        query_from: Start of the query window (UTC, ISO format).
        query_to: End of the query window (UTC, ISO format).

    Returns:
        One output row. Timestamp and Value are None if no data was returned.
    """
    data = get_json(session, 'GetTimeSeriesCorrectedData', {
        'TimeSeriesUniqueId': tsid,
        'QueryFrom': query_from,
        'QueryTo': query_to,
    })
    points = data.get('Points') or []
    timestamp, value = None, None
    if points:
        timestamp = points[-1].get('Timestamp')
        value = (points[-1].get('Value') or {}).get('Numeric')

    return {
        'UniqueId': data['UniqueId'],
        'LocationIdentifier': data['LocationIdentifier'],
        'SiteName': site_name,
        'Parameter': data['Parameter'],
        'Timestamp': timestamp,
        'Value': value,
        'Unit': data['Unit'],
        'Publish': data.get('Label'),
    }


def fetch_metadata(session: requests.Session, tsids: list[str]) -> pd.DataFrame:
    """Get full time series descriptions for a list of unique IDs.

    Args:
        session: Authenticated requests session.
        tsids: Time series unique IDs.

    Returns:
        Flattened DataFrame of the AQUARIUS time series descriptions.
    """
    data = get_json(session, 'GetTimeSeriesDescriptionListByUniqueId',
                    {'TimeSeriesUniqueIds': ','.join(tsids)})
    return pd.json_normalize(data.get('TimeSeriesDescriptions', []))


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    """Query the latest value for each time series and write the CSV outputs."""
    utc_now = dt.datetime.now(dt.timezone.utc)
    query_to = utc_now.strftime(TIME_FMT)
    query_from = (utc_now - dt.timedelta(minutes=LOOKBACK_MINUTES)).strftime(TIME_FMT)

    session = build_session()
    ts_df = collect_tsids(session)
    print(f'{len(ts_df)} time series to query')

    records = []
    for row in ts_df.itertuples(index=False):
        try:
            records.append(fetch_latest_point(
                session, row.UniqueId, row.SiteName, query_from, query_to))
        except requests.RequestException as exc:
            print(f'  [SKIP] {row.UniqueId}: {exc}')

    pd.DataFrame(records).to_csv(OUTPUT_DATA, index=False)
    print(f'Wrote {OUTPUT_DATA}')

    if FETCH_METADATA and not ts_df.empty:
        meta_df = fetch_metadata(session, ts_df['UniqueId'].tolist())
        meta_df.to_csv(OUTPUT_METADATA, index=False)
        print(f'Wrote {OUTPUT_METADATA}')


if __name__ == '__main__':
    main()
