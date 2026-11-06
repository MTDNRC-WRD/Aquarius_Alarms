"""
Add missing Discharge time series to Qlist.xlsx.

Compares the UniqueIds in Qlist.xlsx against output_tsid.csv rows where
Parameter == 'Discharge' and Publish (lower-cased) == 'discharge'. Any UniqueId
missing from Qlist.xlsx is appended in the same format as the existing rows,
with default alarm thresholds. Existing rows are never changed.

SiteName and Tech are looked up by LocationIdentifier from SensorList.xlsx
(and from existing Qlist rows) when available; otherwise they are left blank.
"""

from copy import copy
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

# =============================================================================
# CONFIG
# =============================================================================
Q_LIST = Path('Qlist.xlsx')
Q_SHEET = 'q_list'
TSID_CSV = Path('output_tsid.csv')
SENSOR_LIST = Path('SensorList.xlsx')       # used to look up SiteName / Tech
SENSOR_SHEET = 'sensor_list'
OUTPUT_LIST = Path('Qlist_updated.xlsx')

PARAMETER = 'Discharge'
PUBLISH_LABEL = 'discharge'                 # compared after .lower()

DEFAULT_LOW = 0.5
DEFAULT_HIGH = 10000
DEFAULT_DELTA = 500
DEFAULT_PUBLISH = False                     # new rows are not alarmed until you turn them on
DEFAULT_UNIT = 'ft^3/s'


def clean(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def build_lookup(q_df: pd.DataFrame) -> pd.DataFrame:
    """SiteName/Tech by LocationIdentifier from Qlist, then SensorList."""
    cols = ['LocationIdentifier', 'SiteName', 'Tech']
    frames = [q_df[cols]]
    if SENSOR_LIST.exists():
        sensors = pd.read_excel(SENSOR_LIST, sheet_name=SENSOR_SHEET)
        frames.append(sensors[cols])
    lookup = pd.concat(frames, ignore_index=True)
    lookup['LocationIdentifier'] = clean(lookup['LocationIdentifier'])
    return lookup.dropna(subset=['SiteName']).drop_duplicates('LocationIdentifier')


def main() -> None:
    q_df = pd.read_excel(Q_LIST, sheet_name=Q_SHEET, dtype={'UniqueId': str})
    tsids = pd.read_csv(TSID_CSV, dtype=str, encoding='utf-8-sig')

    discharge = tsids[
        (clean(tsids['Parameter']) == PARAMETER)
        & (clean(tsids['Publish']).str.lower() == PUBLISH_LABEL)
    ].copy()
    discharge['UniqueId'] = clean(discharge['UniqueId'])
    discharge['LocationIdentifier'] = clean(discharge['LocationIdentifier'])
    discharge = discharge.drop_duplicates('UniqueId')

    have = set(clean(q_df['UniqueId']))
    missing = discharge[~discharge['UniqueId'].isin(have)].copy()
    print(f'Discharge time series in {TSID_CSV.name}: {len(discharge)}')
    print(f'Already in {Q_LIST.name}:                 {len(discharge) - len(missing)}')
    print(f'Missing (to add):                         {len(missing)}')

    not_in_csv = q_df[~clean(q_df['UniqueId']).isin(set(discharge['UniqueId']))]
    if len(not_in_csv):
        print(f'\nNote: {len(not_in_csv)} Qlist rows have no matching "{PUBLISH_LABEL}" row in the CSV (left unchanged):')
        for _, r in not_in_csv.iterrows():
            print(f"  {r['LocationIdentifier']}  {r['SiteName']}  {r['UniqueId']}")

    if missing.empty:
        print('\nNothing to add.')
        return

    lookup = build_lookup(q_df).set_index('LocationIdentifier')

    wb = load_workbook(Q_LIST)
    ws = wb[Q_SHEET]
    header = [c.value for c in ws[1]]
    template_row = ws.max_row           # copy cell styles from the last existing row

    print('\nAdded:')
    for _, r in missing.iterrows():
        loc = r['LocationIdentifier']
        site = lookup['SiteName'].get(loc, '')
        tech = lookup['Tech'].get(loc, '')
        values = {
            'UniqueId': r['UniqueId'],
            'LocationIdentifier': loc,
            'SiteName': site,
            'Parameter': PARAMETER,
            'Unit': r['Unit'] if pd.notna(r.get('Unit')) else DEFAULT_UNIT,
            'LowAlarm': DEFAULT_LOW,
            'HighAlarm': DEFAULT_HIGH,
            'DeltaAlarm': DEFAULT_DELTA,
            'Publish': DEFAULT_PUBLISH,
            'Tech': tech,
            'Notes': None,
        }
        new_row = ws.max_row + 1
        for col_idx, name in enumerate(header, start=1):
            cell = ws.cell(row=new_row, column=col_idx, value=values.get(name))
            src = ws.cell(row=template_row, column=col_idx)
            cell.font = copy(src.font)
            cell.fill = copy(src.fill)
            cell.border = copy(src.border)
            cell.alignment = copy(src.alignment)
            cell.number_format = src.number_format
        flag = '' if site else '   <-- no SiteName found, fill in manually'
        print(f'  {loc}  {site or "(blank)"}  {r["UniqueId"]}{flag}')

    if ws.auto_filter.ref:
        ws.auto_filter.ref = f'A1:{ws.cell(row=1, column=len(header)).column_letter}{ws.max_row}'

    wb.save(OUTPUT_LIST)
    print(f'\nWrote {OUTPUT_LIST} ({ws.max_row - 1} data rows)')


if __name__ == '__main__':
    main()
