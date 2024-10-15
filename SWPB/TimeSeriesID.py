import requests
import json
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


tmin_day = dt.datetime.utcnow() - dt.timedelta(minutes=1500)
tmin_day = tmin_day.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now = dt.datetime.utcnow()
t_now = t_now.strftime(f"%Y-%m-%dT%H:%M:%SZ")

t_now_format = dt.datetime.now()
t_now_format = t_now_format.strftime(f"%b %d, %Y")

# # Gets times series id's for everything transmitted during last day, when adding new site search by loc id # #
response = requests.get(
    url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesUniqueIdList',
    auth=(USER_NAME, PASSWORD),
    # params={"ChangesSinceToken": tmin_day}
    params={"LocationIdentifier": "42B 01900"}  # # Gets location descriptions and create list of location ID, unique, ID, site name # #
)
response.raise_for_status()
time_data = response.json()
time_data = time_data["TimeSeriesUniqueIds"]
# print(json.dumps(time_data, indent=4))
time_id = [key["UniqueId"] for key in time_data]
print(time_id)
print(len(time_id))
df = pd.DataFrame(time_id)
df.to_csv('site_ts_ids.csv')

# # Outputs csv of all published sites based on input timeseries id list # #
# # df = pd.read_csv('sensor_list.csv')
# # ts_ids = df['UniqueId'].to_list()
# ts_ids = time_id
# site_data = []
# for i in ts_ids:
#     aq_params = {'TimeSeriesUniqueId': i,
#                  'QueryFrom': tmin_day,
#                  'QueryTo': t_now}
#     response = requests.get(
#         url=f'http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData',
#         auth=(USER_NAME, PASSWORD),
#         params=aq_params)
#     response.raise_for_status()
#     series_data = response.json()
#     # print(json.dumps(series_data, indent=4))
#     site_index = site_id.index(series_data["LocationIdentifier"])
#     try:
#         timestamp = series_data["Points"][-1]["Timestamp"]
#     except IndexError:
#         timestamp = 0
#     try:
#         value = series_data["Points"][-1]["Value"]["Numeric"]
#     except IndexError:
#         value = 0
#     point_dict = {
#         "UniqueId": series_data["UniqueId"],
#         "LocationIdentifier": series_data["LocationIdentifier"],
#         "SiteName": site_name[site_index],
#         "Parameter": series_data["Parameter"],
#         "Timestamp": timestamp,
#         "Value": value,
#         "Unit": series_data["Unit"],
#         "Publish": publish[site_index]
#     }
#
#     site_data.append(point_dict)
#
# print(json.dumps(site_data, indent=4))
# df = pd.DataFrame.from_records(site_data)
# df.to_csv('output_published.csv')


