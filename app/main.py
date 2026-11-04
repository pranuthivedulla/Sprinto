"""FastAPI app: one page. Paste domains, run, review, approve or reject.

Run and Approve are admin actions: the passcode is checked here, on the server.
"""
import json

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import clean, config, db, mailer, pipeline

app = FastAPI(title="Sprinto cold outreach")
templates = Jinja2Templates(directory=str(config.ROOT / "app" / "templates"))

TIER_ORDER = {"High": 0, "Medium": 1, "Low": 2}
REQUIRED_KEYS = ["GEMINI_API_KEY", "HUNTER_API_KEY", "REVIEW_PASSCODE", "TO_EMAIL"]
SEND_KEYS = ["GMAIL_SENDER_ADDRESS", "GMAIL_APP_PASSWORD", "TO_EMAIL"]


@app.on_event("startup")
def _startup():
    db.init()


def _loads(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def passcode_ok(given):
    expected = config.get("REVIEW_PASSCODE")
    return bool(expected) and given == expected


def _row_to_card(row):
    hook = _loads(row["hook_json"], {})
    return {
        "id": row["id"],
        "domain": row["domain"],
        "company_name": row["company_name"] or row["domain"],
        "status": row["status"],
        "tier": row["tier"] or "",
        "flags": _loads(row["flags_json"], []),
        "check_flags": _loads(row["check_flags_json"], []),
        "signals": _loads(row["signals_json"], []),
        "fields": _loads(row["fields_json"], {}),
        "pains": _loads(row["pains_json"], []),
        "hook": hook,
        "audit_verdict": hook.get("audit_verdict", ""),
        "poc_name": row["poc_name"],
        "poc_title": row["poc_title"],
        "poc_email": row["poc_email"],
        "poc_confidence": row["poc_confidence"],
        "poc_reason": row["poc_reason"],
        "subject": row["email_subject"] or "",
        "body": row["email_body"] or "",
        "reject_reason": row["reject_reason"] or "",
        "sent_at": mailer.to_ist(row["sent_at"]),
        "drop_rule": row["drop_rule"] or "",
        "drop_quote": row["drop_quote"] or "",
        "drop_source": row["drop_source"] or "",
    }


def _page_context(request, message="", error=""):
    run_id = db.latest_run_id()
    rows = db.companies_for_run(run_id) if run_id else []
    cards = [_row_to_card(r) for r in rows]
    review = [c for c in cards if c["status"] in ("queued", "approved", "rejected", "sent")]
    review.sort(key=lambda c: (TIER_ORDER.get(c["tier"], 9), c["id"]))
    drops = [c for c in cards if c["status"] in ("dropped", "error")]
    return {
        "request": request,
        "message": message,
        "error": error,
        "job": pipeline.JOB,
        "run_id": run_id,
        "review": review,
        "drops": drops,
        "cap": mailer.cap_state(),
        "missing_keys": config.missing_keys(REQUIRED_KEYS),
        "missing_send_keys": config.missing_keys(SEND_KEYS),
        "sent": [
            {
                "sent_at": mailer.to_ist(r["sent_at"]),
                "to_address": r["to_address"],
                "domain": r["domain"],
                "subject": r["email_subject"],
            }
            for r in db.sent_rows()
        ],
    }


@app.get("/")
def index(request: Request, message: str = "", error: str = ""):
    return templates.TemplateResponse(
        request=request, name="index.html",
        context=_page_context(request, message, error),
    )


@app.get("/job")
def job():
    return JSONResponse(pipeline.JOB)


def _back(message="", error=""):
    from urllib.parse import urlencode

    query = urlencode({k: v for k, v in (("message", message), ("error", error)) if v})
    return RedirectResponse(f"/?{query}" if query else "/", status_code=303)


@app.post("/run")
def run(passcode: str = Form(""), domains: str = Form("")):
    if not passcode_ok(passcode):
        return _back(error="Wrong passcode. Run is an admin action.")
    missing = config.missing_keys(["GEMINI_API_KEY", "HUNTER_API_KEY"])
    if missing:
        return _back(error=f"Not set in .env: {', '.join(missing)}")
    cleaned = clean.clean_list(domains)
    if not cleaned:
        return _back(error="No usable domain in that list.")
    thread, problem = pipeline.start(cleaned)
    if problem:
        return _back(error=problem)
    return _back(message=f"Run started on {len(cleaned)} domains: {', '.join(cleaned)}")


@app.post("/save")
def save(passcode: str = Form(""), company_id: int = Form(...),
         subject: str = Form(""), body: str = Form("")):
    if not passcode_ok(passcode):
        return _back(error="Wrong passcode.")
    db.update_company(company_id, email_subject=subject.strip(), email_body=body.strip(),
                      reviewer_action="edited")
    db.log("edited", "", company_id)
    return _back(message="Edit saved. Nothing has been sent.")


@app.post("/reject")
def reject(passcode: str = Form(""), company_id: int = Form(...), reason: str = Form("")):
    if not passcode_ok(passcode):
        return _back(error="Wrong passcode.")
    if not reason.strip():
        return _back(error="A reject needs a reason: that is what tunes the ICP rules.")
    db.update_company(company_id, status="rejected", reviewer_action="rejected",
                      reject_reason=reason.strip())
    db.log("rejected", reason.strip(), company_id)
    return _back(message="Rejected and logged.")


@app.post("/approve")
def approve(passcode: str = Form(""), company_id: int = Form(...),
            subject: str = Form(""), body: str = Form("")):
    if not passcode_ok(passcode):
        return _back(error="Wrong passcode. Approve is an admin action.")
    row = db.get_company(company_id)
    if row is None:
        return _back(error="No such company.")
    if row["status"] == "sent":
        return _back(error="That email has already been sent.")
    missing = config.missing_keys(SEND_KEYS)
    if missing:
        return _back(error=f"Cannot send, not set in .env: {', '.join(missing)}")

    subject, body = subject.strip(), body.strip()
    db.update_company(company_id, email_subject=subject, email_body=body)
    try:
        sent_at = mailer.send(company_id, subject, body)
    except Exception as exc:
        db.log("send_failed", f"{type(exc).__name__}: {exc}", company_id)
        return _back(error=f"Send failed: {exc}")
    db.update_company(company_id, status="sent", reviewer_action="approved",
                      sent_at=sent_at)
    return _back(message=f"Sent to {config.get('TO_EMAIL')}.")
