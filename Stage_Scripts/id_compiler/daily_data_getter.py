import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError, Timeout, ConnectionError, RequestException
from urllib3.util.retry import Retry
from pathlib import Path
from datetime import datetime as dt
from tqdm import tqdm
import time
import re
import json

# =============================================================================
# CONFIG
# =============================================================================
# SERVER_NAME = 'dnrhln6386.state.mt.ads'
SERVER_NAME  = 'dnrc-mt-prod.aquaticinformatics.net'
USER_NAME    = 'DNRC'
PASSWORD     = 'DNRC'

DIRECTORY       = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Stage_Scripts\id_compiler')
INPUT_CSV       = DIRECTORY / 'daily_averages.csv'
OUTPUT_PARQUET  = DIRECTORY / 'daily_discharge_history.parquet'
ERROR_LOG       = DIRECTORY / 'daily_discharge_errors.csv'

TIME_START      = '01-01-1901'
TIME_END        = '04-01-2026'
REQUEST_TIMEOUT = 300
PAUSE_SECONDS   = 15

# =============================================================================
# HELPERS
# =============================================================================
def dt_format(mdy):
    """Convert DD-MM-YYYY to AQUARIUS ISO query string."""
    return dt.strptime(mdy, "%d-%m-%Y").strftime("%Y-%m-%dT%H:%M:%SZ")


def build_session():
    """Requests session with automatic retry on transient errors."""
    retry = Retry(
        total=5,
        read=5,
        connect=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.auth = (USER_NAME, PASSWORD)
    return session


def get_points(session, ts_uid, query_from, query_to):
    """Pull corrected time-series points from AQUARIUS Publish API."""
    params = {
        'TimeSeriesUniqueId': ts_uid,
        'QueryFrom': query_from,
        'QueryTo':   query_to,
    }
    resp = session.get(
        url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    payload = resp.json()
    # print(json.dumps(payload, indent=4))
    return payload


def normalize_aquarius_timestamp(ts):
    """
    Handle AQUARIUS timestamps like:
      2024-10-01T24:00:00.0000000-07:00
    by rolling them to:
      2024-10-02T00:00:00.0000000-07:00
    """
    if pd.isna(ts):
        return ts

    ts = str(ts).strip()

    if 'T24:' not in ts:
        return ts

    m = re.match(r'(\d{4}-\d{2}-\d{2})T24:(\d{2}:\d{2}\.\d+)([+-]\d{2}:\d{2})$', ts)
    if not m:
        return ts

    date_part, rest_part, tz_part = m.groups()
    next_day = pd.to_datetime(date_part) + pd.Timedelta(days=1)
    return f"{next_day.strftime('%Y-%m-%d')}T00:{rest_part}{tz_part}"


def points_to_df(payload, ts_uid):
    """
    Flatten the Points list from an AQUARIUS response into a tidy DataFrame.

    Columns returned:
        site_id           – TimeSeriesUniqueId
        location_id       – LocationIdentifier  (e.g. '41H 08900')
        parameter         – Parameter label      (e.g. 'Discharge')
        unit              – Unit string          (e.g. 'ft3s')
        timestamp         – original AQ timestamp string (tz-aware)
        timestamp_utc     – parsed UTC datetime
        date              – date only (local calendar day from timestamp)
        day_of_year       – 1-366
        water_year        – Oct 1 rollover
        discharge         – float (ft3/s)
    """
    points = payload.get('Points', [])
    if not points:
        return pd.DataFrame()

    rows = [{
        'site_id':     ts_uid,
        'location_id': payload.get('LocationIdentifier', ''),
        'parameter':   payload.get('Parameter', ''),
        'unit':        payload.get('Unit', ''),
        'timestamp':   pt.get('Timestamp'),
        'discharge':   pt.get('Value', {}).get('Numeric'),
    } for pt in points]

    df = pd.DataFrame(rows)

    # Parse timestamps
    df["timestamp"] = df["timestamp"].apply(normalize_aquarius_timestamp)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp"], format="%Y-%m-%dT%H:%M:%S.%f%z", utc=True, errors="coerce")
    df["discharge"] = pd.to_numeric(df["discharge"], errors="coerce")
    df = df.dropna(subset=['timestamp_utc']).copy()

    # Calendar date from local time embedded in the offset string
    df['date']        = df['timestamp_utc'].dt.tz_convert('America/Denver').dt.normalize()
    df['day_of_year'] = df['timestamp_utc'].dt.tz_convert('America/Denver').dt.day_of_year
    df['water_year']  = df['timestamp_utc'].dt.tz_convert('America/Denver').dt.year
    df.loc[df['timestamp_utc'].dt.tz_convert('America/Denver').dt.month >= 10, 'water_year'] += 1

    return df


# =============================================================================
# MAIN
# =============================================================================
def main():
    dt_s = dt_format(TIME_START)
    dt_e = dt_format(TIME_END)

    print("Loading site list...")
    sl_df   = pd.read_csv(INPUT_CSV, index_col=0, skip_blank_lines=True)
    site_ids = [str(i).strip() for i in sl_df.index if pd.notna(i)]
    print(f"  {len(site_ids)} time-series IDs loaded.\n")

    session    = build_session()
    all_frames = []
    errors     = []

    print("Pulling discharge history from AQUARIUS...")
    for ts_uid in tqdm(site_ids, desc="Sites", unit="site"):
        try:
            payload = get_points(session, ts_uid, dt_s, dt_e)
            df      = points_to_df(payload, ts_uid)

            if df.empty:
                errors.append({'site_id': ts_uid, 'error_type': 'NoData',
                                'message': 'No points returned'})
                tqdm.write(f"  [NoData]  {ts_uid}")
            else:
                all_frames.append(df)
                tqdm.write(f"  [OK]      {ts_uid}  |  {payload.get('LocationIdentifier','')}  |  {len(df)} rows")

        except (HTTPError, Timeout, ConnectionError, RequestException) as exc:
            errors.append({'site_id': ts_uid, 'error_type': type(exc).__name__,
                           'message': str(exc)})
            tqdm.write(f"  [ERROR]   {ts_uid}  {type(exc).__name__}: {exc}")

        time.sleep(PAUSE_SECONDS)

    # -------------------------------------------------------------------------
    # Write outputs
    # -------------------------------------------------------------------------
    if all_frames:
        out_df = (pd.concat(all_frames, ignore_index=True)
                    .sort_values(['site_id', 'timestamp_utc'])
                    .reset_index(drop=True))

        out_df.to_parquet(OUTPUT_PARQUET, index=False, engine='pyarrow')
        print(f"\nParquet saved  → {OUTPUT_PARQUET}")
        print(f"  Total rows   : {len(out_df):,}")
        print(f"  Total sites  : {out_df['site_id'].nunique():,}")
        print(f"  Date range   : {out_df['date'].min()}  →  {out_df['date'].max()}")
    else:
        print("\nNo data retrieved – parquet not written.")

    if errors:
        err_df = pd.DataFrame(errors)
        err_df.to_csv(ERROR_LOG, index=False)
        print(f"Error log saved → {ERROR_LOG}  ({len(errors)} entries)")

    print("\nDone.")


if __name__ == '__main__':
    main()
