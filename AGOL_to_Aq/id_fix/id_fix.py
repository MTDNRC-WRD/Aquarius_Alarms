import pandas as pd
import geopandas

excel_dict = {
    'A2': 'gage_site_id',
    'AL2': 'hydro_name',
    'T5': 'party_initials',
    'F4': '',  # link to dictonary of names!!!
    'F5': 'measurement_date',
    'A7': 'cross_section_width',
    'D7': 'cross_section_area',
    'N7': 'ave_velocity_measured',
    'T7': '',  #calculate this field!!!
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
    'T15': 'recording_gage_3',
    'A16': 'gage_reading_time_3',
    'G16': 'reference_gage_3',
    'T16': 'recording_gage_3',
    'A17': 'gage_reading_time_4',
    'G17': 'reference_gage_4',
    'T17': 'recording_gage_5',
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
    'Q50': 'number_of_transects'
}

dict_dict = {'A2': 'gage_site_',
             'AL1': 'measurem_5',
             'AL2': 'hydro_name',
             'T5': 'party_init',
             'F4': '',
             'F5': 'measurem_4',
             'A7': 'cross_se_2',
             'D7': 'cross_se_3',
             'N7': 'ave_veloci',
             'T7': '',
             'AH7': 'Measured_D',
             'A9': 'measuremen',
             'I9': 'rate_num',
             'Q9': 'shift_ft',
             'AF9': 'time_of_di',
             'A11': 'sensor_tem',
             'G11': 'measured_t',
             'N11': 'water_temp',
             'T11': 'weather',
             'AB11': 'air_temper',
             'AF11': 'wind_est',
             'AL11': 'wind_direc',
             'AN2': 'location_n',
             'G13': 'reference_',
             'A14': 'gage_rea_1',
             'G14': 'reference1',
             'T14': 'recording_',
             'A15': 'gage_rea_2',
             'G15': 'referenc_1',
             'T15': 'recording1',
             'A16': 'gage_rea_3',
             'G16': 'referenc_2',
             'T16': 'recordin_1',
             'A17': 'gage_rea_4',
             'G17': 'referenc_3',
             'T17': 'recordin_3',
             'A18': 'gage_rea_5',
             'G18': 'referenc_4',
             'T18': 'recordin_3',
             'A19': 'gage_rea_6',
             'G19': 'referenc_5',
             'T19': 'recordin_4',
             'A20': 'gage_rea_7',
             'G20': 'referenc_6',
             'T20': 'recordin_5',
             'A21': 'gage_rea_8',
             'G21': 'referenc_7',
             'T21': 'recordin_6',
             'A23': 'gage_heigh',
             'AC24': 'checkbar_c',
             'H25': 'measurem_3',
             'H28': 'measurem_2',
             'C29': '_control',
             'B30': 'errors',
             'C31': 'photos_not',
             'F32': 'maintenanc',
             'Q32': 'maintena_1',
             'AG32': 'maintena_2',
             'F33': 'battery_re',
             'AA33': 'maintena_3',
             'AO14': 'initial_di',
             'AO15': 'cross_se_1',
             'AP15': 'width_meas',
             'AO16': 'average_de',
             'AP16': 'depth_meas',
             'AO17': 'approximat',
             'AP17': 'velocity_m',
             'AO18': 'educated_d',
             'AO20': 'how_famili',
             'AO21': 'channel_ty',
             'AO22': 'water_clar',
             'AO23': 'surface__1',
             'AO24': 'flow_regim',
             'AO25': 'vegetation',
             'AO26': 'bank_veget',
             'AO27': 'bed_materi',
             'AO28': 'cross_sect',
             'AO29': 'left_bank',
             'AO30': 'right_bank',
             'E43': 'left_bank',
             'E45': 'right_bank',
             'A48': 'adcp_boat',
             'O48': 'gps_used',
             'W48': 'acdp_depth',
             'Q50': 'number_of1'
             }

other_dict_dict = {'A2': '',
                   'F4': 'gage_site1',
                   'C29': 'untitled_q',
                   'G13': 'refrence_g',
                   'A9': 'measurem1',
                   'A48': 'adcp_other'
                   }

gage_read_dict = {'A14': 'gage_rea_1',
                  'G14': 'wire_weigh',
                  'M14': 'staff_1',
                  'P14': 'cantilever',
                  'T14': 'recording_',
                  'A15': 'gage_rea_2',
                  'G15': 'wire_wei_1',
                  'M15': 'staff_2',
                  'P15': 'cantilev_1',
                  'T15': 'recordin_1',
                  'A16': 'gage_rea_3',
                  'G16': 'wire_wei_2',
                  'M16': 'staff_3',
                  'P16': 'cantilev_2',
                  'T16': 'recordin_1',
                  'A17': 'gage_rea_4',
                  'G17': 'wire_wei_3',
                  'M17': 'staff_4',
                  'P17': 'cantilev_3',
                  'T17': 'recordin_3',
                  'A18': 'gage_rea_5',
                  'G18': 'wire_wei_4',
                  'M18': 'staff_5',
                  'P18': 'cantilev_4',
                  'T18': 'recordin_3',
                  'A19': 'gage_rea_6',
                  'G19': 'wire_wei_5',
                  'M19': 'staff_6',
                  'P19': 'cantilev_5',
                  'T19': 'recordin_4',
                  'A20': 'gage_rea_7',
                  'G20': 'wire_wei_6',
                  'M20': 'staff_7',
                  'P20': 'cantilev_6',
                  'T20': 'recordin_5',
                  'A21': 'gage_rea_8',
                  'G21': 'wire_wei_7',
                  'M21': 'staff_8',
                  'P21': 'cantilev_7',
                  'T21': 'recordin_6'
                  }





# name_list = []
# for value in excel_dict.values():
#     name_list.append(value)
#
# df = pd.read_csv('form_data.csv')
# csv_col_list = df.columns.to_list()





# df_n = pd.read_csv('name_shortname.csv')
# print(df_n)
# site_name_dict = {}
# for idx, row in df_n.iterrows():
#     site_name_dict[row['unique_name']] = row['name']
#
# df_sh_n = pd.read_csv('name_table.csv')
# print(df_sh_n)
# shp_name_dict = {}
# for idx, row in df_sh_n.iterrows():
#     shp_name_dict[row['long_name']] = row['shp_n']
#
# new_excel_dict = excel_dict
# name_sequence = []
# for key, value in excel_dict.items():
#     try:
#         lng_name = site_name_dict[value]
#         shp_name = shp_name_dict[lng_name]
#         new_excel_dict[key] = shp_name
#     except KeyError:
#         pass
#
#
# print(new_excel_dict)



# df_ref = pd.read_csv('refs.csv')
# ref_dict = {}
# for idx, row in df_ref.iterrows():
#     ref_dict[row['long']] = row['short']
#
# print(ref_dict)
#








