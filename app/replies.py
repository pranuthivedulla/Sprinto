"""Sequence 1: read replies to the emails this app sent, and classify them.

One tool was sent out (the email). This reads what came back and sets one field,
reply_status, to no_reply, interested or not_interested. There is no calendar and
no scheduling here on purpose: when a reply is interested, the run stops and says so.

Replies arrive at the sending account, not the reviewer's inbox, and are matched to
a company by the Message-ID the send recorded. Subject matching is a fallback only.
"""
import email
import imaplib
import re
from email.header import decode_header, make_header

from . import ai, config, db

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
TIMEOUT = 30
LOOKBACK = 200  # most recent messages to consider

NO_REPLY = "no_reply"
INTERESTED = "interested"
NOT_INTERESTED = "not_interested"
VALID = (NO_REPLY, INTERESTED, NOT_INTERESTED)


def _header(message, name):
    raw = message.get(name, "")
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def plain_body(message):
    """The text of a reply, with the quoted original removed.

    Without stripping the quote the classifier reads our own pitch back and calls
    every reply interested.
    """
    text = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    text = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace"
                    )
                except Exception:
                    continue
                break
    else:
        try:
            text = message.get_payload(decode=True).decode(
                message.get_content_charset() or "utf-8", "replace"
            )
        except Exception:
            text = str(message.get_payload())

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if re.match(r"^On .+ wrote:$", stripped):
            break
        if stripped.startswith("[Demo redirect]"):
            continue
        if re.match(r"^-{2,}\s*Original Message", stripped, re.I):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def fetch_inbox():
    """Return the recent messages in the sending account's inbox."""
    address = config.get("GMAIL_SENDER_ADDRESS")
    password = config.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise RuntimeError("GMAIL_SENDER_ADDRESS or GMAIL_APP_PASSWORD is not set")

    out = []
    box = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=TIMEOUT)
    try:
        box.login(address, password)
        box.select("INBOX", readonly=True)
        typ, data = box.search(None, "ALL")
        ids = (data[0].split() if data and data[0] else [])[-LOOKBACK:]
        for num in reversed(ids):
            typ, raw = box.fetch(num, "(RFC822)")
            if not raw or not raw[0]:
                continue
            message = email.message_from_bytes(raw[0][1])
            out.append(
                {
                    "from": _header(message, "From"),
                    "subject": _header(message, "Subject"),
                    "date": _header(message, "Date"),
                    "in_reply_to": message.get("In-Reply-To", ""),
                    "references": message.get("References", ""),
                    "body": plain_body(message),
                }
            )
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return out


def matches(company, message):
    """True when this message is a reply to the email we sent that company."""
    sent_id = (company["sent_message_id"] or "").strip()
    if sent_id:
        blob = f"{message.get('in_reply_to', '')} {message.get('references', '')}"
        if sent_id in blob:
            return True
    # Exact subject, not substring: "...for HealthPlix" is contained in
    # "...for HealthPlix EMR", so a substring test matches a reply to a different
    # company and flips both.
    subject = normalise_subject(company["email_subject"])
    return bool(subject) and subject == normalise_subject(message.get("subject"))


def normalise_subject(subject):
    """Lowercased, with any number of Re:/Fwd: prefixes and extra spaces removed."""
    text = (subject or "").strip().lower()
    while True:
        stripped = re.sub(r"^(re|fw|fwd)\s*:\s*", "", text)
        if stripped == text:
            break
        text = stripped
    return re.sub(r"\s+", " ", text).strip()


def check(company_ids=None):
    """Look for replies to sent emails and set reply_status. Returns a summary list."""
    rows = [r for r in db.sent_awaiting_reply() if not company_ids or r["id"] in company_ids]
    if not rows:
        return []
    inbox = fetch_inbox()
    results = []
    for row in rows:
        reply = next((m for m in inbox if matches(row, m)), None)
        now = db.utcnow()
        if reply is None or not reply["body"]:
            db.update_company(row["id"], reply_checked_at=now)
            results.append({"company_id": row["id"], "domain": row["domain"],
                            "reply_status": NO_REPLY, "quote": ""})
            continue
        verdict = ai.classify_reply(reply["body"])
        status = verdict.get("status", NO_REPLY)
        if status not in VALID:
            status = NO_REPLY
        db.update_company(row["id"], reply_status=status, reply_quote=verdict.get("quote", ""),
                          reply_checked_at=now)
        db.log("reply", f"{row['domain']}: {status}", row["id"])
        results.append({"company_id": row["id"], "domain": row["domain"],
                        "company_name": row["company_name"], "reply_status": status,
                        "quote": verdict.get("quote", "")})
    return results


def interested(results):
    """Sequence 1 stops here: these are the ones to tell the Growth Lead about."""
    return [r for r in results if r["reply_status"] == INTERESTED]
