"""Build the SQLite tracking database from existing AGOL discharge records.

This script reads the discharge measurement feature class, filters to rows where
rt_gage_site == 'Yes', and inserts every eligible record into the SQLite
tracking database using a composite unique identifier derived from
measurement_date + visitation_time + gage_site_id.

Set TRIM_LAST_N_ROWS to a positive integer to exclude that many rows from the
end of the source GeoDataFrame for debugging.
"""

import sqlite3
from pathlib import Path

import geopandas as gpd
import pandas as pd


BASE_DIRECTORY = Path(
    r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Gage_Form_Filler'
)
GDB_PATH = Path(
    r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form.gdb'
)
FEATURE_CLASS_NAME = 'WSB_Discharge_Measurement_Form_Data'
TRACKING_DB_PATH = BASE_DIRECTORY / 'db' / 'uploaded_data.sqlite'
TRACKING_TABLE_NAME = 'processed_records'
START_ROW_INDEX = 0
TRIM_LAST_N_ROWS = 5


def normalize_text(value):
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except TypeError:
        pass
    return str(value).strip()


def normalize_measurement_date(raw_value):
    parsed = pd.to_datetime(raw_value, errors='coerce')
    if pd.isna(parsed):
        return ''
    if getattr(parsed, 'tzinfo', None) is not None:
        parsed = parsed.tz_localize(None)
    return parsed.strftime('%Y-%m-%d')


def normalize_visitation_time(raw_value):
    if raw_value in [None, '']:
        return ''

    parsed = pd.to_datetime(raw_value, errors='coerce')
    if not pd.isna(parsed):
        if getattr(parsed, 'tzinfo', None) is not None:
            parsed = parsed.tz_localize(None)
        return parsed.strftime('%H:%M:%S')

    return normalize_text(raw_value)


def build_processed_at_key(measurement_date, visitation_time):
    normalized_date = normalize_measurement_date(measurement_date)
    normalized_time = normalize_visitation_time(visitation_time)

    if not normalized_date or not normalized_time:
        return ''

    return f'{normalized_date}T{normalized_time}'


def initialize_tracking_db(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TRACKING_TABLE_NAME} (
                processed_at TEXT NOT NULL,
                gage_site_id TEXT NOT NULL,
                output_pdf TEXT,
                PRIMARY KEY (processed_at, gage_site_id)
            )
            """
        )


def load_source_records():
    print('Loading feature class...')
    source_gdf = gpd.read_file(GDB_PATH, layer=FEATURE_CLASS_NAME)
    source_gdf = source_gdf.iloc[START_ROW_INDEX:].copy()

    if TRIM_LAST_N_ROWS > 0:
        if TRIM_LAST_N_ROWS >= len(source_gdf):
            raise ValueError(
                f'TRIM_LAST_N_ROWS ({TRIM_LAST_N_ROWS}) removes all available rows.'
            )
        source_gdf = source_gdf.iloc[:-TRIM_LAST_N_ROWS].copy()
        print(f'Trimmed last {TRIM_LAST_N_ROWS} rows for debugging.')

    return source_gdf


def select_records(source_gdf):
    required_fields = ['rt_gage_site', 'gage_site_id', 'measurement_date', 'visitation_time']
    missing_fields = [field for field in required_fields if field not in source_gdf.columns]
    if missing_fields:
        raise KeyError(
            f'Missing required field(s): {missing_fields}. '
            f'Available columns are: {list(source_gdf.columns)}'
        )

    selected = source_gdf[source_gdf['rt_gage_site'] == 'Yes'].copy()

    selected['processed_at_key'] = selected.apply(
        lambda row: build_processed_at_key(
            row.get('measurement_date', ''),
            row.get('visitation_time', ''),
        ),
        axis=1,
    )
    selected['gage_site_id_key'] = selected['gage_site_id'].apply(normalize_text)

    selected = selected[
        (selected['processed_at_key'] != '') &
        (selected['gage_site_id_key'] != '')
    ].copy()

    return selected


def insert_records(db_path, records_df):
    rows = [
        (
            row['processed_at_key'],
            row['gage_site_id_key'],
            ''
        )
        for _, row in records_df.iterrows()
    ]

    with sqlite3.connect(db_path) as conn:
        cursor = conn.executemany(
            f"""
            INSERT OR IGNORE INTO {TRACKING_TABLE_NAME} (
                processed_at,
                gage_site_id,
                output_pdf
            )
            VALUES (?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return cursor.rowcount


def main():
    initialize_tracking_db(TRACKING_DB_PATH)
    source_gdf = load_source_records()
    selected_records = select_records(source_gdf)

    print(f"Source rows after trimming: {len(source_gdf)}")
    print(f"Eligible records: {len(selected_records)}")
    inserted = insert_records(TRACKING_DB_PATH, selected_records)
    print(f"Inserted records: {inserted}")


if __name__ == '__main__':
    main()