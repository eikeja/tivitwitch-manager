import smtplib
from email.mime.text import MIMEText
from flask import current_app
from db import get_db, get_setting

def send_mail(to, subject, body):
    """Sends an email using the SMTP settings from the database."""
    try:
        smtp_host = get_setting('smtp_host', 'smtp.example.com')
        smtp_port = int(get_setting('smtp_port', '587'))
        smtp_user = get_setting('smtp_user', '')
        smtp_password = get_setting('smtp_password', '')
        smtp_from = get_setting('smtp_from', 'noreply@example.com')

        if not smtp_host or smtp_host == 'smtp.example.com':
            current_app.logger.warning(f"[Mail] SMTP not configured. Skipping email to {to}.")
            return False

        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = smtp_from
        msg['To'] = to

        current_app.logger.info(f"[Mail] Connecting to {smtp_host}:{smtp_port}...")
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
            
        current_app.logger.info(f"[Mail] Email sent to {to}")
        return True
    except Exception as e:
        current_app.logger.error(f"[Mail] Failed to send email to {to}: {e}")
        return False
