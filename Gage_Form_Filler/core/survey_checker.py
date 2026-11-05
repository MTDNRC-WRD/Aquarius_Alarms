import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

GDB_PATH = Path(
    r'\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\GIS\AGOL\Discharge_Form_Data\WSB_Discharge_Measurement_Form.gdb'
)
HOUR_WINDOW = 30
RECIPIENTS = ['david.saba@mt.gov', 'nyoungstrom@mt.gov']
EMAIL_FROM = 'Form_Checker_Daemon@dnrc.mt.gov'
DRY_RUN = False

def send_email(subject, text):
    if DRY_RUN:
        print(f'[DRY RUN] To: {RECIPIENTS}\nSubject: {subject}\n{text}')
        return
    msg = MIMEText(text)
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = ', '.join(RECIPIENTS)
    with smtplib.SMTP('mail.mt.gov', 25) as server:
        server.send_message(msg)
    print('email sent')


try:
    if not GDB_PATH.exists():
        raise FileNotFoundError(f"Geodatabase '{GDB_PATH}' does not exist")

    files = [p for p in GDB_PATH.glob('*.gdbtable*') if p.is_file()]
    if not files:
        raise RuntimeError('No .gdbtable files found in geodatabase')

    newest = max(files, key=lambda p: p.stat().st_mtime)
    last_modified = datetime.fromtimestamp(newest.stat().st_mtime)
    age = datetime.now() - last_modified
    print(f'Last update: {last_modified:%Y-%m-%d %H:%M:%S} ({newest.name}), {age} ago')

    if age > timedelta(hours=HOUR_WINDOW):
        send_email('Survey123 Field Forms Issue',
                   f"UPDATE FAILED: WSB's Survey123 geodatabase was last updated "
                   f'{last_modified:%Y-%m-%d %H:%M:%S}, {age.total_seconds()/3600:.1f} hours ago.')
    else:
        print('Geodatabase updated within window; no email.')
except Exception as e:
    send_email('Survey123 Field Forms Issue', f'Error checking geodatabase: {e}')

