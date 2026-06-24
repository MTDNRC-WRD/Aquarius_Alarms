"""Generate discharge form PDFs from AGOL geodatabase records.

This script reads discharge measurement records from a file geodatabase,
maps record fields into an Excel template, exports PDFs, and logs each
successfully processed record to a SQLite tracking database.

The script intentionally ignores all source rows before START_ROW_INDEX.
"""

import datetime as dt
import os
import shutil
import smtplib
import sqlite3
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aspose.cells
import geopandas as gpd
import openpyxl
import pandas as pd
from aspose.cells import SaveFormat


BASE_DIRECTORY = Path(
    r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\AGOL_to_Aq'
)
OUTPUT_DIRECTORY = Path(
    r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Water_Management\Electronic Field Forms'
)
GDB_PATH = Path(
    r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form.gdb'
)
FEATURE_CLASS_NAME = 'WSB_Discharge_Measurement_Form_Data'
TRACKING_DB_PATH = BASE_DIRECTORY / 'uploaded_data.sqlite'
TRACKING_TABLE_NAME = 'processed_records'
GAGE_LIST_PATH = BASE_DIRECTORY / 'gage_list.csv'
TEMPLATE_XLSX_PATH = BASE_DIRECTORY / 'DNRC_Qm_Form_live.xlsx'
TEMP_XLSX_PATH = BASE_DIRECTORY / 'DNRC-Qm_Form_temp.xlsx'
EMAIL_RECIPIENTS = 'David.Saba@mt.gov'
START_ROW_INDEX = 1090
WORKSHEET_NAME = 'Table 1'

CELL_FIELD_MAP = {
    'A2': 'gage_site_id',
    'AL1': 'measurement_id_number',
    'AL2': 'hydro_name',
    'T5': 'party_initials',
    'F4': '',
    'F5': 'measurement_date',
    'A7': 'cross_section_width',
    'D7': 'cross_section_area',
    'N7': 'ave_velocity_measured',
    'T7': '',
    'Z7': 'number_of_measurements',
    'AH7': 'Measured_Discharge',
    'A9': 'measurement_type',
    'I9': 'rate_num',
    'Q9': 'shift_ft',
    'AF9': 'time_of_discharge_measurement',
    'A11': 'sensor_temp_reading',
    'G11': 'measured_temperature_f',
    'N11': 'water_temperature_f',
    'T11': 'weather',
    'AB11': 'air_temperature_f',
    'AF11': 'wind_est',
    'AL11': 'wind_direction',
    'AN2': 'location_notes',
    'G13': 'reference_gage_type',
    'A14': 'gage_reading_time_1',
    'G14': 'reference_gage_1',
    'T14': 'recording_gage_1',
    'A15': 'gage_reading_time_2',
    'G15': 'reference_gage_2',
    'T15': 'recording_gage_2',
    'A16': 'gage_reading_time_3',
    'G16': 'reference_gage_3',
    'T16': 'recording_gage_3',
    'A17': 'gage_reading_time_4',
    'G17': 'reference_gage_4',
    'T17': 'recording_gage_4',
    'A18': 'gage_reading_time_5',
    'G18': 'reference_gage_5',
    'T18': 'recording_gage_5',
    'A19': 'gage_reading_time_6',
    'G19': 'reference_gage_6',
    'T19': 'recording_gage_6',
    'A20': 'gage_reading_time_7',
    'G20': 'reference_gage_7',
    'T20': 'recording_gage_7',
    'A21': 'gage_reading_time_8',
    'G21': 'reference_gage_8',
    'T21': 'recording_gage_8',
    'A23': 'gage_height_correction_ft',
    'AC24': 'checkbar_changed_to_ft',
    'H25': 'measurement_notes',
    'H28': 'measurement_error',
    'C29': '_control',
    'B30': 'errors',
    'C31': 'photos_notes',
    'F32': 'maintenance_gage_operational',
    'Q32': 'maintenance_data_downloaded',
    'AG32': 'maintenance_desiccant_changed',
    'F33': 'battery_reading',
    'AA33': 'maintenance_orifice_purged',
    'AO14': 'initial_discharge_guess_cfs',
    'AO15': 'cross_sectional_width_ft',
    'AP15': 'width_measurement_method',
    'AO16': 'average_depth_ft',
    'AP16': 'depth_measurement_method',
    'AO17': 'approximate_surface_velocity_ft',
    'AP17': 'velocity_measurement_method',
    'AO18': 'educated_discharge_guess',
    'AO20': 'how_familiar_are_you_with_this_',
    'AO21': 'channel_type',
    'AO22': 'water_clarity',
    'AO23': 'surface_ice_',
    'AO24': 'flow_regime_',
    'AO25': 'vegetation_in_channel',
    'AO26': 'bank_vegetation',
    'AO27': 'bed_material',
    'AO28': 'cross_section_morphology',
    'AO29': 'left_bank',
    'AO30': 'right_bank',
    'E43': 'left_bank',
    'E45': 'right_bank',
    'A48': 'adcp_boat',
    'O48': 'gps_used',
    'W48': 'acdp_depth',
    'Q50': 'number_of_transects',
}

FALLBACK_FIELD_MAP = {
    'A2': '',
    'F4': 'gage_site_other',
    'C29': 'untitled_question_113_other',
    'G13': 'refrence_gage_type_other',
    'A9': 'measurem1',
    'A48': 'adcp_other',
}

GAGE_READING_CELLS = ['T14', 'T15', 'T16', 'T17', 'T18', 'T19', 'T20', 'T21']


def clean_excel_value(value):
    """Convert values into Excel-safe types.

    Args:
        value: Any source value from the GeoDataFrame row.

    Returns:
        A value safe to write with openpyxl.
    """
    if value is None:
        return ''

    try:
        if pd.isna(value):
            return ''
    except TypeError:
        pass

    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None:
            value = value.tz_localize(None)
        return value.to_pydatetime()

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    return value


def format_output_date(raw_date):
    """Convert a date-like value into YYYYMMDD text.

    Args:
        raw_date: A string, datetime, or pandas Timestamp.

    Returns:
        A YYYYMMDD string, or an empty string if parsing fails.
    """
    if raw_date in [0, '', None]:
        return ''

    parsed = pd.to_datetime(raw_date, errors='coerce')
    if pd.isna(parsed):
        return ''

    if getattr(parsed, 'tzinfo', None) is not None:
        parsed = parsed.tz_localize(None)

    return parsed.strftime('%Y%m%d')


def round_if_numeric(value, digits=2):
    """Round a numeric value if possible.

    Args:
        value: Any value.
        digits: Number of decimal places.

    Returns:
        Rounded float if numeric, otherwise original value.
    """
    try:
        if value in ['', None]:
            return value
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def load_site_name_map(csv_path):
    """Load site IDs to site names from CSV.

    Args:
        csv_path: Path to gage_list.csv.

    Returns:
        A dictionary mapping site ID to site name.
    """
    site_df = pd.read_csv(csv_path)
    return dict(zip(site_df['id'], site_df['name']))


def initialize_tracking_db(db_path):
    """Create the SQLite tracking database and table if needed.

    Args:
        db_path: Path to the SQLite database file.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TRACKING_TABLE_NAME} (
                globalid TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL,
                gage_site_id TEXT,
                output_pdf TEXT
            )
            """
        )


def fetch_processed_ids(db_path):
    """Fetch processed global IDs from the tracking database.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A set of processed globalid values.
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT globalid FROM {TRACKING_TABLE_NAME}"
        ).fetchall()

    return {str(row[0]) for row in rows}


def insert_processed_record(db_path, global_id, gage_site_id, output_pdf):
    """Insert one processed record into the tracking database.

    Args:
        db_path: Path to the SQLite database file.
        global_id: Record globalid.
        gage_site_id: Gage site identifier.
        output_pdf: Output PDF path.

    Returns:
        True if a new row was inserted, otherwise False.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            f"""
            INSERT OR IGNORE INTO {TRACKING_TABLE_NAME} (
                globalid,
                processed_at,
                gage_site_id,
                output_pdf
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(global_id),
                dt.datetime.now().isoformat(),
                str(gage_site_id),
                str(output_pdf),
            ),
        )
        return cursor.rowcount == 1


def load_source_records():
    """Load source records from the geodatabase and apply row filtering.

    Returns:
        A filtered GeoDataFrame containing only rows at or after START_ROW_INDEX.
    """
    print('Loading feature class...')
    source_gdf = gpd.read_file(GDB_PATH, layer=FEATURE_CLASS_NAME)
    source_gdf = source_gdf.iloc[START_ROW_INDEX:].copy()
    return source_gdf


def select_records_to_process(source_gdf, processed_ids):
    """Select source records eligible for processing.

    Args:
        source_gdf: Full filtered source GeoDataFrame.
        processed_ids: Set of already processed global IDs.

    Returns:
        GeoDataFrame with only new rt_gage_site == 'Yes' records.
    """
    return source_gdf[
        (source_gdf['rt_gage_site'] == 'Yes') &
        (~source_gdf['globalid'].astype(str).isin(processed_ids))
    ].copy()


def build_excel_value_map(row, site_name_map):
    """Build the Excel cell/value dictionary for a single record.

    Args:
        row: A pandas Series containing one source record.
        site_name_map: Dictionary mapping gage IDs to site names.

    Returns:
        Dictionary keyed by Excel cell reference.
    """
    excel_values = {}

    for cell_ref, field_name in CELL_FIELD_MAP.items():
        if field_name == '':
            excel_values[cell_ref] = ''
        else:
            excel_values[cell_ref] = row.get(field_name, '')

    site_id = excel_values.get('A2', '')
    excel_values['F4'] = site_name_map.get(site_id, '')

    for cell_ref, fallback_field in FALLBACK_FIELD_MAP.items():
        if excel_values.get(cell_ref, '') in ['other', '']:
            excel_values[cell_ref] = row.get(fallback_field, '') if fallback_field else ''

    gage_values = []
    for cell_ref in GAGE_READING_CELLS:
        value = excel_values.get(cell_ref, '')
        try:
            numeric_value = float(value)
            if numeric_value > 0:
                gage_values.append(numeric_value)
        except (TypeError, ValueError):
            continue

    if gage_values:
        excel_values['T7'] = round(sum(gage_values) / len(gage_values), 2)
    else:
        excel_values['T7'] = ''

    excel_values['AH7'] = round_if_numeric(excel_values.get('AH7', ''), digits=2)

    for cell_ref, value in excel_values.items():
        if value == 0.0:
            excel_values[cell_ref] = ''

    return excel_values


def write_excel_template(cell_values):
    """Populate the Excel template with mapped values.

    Args:
        cell_values: Dictionary keyed by Excel cell reference.
    """
    if os.path.exists(TEMP_XLSX_PATH):
        os.remove(TEMP_XLSX_PATH)

    shutil.copy(TEMPLATE_XLSX_PATH, TEMP_XLSX_PATH)
    workbook = openpyxl.load_workbook(TEMP_XLSX_PATH)
    worksheet = workbook[WORKSHEET_NAME]

    for cell_ref, value in cell_values.items():
        worksheet[cell_ref] = clean_excel_value(value)

    workbook.save(TEMP_XLSX_PATH)
    workbook.close()


def export_pdf(output_date, output_id):
    """Export the current temp workbook to a PDF.

    Args:
        output_date: Date string used in the output filename.
        output_id: Site or form identifier used in the output filename.

    Returns:
        Path to the saved PDF.
    """
    workbook = aspose.cells.Workbook(str(TEMP_XLSX_PATH))
    pdf_name = f'{output_id}_{output_date}.pdf'
    pdf_path = os.path.join(OUTPUT_DIRECTORY, pdf_name)

    if not os.path.exists(pdf_path):
        workbook.save(str(pdf_path), SaveFormat.PDF)
        print(f'{pdf_name} saved')
        return Path(pdf_path)

    for suffix in range(1, 10):
        pdf_name = f'{output_id}_{output_date}_{suffix:02d}.pdf'
        pdf_path = os.path.join(OUTPUT_DIRECTORY, pdf_name)
        if not os.path.exists(pdf_path):
            workbook.save(str(pdf_path), SaveFormat.PDF)
            print(f'{pdf_name} saved')
            return Path(pdf_path)

    raise FileExistsError(f'Could not create unique PDF name for {output_id} {output_date}.')


def send_summary_email(recipient_list, save_count):
    """Send an email summary for the current run.

    Args:
        recipient_list: Email recipient string.
        save_count: Number of successfully saved files.
    """
    current_date = dt.datetime.now().strftime('%b %d, %Y')
    message = MIMEMultipart()
    message['Subject'] = f'E-Field Forms {current_date}'
    message['From'] = 'StAGE_Alarm@dnrc.mt.gov'
    message['To'] = recipient_list
    message.attach(MIMEText(f'{save_count} files saved'))

    with smtplib.SMTP('mail.mt.gov', 25) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(message)


def push_data_to_aq():
    """Push processed data into Aquarius.

    This is a placeholder for the Aquarius integration step.
    """
    pass


def main():
    """Run the discharge form export workflow."""
    initialize_tracking_db(TRACKING_DB_PATH)

    site_name_map = load_site_name_map(GAGE_LIST_PATH)
    source_gdf = load_source_records()
    processed_ids = fetch_processed_ids(TRACKING_DB_PATH)
    records_to_process = select_records_to_process(source_gdf, processed_ids)

    print(records_to_process)

    saved_file_count = 0

    for _, row in records_to_process.iterrows():
        print(f"Parsing: {row['gage_site_id']}")

        excel_values = build_excel_value_map(row, site_name_map)
        write_excel_template(excel_values)

        measurement_date = excel_values.get('F5', '')
        output_date = format_output_date(measurement_date)

        site_id = str(excel_values.get('A2', '')).strip().replace(' ', '')
        if not site_id:
            site_id = str(excel_values.get('F4', '')).strip().replace(' ', '')

        pdf_path = export_pdf(output_date, site_id)
        push_data_to_aq()

        insert_processed_record(
            TRACKING_DB_PATH,
            global_id=row.get('globalid', ''),
            gage_site_id=site_id,
            output_pdf=pdf_path,
        )
        saved_file_count += 1

    print(f'{saved_file_count} files saved')
    send_summary_email(EMAIL_RECIPIENTS, saved_file_count)
    print('email sent')


if __name__ == '__main__':
    main()
