import datetime as dt
import os
import shutil
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aspose.cells
import geopandas as gpd
import openpyxl
import pandas as pd
from aspose.cells import SaveFormat

from id_fix.id_fix import dict_dict, other_dict_dict

# SERVER_NAME = 'dnrhln6385.state.mt.ads'  # 65 is test, 63 is live
# USER_NAME = ''
# PASSWORD = ''
DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\AGOL_to_Aq')
PDF_DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Water_Management\Electronic Field Forms')
AGOL_FILE = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form_Data.shp')
UPLOADED_FILES = Path.joinpath(DIRECTORY, 'uploaded_data.csv')
GAGE_LIST = Path.joinpath(DIRECTORY, 'gage_list.csv')
XLSX_FILE = Path.joinpath(DIRECTORY, 'DNRC_Qm_Form_live.xlsx')
XLSX_TEMP = Path.joinpath(DIRECTORY, 'temp_form.xlsx')
RECIPIENTS = 'David.Saba@mt.gov, Ryan.Koehnlein2@mt.gov'


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
    workbook = aspose.cells.Workbook(str(XLSX_TEMP))
    pdf_file = f"{_id}_{date}.pdf"
    pdf_filepath = os.path.join(PDF_DIRECTORY, pdf_file)
    if not os.path.exists(pdf_filepath):
        workbook.save(str(pdf_filepath), SaveFormat.PDF)
        print(f"{pdf_file} saved \n")
    else:
        for i in range(1,10):
            pdf_file = f"{_id}_{date}_{i:02d}.pdf"
            pdf_filepath = os.path.join(PDF_DIRECTORY, pdf_file)
            if not os.path.exists(pdf_filepath):
                workbook.save(str(pdf_filepath), SaveFormat.PDF)
                print(f"{pdf_file} saved \n")
                break


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
    df_n = pd.read_csv(GAGE_LIST)
    site_name_dict = {}
    for idx, row in df_n.iterrows():
        site_name_dict[row['id']] = row['name']

    #  gets list of id's of already uploaded data
    df_u = pd.read_csv(UPLOADED_FILES, index_col=[0])
    try:
        up_id_list = df_u['globalid'].tolist()
    except KeyError:
        up_id_list = []

    # gets all shapefile data
    # df_s = pd.read_csv('QForm.csv', index_col=[0])  # for testing
    df_s = gpd.read_file(AGOL_FILE)
    df_g = pd.DataFrame()

    #  itterates over all data, updates uploaded list and sends to be uploaded data to temp dataframe
    for idx, row in df_s.iterrows():
        if row['rt_gage_si'] == 'Yes' and row['globalid'] not in up_id_list:
            df_g = pd.concat([df_g, df_s.loc[[idx]]], ignore_index=True)
            df_u = pd.concat([df_u, df_s.loc[[idx]]], ignore_index=True)
    # df_u.to_csv('uploaded_data.csv')
    # print(df_g)

    save_count = 0

    # assigns values to excell cell keys and calls the write to file functions
    for idx, row in df_g.iterrows():
        print(f"Parsing: {row['gage_site_']}")
        new_dict = dict_dict
        # print(new_dict)
        temp_dict = {}
        for key, value in new_dict.items():
            try:
                temp_dict[key] = row[value]
            except KeyError:
                pass
        # print(temp_dict)
        try:
            temp_dict['F4'] = site_name_dict[temp_dict['A2']]
        except KeyError:
            temp_dict['F4'] = ''

        # swaps value with other_values
        new_new_dict = other_dict_dict
        other_list = ['F4', 'C29', 'G13', 'A9', 'A48']
        for key, value in new_new_dict.items():
            if temp_dict[key] == 'other' or temp_dict[key] == '':
                try:
                    temp_dict[key] = row[value]
                except KeyError:
                    temp_dict[key] = ''

        # print(temp_dict)
        value_list = []
        key_list = ['T14', 'T15', 'T16', 'T17', 'T18', 'T19', 'T20', 'T21']
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
        save_count += 1

        meas_date = temp_dict['F5']
        reform_date = format_date(meas_date)
        site_id = temp_dict['A2']
        reform_id = site_id.replace(' ', '')
        if reform_id == '':
            reform_id = temp_dict['F4']
        # save_excel_to_folder(reform_date, reform_id)
        excel_to_pdf(reform_date, reform_id)

        push_data_to_aq()
    # Save sites that have been uploaded to csv last (if crash won't save)
    df_u.to_csv(UPLOADED_FILES)

    print(f"{save_count} files saved")

    t_now_format = dt.datetime.now()
    t_now_format = t_now_format.strftime(f"%b %d, %Y")
    msg = MIMEMultipart()
    msg['Subject'] = f"E-Field Forms {t_now_format}"
    msg['From'] = 'StAGE_Alarm@dnrc.mt.gov'
    msg['To'] = RECIPIENTS

    body = MIMEText(f"{save_count} files saved")

    msg.attach(body)

    with smtplib.SMTP('mail.mt.gov', 25) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)
        server.quit()
    print("email sent")
