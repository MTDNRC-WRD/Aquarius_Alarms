import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

# =============================================================================
# CONFIG
# =============================================================================
DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Stage_Scripts\id_compiler')

INPUT_PARQUET = DIRECTORY / 'daily_discharge_history.parquet'
OUTPUT_PARQUET = DIRECTORY / 'daily_discharge_hydrology.parquet'
OUTPUT_YEARS_PARQUET = DIRECTORY / 'daily_discharge_hydrology_year_values.parquet'

VALUE_COL = 'discharge'
SITE_COL = 'location_id'
DATE_COL = 'date'

# =============================================================================
# HELPERS
# =============================================================================
def load_input_data(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)

    needed = {SITE_COL, DATE_COL, VALUE_COL}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f'Missing required columns: {sorted(missing)}')

    df = df[[SITE_COL, DATE_COL, VALUE_COL]].copy()
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors='coerce')
    df[VALUE_COL] = pd.to_numeric(df[VALUE_COL], errors='coerce')
    df = df.dropna(subset=[SITE_COL, DATE_COL]).copy()

    # One value per site/date is expected; if duplicates exist, average them.
    df = (
        df.groupby([SITE_COL, DATE_COL], as_index=False)[VALUE_COL]
          .mean()
    )

    df['year'] = df[DATE_COL].dt.year
    df['month'] = df[DATE_COL].dt.month
    df['day'] = df[DATE_COL].dt.day

    return df


def build_complete_daily_series(site_df: pd.DataFrame, doy_lookup: pd.DataFrame) -> pd.DataFrame:
    """
    Build one row per site/year/day_of_year, including:
      - synthetic Feb 29 for non-leap years (avg of Feb 28 & Mar 1)
      - all 1..366 day_of_year values in the final climatology (filled later)
    """
    site_id = site_df[SITE_COL].iloc[0]
    years = sorted(site_df['year'].unique())
    records = []

    for year in years:
        yr = site_df.loc[site_df['year'] == year, [DATE_COL, VALUE_COL, 'month', 'day']].copy()

        # existing daily rows
        for row in yr.itertuples(index=False):
            records.append({
                SITE_COL: site_id,
                'year': year,
                'month': int(row.month),
                'day': int(row.day),
                VALUE_COL: float(row.discharge) if pd.notna(row.discharge) else np.nan,
            })

        # synthetic Feb 29 if possible for non-leap years
        is_leap = pd.Timestamp(year=year, month=1, day=1).is_leap_year
        if not is_leap:
            feb28 = yr.loc[(yr['month'] == 2) & (yr['day'] == 28), VALUE_COL]
            mar01 = yr.loc[(yr['month'] == 3) & (yr['day'] == 1), VALUE_COL]
            if not feb28.empty and not mar01.empty:
                leap_val = (float(feb28.iloc[0]) + float(mar01.iloc[0])) / 2.0
                records.append({
                    SITE_COL: site_id,
                    'year': year,
                    'month': 2,
                    'day': 29,
                    VALUE_COL: leap_val,
                })

    out = pd.DataFrame(records)
    if out.empty:
        return out

    # merge day_of_year
    out = out.merge(doy_lookup, on=['month', 'day'], how='left')

    # enforce NaN for <= 0 values (exclude from stats and year count)
    out.loc[out[VALUE_COL] <= 0, VALUE_COL] = np.nan

    return out


def summarize_daily_stats(full_daily: pd.DataFrame, doy_lookup: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-site, per-day-of-year stats, and ensure every site has rows
    for all day_of_year 1..366.
    """

    grouped = full_daily.groupby([SITE_COL, 'day_of_year', 'month', 'day'])[VALUE_COL]

    stats = grouped.agg(
        n_years='count',
        min_value='min',
        median_value='median',
        mean_value='mean',
        max_value='max',
    ).reset_index()[[SITE_COL, 'day_of_year', 'month', 'day',
                     'n_years', 'min_value', 'median_value', 'mean_value', 'max_value']]

    # quantiles (25th, 75th)
    q = grouped.quantile([0.25, 0.75]).unstack().reset_index().rename(
        columns={0.25: 'p25', 0.75: 'p75'}
    )[[SITE_COL, 'day_of_year', 'p25', 'p75']]

    stats = stats.merge(q, on=[SITE_COL, 'day_of_year'], how='left')

    # ensure full day_of_year coverage 1..366 for each site via reindex
    sites = stats[SITE_COL].unique()
    target_index = pd.MultiIndex.from_product(
        [sites, doy_lookup['day_of_year'].values],
        names=[SITE_COL, 'day_of_year'],
    )

    stats = stats.set_index([SITE_COL, 'day_of_year']).reindex(target_index).reset_index()

    # fill month/day from lookup where missing
    stats = stats.merge(doy_lookup, on='day_of_year', how='left', suffixes=('', '_lkp'))
    stats['month'] = stats['month'].fillna(stats['month_lkp']).astype('Int64')
    stats['day'] = stats['day'].fillna(stats['day_lkp']).astype('Int64')
    stats = stats.drop(columns=['month_lkp', 'day_lkp'])

    # format output: integer n_years, 0.1 cfs for flow stats
    flow_cols = ['min_value', 'p25', 'median_value', 'p75', 'mean_value', 'max_value']
    stats['n_years'] = stats['n_years'].fillna(0).astype('Int64')
    stats[flow_cols] = stats[flow_cols].round(1)

    # sort columns and rows
    stats = stats[[SITE_COL, 'day_of_year', 'month', 'day',
                   'n_years', 'min_value', 'p25', 'median_value', 'p75',
                   'mean_value', 'max_value']]
    stats = stats.sort_values([SITE_COL, 'day_of_year']).reset_index(drop=True)

    return stats


# =============================================================================
# MAIN
# =============================================================================
def main():
    print('Loading historical parquet...')
    df = load_input_data(INPUT_PARQUET)
    print(f'  Rows loaded : {len(df):,}')
    print(f'  Sites found : {df[SITE_COL].nunique():,}')

    # day-of-year lookup including leap day
    doy_lookup = pd.DataFrame({
        'month': [d.month for d in pd.date_range('2000-01-01', '2000-12-31', freq='D')],
        'day': [d.day for d in pd.date_range('2000-01-01', '2000-12-31', freq='D')],
        'day_of_year': range(1, 367),
    })

    site_frames = []
    site_ids = sorted(df[SITE_COL].unique())

    print('\nBuilding complete year-by-day series (including leap day fill)...')
    for site_id in tqdm(site_ids, desc='Sites', unit='site'):
        site_df = df.loc[df[SITE_COL] == site_id].copy()
        complete_site = build_complete_daily_series(site_df, doy_lookup)
        if not complete_site.empty:
            site_frames.append(complete_site)

    if not site_frames:
        raise ValueError('No site data available to summarize.')

    full_daily = pd.concat(site_frames, ignore_index=True)
    full_daily = full_daily.sort_values([SITE_COL, 'year', 'day_of_year']).reset_index(drop=True)

    print('\nCalculating hydrology statistics (excluding <= 0 values)...')
    stats_df = summarize_daily_stats(full_daily, doy_lookup)

    print(f'  Output rows : {len(stats_df):,}')
    print(f'  Output sites: {stats_df[SITE_COL].nunique():,}')

    print('\nWriting parquet files...')
    stats_df.to_parquet(OUTPUT_PARQUET, index=False, engine='pyarrow')
    full_daily.to_parquet(OUTPUT_YEARS_PARQUET, index=False, engine='pyarrow')

    print(f'  Hydrology parquet saved    : {OUTPUT_PARQUET}')
    print(f'  Year-value parquet saved   : {OUTPUT_YEARS_PARQUET}')
    print('\nDone.')


if __name__ == '__main__':
    main()