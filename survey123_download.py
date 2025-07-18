import pandas as pd
import geopandas as gpd
from pathlib import Path


DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms')
AGOL_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form_Data.shp')


if __name__ == '__main__':

    df_s = gpd.read_file(AGOL_FILE)
    df_g = pd.DataFrame()

    #  itterates over all data, updates uploaded list and sends to be uploaded data to temp dataframe
    for idx, row in df_s.iterrows():
        if row['rt_gage_si'] == 'No':
            df_g = pd.concat([df_g, df_s.loc[[idx]]], ignore_index=True)

    df_g.to_csv('non_RT_data.csv')
    # print(df_g)

