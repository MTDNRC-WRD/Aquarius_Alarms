import pandas as pd
import requests
from requests.exceptions import HTTPError, Timeout, ConnectionError
import json
from pathlib import Path
import datetime as dt
from tqdm import tqdm
import time

# SERVER_NAME = 'dnrhln6386.state.mt.ads'
SERVER_NAME = 'dnrc-mt-prod.aquaticinformatics.net'
USER_NAME = ''
PASSWORD = ''

RETRY_TIMEOUT = 600
RETRY_INTERVAL = 30

tmin_day = dt.datetime.utcnow() - dt.timedelta(minutes=1500)
tmin_day = tmin_day.strftime(f"%Y-%m-%dT%H:%M:%SZ")
t_now = dt.datetime.utcnow()
t_now = t_now.strftime(f"%Y-%m-%dT%H:%M:%SZ")
t_now_format = dt.datetime.now()
t_now_format = t_now_format.strftime(f"%b %d, %Y")

gage_csv = Path(__file__).parent.parent.parent / 'Q_Alarm' / 'q_list.csv'
gage_df = pd.read_csv(gage_csv, skip_blank_lines=True)
location_id_list = gage_df['LocationIdentifier'].tolist()

# ── Step 1: Fetch all UniqueIds for each location ──────────────────────────────
df_columns = ['UniqueId', 'LocationIdentifier', 'SiteName', 'Parameter', 'Timestamp', 'Value', 'Unit', 'Publish']
failed_ids = []
int_df = pd.DataFrame(columns=df_columns)

for gid in tqdm(location_id_list, desc="Fetching Unique IDs"):  # single loop, no duplicate
    retry_start = time.time()
    success = False

    while True:
        try:
            response = requests.get(
                url=f"http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesUniqueIdList",
                auth=(USER_NAME, PASSWORD),
                params={"LocationIdentifier": gid},
            )
            response.raise_for_status()

            time_data = response.json()
            time_data_list = time_data["TimeSeriesUniqueIds"]

            temp_df = pd.DataFrame(time_data_list)
            temp_df.rename(columns={"TimeSeriesUniqueId": "UniqueId"}, inplace=True)
            temp_df["LocationIdentifier"] = gid
            int_df = pd.concat([int_df, temp_df], ignore_index=True)

            success = True
            break

        except (Timeout, ConnectionError) as e:
            elapsed = time.time() - retry_start
            remaining = RETRY_TIMEOUT - elapsed
            if remaining <= 0:
                print(f"\nConnection could not be re-established after {RETRY_TIMEOUT}s at location {gid}.")
                print("Saving progress and exiting...")
                break
            print(f"\nConnection lost at location {gid}. Retrying for up to {remaining:.0f}s more... ({e})")
            time.sleep(RETRY_INTERVAL)

        except HTTPError as e:
            print(f"Request failed for ID {gid}: {e}")
            failed_ids.append(gid)
            success = True
            break

    if not success:
        break  # Connection retries exhausted, exit outer loop

# Saves whether loop completed or broke early
int_df.to_csv('unique_ids.csv', index=False)
print(f"Successfully fetched {len(int_df)} unique IDs.")
print(f"Failed to process {len(failed_ids)} location IDs.")
if failed_ids:
    print(f"Failed IDs: {failed_ids}")


# ── Step 2: Fetch corrected time series data for each UniqueId ─────────────────
uid_list = int_df['UniqueId'].tolist()
site_data = []
failed_uids = []

for uid in tqdm(uid_list, desc="Fetching Time Series Data"):
    retry_start = time.time()
    success = False

    while True:
        try:
            response = requests.get(
                url=f"http://{SERVER_NAME}/AQUARIUS/Publish/v2/GetTimeSeriesCorrectedData",
                auth=(USER_NAME, PASSWORD),
                params={
                    'TimeSeriesUniqueId': uid,
                    'QueryFrom': tmin_day,
                    'QueryTo': t_now,
                },
            )
            response.raise_for_status()
            series_data = response.json()

            points = series_data.get("Points", [])
            timestamp = points[-1]["Timestamp"] if points else None
            value = points[-1]["Value"]["Numeric"] if points else None

            site_data.append({
                "UniqueId":           series_data.get("UniqueId"),
                "LocationIdentifier": series_data.get("LocationIdentifier"),
                "SiteName":           None,
                "Parameter":          series_data.get("Parameter"),
                "Timestamp":          timestamp,
                "Value":              value,
                "Unit":               series_data.get("Unit"),
                "Publish":            series_data.get("Label"),
            })
            success = True
            break

        except (Timeout, ConnectionError) as e:
            elapsed = time.time() - retry_start
            remaining = RETRY_TIMEOUT - elapsed
            if remaining <= 0:
                print(f"\nConnection could not be re-established after {RETRY_TIMEOUT}s at UniqueId {uid}.")
                print("Saving progress and exiting...")
                break
            print(f"\nConnection lost at UniqueId {uid}. Retrying for up to {remaining:.0f}s more... ({e})")
            time.sleep(RETRY_INTERVAL)

        except HTTPError as e:
            print(f"Request failed for UniqueId {uid}: {e}")
            failed_uids.append(uid)
            success = True
            break

    if not success:
        break  # Connection retries exhausted, exit outer loop

# Build final DataFrames — save full results, then filtered
out_df = pd.DataFrame.from_records(site_data, columns=df_columns)
out_df.to_csv('final_fields.csv', index=False)

daily_avg_df = out_df[(out_df['Publish'] == 'Daily Average') & (out_df['Parameter'] == 'Discharge')]
daily_avg_df.to_csv('daily_averages.csv', index=False)

print(f"Successfully processed {len(out_df)} total records.")
print(f"Saved {len(daily_avg_df)} Daily Average records.")
print(f"Failed to process {len(failed_uids)} UniqueIds.")
if failed_uids:
    print(f"Failed UniqueIds: {failed_uids}")
