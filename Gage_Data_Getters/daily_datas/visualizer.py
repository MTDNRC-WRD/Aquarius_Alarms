import pandas as pd
from pathlib import Path

DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Stage_Scripts\id_compiler')
INPUT_PARQUET = DIRECTORY / 'daily_discharge_history.parquet'
OUTPUT_PARQUET = DIRECTORY / 'daily_discharge_hydrology.parquet'
OUTPUT_YEARS_PARQUET = DIRECTORY / 'daily_discharge_hydrology_year_values.parquet'


all_data = pd.read_parquet(INPUT_PARQUET)
hydro = pd.read_parquet(OUTPUT_PARQUET)
hydro_years = pd.read_parquet(OUTPUT_YEARS_PARQUET)


hydro.to_csv('median_hydo_data.csv')

print("STOP")