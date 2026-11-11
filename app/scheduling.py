"""Calendar slots and scheduling replies, for Sequence 2.

Slots come from stated availability rather than a real calendar: working days and
hours in config, minus anything this app has already booked. No OAuth, and the
meeting that comes out is real inside this app.

Every message Sequence 2 sends, including the calendar invite, is delivered to
TO_EMAIL. The invite is the one artefact that could otherwise reach the contact,
so it is redirected as firmly as the email is.
"""
from datetime import datetime, timedelta

from . import ai, config, db, gemini, mailer


def booked_times():
    with db.connect() as conn:
        rows = conn.execute(
            db._q("SELECT meeting_time FROM companies WHERE meeting_time IS NOT NULL")
        ).fetchall()
    return {r["meeting_time"] for r in rows}


def free_slots(count=None, start=None):
    """The next few free working slots, in India time, as 'YYYY-MM-DD HH:MM' strings."""
    count = count or config.SLOTS_TO_PROPOSE
    now = (start or mailer.ist_now()) + timedelta(hours=24)
    taken = booked_times()
    first, last = config.WORKING_HOURS
    cursor = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    out = []
    guard = 0
    while len(out) < count and guard < 500:
        guard += 1
        if cursor.weekday() in config.WORKING_DAYS and first <= cursor.hour < last:
            label = cursor.strftime("%Y-%m-%d %H:%M")
            if label not in taken:
                out.append(label)
        cursor += timedelta(minutes=config.SLOT_MINUTES)
    return out


def human(slot):
    """'2026-11-13 10:30' as 'Thu 13 Nov, 10:30 IST'."""
    try:
        return datetime.strptime(slot, "%Y-%m-%d %H:%M").strftime("%a %d %b, %H:%M IST")
    except ValueError:
        return slot


# --- what the prospect said about the times ---------------------------------

SCHEDULING_PROMPT = """You proposed these meeting times to someone and they replied.
Decide what their reply means about the times.

Times proposed:
{slots}

Their reply:
---
{body}
---

{rules}

confirmed      they accept one of the proposed times. Say which, copied exactly
               from the list above.
counter        they want to meet but at a different time, or ask for other options
neither        they say nothing about scheduling either way

Return: {{"outcome": "confirmed|counter|neither",
          "slot": "the exact proposed time they accepted, or empty",
          "quote": "the sentence you based that on, copied exactly"}}"""


def read_scheduling_reply(body, slots):
    data = gemini.call_json(
        SCHEDULING_PROMPT.format(
            slots="\n".join(f"- {s} ({human(s)})" for s in slots),
            body=body[:4000],
            rules=ai.EVIDENCE_RULES,
        )
    )
    outcome = str(data.get("outcome", "")).strip().lower()
    if outcome not in ("confirmed", "counter", "neither"):
        outcome = "neither"
    slot = str(data.get("slot", "")).strip()
    # Code decides, not the model: an accepted slot has to be one we actually offered.
    if slot not in slots:
        slot = ""
    if outcome == "confirmed" and not slot:
        outcome = "counter"
    return {"outcome": outcome, "slot": slot, "quote": str(data.get("quote", "")).strip()}


# --- the two things Sequence 2 sends ----------------------------------------

def send_times(company, slots):
    """propose_time's outbound message. Returns the Message-ID that a reply carries."""
    lines = [f"Hi {(company['poc_name'] or '').split(' ')[0] or 'there'},", ""]
    lines.append("Thanks for coming back to me. Would any of these suit for a short call?")
    lines.append("")
    lines += [f"  - {human(s)}" for s in slots]
    lines += ["", "Happy to work around you if none of those fit.", "", "Best,"]
    subject = f"Times for a call - {company['company_name'] or company['domain']}"
    return mailer.send(company["id"], subject, "\n".join(lines))


def send_invite(company, slot):
    """book_meeting's invite. Delivered to TO_EMAIL, never to the contact."""
    who = f"{company['poc_name']} <{company['poc_email']}>" if company["poc_email"] else "the contact"
    body = "\n".join([
        f"Meeting confirmed for {human(slot)}.",
        "",
        f"This invite is for a call with {who} at "
        f"{company['company_name'] or company['domain']}.",
        "It was delivered to you, not to them.",
    ])
    subject = f"Meeting booked - {company['company_name'] or company['domain']}"
    return mailer.send(company["id"], subject, body)
