import pandas as pd
import geopandas as gpd
import datetime as dt
import openpyxl
from win32com import client
import os
import shutil
from pathlib import Path
from id_fix.id_fix import dict_dict
from id_fix.id_fix import gage_read_dict


SERVER_NAME = 'dnrhln6385.state.mt.ads'  # 65 is test, 63 is live
USER_NAME = ''
PASSWORD = ''
DIRECTORY = Path(r"S:\Aquarius_Alarms\AGOL_to_Aq")
PDF_DIRECTORY = Path(r"S:\Water_Management\Electronic Field Forms")
AGOL_FILE = Path(r"S:\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form_Data.shp")
UPLOADED_FILES = Path(r"S:\Aquarius_Alarms\AGOL_to_Aq\uploaded_data.csv")
XLSX_FILE = Path(r"S:\Aquarius_Alarms\AGOL_to_Aq\DNRC_Qm_Form_live.xlsx")
XLSX_TEMP = Path(r"S:\Aquarius_Alarms\AGOL_to_Aq\temp_form.xlsx")
RECIPIENTS = "David.Saba@mt.gov"


def write_data_to_excel(cell_dict):
    if os.path.exists(XLSX_TEMP):
        os.remove(XLSX_TEMP)
    shutil.copy(XLSX_FILE, XLSX_TEMP)
    temp_xl_wb = openpyxl.load_workbook(XLSX_TEMP)
    sheet = temp_xl_wb['Table 1']
    for key, value in cell_dict.items():
        sheet[key] = value
    temp_xl_wb.save(XLSX_TEMP)
    temp_xl_wb.close()


def save_excel_to_folder(date, _id):  # Temp solution, saves Excel file to folder rather than pdf
    save_file = f"{_id}_{date}.xlsx"
    save_filepath = os.path.join(PDF_DIRECTORY, save_file)
    shutil.copy(XLSX_TEMP, save_filepath)


def excel_to_pdf(date, _id):
    excel = client.Dispatch("Excel.Application")
    excel.Visible = 0
    wb = excel.Workbooks.Open(XLSX_TEMP)
    # ws = wb.Worksheets[1]
    pdf_file = f"{_id}_{date}.pdf"
    print(f"{pdf_file} saved")
    pdf_filepath = os.path.join(PDF_DIRECTORY, pdf_file)
    # print(pdf_filepath)
    # wb.ActiveSheet.ExportAsFixedFormat(client.constants.xlTypePDF, pdf_filepath)
    # ws.ExportAsFixedFormat(0, pdf_filepath)
    # # wb.ActiveSheet.SaveAs(pdf_filepath, FileFormat=57)
    wb.ActiveSheet.ExportAsFixedFormat(0, pdf_filepath)
    wb.Close(SaveChanges=False)
    excel.Quit()


def format_date(raw_date):
    if raw_date == 0:
        return 0
    else:
        d = dt.datetime.strptime(raw_date, "%Y-%m-%d")
        nd = d.strftime("%Y%m%d")
        return nd

def push_data_to_aq():
    # push to external program
    pass


if __name__ == '__main__':
    # builds dictionary of site names
    df_n = pd.read_csv('gage_list.csv')
    site_name_dict = {}
    for idx, row in df_n.iterrows():
        site_name_dict[row['id']] = row['name']

    #  gets list of id's of already uploaded data
    df_u = pd.read_csv('uploaded_data.csv', index_col=[0])
    try:
        up_id_list = df_u['globalid'].tolist()
    except KeyError:
        up_id_list = []

    # gets all shapefile data
    df_s = pd.read_csv('QForm.csv', index_col=[0])  # for testing
    # df_s = gpd.read_file(AGOL_FILE)
    df_g = pd.DataFrame()

    #  itterates over all data, updates uploaded list and sends to be uploaded data to temp dataframe
    for idx, row in df_s.iterrows():
        if row['rt_gage_si'] == 'Yes' and row['globalid'] not in up_id_list:
            df_g = pd.concat([df_g, df_s.loc[[idx]]], ignore_index=True)
            df_u = pd.concat([df_u, df_s.loc[[idx]]], ignore_index=True)
    df_u.to_csv('uploaded_data.csv')
    # print(df_g)

    # assigns values to excell cell keys and calls the write to file functions
    for idx, row in df_g.iterrows():
        print(f"Parsing: {row['gage_site_']}")
        new_dict = dict_dict
        print(new_dict)
        temp_dict = {}
        for key, value in new_dict.items():
            try:
                temp_dict[key] = row[value]
            except KeyError:
                pass
        # print(temp_dict)
        temp_dict['F4'] = site_name_dict[temp_dict['A2']]
        print(temp_dict['F4'])
        key_list = ['T14', 'T15', 'T16', 'T17', 'T18', 'T19', 'T20', 'T21']
        value_list = []

        for key in key_list:
            if temp_dict[key] != '':
                if float(temp_dict[key]) > 0:
                    value_list.append(temp_dict[key])
        if len(value_list) != 0:
            ave_gage_ht = sum(value_list) / len(value_list)
            temp_dict['T7'] = ave_gage_ht
        for key, value in temp_dict.items():
            if value == 0.0:
                temp_dict[key] = ''
        # print(temp_dict)
        write_data_to_excel(temp_dict)

        meas_date = temp_dict['F5']
        reform_date = format_date(meas_date)
        site_id = temp_dict['A2']
        reform_id = site_id.replace(' ', '')
        # save_excel_to_folder(reform_date, reform_id)
        excel_to_pdf(reform_date, reform_id)

        push_data_to_aq()

