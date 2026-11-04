"""Spike 5: send one test email to TO_EMAIL through the throwaway Gmail account.

This is a real send. It counts against the daily cap, and it goes only to TO_EMAIL.

    python -m spikes.spike5_gmail
"""
from app import config, db, mailer


def main():
    db.init()
    missing = config.missing_keys(
        ["GMAIL_SENDER_ADDRESS", "GMAIL_APP_PASSWORD", "TO_EMAIL"]
    )
    if missing:
        raise SystemExit(f"not set in .env: {', '.join(missing)}")

    state = mailer.cap_state()
    print(f"daily cap: {state['used']} used of {state['cap']}")
    sent_at = mailer.send(
        company_id=0,
        subject="Sprinto pipeline: spike 5 test send",
        body=(
            "This is the spike 5 test send from the Sprinto cold outreach pipeline.\n"
            "If you are reading this, Gmail SMTP and the app password work.\n"
        ),
    )
    print(f"VERDICT: sent at {sent_at} UTC ({mailer.to_ist(sent_at)}) to "
          f"{config.get('TO_EMAIL')}")


if __name__ == "__main__":
    main()
