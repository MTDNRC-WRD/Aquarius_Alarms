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
DIRECTORY = Path(r"\\DNRHLN6386.state.mt.ads\Fileshare$\Aquarius_Alarms\Q_Alarm")
RECIPIENTS = "David.Saba@mt.gov, TLechman@mt.gov, MNorberg@mt.gov, diane.wagner@mt.gov, Ryan.Koehnlein2@mt.gov," \
             "Christopher.Basden@mt.gov, b.grigsby@mt.gov, Ashley.Peterson@mt.gov, raeya.gordon@mt.gov"
# RECIPIENTS = "David.Saba@mt.gov"  # dnrcstage@mt.gov


def format_timestamp(time):
    if time == 'null':
        return 'null'
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


def value_diff(now, old):
    if now == 'null' or old == 'null':
        return 0
    else:
        val = int(now) - int(old)
        return val


tmin_day = dt.datetime.utcnow() - dt.timedelta(minutes=1680)
tmin_day = tmin_day.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now = dt.datetime.utcnow()
t_now = t_now.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now_format = dt.datetime.now()
t_now_format = t_now_format.strftime(f"%b %d, %Y")

# # Outputs csv of sensor data anomalies based on reference to master sensor list csv # #
sl_df = pd.read_csv(Path.joinpath(DIRECTORY, 'q_list.csv'), index_col=[0], skip_blank_lines=True)
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
    response.raise_for_status()
    series_data = response.json()
    # print(json.dumps(series_data, indent=4))
    try:
        timestamp = series_data["Points"][-1]["Timestamp"]
        timestamp_min_one = series_data["Points"][-4]["Timestamp"]
        timestamp_min_day = series_data["Points"][-96]["Timestamp"]
    except IndexError:
        timestamp = 'null'
        timestamp_min_one = 'null'
        timestamp_min_day = 'null'
    try:
        value = int(series_data["Points"][-1]["Value"]["Numeric"])
        value_min_one = int(series_data["Points"][-4]["Value"]["Numeric"])
        value_min_day = int(series_data["Points"][-96]["Value"]["Numeric"])
    except IndexError:
        value = 'null'
        value_min_one = 'null'
        value_min_day = 'null'

    point_dict = {
        "UniqueId": series_data["UniqueId"],
        "LocationIdentifier": series_data["LocationIdentifier"],
        "SiteName": sl_df.loc[series_data['UniqueId'], "SiteName"],
        "Parameter": series_data["Parameter"],
        "Timestamp": format_timestamp(timestamp),
        "Value": value,
        "Timestamp_min_1hr": format_timestamp(timestamp_min_one),
        "Value_min_1hr": value_min_one,
        "Timestamp_min_day": format_timestamp(timestamp_min_day),
        "Value_min_day": value_min_day,
        "Delta_Day": '',
        "Unit": series_data["Unit"],
        "Alarm_Type": '',
        "LowAlarm": sl_df.loc[series_data['UniqueId'], "LowAlarm"],
        "HighAlarm": sl_df.loc[series_data['UniqueId'], "HighAlarm"],
        "DeltaAlarm": sl_df.loc[series_data['UniqueId'], "Delta"],
        "Publish": sl_df.loc[series_data['UniqueId'], "Publish"]
            }
    site_data.append(point_dict)
# print(json.dumps(site_data, indent=4))
today_df = pd.DataFrame.from_records(site_data)
today_df.to_csv(Path.joinpath(DIRECTORY, 'Instant_Discharge.csv'))

error_list = []
for index, row in today_df.iterrows():
    row["Delta_Day"] = value_diff(row['Value'], row["Value_min_day"])
    if row["Publish"] is True:
        if row["Timestamp"] == 'null':
            error_list.append(row)
        elif row["Value"] > row["HighAlarm"]:  # or row["Value"] == 0:    above rating reporting as null not zero, could pull stage data to verify if zero
            row["Alarm_Type"] = 'HighAlarm'
            error_list.append(row)
            pass
        elif row["Delta_Day"] > row["DeltaAlarm"]:
            row["Alarm_Type"] = 'DeltaAlarm'
            error_list.append(row)
error_df = pd.DataFrame.from_records(error_list)
error_df.to_csv(Path.joinpath(DIRECTORY, 'Instant_Discharge_Alarms.csv'))

no_report_inst = []
no_report_keys_inst = []
high_data = []
high_data_keys = []
delta_day = []
delta_day_keys = []
for index, row in error_df.iterrows():
    if row["Timestamp"] == 'null':
        if row["LocationIdentifier"] not in no_report_keys_inst:
            no_report_inst.append({row["LocationIdentifier"]: row["SiteName"]})
            no_report_keys_inst.append(row["LocationIdentifier"])
    elif row["Alarm_Type"] == 'HighAlarm':
        high_data.append({row["LocationIdentifier"]: row["SiteName"]})
        high_data_keys.append(row["LocationIdentifier"])
    elif row["Alarm_Type"] == 'DeltaAlarm':
        delta_day.append({row["LocationIdentifier"]: row["SiteName"]})
        delta_day_keys.append(row["LocationIdentifier"])

print(f"{len(high_data)} sites reporting high flow")
print(f"{len(delta_day)} other sites reporting substantial increases in flow")

format_no_report = str(no_report_inst).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
    .replace("]", '').replace('{', '-').replace('}', '')
format_high_data = str(high_data).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
    .replace("]", '').replace('{', '-').replace('}', '')
format_delta_day = str(delta_day).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
    .replace("]", '').replace('{', '-').replace('}', '')

attachment = str(Path.joinpath(DIRECTORY, 'Instant_Discharge_Alarms.csv'))
msg = MIMEMultipart()
msg['Subject'] = f"StAGE Discharge {t_now_format}"
msg['From'] = 'StAGE_Alarm@dnrc.mt.gov'
msg['To'] = RECIPIENTS

body = MIMEText(f"Discharge Alarm:\n\n"
                "Missing Instantaneous Discharge:\n"
                f"{format_no_report}\n\n"
                "Sites Reporting High Discharge:\n"
                f"{format_high_data}\n\n"
                "Sites Reporting Significant 24hr Discharge Increase:\n"
                f"{delta_day}\n\n")

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
    server.quit()
print("email sent")
