# Aquarius_Alarms

Scripts that monitor DNRC/WRD gages in AQUARIUS and the AGOL (Survey123) field-form pipeline. They send email alarms, pull data for analysis, and turn field-form records into PDFs.

Scripts are designed to run unattended on a schedule (Windows Task Scheduler via the `.bat` files) and read/write to the shared network drive:

`\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\`

## Repository layout

```
Aquarius_Alarms/
├── aq_env.yml # Conda environment (Python 3.9)
├── Discharge_Alarms/ # Daily discharge alarm (all monitored sites)
├── Gage_Alarms/
│ ├── WSB/ # Daily sensor alarms (stage, battery voltage, etc.)
│ ├── GoldCreek/ # Gold Creek low-flow alarm and daily weather
│ └── SWPB/ # SWPB daily sensor alarm email
├── Gage_Data_Getters/ # Utilities that pull data from AQUARIUS
│ ├── daily_datas/ # Daily means, medians, visualizations
│ └── timeseries_ids/ # TimeSeriesUniqueId lookup
└── Gage_Form_Filler/ # AGOL discharge-measurement form -> PDF pipeline
```


Most projects follow the same sub-structure:

| Folder | Purpose |
|---|---|
| `core/` | The Python scripts that run |
| `bat/` | Batch files used by Task Scheduler |
| `cache/` | Temporary files |
| `outputs/` | CSV outputs from the last run |

**Note:** every `core/old/` folder contains deprecated scripts kept for reference only. They aren't maintained or scheduled, and they're not documented here.

## Projects

### Discharge_Alarms
`core/discharge_alarm.py` queries AQUARIUS for instantaneous discharge at each site in `Qlist.xlsx` and sends a daily email when a site:

- has no data, or reports zero or null discharge
- exceeds its high-flow threshold
- has a 24-hour increase above its delta threshold

Values are compared at the latest point, about 1 hour ago and about 24 hours ago (15-minute data). The email is HTML with a plain-text fallback (see [Alarm email format](#alarm-email-format)). It lists the alarmed sites and attaches `Instant_Discharge_Alarms.csv`. Full results go to `outputs/Instant_Discharge.csv`. The low-flow column exists in `Qlist.xlsx` but is not evaluated.

### Gage_Alarms/WSB
`core/sensor_alarms.py` checks the latest reading for every sensor in `SensorList.xlsx` and emails a daily summary of:

- sites not reporting in the last 24 hours
- battery voltage outside its band
- other parameters outside their low/high alarm band

The email is HTML with a plain-text fallback (see [Alarm email format](#alarm-email-format)). It has one table per alarm type, shows each value with its unit, and ends with a randomly chosen pleasantry. A second email with the same content goes to the Paradise Valley list when one of the Paradise Valley sites is in alarm. If the script crashes, a separate plain-text failure email with the traceback goes to the failure recipients. Outputs are `outputs/todays_data.csv` and `outputs/STAGE_Alarms.csv`.

### Gage_Alarms/GoldCreek
- `core/low_flow.py` is the Gold Creek low/high flow alarm. It emails the pump crew when flow crosses a threshold. It also sends a data-problem ("broken") email when data is stale or missing.
- `core/alarm_state.json` holds the alarm state, so each alarm is sent once rather than on every run.
- `core/daily_weather.py` is the daily weather script.

### Gage_Alarms/SWPB
A flat folder with a daily alarm email script (`SWPB_daily_alarm_email.py`), sensor list files, a `TimeSeriesID.py` helper, and sample or output CSVs.

### Gage_Data_Getters
- `daily_datas/` has scripts that get daily data (`daily_data_getter.py`), calculate daily mean discharge (`Daily_mean_Q.py`) and medians (`medians_calc.py`), and make plots (`visualizer.py`). Inputs go in `inputs/` and results in `outputs/`.
- `timeseries_ids/` has `TimeSeriesID.py` and `output_tsid.csv`, a lookup of AQUARIUS TimeSeriesUniqueIds.

### Gage_Form_Filler
Turns Survey123 discharge-measurement records into PDF field forms.

- `core/Form_Filler.py` reads records from the AGOL file geodatabase (`WSB_Discharge_Measurement_Form.gdb`, feature class `WSB_Discharge_Measurement_Form_Data`). It keeps records where `rt_gage_site == 'Yes'` and maps fields to cells in an Excel template (`db/DNRC_Qm_Form_live.xlsx`). It exports each one as a PDF to the Electronic Field Forms folder and emails a summary of how many files were saved.
- Processed records are tracked in a SQLite database (`db/uploaded_data.sqlite`). A record is identified by measurement date, visitation time and gage site ID, so each is only processed once.
- `core/SQLite_builder.py` and `core/Print_SQLite.py` help create and inspect the tracking database.
- `core/survey_checker.py` checks that the geodatabase is still being synced from AGOL. It emails an alert if no table file in the `.gdb` has been modified within the configured window. The AGOL sync runs every 24 hours, so the window should be longer than that.
- `gage_list.csv` maps gage site IDs to site names.
- `push_data_to_aq()` in `Form_Filler.py` is a placeholder. Pushing data back into AQUARIUS is not implemented.

## Setup

1. Create the environment:
   ```
   conda env create -f aq_env.yml
   conda activate aquarius
   ```
   The environment file includes Windows-specific builds and a user-specific `prefix` line, so you may need to remove the `prefix:` line or adjust builds on a different machine. `aspose-cells-python` is used to export PDFs and requires a license for production use without a watermark.
2. Create a credentials file at `...\AQMetadata\Aquarius_Alarms\creds.txt` (not in the repo):
   ```
   AQUARIUS_USER=your_username
   AQUARIUS_PASSWORD=your_password
   ```
3. Make sure the machine can reach the network share, the SMTP relay `mail.mt.gov` (port 25), and the AQUARIUS server `dnrc-mt-prod.aquaticinformatics.net`.

## Configuration

Each script has a CONFIG block at the top with paths, server name, thresholds, and email lists. Alarm thresholds live in the Excel site lists:

| File | Columns |
|---|---|
| `Qlist.xlsx` (sheet `q_list`) | TimeSeriesUniqueId (index), SiteName, LowAlarm, HighAlarm, Delta, Publish |
| `SensorList.xlsx` (sheet `sensor_list`) | TimeSeriesUniqueId (index), LocationIdentifier, SiteName, Parameter, Unit, LowAlarm, HighAlarm, Publish |

Only rows with `Publish = True` are evaluated. Bad rows (blank thresholds, duplicate IDs) don't stop a run. They're skipped, and a warning email goes to the failure recipients.

Other conventions:

- **Testing:** several scripts have a commented-out `RECIPIENTS = ['...']` line. Swap it in to send only to yourself. The Gold Creek and survey checker scripts have a `DRY_RUN` flag that prints emails instead of sending them.
- **Timezones:** AQUARIUS returns UTC. The scripts convert to Mountain time by subtracting 6 or 7 hours.
- **Failure emails:** scheduled alarm scripts email the failure list with a traceback if they crash.

## Alarm email format

The discharge and sensor alarm emails are multipart: an HTML body with a plain-text fallback, plus the alarm CSV as an attachment. Both scripts use the same HTML helpers (`build_alarm_table()` and `build_html_body()`), which produce:

- one table per alarm type, with ID, Site Name and value columns
- a colored header per section showing the section name and count; empty sections show **None**
- alternating light-tinted rows and a thin line under every row and under the header
- a fixed layout capped at 640 px wide; long site names are cut off with an ellipsis

Look and feel is controlled by constants near the top of each script:

| Constant | Effect |
|---|---|
| `HTML_MAX_WIDTH` | Maximum table width in px |
| `HTML_ID_COL_PX`, `HTML_VALUE_COL_PX` | Fixed widths of the ID and value columns; Site Name takes the rest |
| `HTML_TINT` | How light the alternating row color is (0 = full header color, 1 = white) |
| `SECTION_STYLES` | Header color for each section |

Notes:

- Styles are inline and the layout uses tables so the email renders in mail clients. Desktop Outlook may ignore `max-width` and show the table wider than 640 px.
- `send_email()` takes an optional `html_body`. If it is left out, recipients get the plain-text version.
- Failure and site-list-warning emails stay plain text.

## Running

Run a script directly:


```
conda activate aquarius
python Discharge_Alarms\core\discharge_alarm.py
```

For scheduled runs, point Task Scheduler at the `.bat` file in each project's `bat/` folder. Check the data schedule when choosing times. For example, the Gold Creek gage transmits 15-minute data hourly, and the AGOL sync runs every 24 hours.

## Maintainers

DNRC Water Resources Division. Contact: David Saba (david.saba@mt.gov).
