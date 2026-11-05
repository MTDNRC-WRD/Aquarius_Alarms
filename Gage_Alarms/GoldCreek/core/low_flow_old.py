import datetime as dt
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd
import requests

# SERVER_NAME = 'dnrhln6386.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'
USER_NAME = 'DNRC'
PASSWORD = 'DNRC'
DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\GoldCreek')
RECIPIENTS = "bruce@thomasherefords.com, 4065441536@vtext.com, John.Lunzer@mt.gov, 4069169738@tmomail.net, David.Saba@mt.gov"
# RECIPIENTS = "David.Saba@mt.gov"
Q_ID = '9c276f5ebcdf4a758e1a9dc93f891f87'
GAGE = '76G 05850'
GAGE_NAME = 'Gold Creek near Gold Creek, MT'

LAST_ALARM_FILE = Path.joinpath(DIRECTORY,'last_Q_alarm.csv')
BROKEN_FILE = Path.joinpath(DIRECTORY,'am_i_broken.csv')

ALARM_LOW = 6.0
ALARM_HIGH = 8.0

tmin_day = dt.datetime.utcnow() - dt.timedelta(minutes=1440)
tmin_day = tmin_day.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now = dt.datetime.utcnow()
t_now = t_now.strftime(f"%Y-%m-%dT%H:%M:%SZ")


def format_timestamp(time):
    if time == 'null':
        return 'null'
    else:
        try:
            tf = dt.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%f0%z")
            tf = tf.strftime("%b-%d %H:%M")
            return tf
        except ValueError:
            time_list = list(time.strip(""))
            time_list[12] = "3"
            time = ''.join(time_list)
            tf = dt.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%f0%z")
            tf = tf.strftime("%b-%d %H:%M")
            return tf

# def save_trans_time():
#     trans_df = pd.DataFrame({'last_transmission': [t_now]})
#     trans_df.to_csv(Path.joinpath(DIRECTORY,'last_low_Q_alarm.csv'))
#     print("transmission time updated")
#
#
# def check_trans_time():
#     trans_df = pd.read_csv(Path.joinpath(DIRECTORY,'last_low_Q_alarm.csv'))
#     last_tt = dt.datetime.strptime(trans_df['last_transmission'][0], f"%Y-%m-%dT%H:%M:%SZ")
#     utc_now = dt.datetime.utcnow()
#     t_diff = utc_now - last_tt
#     t_delta = timedelta(hours=24)
#
#     if t_diff >= t_delta:
#         return True
#     else:
#         return False

def say_i_broke():
    br_df = pd.DataFrame({'Status': ['broken']})
    br_df.to_csv(BROKEN_FILE)

def check_if_i_broke_before():
    br_df = pd.read_csv(BROKEN_FILE)
    status = br_df['Status'][0]
    if status == 'broken':
        return False
    else:
        return True


def save_current_alarm(a_type):
    al_df = pd.DataFrame({'alarm': [a_type]})
    al_df.to_csv(LAST_ALARM_FILE)
    print("alarm type updated")

def check_last_alarm(n_type):
    al_df = pd.read_csv(LAST_ALARM_FILE)
    l_type = al_df['alarm'][0]
    if l_type == n_type:
        return False
    else:
        return True


print("Acquiring StAGE data...")
aq_params = {'TimeSeriesUniqueId': Q_ID,
             'QueryFrom': tmin_day,
             'QueryTo': t_now}
response = requests.get(
    url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
    auth=(USER_NAME, PASSWORD),
    params=aq_params)

try:
    response.raise_for_status()
    series_data = response.json()
    # print(json.dumps(series_data, indent=4))
except requests.exceptions.HTTPError:
    print(f"Can't Retrieve Data")

try:
    timestamps_list = []
    for timestamp in series_data["Points"][-4:]:
        timestamps_list.append(timestamp["Timestamp"])
except IndexError:
    timestamps_list = ['null']

try:
    discharge_list = []
    for discharge in series_data["Points"][-4:]:
        discharge_list.append(float(discharge["Value"]["Numeric"]))
except IndexError:
    discharge_list = ['null']


# discharge checker, is Q < low alarm or > high alarm? Gets the first instance
broken = False
alarm = False
for index, discharge in enumerate(discharge_list):
    if discharge == 'null':
        broken = True
    elif discharge <= ALARM_LOW:
        q = discharge
        ts = timestamps_list[index]
        alarm_type = 'low'
        alarm = True
        break
    elif discharge >= ALARM_HIGH:
        q = discharge
        ts = timestamps_list[index]
        alarm_type = 'high'
        alarm = True
        break

# We only want to send one broken email so lets check the broken status
if broken:
    first_time = check_if_i_broke_before()
    if first_time:
        say_i_broke()
        msg = MIMEMultipart()
        msg['Subject'] = f"Gold Creek Discharge Warning"
        msg['From'] = 'Alarm@dnrc.mt.gov'
        msg['To'] = RECIPIENTS

        body = MIMEText("Something is broken.\n"
                        "Go find Dave and tell him to fix it!"
                     )
        msg.attach(body)
        with smtplib.SMTP('mail.mt.gov', 25) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.send_message(msg)
            server.quit()
        print("broken email sent")


elif alarm:
    # Let's see what the last alarm was
    # We only want to transmit of the last alarm sent was opposite this one
    send_it = check_last_alarm(alarm_type)
    if send_it:
        save_current_alarm(alarm_type)
        q_format = round(q, 1)
        ts_format = format_timestamp(ts)
        if alarm_type == 'high':
            body = MIMEText("\n"
                            f"{ts_format}: {q_format}cfs\n\n"
                            "TURN THEM PUMPS BACK ON BOYS!\n"
                            )
            print("sending high alarm email")

        elif alarm_type == 'low':
            body = MIMEText("\n"
                            f"{ts_format}: {q_format}cfs\n\n"
                            "SHUT THEM PUMPS DOWN BOYS!\n"
                            )
            print("sending low alarm email")

        msg = MIMEMultipart()
        msg['Subject'] = f"Gold Creek Discharge Warning"
        msg['From'] = 'Alarm@dnrc.mt.gov'
        msg['To'] = RECIPIENTS
        msg.attach(body)

        with smtplib.SMTP('mail.mt.gov', 25) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.send_message(msg)
            server.quit()
