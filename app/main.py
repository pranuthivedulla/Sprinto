"""FastAPI app: one page. Paste domains, run, review, approve or reject.

Run and Approve are admin actions: the passcode is checked here, on the server.
"""
import json

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, clean, config, db, mailer, pipeline, replies, sequence2

app = FastAPI(title="Sprinto cold outreach")
templates = Jinja2Templates(directory=str(config.ROOT / "app" / "templates"))

TIER_ORDER = {"High": 0, "Medium": 1, "Low": 2}
REQUIRED_KEYS = ["GEMINI_API_KEY", "HUNTER_API_KEY", "TO_EMAIL"]
SEND_KEYS = ["GMAIL_SENDER_ADDRESS", "GMAIL_APP_PASSWORD", "TO_EMAIL"]


MISCONFIGURED_IN_PRODUCTION = ("SESSION_SECRET",)


def misconfigured():
    """A gate that exists must be able to sign its own cookie.

    REVIEW_PASSCODE is optional: without it there is no gate and the page is
    open to anyone with the link, which it says so itself. With it, production
    also needs SESSION_SECRET, or the session a reviewer is handed is signed
    with a key that dies on the next cold start.
    """
    if not config.is_production() or not auth.gate_on():
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


@app.exception_handler(RequestValidationError)
async def _unusable_input(request, exc):
    """A missing or unparseable field is a bad request, answered in one line.

    FastAPI's own answer is a 422 carrying a list of validation objects. That is
    accurate and unreadable, and anything calling this app from the outside -
    a script, or someone with curl - deserves to be told which field it is.
    """
    fields = sorted({str(e["loc"][-1]) for e in exc.errors()}) or ["body"]
    return JSONResponse(
        {"error": "Missing or unusable: " + ", ".join(fields) + "."},
        status_code=400,
    )


async def _inputs(request):
    """Every way a caller might send a value, flattened into one dict.

    The page posts a form. Anything scripted is at least as likely to post
    JSON, and a caller that guesses wrong should not be told its domain was
    empty. Query string, JSON body and form body all land in the same place.
    """
    data = dict(request.query_params)
    raw = await request.body()
    if raw:
        content_type = request.headers.get("content-type", "")
        if "json" in content_type or raw.lstrip()[:1] in (b"{", b"["):
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                data.update(parsed)
        else:
            try:
                data.update(dict(await request.form()))
            except Exception:
                pass
    return data


def _field(data, *names):
    """The first of these keys that carries anything, as a string."""
    for name in names:
        value = data.get(name)
        if value not in (None, "", []):
            return str(value).strip()
    return ""


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
        "meeting_status": row["meeting_status"] or "",
        "meeting_time": row["meeting_time"] or "",
        "reply_status": row["reply_status"] or "",
        "reply_quote": row["reply_quote"] or "",
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
    cards = [_row_to_card(r) for r in db.all_companies()]

    def of(*statuses):
        return [c for c in cards if c["status"] in statuses]

    # One row per company. Researching a domain again supersedes the earlier
    # draft; showing both makes four companies look like seven decisions.
    review, seen = [], set()
    for card in of("queued"):          # already newest first
        if card["domain"] in seen:
            continue
        seen.add(card["domain"])
        review.append(card)
    superseded = len(of("queued")) - len(review)
    review.sort(key=lambda c: (TIER_ORDER.get(c["tier"], 9), -c["id"]))
    scheduling = [c for c in cards if c["meeting_status"]]
    scheduling.sort(key=lambda c: (c["meeting_status"] != "booked", -c["id"]))

    return {
        "request": request,
        "message": message,
        "error": error,
        "demo_domains": demo_domains(),
        "gate_on": auth.gate_on(),
        "to_schedule": [
            {"id": r["id"], "name": r["company_name"] or r["domain"],
             "quote": r["reply_quote"] or ""}
            for r in db.interested_not_scheduling()
        ],
        "review": review,
        "superseded": superseded,
        "decided": of("approved", "rejected", "sent"),
        "scheduling": scheduling,
        "drops": of("dropped"),
        "unresearched": of("failed", "error"),
        "funnel": {
            "researched": len(cards),
            "not_a_fit": len(of("dropped")),
            "unresearched": len(of("failed", "error")),
            "drafted": len([c for c in cards if c["subject"]]),
            "sent": len(of("sent")),
            "replied": len([c for c in cards if c["reply_status"]
                            in ("interested", "not_interested")]),
            "booked": len([c for c in cards if c["meeting_status"] == "booked"]),
        },
        "cap": mailer.cap_state(),
        "max_domains": config.MAX_DOMAINS_PER_RUN,
        "missing_keys": config.missing_keys(REQUIRED_KEYS),
        "missing_send_keys": config.missing_keys(SEND_KEYS),
        "sent": [
            {
                "sent_at": mailer.to_ist(r["sent_at"]),
                "domain": r["domain"],
                "subject": r["subject"] or r["email_subject"],
                "to_address": r["to_address"],
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


@app.get("/robots.txt")
def robots():
    """Belt and braces with the X-Robots-Tag header: with no gate in front of
    the page, a crawler finding the link is the way it would get indexed."""
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.post("/login")
def login(request: Request, passcode: str = Form("")):
    if not auth.gate_on():
        return RedirectResponse("/", status_code=303)
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
async def run_domain(request: Request):
    """Research exactly one domain and return its result.

    One domain per request, so the work fits inside a single serverless invocation.
    The page calls this once per chip, in order. A form, a JSON body and a query
    string are all read the same way, and the domain may arrive under any of the
    obvious names, because a caller that spells it differently should get the
    research rather than a complaint.
    """
    data = await _inputs(request)
    passcode = _field(data, "passcode")
    domain = _field(data, "domain", "company", "company_domain", "url", "website")
    run_id = _field(data, "run_id", "runId")

    if not auth.authorized(request, passcode):
        return JSONResponse({"error": "Wrong passcode."}, status_code=403)
    missing = config.missing_keys(["GEMINI_API_KEY", "HUNTER_API_KEY"])
    if missing:
        return JSONResponse(
            {"error": f"Not set in .env: {', '.join(missing)}"}, status_code=400
        )
    if not domain:
        return JSONResponse(
            {"error": 'No domain in the request. Send {"domain": "acme.com"} as '
                      "JSON or as a form field."},
            status_code=400,
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


def _advance_scheduling():
    """Resume any paused scheduling graph whose reply has arrived."""
    waiting = db.scheduling_awaiting_reply()
    if not waiting:
        return []
    inbox = replies.fetch_inbox()
    notes = []
    for row in waiting:
        message = next((m for m in inbox if replies.matches(row, m)), None)
        state = sequence2.resume(row["id"], (message or {}).get("body", ""))
        notes.append(f"{row['company_name'] or row['domain']}: {state.get('note', '')}")
    return notes


@app.post("/check-replies")
def check_replies(request: Request, passcode: str = Form("")):
    """Sequence 1: look at what came back and set reply_status. Nothing else.

    No calendar, no scheduling. An interested reply stops here and says so.
    """
    if not auth.authorized(request, passcode):
        return _back(error="Wrong passcode.")
    try:
        results = replies.check()
        scheduled = _advance_scheduling()
    except Exception as exc:
        return _back(error=f"Could not read the inbox: {exc}")
    if scheduled:
        return _back(message="Scheduling: " + "; ".join(scheduled))
    if not results:
        return _back(message="No sent emails are waiting on a reply.")
    keen = replies.interested(results)
    if keen:
        names = ", ".join(r.get("company_name") or r["domain"] for r in keen)
        return _back(message=f"Interested: {names}. Sequence 1 stops here - "
                             "scheduling is the next part, and is not built.")
    counts = {}
    for r in results:
        counts[r["reply_status"]] = counts.get(r["reply_status"], 0) + 1
    summary = ", ".join(f"{n} {s.replace('_', ' ')}" for s, n in sorted(counts.items()))
    return _back(message=f"Checked {len(results)}: {summary}.")


@app.post("/start-scheduling")
def start_scheduling(request: Request, company_id: int = Form(...), passcode: str = Form("")):
    """Sequence 2: run check_calendar and propose_time, then pause for a reply."""
    if not auth.authorized(request, passcode):
        return _back(error="Wrong passcode.")
    row = db.get_company(company_id)
    if row is None or row["reply_status"] != "interested":
        return _back(error="Scheduling only starts from an interested reply.")
    if row["thread_id"]:
        return _back(error="Scheduling is already running for that company.")
    try:
        state = sequence2.start(company_id)
    except Exception as exc:
        return _back(error=f"Scheduling could not start: {exc}")
    return _back(message=f"{row['company_name'] or row['domain']}: {state.get('note', 'started')}.")


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
