import requests
import json
import time
import random
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
DIRECTORY = Path(r"\\DNRHLN6386.state.mt.ads\Fileshare$\Aquarius_Alarms\WSB")
RECIPIENTS = "David.Saba@mt.gov, TLechman@mt.gov, MNorberg@mt.gov, Ryan.Koehnlein2@mt.gov," \
             " Christopher.Basden@mt.gov, b.grigsby@mt.gov, Ashley.Peterson@mt.gov, Kaitlin.Boren@mt.gov"
PARADISE_RECIPIENTS = "John.Lunzer@mt.gov, Raeya.Gordon@mt.gov, Madeline.McKeefry@mt.gov, David.Saba@mt.gov"
# RECIPIENTS = "David.Saba@mt.gov, dnrcstage@mt.gov"
# PARADISE_RECIPIENTS = "David.Saba@mt.gov"



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
sl_df = pd.read_csv(Path.joinpath(DIRECTORY, 'sensor_list.csv'), index_col=[0])
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

if len(no_report) > 0:
    format_no_report = str(no_report).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
        .replace("]", '').replace('{', '-').replace('}', '')
else:
    format_no_report = "[]"

if len(irreg_v) > 0:
    format_irreg_v = str(irreg_v).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
        .replace("]", '').replace('{', '-').replace('}', '')
else:
    format_irreg_v = "[]"

if len(irreg_data) > 0:
    format_irreg_data = str(irreg_data).replace(', MT', '').replace(',', '\n').replace("'", ' ').replace("[", ' ')\
        .replace("]", '').replace('{', '-').replace('}', '')
else:
    format_irreg_data = "[]"

pleasantries = ['agreeable',
                'amiable',
                'amusing',
                'sublime',
                'charming',
                'cheerful',
                'congenial',
                'cool',
                'cordial',
                'delightful',
                'engaging',
                'enjoyable',
                'fun',
                'homey',
                'likable',
                'lovely',
                'mild',
                'pleasing',
                'pleasurable',
                'refreshing',
                'satisfying',
                'sweet',
                'affable',
                'civil',
                'civilized',
                'copacetic',
                'delectable',
                'diplomatic',
                'enchanting',
                'fine',
                'fine and dandy',
                'admissible',
                'all right',
                'average',
                'big',
                'cooking with gas',
                'cool',
                'delightful',
                'hep',
                'hip',
                'hunky-dory',
                'in the swim',
                'kosher',
                'large',
                'okay',
                'on the ball',
                'passable',
                'peachy keen',
                'pleasing',
                'right on',
                'standard',
                'swell',
                'trendy',
                'unexceptional',
                'unobjectionable',
                'up to code',
                'up to snuff',
                'A-OK',
                'dandy',
                'genial',
                'good - humored',
                'gratifying',
                'jolly',
                'jovial',
                'kindly',
                'mild - mannered',
                'nice',
                'obliging',
                'social',
                'urbane',
                'cultured',
                'suave',
                'cosmopolitan',
                'elegant',
                'genteel'
                'obliging',
                'metropolitan',
                'mannerly',
                'astonishing',
                'astounding',
                'breathtaking',
                'colossal',
                'dynamite',
                'fab',
                'fabulous',
                'fantastic',
                'fat',
                'gigantic',
                'great',
                'huge',
                'marvelous',
                'mind-blowing',
                'mind-boggling',
                'miraculous',
                'monster',
                'monumental',
                'phenomenal',
                'prodigious',
                'radical',
                'smashing',
                'spectacular',
                'staggering',
                'stunning',
                'super',
                'superb',
                'surprising',
                'terrific',
                'titantic',
                'tremendous',
                'unreal',
                'utmost',
                'wondrous',
                'punctual',
                'scrupulous',
                'heedful',
                'upright',
                'meticulous',
                'punctilious'
                ]
adj = pleasantries[random.randint(0, len(pleasantries))]
letter = adj[0]
vowels = ['a', 'e', 'i', 'o', 'u']
if letter in vowels:
    art = 'an'
else:
    art = 'a'
valediction = f"Have {art} {adj} day!"

attachment = str(Path.joinpath(DIRECTORY, 'STAGE_Alarms.csv'))
msg = MIMEMultipart()
msg['Subject'] = f"StAGE Alarms {t_now_format}"
msg['From'] = 'StAGE_Alarm@dnrc.mt.gov'
msg['To'] = RECIPIENTS

body = MIMEText(f"Daily Alarm summary\n\n"
                "Sites not reporting: \n"
                f"{format_no_report}\n\n"
                "Sites reporting irregular voltage: \n"
                f"{format_irreg_v}\n\n"
                "Sites reporting irregular data: \n"
                f"{format_irreg_data}\n\n"
                f"{valediction}")

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

paradise_list = ['43B 05990', '43B 10000', '43B 05000', '43B 04000', '76G 05850']
end = False
for site in paradise_list:
    if end is False:
        for idx, row in error_df.iterrows():
            if site in row['LocationIdentifier']:
                attachment = str(Path.joinpath(DIRECTORY, 'STAGE_Alarms.csv'))
                msg = MIMEMultipart()
                msg['Subject'] = f"StAGE Alarms {t_now_format}"
                msg['From'] = 'StAGE_Alarm@dnrc.mt.gov'
                msg['To'] = RECIPIENTS

                body = MIMEText(f"Daily Alarm summary:\n\n"
                                "Sites not reporting: \n"
                                f"{format_no_report}\n\n"
                                "Sites reporting irregular voltage: \n"
                                f"{format_irreg_v}\n\n"
                                "Sites reporting irregular data: \n"
                                f"{format_irreg_data}\n\n"
                                f"{valediction}")

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
                print("paradise email sent")
                end = True
                break
    else:
        break

