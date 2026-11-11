"""FastAPI app: one page. Paste domains, run, review, approve or reject.

Run and Approve are admin actions: the passcode is checked here, on the server.
"""
import json

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, clean, config, db, mailer, pipeline

app = FastAPI(title="Sprinto cold outreach")
templates = Jinja2Templates(directory=str(config.ROOT / "app" / "templates"))

TIER_ORDER = {"High": 0, "Medium": 1, "Low": 2}
REQUIRED_KEYS = ["GEMINI_API_KEY", "HUNTER_API_KEY", "REVIEW_PASSCODE", "TO_EMAIL"]
SEND_KEYS = ["GMAIL_SENDER_ADDRESS", "GMAIL_APP_PASSWORD", "TO_EMAIL"]


MISCONFIGURED_IN_PRODUCTION = ("REVIEW_PASSCODE", "SESSION_SECRET")


def misconfigured():
    """In production these two must be set, or the review page is open to anyone."""
    if not config.is_production():
        return []
    return [n for n in MISCONFIGURED_IN_PRODUCTION if not config.get(n)]


@app.middleware("http")
async def _guard(request: Request, call_next):
    missing = misconfigured()
    if missing:
        # Refuse to serve, and say why. A crash at import would be an opaque 500
        # with the reason buried in a log nobody is looking at.
        response = PlainTextResponse(
            "This deployment is not configured. Set "
            + " and ".join(missing)
            + " in the project's environment variables, then redeploy.",
            status_code=503,
        )
    else:
        try:
            db.ensure_schema()
        except Exception as exc:
            response = PlainTextResponse(
                f"The database is not reachable: {type(exc).__name__}. "
                "Check DATABASE_URL in the project's environment variables.",
                status_code=503,
            )
        else:
            response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _loads(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def demo_domains():
    """Starter lists from demo_domains.txt, grouped by the '# Heading' lines above them.

    The file is the user's: these are suggestions to click, not a hard-coded list.
    """
    path = config.ROOT / config.DEMO_DOMAINS_FILE
    if not path.exists():
        return {}
    groups, heading, seen = {}, "Demo list", set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            label = line.lstrip("#").strip()
            # A one-or-two word heading names a group; longer lines are just notes.
            if label and len(label.split()) <= 3:
                heading = label
            continue
        domain = clean.clean_domain(line)
        if domain and domain not in seen:
            seen.add(domain)
            groups.setdefault(heading, []).append(domain)
    return {k: v[: config.MAX_DOMAINS_PER_RUN] for k, v in groups.items() if v}


passcode_ok = auth.passcode_ok


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
    drops = [c for c in cards if c["status"] in ("dropped", "failed", "error")]
    return {
        "request": request,
        "message": message,
        "error": error,
        "demo_domains": demo_domains(),
        "run_id": run_id,
        "review": review,
        "drops": drops,
        "cap": mailer.cap_state(),
        "max_domains": config.MAX_DOMAINS_PER_RUN,
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


@app.get("/login")
def login_form(request: Request, error: str = ""):
    if auth.authorized(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": error},
        status_code=200,
    )


@app.post("/login")
def login(request: Request, passcode: str = Form("")):
    ip = auth.client_ip(request)
    if auth.throttled(ip):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Too many wrong tries. Wait ten minutes."},
            status_code=429,
        )
    if not auth.passcode_ok(passcode):
        auth.record_failure(ip)
        db.log("login_failed", f"ip={ip}")
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "That passcode is not right."},
            status_code=401,
        )
    auth.clear_failures(ip)
    return auth.set_cookie(RedirectResponse("/", status_code=303))


@app.get("/")
def index(request: Request, message: str = "", error: str = ""):
    if not auth.authorized(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request=request, name="index.html",
        context=_page_context(request, message, error),
    )


def _back(message="", error=""):
    from urllib.parse import urlencode

    query = urlencode({k: v for k, v in (("message", message), ("error", error)) if v})
    return RedirectResponse(f"/?{query}" if query else "/", status_code=303)


@app.post("/run-domain")
def run_domain(request: Request, passcode: str = Form(""),
               domain: str = Form(""), run_id: str = Form("")):
    """Research exactly one domain and return its result.

    One domain per request, so the work fits inside a single serverless invocation.
    The page calls this once per chip, in order.
    """
    if not auth.authorized(request, passcode):
        return JSONResponse({"error": "Wrong passcode."}, status_code=403)
    missing = config.missing_keys(["GEMINI_API_KEY", "HUNTER_API_KEY"])
    if missing:
        return JSONResponse(
            {"error": f"Not set in .env: {', '.join(missing)}"}, status_code=400
        )
    cleaned = clean.clean_domain(domain)
    if not cleaned:
        return JSONResponse({"error": f"{domain!r} is not a usable domain."},
                            status_code=400)

    rid = int(run_id) if run_id.strip().isdigit() and db.run_exists(int(run_id)) else None
    if rid is None:
        rid = db.create_run(0)
    done = db.count_companies(rid)
    if done >= config.MAX_DOMAINS_PER_RUN:
        return JSONResponse(
            {"error": f"One run takes at most {config.MAX_DOMAINS_PER_RUN} domains.",
             "run_id": rid},
            status_code=400,
        )

    result = pipeline.process_domain_safely(rid, cleaned)
    db.set_run_count(rid, done + 1)
    return JSONResponse({"run_id": rid, **result})


@app.post("/save")
def save(request: Request, passcode: str = Form(""), company_id: int = Form(...),
         subject: str = Form(""), body: str = Form("")):
    if not auth.authorized(request, passcode):
        return _back(error="Wrong passcode.")
    stored = db.get_company(company_id)
    # An empty field means "not supplied", never "replace the draft with nothing".
    db.update_company(
        company_id,
        email_subject=subject.strip() or (stored["email_subject"] if stored else ""),
        email_body=body.strip() or (stored["email_body"] if stored else ""),
        reviewer_action="edited",
    )
    db.log("edited", "", company_id)
    return _back(message="Edit saved. Nothing has been sent.")


@app.post("/reject")
def reject(request: Request, passcode: str = Form(""),
           company_id: int = Form(...), reason: str = Form("")):
    if not auth.authorized(request, passcode):
        return _back(error="Wrong passcode.")
    if not reason.strip():
        return _back(error="A reject needs a reason: that is what tunes the ICP rules.")
    db.update_company(company_id, status="rejected", reviewer_action="rejected",
                      reject_reason=reason.strip())
    db.log("rejected", reason.strip(), company_id)
    return _back(message="Rejected and logged.")


@app.post("/approve")
def approve(request: Request, passcode: str = Form(""), company_id: int = Form(...),
            subject: str = Form(""), body: str = Form("")):
    if not auth.authorized(request, passcode):
        return _back(error="Wrong passcode. Approve is an admin action.")
    row = db.get_company(company_id)
    if row is None:
        return _back(error="No such company.")
    if row["status"] == "sent":
        return _back(error="That email has already been sent.")
    missing = config.missing_keys(SEND_KEYS)
    if missing:
        return _back(error=f"Cannot send, not set in .env: {', '.join(missing)}")

    subject = subject.strip() or (row["email_subject"] or "")
    body = body.strip() or (row["email_body"] or "")
    db.update_company(company_id, email_subject=subject, email_body=body)
    try:
        sent_at = mailer.send(company_id, subject, body)
    except Exception as exc:
        db.log("send_failed", f"{type(exc).__name__}: {exc}", company_id)
        return _back(error=f"Send failed: {exc}")
    db.update_company(company_id, status="sent", reviewer_action="approved",
                      sent_at=sent_at)
    return _back(message=f"Sent to {config.get('TO_EMAIL')}.")
