"""The seven-step pipeline, for exactly one domain per call.

1 scrape  2 extract  3 qualify (with the agent loop)  4 contact  5 pain points
6 draft   7 send (elsewhere: only a human approval triggers app.mailer)

One call handles one domain so it fits inside a single serverless invocation.
Everything shares one wall-clock budget, and a step we could not complete is
recorded as "failed, retry" - never as a company that was judged and rejected.
"""
import traceback

from . import ai, config, db, gemini, hunter, news, qualify, scrape

RETRY_RULE = "not researched - retry"


def plain_reason(exc):
    """Say what went wrong in words the reviewer can act on."""
    text = str(exc).lower()
    if "timed out" in text or "timeout" in text or "did not answer in time" in text:
        return "took too long to finish"
    if "429" in text or "rate limit" in text or "quota" in text:
        return "the service was busy, try again shortly"
    if "401" in text or "403" in text or "api key" in text:
        return "a key was rejected, check .env"
    if "connection" in text or "resolve" in text or "network" in text:
        return "could not reach the service"
    if "hunter http" in text:
        return str(exc)
    return f"{type(exc).__name__}"


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


def _result(company_id, domain, status, **extra):
    return {"company_id": company_id, "domain": domain, "status": status, **extra}


def _page_notes(pages):
    return {
        k: {"url": p.get("url"), "status": p.get("status"), "note": p.get("note", "")}
        for k, p in pages.items() if p
    }


def process_domain(run_id, domain, budget=None):
    """Run one domain end to end and store the result. Returns a result dict."""
    deadline = scrape.Deadline(budget or config.DOMAIN_TIME_BUDGET)
    gemini.set_deadline(deadline)

    scraped = scrape.scrape_company(domain, deadline=deadline)
    pages = scraped["pages"]
    blob = scrape.pages_blob(pages)
    haystack = scrape.all_text(pages)

    if not blob.strip():
        # We did not get to read this company. That is not a verdict about them.
        notes = _page_notes(pages)
        why = "; ".join(
            f"{k}: {v['note'] or v['status']}" for k, v in notes.items()
        )[:400]
        company_id = db.insert_company(
            run_id, domain, "failed",
            drop_rule=RETRY_RULE,
            drop_quote=f"No page on this domain could be read. {why}",
            drop_source=f"https://{domain}/",
            fields_json={"_pages": notes},
            flags_json=["site could not be read - nothing was judged"],
        )
        db.log("failed", f"{domain}: nothing readable", company_id, run_id)
        return _result(company_id, domain, "failed", reason="could not read the site")

    fields = ai.verify_fields(ai.extract_fields(blob), haystack)
    vertical = ai.classify_vertical(blob)
    vertical["verified"] = ai.quote_is_real(vertical.get("quote"), haystack)

    # --- step 3 agent loop: fetch at most two more pages when things are thin ---
    loop_notes = []
    gaps = unknown_fields(fields, vertical)
    if gaps and scraped["unfetched"] and deadline.room_for_a_fetch():
        read_urls = [p["url"] for p in pages.values() if p and p.get("url")]
        decision = ai.needs_more_info(
            gaps, read_urls, scraped["unfetched"], config.MAX_LOOP_FETCHES
        )
        if decision["need_more"]:
            for url in decision["urls"]:
                if not deadline.room_for_a_fetch():
                    loop_notes.append(f"{url} (skipped - out of time)")
                    continue
                extra = scrape.fetch(url, deadline)
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
    fields["_pages"] = _page_notes(pages)
    fields["_loop"] = loop_notes

    # --- hard filters 1-4, before any Hunter credit is spent -------------------
    drop = qualify.site_filters(fields, vertical)
    fields["vertical"] = vertical
    if drop:
        rule, quote, source = drop
        company_id = db.insert_company(
            run_id, domain, "dropped",
            company_name=company_name,
            drop_rule=rule, drop_quote=quote, drop_source=source,
            fields_json=fields,
        )
        db.log("dropped", f"{domain}: {rule}", company_id, run_id)
        return _result(company_id, domain, "dropped", rule=rule,
                       company_name=company_name)

    # --- news (one query per company) -----------------------------------------
    headlines, news_source = news.fetch(company_name, domain)
    classifications = ai.classify_headlines(company_name, domain, headlines) if headlines else []
    news_sig = qualify.news_signals(company_name, domain, headlines, classifications)
    signals = qualify.build_signals(fields, vertical, news_sig)

    # --- contact (filter 5) ----------------------------------------------------
    try:
        data, hunter_source = hunter.search(domain)
    except RuntimeError as exc:
        # Hunter was unreachable. We never asked the question, so we cannot answer it.
        company_id = db.insert_company(
            run_id, domain, "failed",
            company_name=company_name,
            drop_rule=RETRY_RULE,
            drop_quote=f"Contact lookup did not complete: {exc}",
            drop_source="hunter.io domain-search",
            fields_json=fields, signals_json=signals,
            flags_json=["contact lookup failed - no contact was searched for"],
        )
        db.log("failed", f"{domain}: hunter {exc}", company_id, run_id)
        return _result(company_id, domain, "failed",
                       reason="contact lookup " + plain_reason(exc),
                       company_name=company_name)

    person, poc_reason = hunter.choose(data)
    if not person:
        company_id = db.insert_company(
            run_id, domain, "dropped",
            company_name=company_name,
            drop_rule=qualify.HARD_FILTERS[4],
            drop_quote=poc_reason,
            drop_source="hunter.io domain-search",
            fields_json=fields, signals_json=signals,
        )
        db.log("dropped", f"{domain}: no contact", company_id, run_id)
        return _result(company_id, domain, "dropped",
                       rule=qualify.HARD_FILTERS[4], company_name=company_name)

    tier, score = qualify.tier_for(signals)
    flags = qualify.build_flags(fields, vertical, signals, hunter_source)
    if news_source == "failed":
        flags.append("news search failed - treated as unknown, not as 'no news'")
    if any(p.get("status") in ("timed_out", "skipped")
           for p in pages.values() if isinstance(p, dict)):
        flags.append("some pages were not read in time - those rows stay unknown")
    verdict = qualify.audit_verdict(fields, signals)
    hook = qualify.choose_hook(fields, signals)

    # --- pain points and draft -------------------------------------------------
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
    return _result(company_id, domain, "queued", tier=tier, company_name=company_name,
                   flags=len(flags) + len(check_flags))


def process_domain_safely(run_id, domain, budget=None):
    """process_domain, but an unexpected error is stored as retryable, not as a verdict."""
    try:
        return process_domain(run_id, domain, budget)
    except Exception as exc:
        company_id = db.insert_company(
            run_id, domain, "failed",
            drop_rule=RETRY_RULE,
            drop_quote=f"{type(exc).__name__}: {exc}",
            flags_json=["run did not complete - nothing was judged"],
        )
        db.log("failed", traceback.format_exc()[-1500:], company_id, run_id)
        return _result(company_id, domain, "failed", reason=plain_reason(exc))
