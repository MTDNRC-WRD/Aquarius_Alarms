"""
Keep only the 'working' Stage rows in SensorList.xlsx.

For every row in the sensor list where Parameter == 'Stage', check it against
the Stage rows in output_tsid.csv whose Publish value is 'working'. Stage rows
with no match are dropped. All other rows (Voltage, Water Temp, etc.) are kept
exactly as they are. Edits are made with openpyxl, so formatting is preserved.
"""

from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

# =============================================================================
# CONFIG
# =============================================================================
SENSOR_LIST = Path('SensorList.xlsx')
TSID_CSV = Path('output_tsid.csv')
OUTPUT_LIST = Path('SensorList_filtered.xlsx')
SHEET_NAME = 'sensor_list'

PARAM_COL = 'Parameter'
PUBLISH_COL = 'Publish'
ID_COL = 'UniqueId'
STAGE = 'Stage'
WORKING = 'working'


def clean(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def main() -> None:
    sensors = pd.read_excel(SENSOR_LIST, sheet_name=SHEET_NAME, dtype={ID_COL: str})
    tsids = pd.read_csv(TSID_CSV, dtype=str, encoding='utf-8-sig')

    working_ids = set(
        clean(tsids.loc[
            (clean(tsids[PARAM_COL]) == STAGE)
            & (clean(tsids[PUBLISH_COL]).str.lower() == WORKING),
            ID_COL,
        ])
    )

    is_stage = clean(sensors[PARAM_COL]) == STAGE
    matches = clean(sensors[ID_COL]).isin(working_ids)
    drop_mask = is_stage & ~matches

    print(f'Sensor list rows:          {len(sensors)}')
    print(f'Stage rows:                {is_stage.sum()}')
    print(f'Stage rows kept (working): {(is_stage & matches).sum()}')
    print(f'Stage rows dropped:        {drop_mask.sum()}')

    wb = load_workbook(SENSOR_LIST)
    ws = wb[SHEET_NAME]
    header = [c.value for c in ws[1]]
    if ID_COL not in header:
        raise ValueError(f'{ID_COL} column not found in header: {header}')

    # DataFrame row i corresponds to worksheet row i + 2 (header is row 1)
    excel_rows = [i + 2 for i in sensors.index[drop_mask]]
    for row_num in sorted(excel_rows, reverse=True):
        ws.delete_rows(row_num)

    wb.save(OUTPUT_LIST)
    print(f'Wrote {OUTPUT_LIST} ({len(sensors) - len(excel_rows)} data rows)')

    still_missing = sorted(
        set(clean(sensors.loc[is_stage, 'LocationIdentifier']))
        - set(clean(sensors.loc[is_stage & matches, 'LocationIdentifier']))
    )
    if still_missing:
        print('Locations with Stage rows but no working match:', still_missing)


if __name__ == '__main__':
    main()
