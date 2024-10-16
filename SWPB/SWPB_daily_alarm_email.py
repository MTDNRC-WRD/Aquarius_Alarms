import requests
import json
from pathlib import Path
import pandas as pd
import datetime as dt
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.mime.text import MIMEText


SERVER_NAME = 'dnrhln6386.state.mt.ads'
USER_NAME = 'DNRC'
PASSWORD = 'DNRC'
DIRECTORY = Path(r"\\DNRHLN6386.state.mt.ads\Fileshare$\Aquarius_Alarms\SWPB")
RECIPIENTS = "David.Saba@mt.gov, RLaskowski@mt.gov"


def format_timestamp(time):
    if time == 0:
        return 0
    else:
        try:
            tf = dt.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%f0%z") - dt.timedelta(hours=6)
            tf = tf.strftime("%b-%d %H:%M")
            return tf
        except ValueError:
            time_list = list(time.strip(""))
            time_list[12] = "3"
            time = ''.join(time_list)
            tf = dt.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%f0%z") - dt.timedelta(hours=5)
            tf = tf.strftime("%b-%d %H:%M")
            return tf


tmin_day = dt.datetime.utcnow() - dt.timedelta(minutes=1440)
tmin_day = tmin_day.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now = dt.datetime.utcnow()
t_now = t_now.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now_format = dt.datetime.now()
t_now_format = t_now_format.strftime(f"%b %d, %Y")

# # Outputs csv of sensor data anomalies based on reference to master sensor list csv # #
sl_df = pd.read_csv(Path.joinpath(DIRECTORY, 'SWPB_sensor_list.csv'), index_col=[0], skip_blank_lines=True)
print("Acquiring StAGE data...")
site_data = []
for i in sl_df.index:
    aq_params = {'TimeSeriesUniqueId': i,
                 'QueryFrom': tmin_day,
                 'QueryTo': t_now}
    response = requests.get(
        url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
        auth=(USER_NAME, PASSWORD),
        params=aq_params)
    try:
        response.raise_for_status()
        series_data = response.json()
    except requests.exceptions.HTTPError:
        pass
    # print(json.dumps(series_data, indent=4))
    try:
        timestamp = series_data["Points"][-1]["Timestamp"]
    except IndexError:
        timestamp = 0
    try:
        value = series_data["Points"][-1]["Value"]["Numeric"]
    except IndexError:
        value = 0
    point_dict = {
        "UniqueId": series_data["UniqueId"],
        "LocationIdentifier": series_data["LocationIdentifier"],
        "SiteName": sl_df.loc[series_data['UniqueId'], "SiteName"],
        "Parameter": series_data["Parameter"],
        "Timestamp": format_timestamp(timestamp),
        "Value": value,
        "Unit": series_data["Unit"],
        "LowAlarm": sl_df.loc[series_data['UniqueId'], "LowAlarm"],
        "HighAlarm": sl_df.loc[series_data['UniqueId'], "HighAlarm"],
        "Publish": sl_df.loc[series_data['UniqueId'], "Publish"]
    }
    site_data.append(point_dict)
    # print(series_data)
# print(json.dumps(site_data, indent=4))
today_df = pd.DataFrame.from_records(site_data)
today_df.to_csv(Path.joinpath(DIRECTORY, 'today_data.csv'))

error_list = []
for index, row in today_df.iterrows():
    if row["Publish"] is True:
        if row["Timestamp"] == 0:
            error_list.append(row)
        elif row["LowAlarm"] > row["Value"] or row["HighAlarm"] < row["Value"]:
            error_list.append(row)
error_df = pd.DataFrame.from_records(error_list)
error_df.to_csv(Path.joinpath(DIRECTORY, 'STAGE_Alarms.csv'))

no_report = []
no_report_keys = []
irreg_v = []
irreg_v_keys = []
irreg_data = []
irreg_data_keys = []
for index, row in error_df.iterrows():
    if row["Timestamp"] == 0:
        if row["LocationIdentifier"] not in no_report_keys:
            no_report.append({row["LocationIdentifier"]: row["SiteName"]})
            no_report_keys.append(row["LocationIdentifier"])
    elif row["Unit"] == "V":
        if row["LocationIdentifier"] not in irreg_v_keys:
            irreg_v.append({row["LocationIdentifier"]: row["SiteName"]})
            irreg_v_keys.append(row["LocationIdentifier"])
    else:
        if row["LocationIdentifier"] not in irreg_data_keys and row["LocationIdentifier"] not in no_report_keys:
            irreg_data.append({row["LocationIdentifier"]: row["SiteName"]})
            irreg_data_keys.append(row["LocationIdentifier"])

print(f"{len(no_report) + len(irreg_v) + len(irreg_data)} sites reporting anomalies")

format_no_report = str(no_report).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
    .replace("]", '').replace('{', '-').replace('}', '')
format_irreg_v = str(irreg_v).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
    .replace("]", '').replace('{', '-').replace('}', '')
format_irreg_data = str(irreg_data).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
    .replace("]", '').replace('{', '-').replace('}', '')

attachment = str(Path.joinpath(DIRECTORY, 'STAGE_Alarms.csv'))
msg = MIMEMultipart()
msg['Subject'] = f"StAGE Alarms {t_now_format}"
msg['From'] = 'StAGE_Alarm@dnrc.mt.gov'
msg['To'] = RECIPIENTS

body = MIMEText(f"Daily alarm summary for SWPB maintained gauges:\n\n"
                "Sites not reporting: \n"
                f"{format_no_report}\n\n"
                "Sites reporting irregular voltage: \n"
                f"{format_irreg_v}\n\n"
                "Sites reporting irregular data: \n"
                f"{format_irreg_data}\n\n")

part = MIMEBase('application', "octet-stream")
part.set_payload(open(attachment, "rb").read())
encoders.encode_base64(part)
part.add_header('Content-Disposition', 'attachment', filename=attachment)

msg.attach(body)
msg.attach(part)

with smtplib.SMTP('mail.mt.gov', 25) as server:
    server.ehlo()
    server.starttls()
    server.ehlo()

    server.send_message(msg)
print("email sent")

