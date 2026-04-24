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


# SERVER_NAME = 'dnrhln6386.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'
USER_NAME = 'DNRC'
PASSWORD = 'DNRC'
DIRECTORY = Path(r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\GoldCreek')
RECIPIENTS = "bruce@thomasherefords.com, David.Saba@mt.gov, Hannah.Haugen@mt.gov"
# RECIPIENTS = "bruce@thomasherefords.com, David.Saba@mt.gov"
# RECIPIENTS = "David.Saba@mt.gov"

def format_timestamp(time):
    if time == 0 or time == 'null':
        return 0
    else:
        try:
            tf = dt.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%f0%z")  # - dt.timedelta(hours=7)
            tf = tf.strftime("%b-%d  %H:%M")
            return tf
        except ValueError:
            time_list = list(time.strip(""))
            time_list[12] = "3"
            time = ''.join(time_list)
            tf = dt.datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%f0%z")  # - dt.timedelta(hours=6)
            tf = tf.strftime("%b-%d  %H:%M")
            return tf


def format_windspeed(deg):
    if 337 > deg < 23:
        wd = 'North'
    elif 22 < deg < 68:
        wd = 'NorthEast'
    elif 67 < deg < 113:
        wd = 'East'
    elif 112 < deg < 158:
        wd = 'SouthEast'
    elif 157 < deg < 203:
        wd = 'South'
    elif 202 < deg < 248:
        wd = 'SouthWest'
    elif 247 < deg < 293:
        wd = 'West'
    elif 292 < deg < 338:
        wd = 'NorthWest'
    else:
        wd = "Hmmmmm, somethings broken"
    return wd


df = None

tmin_day = dt.datetime.utcnow() - dt.timedelta(minutes=1820)
tmin_day = tmin_day.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now = dt.datetime.utcnow()
t_now = t_now.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now_format = dt.datetime.now()
t_now_format = t_now_format.strftime(f"%b %d, %Y")

# year = dt.date.today().year
# new_years = dt.date(year, 1, 1)
# new_years = new_years.strftime(f"%Y-%m-%dT%H:%M:%SZ")

yesterday = dt.datetime.utcnow() - dt.timedelta(minutes=1440)
yesterday_format = yesterday.strftime(f"%a, %b-%d")
yesterday = yesterday.strftime(f"%b-%d")

today = dt.datetime.utcnow()
today_format = today.strftime(f"%a, %b-%d")
today = today.strftime(f"%b-%d")

# # Outputs csv of sensor data anomalies based on reference to master sensor list csv # #
sl_df = pd.read_csv(Path.joinpath(DIRECTORY, 'sensor_list.csv'))
to_pull_df = sl_df[sl_df['Publish'] == True]
print("Acquiring StAGE data...")
site_data = []
for uid in to_pull_df['UniqueId']:
    aq_params = {'TimeSeriesUniqueId': uid,
                 'QueryFrom': tmin_day,
                 'QueryTo': t_now}
    response = requests.get(
        url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
        auth=(USER_NAME, PASSWORD),
        params=aq_params)
    response.raise_for_status()
    series_data = response.json()
    # print(json.dumps(series_data, indent=4))
    timestamps = []
    try:
        for t in range(len(series_data["Points"])):
            timestamp = series_data["Points"][t]["Timestamp"]
            timestamp = format_timestamp(timestamp)
            timestamps.append(timestamp)
    except IndexError:
        timestamps.append('null')
    values = []
    try:
        for v in range(len(series_data["Points"])):
            value = float(series_data["Points"][v]["Value"]["Numeric"])
            values.append(value)
    except IndexError:
        values.append('null')

    param_dict = {
        "Parameter": series_data["Parameter"],
        "Unit": series_data["Unit"]
    }
    val_dict = dict(zip(timestamps, values))
    if df is None:
        col_list = ['Parameter', 'Unit']
        col_list.extend(timestamps)
        df = pd.DataFrame(columns=col_list)
        param_dict.update(val_dict)
        df.loc[len(df)] = param_dict

    else:
        param_dict.update(val_dict)
        df.loc[len(df)] = param_dict

df.to_csv(Path.joinpath(DIRECTORY, 'today_data.csv'))


airtemp_row = df.loc[df['Parameter'] == 'Air Temp']
airtemp_unit = airtemp_row.drop(airtemp_row.columns[0], axis=1).drop(airtemp_row.columns[2:], axis=1)['Unit'].tolist()[0]
airtemp_data = airtemp_row.drop(airtemp_row.columns[:2], axis=1)

precip_row = df.loc[df['Parameter'] == 'Precip Cumul']
precip_unit = precip_row.drop(precip_row.columns[0], axis=1).drop(precip_row.columns[2:], axis=1)['Unit'].tolist()[0]
precip_data = precip_row.drop(precip_row.columns[:2], axis=1)

winddir_row = df.loc[df['Parameter'] == 'Wind Dir']
winddir_unit = winddir_row.drop(winddir_row.columns[0], axis=1).drop(winddir_row.columns[2:], axis=1)['Unit'].tolist()[0]
winddir_data = df.loc[df['Parameter'] == 'Wind Dir'].drop(df.columns[:2], axis=1)

windvel_row = df.loc[df['Parameter'] == 'Wind Vel']
windvel_unit = windvel_row.drop(windvel_row.columns[0], axis=1).drop(windvel_row.columns[2:], axis=1)['Unit'].tolist()[0]
windvel_data = df.loc[df['Parameter'] == 'Wind Vel'].drop(df.columns[:2], axis=1)


# today's data
current_temp = int(airtemp_data.iloc[:, -1].tolist()[0])
current_temp_time = airtemp_data.columns[-1]
current_temp_text = f"Current Temperature: {current_temp} {airtemp_unit} ({current_temp_time})\n"

current_windvel = windvel_data.iloc[:, -1].tolist()[0]
current_windvel_time = windvel_data.columns[-1]
current_windvel_text = f"Current Wind Speed: {current_windvel} {windvel_unit} ({current_windvel_time})\n"

current_winddir = winddir_data.iloc[:, -1].tolist()[0]
current_winddir_time = winddir_data.columns[-1]
cwd = format_windspeed(int(current_winddir))
current_winddir_text = f"Current Wind Direction: {cwd}  ({current_winddir} {winddir_unit})\n"

morning_temps = airtemp_data.filter(regex=today, axis=1)
over_low = int(morning_temps.min().min())
over_low_time = morning_temps.min().idxmin()
over_low_text = f"Overnight Low: {over_low} {airtemp_unit} ({over_low_time})\n"

over_precip_data = precip_data.filter(regex=today, axis=1)
start_overprecip = float(over_precip_data.iloc[:, 0].tolist()[0])
end_overprecip = float(over_precip_data.iloc[:, -1].tolist()[0])
over_precip = round((end_overprecip - start_overprecip), 2)
new_precip_unit = 'in'
over_precip_text = f"Overnight Precipitation: {over_precip} {new_precip_unit}\n"

over_windvel = windvel_data.filter(regex=today, axis=1)
over_ave_windvel = round(over_windvel.mean(axis=1).tolist()[-1])
over_ave_windvel_text = f"Overnight Average Wind Speed: {over_ave_windvel} {windvel_unit}\n"
over_max_windvel = over_windvel.max().max()
over_max_windvel_time = over_windvel.max().idxmax()
over_max_windvel_text = f"Overnight Max Wind Speed: {over_max_windvel} {windvel_unit} ({over_max_windvel_time})\n"

print(current_temp_text, over_low_text, over_precip_text, over_ave_windvel_text)

# yesterday's data
yes_precip_data = precip_data.filter(regex=yesterday, axis=1)
start_yesprecip = float(yes_precip_data.iloc[:, 0].tolist()[0])
end_yesprecip = float(yes_precip_data.iloc[:, -1].tolist()[0])
daily_precip = round((end_yesprecip - start_yesprecip), 2)
yes_precip_text = f"Precipitation: {daily_precip} {new_precip_unit}\n"

yes_airtemp = airtemp_data.filter(regex=yesterday, axis=1)
yes_max_temp = int(yes_airtemp.max().max())
yes_max_temp_time = yes_airtemp.max().idxmax()
yes_max_temp_text = f"Maximum Temperature: {yes_max_temp} {airtemp_unit} ({yes_max_temp_time})\n"

yes_min_temp = int(yes_airtemp.min().min())
yes_min_temp_time = yes_airtemp.min().idxmin()
yes_min_temp_text = f"Minimum Temperature: {yes_min_temp} {airtemp_unit} ({yes_min_temp_time})\n"

yes_windir = winddir_data.filter(regex=yesterday, axis=1)
ave_winddir = round(yes_windir.mean(axis=1).tolist()[-1])
ywd = format_windspeed(int(ave_winddir))
yes_ave_winddir_text = f"Average Wind Direction: {ywd}  ({ave_winddir} {winddir_unit})\n"

yes_windvel = windvel_data.filter(regex=yesterday, axis=1)
ave_windvel = round(yes_windvel.mean(axis=1).tolist()[-1])
yes_ave_windvel_text = f"Average Wind Speed: {ave_windvel} {windvel_unit}\n"

yes_windvel_max = windvel_data.filter(regex=yesterday, axis=1)
max_windvel = yes_windvel_max.max().max()
max_windvel_time = windvel_data.max().idxmin()
yes_max_windvel_text = f"Maximum Wind Speed: {max_windvel} {windvel_unit} ({max_windvel_time})\n"

print(yes_max_temp_text, yes_min_temp_text, yes_precip_text, yes_ave_windvel_text, yes_max_windvel_text,
      yes_ave_winddir_text)

#YTD data
today_precip = precip_data.filter(regex=today, axis=1)
ytd_precip_raw = float(today_precip.iloc[:, -1].tolist()[0])
ytd_precip = round(ytd_precip_raw, 2)
new_precip_unit = 'in'
ytd_precip_text = f"YTD Precipitation: {ytd_precip} {new_precip_unit}\n"

print(ytd_precip_text)

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
ps = ''
if current_temp < 0:
    ps = "Don't Forget to Put Your Long Johns On!"
if yes_max_temp >= 95:
    ps = "WOOOOOOEEEEEE It's Hot"
if daily_precip >= 1:
    ps = "Don't Forget to Blow Dry The Cows"


attachment = str(Path.joinpath(DIRECTORY, 'STAGE_Alarms.csv'))
msg = MIMEMultipart()
msg['Subject'] = f"Daily Weather Summary {t_now_format}"
msg['From'] = 'GoldCreekWeatherStation@dnrc.mt.gov'
msg['To'] = RECIPIENTS

body = MIMEText(f"Morning Conditions ({today_format}):\n\n"              
                f"-{current_temp_text}\n"
                f"-{over_low_text}\n"
                f"-{over_precip_text}\n"
                f"-{current_windvel_text}\n"
                f"-{current_winddir_text}\n"
                f"-{over_max_windvel_text}\n\n"
                f"Yesterday's Conditions ({yesterday_format}):\n\n"                
                f"-{yes_max_temp_text}\n"
                f"-{yes_min_temp_text}\n"
                f"-{yes_precip_text}\n"
                f"-{yes_max_windvel_text}\n"
                f"-{yes_ave_windvel_text}\n"              
                f"-{yes_ave_winddir_text}\n\n"  
                f"-{ytd_precip_text}\n\n"    
                f"{valediction}\n"
                f"{ps}")

# part = MIMEBase('application', "octet-stream")
# part.set_payload(open(attachment, "rb").read())
# encoders.encode_base64(part)
# part.add_header('Content-Disposition', 'attachment', filename=attachment)

msg.attach(body)
# msg.attach(part)

with smtplib.SMTP('mail.mt.gov', 25) as server:
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.send_message(msg)
print("email sent")

