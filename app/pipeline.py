"""The seven-step pipeline, one domain at a time.

1 scrape  2 extract  3 qualify (with the agent loop)  4 contact  5 pain points
6 draft   7 send (elsewhere: only a human approval triggers app.mailer)
"""
import threading
import traceback

from . import ai, config, db, hunter, news, qualify, scrape

# Job state for the single background run the UI polls.
JOB = {
    "state": "idle",      # idle | running | done | error
    "run_id": None,
    "total": 0,
    "done": 0,
    "current": "",
    "message": "",
    "log": [],
}
_LOCK = threading.Lock()


def _say(message):
    with _LOCK:
        JOB["message"] = message
        JOB["log"] = (JOB["log"] + [message])[-60:]


def unknown_fields(fields, vertical):
    out = []
    for key in ("employee_count", "funding_stage", "compliance_hiring",
                "enterprise_pressure"):
        if qualify.value_of(fields, key).lower() in ("", "unknown"):
            out.append(key.replace("_", " "))
    if not (fields.get("certifications") or []):
        out.append("certifications shown on a trust page")
    if vertical.get("value") in ("", "unknown") or not vertical.get("certain"):
        out.append("vertical")
    return out


def process_domain(run_id, domain):
    """Run one domain end to end and store the result. Returns the company row id."""
    _say(f"{domain}: scraping")
    scraped = scrape.scrape_company(domain)
    pages = scraped["pages"]
    blob = scrape.pages_blob(pages)
    haystack = scrape.all_text(pages)
    readable = [k for k, p in pages.items() if p and p.get("status") == "ok"]

    if not blob.strip():
        return db.insert_company(
            run_id,
            domain,
            "dropped",
            drop_rule=qualify.HARD_FILTERS[0],
            drop_quote="Absence, not a claim: no page on this domain was readable "
                       "(likely JavaScript-rendered or blocked).",
            drop_source=f"https://{domain}/",
            fields_json={},
            flags_json=["site not readable"],
        )

    _say(f"{domain}: extracting fields ({len(readable)} readable pages)")
    fields = ai.verify_fields(ai.extract_fields(blob), haystack)
    vertical = ai.classify_vertical(blob)
    vertical["verified"] = ai.quote_is_real(vertical.get("quote"), haystack)

    # --- step 3 agent loop: fetch at most two more pages when things are thin ---
    loop_notes = []
    budget = config.MAX_LOOP_FETCHES
    gaps = unknown_fields(fields, vertical)
    if gaps and scraped["unfetched"] and budget > 0:
        read_urls = [p["url"] for p in pages.values() if p and p.get("url")]
        decision = ai.needs_more_info(gaps, read_urls, scraped["unfetched"], budget)
        if decision["need_more"]:
            for url in decision["urls"]:
                _say(f"{domain}: loop fetch {url}")
                extra = scrape.fetch(url)
                if extra["status"] == "ok":
                    pages[f"extra:{url}"] = extra
                loop_notes.append(f"{url} ({extra['status']})")
            blob = scrape.pages_blob(pages)
            haystack = scrape.all_text(pages)
            fields = ai.verify_fields(ai.extract_fields(blob), haystack)
            vertical = ai.classify_vertical(blob)
            vertical["verified"] = ai.quote_is_real(vertical.get("quote"), haystack)
            loop_notes.insert(0, decision.get("why", ""))

    company_name = qualify.value_of(fields, "company_name") or domain.split(".")[0]
    fields["_pages"] = {
        k: {"url": p.get("url"), "status": p.get("status"), "note": p.get("note", "")}
        for k, p in pages.items() if p
    }
    fields["_loop"] = loop_notes

    # --- hard filters 1-4, before any Hunter credit is spent -------------------
    drop = qualify.site_filters(fields, vertical)
    fields["vertical"] = vertical
    if drop:
        rule, quote, source = drop
        _say(f"{domain}: dropped - {rule}")
        return db.insert_company(
            run_id, domain, "dropped",
            company_name=company_name,
            drop_rule=rule, drop_quote=quote, drop_source=source,
            fields_json=fields,
        )

    # --- news (one query per company) -----------------------------------------
    _say(f"{domain}: news search")
    headlines, news_source = news.fetch(company_name, domain)
    classifications = ai.classify_headlines(company_name, domain, headlines) if headlines else []
    news_sig = qualify.news_signals(company_name, domain, headlines, classifications)
    signals = qualify.build_signals(fields, vertical, news_sig)

    # --- contact (filter 5) ----------------------------------------------------
    _say(f"{domain}: contact lookup")
    try:
        data, hunter_source = hunter.search(domain)
    except RuntimeError as exc:
        data, hunter_source = {}, f"failed ({exc})"
    person, poc_reason = hunter.choose(data)
    if not person:
        return db.insert_company(
            run_id, domain, "dropped",
            company_name=company_name,
            drop_rule=qualify.HARD_FILTERS[4],
            drop_quote=poc_reason,
            drop_source="hunter.io domain-search",
            fields_json=fields, signals_json=signals,
        )

    tier, score = qualify.tier_for(signals)
    flags = qualify.build_flags(fields, vertical, signals, hunter_source)
    if news_source == "failed":
        flags.append("news search failed - treated as unknown, not as 'no news'")
    verdict = qualify.audit_verdict(fields, signals)
    hook = qualify.choose_hook(fields, signals)

    # --- pain points and draft -------------------------------------------------
    _say(f"{domain}: pain points and draft")
    signal_lines = [
        f"{s['label']}: \"{s['quote']}\"" for s in signals if not s.get("never_in_email")
    ]
    pains = ai.pain_points(
        person, company_name, qualify.value_of(fields, "what_it_does"), signal_lines
    )
    subject, body = ai.draft_email(person, company_name, hook["text"], pains)
    check_flags = qualify.check_email(subject, body, person, signals, hook)

    company_id = db.insert_company(
        run_id, domain, "queued",
        company_name=company_name,
        fields_json=fields,
        signals_json=signals,
        tier=tier,
        flags_json=flags,
        poc_name=person["name"],
        poc_title=person["title"],
        poc_email=person["email"],
        poc_confidence=person.get("confidence"),
        poc_reason=poc_reason,
        pains_json=pains,
        hook_json={**hook, "audit_verdict": verdict, "score": score,
                   "hunter_source": hunter_source, "news_source": news_source},
        email_subject=subject,
        email_body=body,
        check_flags_json=check_flags,
    )
    db.log("queued", f"{domain} tier={tier} score={score}", company_id, run_id)
    return company_id


def run_domains(domains):
    """Blocking run over a cleaned domain list. Called on the background thread."""
    run_id = db.create_run(len(domains))
    with _LOCK:
        JOB.update(state="running", run_id=run_id, total=len(domains), done=0,
                   current="", message="starting", log=[])
    for domain in domains:
        with _LOCK:
            JOB["current"] = domain
        try:
            process_domain(run_id, domain)
        except Exception as exc:  # one bad domain must not end the run
            db.insert_company(
                run_id, domain, "error",
                drop_rule="pipeline error", drop_quote=f"{type(exc).__name__}: {exc}",
            )
            db.log("error", traceback.format_exc()[-1500:], None, run_id)
            _say(f"{domain}: error - {type(exc).__name__}: {exc}")
        with _LOCK:
            JOB["done"] += 1
    with _LOCK:
        JOB.update(state="done", current="", message="run finished")
    return run_id


def start(domains):
    """Start the run on a background thread so the page stays responsive."""
    with _LOCK:
        if JOB["state"] == "running":
            return None, "a run is already in progress"
    thread = threading.Thread(target=run_domains, args=(domains,), daemon=True)
    thread.start()
    return thread, ""
