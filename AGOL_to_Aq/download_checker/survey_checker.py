import os
from datetime import datetime, timedelta

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


FILE = r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form_Data.shp'
HOUR_WINDOW = 12
RECIPIENTS = 'david.saba@mt.gov, nyoungstrom@mt.gov'

email = True

try:
    # Check if file exists
    if not os.path.exists(FILE):
        print(f"Error: File '{FILE}' does not exist")
    # Get the last modification time of the file
    last_modified_timestamp = os.path.getmtime(FILE)
    last_modified_time = datetime.fromtimestamp(last_modified_timestamp)

    # Get current time and calculate the threshold
    current_time = datetime.now()
    time_threshold = current_time - timedelta(hours=HOUR_WINDOW)

    # Compare times
    if last_modified_time < time_threshold:
        txt = f"UPDATE FAILED: WSB's Survey123 shapefile was last updated on {last_modified_time.strftime('%Y-%m-%d %H:%M:%S')}"
        print(txt)
        email = True
    else:
        txt = "Everything's fine, not sure why your getting this email"
        email = False

except Exception as e:
    txt = f"Error checking file: {e}"
    print(txt)
    email = True

if email:
    msg = MIMEMultipart()
    msg['Subject'] = f"Survey123 Field Forms Issue"
    msg['From'] = 'Form_Checker_Daemon@dnrc.mt.gov'
    msg['To'] = RECIPIENTS

    body = MIMEText(txt)

    msg.attach(body)

    with smtplib.SMTP('mail.mt.gov', 25) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.send_message(msg)
        server.quit()
    print("email sent")

