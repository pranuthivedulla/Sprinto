"""Gmail SMTP send. Only ever to TO_EMAIL, only after a human approval, only under the cap.

Times are stored in UTC; the daily cap uses the India-time day, which is the day the
Growth Lead actually works in.
"""
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from . import config, db

IST = timezone(timedelta(hours=5, minutes=30))
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def ist_now():
    return datetime.now(IST)


def to_ist(stamp):
    """Format a stored UTC timestamp string in India time for the UI."""
    if not stamp:
        return ""
    try:
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return stamp
    return when.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def day_start_utc():
    start = ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def cap_state():
    cap = config.get_int("DAILY_SEND_CAP", 15)
    used = db.sends_today(day_start_utc())
    return {"cap": cap, "used": used, "left": max(cap - used, 0)}


def send(company_id, subject, body):
    """Send one approved email. Raises RuntimeError on any refusal or failure."""
    to_address = config.get("TO_EMAIL")
    sender = config.get("GMAIL_SENDER_ADDRESS")
    password = config.get("GMAIL_APP_PASSWORD")
    if not to_address:
        raise RuntimeError("TO_EMAIL is not set")
    if not sender or not password:
        raise RuntimeError("GMAIL_SENDER_ADDRESS or GMAIL_APP_PASSWORD is not set")

    state = cap_state()
    if state["left"] <= 0:
        raise RuntimeError(
            f"daily send cap reached ({state['used']}/{state['cap']} today)"
        )

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)

    sent_at = db.record_send(company_id, to_address)
    db.log("sent", f"to={to_address}", company_id)
    return sent_at
