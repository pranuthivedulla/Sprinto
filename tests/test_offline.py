"""Offline checks. No network, no API key, no credit spent.

Every external call (scrape, Gemini, Hunter, Google News, SMTP) is stubbed, so this
exercises the parts that must be right before a live run: cleaning, the hard filters,
ranking, contact choice, the hook rules and the email code check.

    python -m tests.test_offline
"""
import os
import sys
import tempfile
from pathlib import Path

from app import config

# Point the database at a throwaway file before anything opens it.
config.DATA_DIR = Path(tempfile.mkdtemp(prefix="sprinto-test-"))
config.DB_PATH = config.DATA_DIR / "test.db"

from app import ai, clean, db, hunter, mailer, news, pipeline, qualify, scrape  # noqa: E402

PASS, FAIL = 0, 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


# --- input cleaning ---------------------------------------------------------
print("input cleaning")
check("strips scheme, www and path",
      clean.clean_domain("https://www.Example.com/pricing?x=1") == "example.com")
check("strips a port", clean.clean_domain("example.com:8443") == "example.com")
check("takes the domain out of an email", clean.clean_domain("sam@acme.io") == "acme.io")
check("rejects a bare word", clean.clean_domain("not a domain") == "")
check("deduplicates and preserves order",
      clean.clean_list("a.com\nhttps://a.com/x, b.io ; a.com") == ["a.com", "b.io"])
check("empty blob gives an empty list", clean.clean_list("") == [])

# --- headcount parsing ------------------------------------------------------
print("headcount parsing")
check("range", qualify.parse_headcount("50-200 employees") == (50, 200))
check("single number", qualify.parse_headcount("a team of 80") == (80, 80))
check("open ended", qualify.parse_headcount("200+ people") == (200, None))
check("nothing stated", qualify.parse_headcount("unknown") == (None, None))

# --- quote verification -----------------------------------------------------
print("quote verification")
TEXT = "Acme Pay helps banks move money. We are a team of 60. Book a demo today."
check("real quote passes", ai.quote_is_real("We are a team of 60", TEXT, min_chars=10))
check("case and spacing do not matter",
      ai.quote_is_real("  we ARE a  team of 60. ", TEXT, min_chars=10))
check("invented quote fails",
      not ai.quote_is_real("We are SOC 2 certified since 2024", TEXT, min_chars=10))
check("empty quote fails", not ai.quote_is_real("", TEXT))


def fields_for(**over):
    base = {
        "company_name": {"value": "Acme Pay", "quote": "Acme Pay helps banks move money",
                         "source": "https://acme.io/", "verified": True},
        "what_it_does": {"value": "payments software", "quote": "Acme Pay helps banks move money",
                         "source": "https://acme.io/", "verified": True},
        "is_saas": {"value": "yes", "quote": "Book a demo today",
                    "source": "https://acme.io/", "verified": True},
        "employee_count": {"value": "60", "quote": "We are a team of 60",
                           "source": "https://acme.io/about", "verified": True},
        "funding_stage": {"value": "unknown", "quote": "", "source": "", "verified": False},
        "compliance_hiring": {"value": "unknown", "quote": "", "source": "", "verified": False},
        "enterprise_pressure": {"value": "unknown", "quote": "", "source": "", "verified": False},
        "certifications": [],
    }
    base.update(over)
    return base


VERTICAL_OK = {"value": "fintech", "quote": "Acme Pay helps banks move money",
               "source": "https://acme.io/", "certain": True, "verified": True}

# --- html reader: menu items must not glue into fake sentences ----------------
print("html reader")
NAV_HTML = (
    "<body><p>We are <a href='/soc'>SOC 2</a> certified today.</p>"
    "<a class='card' href='/mf'><span><b>Manufacturing</b>"
    "<em>Where the kiosk is built, in Chakan</em></span></a>"
    "<a class='card' href='/careers'><span><b>Careers</b>"
    "<em>Open roles across engineering</em></span></a></body>"
)
_text, _links = scrape.html_to_text(NAV_HTML)
_lines = [l.strip() for l in _text.splitlines() if l.strip()]
check("a menu card sits on its own line",
      any(l == "Manufacturing Where the kiosk is built, in Chakan" for l in _lines))
check("two menu cards do not glue together",
      not any("Chakan" in l and "Careers" in l for l in _lines))
check("a link inside a sentence stays in the sentence",
      any("We are SOC 2 certified today." in l for l in _lines))
check("links are still collected", len(_links) == 3)

# --- redirect guard ---------------------------------------------------------
print("redirect guard")
check("a real security page counts as the trust page",
      scrape.url_matches_kind("https://www.vanta.com/company/security", "trust"))
check("a campaign landing page does not",
      not scrape.url_matches_kind(
          "https://www.vanta.com/lp/demo-1k?utm_campaign=1k_offer", "trust"))
check("a nested about page still counts",
      scrape.url_matches_kind("https://www.vanta.com/company/about", "about"))
check("a redirect to the homepage does not count",
      not scrape.url_matches_kind("https://www.vanta.com/", "pricing"))
check("the homepage is always itself", scrape.url_matches_kind("https://x.io/", "home"))
_redirected = {"url": "https://x.io/lp/promo", "status": "ok", "text": "Book a demo now",
               "links": [], "note": ""}
check("a redirected page is refused", not scrape._accept(_redirected, "trust"))
check("and its text is dropped so nothing reads it",
      _redirected["status"] == "redirected" and _redirected["text"] == "")
check("a matching page is accepted",
      scrape._accept({"url": "https://x.io/trust", "status": "ok", "text": "SOC 2",
                      "links": [], "note": ""}, "trust"))

# --- hard filters -----------------------------------------------------------
print("hard filters")
check("a clean company passes", qualify.site_filters(fields_for(), VERTICAL_OK) is None)
check("not SaaS drops", qualify.site_filters(
    fields_for(is_saas={"value": "no", "quote": "We are a consultancy", "source": "u",
                        "verified": True}), VERTICAL_OK)[0] == qualify.HARD_FILTERS[0])
check("unanswered SaaS also drops (evidence map row 1)", qualify.site_filters(
    fields_for(is_saas={"value": "unknown", "quote": "", "source": "", "verified": False}),
    VERTICAL_OK)[0] == qualify.HARD_FILTERS[0])
check("vertical none drops", qualify.site_filters(
    fields_for(), {**VERTICAL_OK, "value": "none"})[0] == qualify.HARD_FILTERS[1])
check("unclear vertical does not drop", qualify.site_filters(
    fields_for(), {**VERTICAL_OK, "value": "unknown", "certain": False}) is None)
check("600 employees drops", qualify.site_filters(
    fields_for(employee_count={"value": "600 employees", "quote": "600 employees",
                               "source": "u", "verified": True}),
    VERTICAL_OK)[0] == qualify.HARD_FILTERS[2])
check("5 employees drops", qualify.site_filters(
    fields_for(employee_count={"value": "5", "quote": "team of 5", "source": "u",
                               "verified": True}),
    VERTICAL_OK)[0] == qualify.HARD_FILTERS[2])
check("unknown headcount does not drop", qualify.site_filters(
    fields_for(employee_count={"value": "unknown", "quote": "", "source": "",
                               "verified": False}), VERTICAL_OK) is None)
check("an unverified quote never drops", qualify.site_filters(
    fields_for(employee_count={"value": "600", "quote": "made up", "source": "u",
                               "verified": False}), VERTICAL_OK) is None)
both = [
    {"framework": "SOC 2", "status": "active", "quote": "SOC 2 Type II active",
     "source": "https://acme.io/trust", "verified": True},
    {"framework": "ISO 27001", "status": "active", "quote": "ISO 27001 certified",
     "source": "https://acme.io/trust", "verified": True},
]
check("both certifications active drops",
      qualify.site_filters(fields_for(certifications=both), VERTICAL_OK)[0]
      == qualify.HARD_FILTERS[3])
check("SOC 2 alone does not drop",
      qualify.site_filters(fields_for(certifications=both[:1]), VERTICAL_OK) is None)

# --- signals and ranking ----------------------------------------------------
print("signals and ranking")
hiring = {"value": "yes", "quote": "GRC Manager", "source": "https://acme.io/careers",
          "verified": True}
pressure = {"value": "yes", "quote": "Enterprise plan with security questionnaire support",
            "source": "https://acme.io/pricing", "verified": True}
sig_two = qualify.build_signals(
    fields_for(compliance_hiring=hiring, enterprise_pressure=pressure), VERTICAL_OK,
    {"funding": None, "audit_prep": None, "certified": None, "negative": None})
check("two site signals become High", qualify.tier_for(sig_two)[0] == "High")
sig_one = qualify.build_signals(fields_for(compliance_hiring=hiring), VERTICAL_OK,
                                {"funding": None, "audit_prep": None, "certified": None,
                                 "negative": None})
check("one signal is Medium", qualify.tier_for(sig_one)[0] == "Medium")
sig_none = qualify.build_signals(fields_for(), VERTICAL_OK,
                                 {"funding": None, "audit_prep": None, "certified": None,
                                  "negative": None})
check("no signal is Low", qualify.tier_for(sig_none)[0] == "Low")
cert_news = {"headline": "Acme Pay achieves ISO 27001", "published": "2026-06-01",
             "source": "http://n/1"}
sig_minus = qualify.build_signals(
    fields_for(compliance_hiring=hiring, enterprise_pressure=pressure), VERTICAL_OK,
    {"funding": None, "audit_prep": None, "certified": cert_news, "negative": None})
check("a certification headline counts against the tier",
      qualify.tier_for(sig_minus)[0] == "Medium")
check("the certification headline only flags, never drops",
      "likely already certified" in qualify.build_flags(
          fields_for(), VERTICAL_OK, sig_minus, "api"))

neg = {"headline": "Acme Pay hit by outage", "published": mailer.ist_now().strftime("%Y-%m-%d"),
       "source": "http://n/2"}
sig_neg = qualify.build_signals(fields_for(compliance_hiring=hiring), VERTICAL_OK,
                                {"funding": None, "audit_prep": None, "certified": None,
                                 "negative": neg})
check("negative news raises the tier", qualify.tier_for(sig_neg)[0] == "High")

# --- hook -------------------------------------------------------------------
print("hook choice")
check("hiring outranks enterprise pressure",
      qualify.choose_hook(fields_for(), sig_two)["key"] == "compliance_job")
check("negative news is never the hook",
      qualify.choose_hook(fields_for(), sig_neg)["key"] != "negative_news")
check("no signal falls back to a descriptive hook",
      qualify.choose_hook(fields_for(), sig_none)["descriptive_only"] is True)

# --- email code check -------------------------------------------------------
print("email code check")
person = {"name": "Riya Menon", "title": "Head of Security", "email": "riya@acme.io"}
good_body = ("Hi Riya, I saw you have a GRC Manager role open at Acme Pay. Teams at your "
             "stage usually lose engineering weeks to evidence collection, and "
             "questionnaires stall deals. Worth 15 minutes?")
hook_two = qualify.choose_hook(fields_for(), sig_two)
check("a clean draft raises no check flag",
      qualify.check_email("Acme Pay and SOC 2", good_body, person, sig_two, hook_two) == [])
check("a missing first name is flagged",
      any("first name" in f for f in qualify.check_email(
          "s", "Hello there, we help with GRC Manager hiring.", person, sig_two, hook_two)))
check("an unsupported funding claim is flagged",
      any("funding" in f for f in qualify.check_email(
          "s", "Hi Riya, congratulations on your Series B. GRC Manager role noted.",
          person, sig_two, hook_two)))
check("negative news language is flagged",
      any("breach" in f for f in qualify.check_email(
          "s", "Hi Riya, after the breach last month. GRC Manager role noted.",
          person, sig_two, hook_two)))
check("an over-long draft is flagged",
      any("word limit" in f or "words, over" in f for f in qualify.check_email(
          "s", "Hi Riya GRC Manager " + "word " * 200, person, sig_two, hook_two)))
check("an unused hook is flagged",
      any("hook" in f for f in qualify.check_email(
          "s", "Hi Riya, we sell compliance software. Fifteen minutes?",
          person, sig_two, hook_two)))

# --- contact choice ---------------------------------------------------------
print("contact choice")
HUNTER = {"data": {"emails": [
    {"first_name": "Dev", "last_name": "Rao", "position": "Co-Founder and CEO",
     "value": "dev@acme.io", "confidence": 94},
    {"first_name": "Riya", "last_name": "Menon", "position": "Head of Security",
     "value": "riya@acme.io", "confidence": 90},
    {"first_name": "No", "last_name": "Title", "position": "", "value": "x@acme.io"},
]}}
chosen, reason = hunter.choose(HUNTER)
check("security title beats founder", chosen["email"] == "riya@acme.io")
check("the reason names the tier", "security" in reason.lower())
check("records without a title are ignored", len(hunter.people(HUNTER)) == 2)
check("no usable record returns None", hunter.choose({"data": {"emails": []}})[0] is None)

# --- news helpers -----------------------------------------------------------
print("news helpers")
check("a headline naming the company counts",
      news.names_company("Acme Pay raises Series B", "Acme Pay", "acme.io"))
check("an unrelated headline does not",
      not news.names_company("Beta Corp raises Series B", "Acme Pay", "acme.io"))
check("an old date fails the 12 month window",
      not news.within_days("2019-01-01", 365))

# --- end to end with every external call stubbed ----------------------------
print("pipeline end to end (stubbed)")
db.init()

PAGES = {
    "home": {"url": "https://acme.io/", "status": "ok", "links": [],
             "text": "Acme Pay helps banks move money. Book a demo today."},
    "about": {"url": "https://acme.io/about", "status": "ok", "links": [],
              "text": "We are a team of 60."},
    "careers": {"url": "https://acme.io/careers", "status": "ok", "links": [],
                "text": "Open role: GRC Manager."},
}

scrape.scrape_company = lambda domain, kinds=None: {"pages": dict(PAGES), "unfetched": []}
ai.extract_fields = lambda blob: fields_for(compliance_hiring=dict(hiring))
ai.classify_vertical = lambda blob: dict(VERTICAL_OK)
ai.classify_headlines = lambda c, d, h: []
ai.pain_points = lambda *a, **k: ["Evidence collection eats your week.",
                                  "Questionnaires stall enterprise deals."]
ai.draft_email = lambda person, company, hook, pains: (
    "Acme Pay and the GRC Manager role",
    "Hi Riya, I saw the GRC Manager role open at Acme Pay. Teams your size lose weeks to "
    "evidence collection and stall on questionnaires. Worth 15 minutes?")
news.fetch = lambda company, domain, force=False: ([], "api")
hunter.search = lambda domain, force=False: (HUNTER, "api")

run_id = db.create_run(1)
company_id = pipeline.process_domain(run_id, "acme.io")
row = db.get_company(company_id)
check("the company is queued for review", row["status"] == "queued")
check("the tier is stored", row["tier"] == "Medium")
check("the contact is the security lead", row["poc_email"] == "riya@acme.io")
check("a subject was written", bool(row["email_subject"]))
check("the draft passed the code check", row["check_flags_json"] == "[]")

ai.extract_fields = lambda blob: fields_for(
    is_saas={"value": "no", "quote": "We are a consultancy", "source": "https://acme.io/",
             "verified": False})
drop_id = pipeline.process_domain(run_id, "acme.io")
drop_row = db.get_company(drop_id)
check("a failing company is dropped", drop_row["status"] == "dropped")
check("the drop stores the rule", drop_row["drop_rule"] == qualify.HARD_FILTERS[0])
check("the drop stores a quote", bool(drop_row["drop_quote"]))

# --- the review page renders a real card ------------------------------------
print("review page")
from app import main  # noqa: E402


card = main._row_to_card(row)
drop_card = main._row_to_card(drop_row)
html = main.templates.get_template("index.html").render(
    request=None, message="", error="", job=pipeline.JOB, run_id=run_id,
    review=[card], drops=[drop_card], cap=mailer.cap_state(),
    missing_keys=[], missing_send_keys=[], sent=[],
)
check("the card shows the company", "Acme Pay" in html)
check("the card shows the tier", ">MEDIUM<" in html.upper().replace(" ", "")
      or "Medium" in html)
check("the card shows the draft subject", card["subject"] in html)
check("the card shows why this person", "Why this person" in html)
check("the card shows the contact reason", "Head of Security" in html)
check("the drop log shows the rule", qualify.HARD_FILTERS[0] in html)
check("approve, save and reject are all offered",
      "Approve and send" in html and "Save edit" in html and ">Reject<" in html)

# --- caps and passcode ------------------------------------------------------
print("caps and passcode")
os.environ["DAILY_SEND_CAP"] = "2"
check("cap reads from the environment", mailer.cap_state()["cap"] == 2)
db.record_send(company_id, "someone@example.com")
check("a send counts against the cap", mailer.cap_state()["used"] >= 1)


os.environ["REVIEW_PASSCODE"] = "letmein"
config._ENV_LOADED = True
check("the right passcode passes", main.passcode_ok("letmein"))
check("a wrong passcode fails", not main.passcode_ok("nope"))
os.environ["REVIEW_PASSCODE"] = ""
check("an unset passcode refuses everything", not main.passcode_ok(""))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
