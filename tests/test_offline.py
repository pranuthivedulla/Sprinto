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
from urllib.parse import urlsplit

from app import config

# Point the database at a throwaway file before anything opens it.
config.DATA_DIR = Path(tempfile.mkdtemp(prefix="sprinto-test-"))
config.DB_PATH = config.DATA_DIR / "test.db"

# These tests write runs, companies and send_log rows. A send_log row counts against
# the real daily cap, so a stray DATABASE_URL must not quietly point them at the
# deployed database. Pass --use-database-url to aim them there on purpose.
USE_REAL_DB = "--use-database-url" in sys.argv
config.load_env()
if USE_REAL_DB:
    # Host only. The connection string carries a password.
    _host = urlsplit(os.environ.get("DATABASE_URL", "")).hostname or "?"
    print(f"WRITING TO THE REAL DATABASE at {_host}")
    print("rows this run creates will stay there unless you remove them")
    print()
elif os.environ.pop("DATABASE_URL", None):
    print("DATABASE_URL ignored; using a temporary SQLite file.")
    print("pass --use-database-url to run against the real database instead")
    print()

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

scrape.scrape_company = lambda domain, kinds=None, deadline=None: {
    "pages": dict(PAGES), "unfetched": []}
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
_REAL_HUNTER_SEARCH = hunter.search
_REAL_HUNTER_CHOOSE = hunter.choose
hunter.search = lambda domain, force=False: (HUNTER, "api")

run_id = db.create_run(1)
result = pipeline.process_domain(run_id, "acme.io")
company_id = result["company_id"]
row = db.get_company(company_id)
check("the company is queued for review", row["status"] == "queued")
check("the tier is stored", row["tier"] == "Medium")
check("the contact is the security lead", row["poc_email"] == "riya@acme.io")
check("a subject was written", bool(row["email_subject"]))
check("the draft passed the code check", row["check_flags_json"] == "[]")

ai.extract_fields = lambda blob: fields_for(
    is_saas={"value": "no", "quote": "We are a consultancy", "source": "https://acme.io/",
             "verified": False})
drop_id = pipeline.process_domain(run_id, "acme.io")["company_id"]
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
    request=None, message="", error="", run_id=run_id,
    review=[card], drops=[drop_card], cap=mailer.cap_state(),
    missing_keys=[], missing_send_keys=[], sent=[],
    demo_domains={"Healthtech": ["a.com", "b.com"]},
    max_domains=config.MAX_DOMAINS_PER_RUN,
)
check("the card shows the company", "Acme Pay" in html)
check("the page offers a one-click list button",
      'data-pick="Healthtech"' in html and ">Healthtech" in html)
check("the page offers the chip input, not a textarea",
      'id="chipinput"' in html and "<textarea name=\"domains\"" not in html)
check("the card shows the tier", ">MEDIUM<" in html.upper().replace(" ", "")
      or "Medium" in html)
check("the card shows the draft subject", card["subject"] in html)
check("the card shows why this person", "Why this person" in html)
check("the card shows the contact reason", "Head of Security" in html)
check("the drop log shows the rule", qualify.HARD_FILTERS[0] in html)
check("approve, save and reject are all offered",
      "Approve and send" in html and "Save edit" in html and ">Reject<" in html)

# --- database dialect: same tables, two engines ------------------------------
print("database dialect")


class FakeConn:
    """Records the SQL it is handed, so the Postgres path can be read without a server."""
    def __init__(self): self.sql = []
    def execute(self, sql, params=None): self.sql.append(sql); return self


def _with_db_url(value, fn):
    """Run fn with DATABASE_URL forced on or off, then put back what was there.

    The suite must not disturb a real DATABASE_URL, because the whole point of
    setting one is to run these same checks against the real database.
    """
    before = os.environ.get("DATABASE_URL")
    if value:
        os.environ["DATABASE_URL"] = value
    else:
        os.environ.pop("DATABASE_URL", None)
    config._ENV_LOADED = True
    try:
        return fn()
    finally:
        if before is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = before


def _as_postgres(fn):
    return _with_db_url("postgresql://user:pw@host/db", fn)


def _as_sqlite(fn):
    return _with_db_url("", fn)


check("SQLite is the default with no DATABASE_URL",
      _as_sqlite(lambda: not db.is_postgres()))
check("DATABASE_URL switches the dialect", _as_postgres(db.is_postgres))
check("placeholders stay ? on SQLite",
      _as_sqlite(lambda: db._q("WHERE a=? AND b=?")) == "WHERE a=? AND b=?")
check("placeholders become %s on Postgres",
      _as_postgres(lambda: db._q("WHERE a=? AND b=?")) == "WHERE a=%s AND b=%s")
check("SQLite schema uses AUTOINCREMENT",
      _as_sqlite(lambda: any("AUTOINCREMENT" in s for s in db.schema_statements())))
check("Postgres schema uses SERIAL instead",
      _as_postgres(lambda: all("AUTOINCREMENT" not in s for s in db.schema_statements())
                   and any("SERIAL PRIMARY KEY" in s for s in db.schema_statements())))


def _columns(statements):
    return sorted(
        line.strip().split()[0]
        for s in statements if "companies" in s.split("(")[0]
        for line in s.split("(", 1)[1].rsplit(")", 1)[0].splitlines()
        if line.strip() and not line.strip().startswith(")")
    )


check("both engines declare exactly the same company columns",
      _as_sqlite(lambda: _columns(db.schema_statements()))
      == _as_postgres(lambda: _columns(db.schema_statements())))
check("every table in the build prompt is created",
      {"runs", "companies", "hunter_cache", "news_cache", "send_log"}
      <= {s.split("IF NOT EXISTS")[1].split("(")[0].strip()
          for s in db.schema_statements()})

_c = FakeConn()
_as_sqlite(lambda: db._upsert(_c, "hunter_cache", ["domain"],
                              ["response_json", "fetched_at"], ("a", "b", "c")))
check("SQLite caches with INSERT OR REPLACE", "INSERT OR REPLACE" in _c.sql[0])
_c = FakeConn()
_as_postgres(lambda: db._upsert(_c, "hunter_cache", ["domain"],
                                ["response_json", "fetched_at"], ("a", "b", "c")))
check("Postgres caches with ON CONFLICT DO UPDATE",
      "ON CONFLICT (domain) DO UPDATE" in _c.sql[0] and "%s" in _c.sql[0])
_c = FakeConn()
_as_postgres(lambda: db._upsert(_c, "news_cache", ["company", "query"],
                                ["headlines_json", "fetched_at"], ("a", "b", "c", "d")))
check("the news cache keys on both columns", "ON CONFLICT (company,query)" in _c.sql[0])

# --- the demo redirect: named in the email, never delivered to them ----------
print("demo redirect")
import smtplib  # noqa: E402

os.environ["TO_EMAIL"] = "me@example.com"
os.environ["GMAIL_SENDER_ADDRESS"] = "bot@example.com"
os.environ["GMAIL_APP_PASSWORD"] = "x"
os.environ["DAILY_SEND_CAP"] = "15"
config._ENV_LOADED = True

_sent = []


class FakeSMTP:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self): pass
    def login(self, *a): pass
    def send_message(self, msg): _sent.append(msg)


smtplib.SMTP = FakeSMTP

mailer.send(company_id, "Subject here", "Hi Riya, body of the draft.")
_msg = _sent[-1]
check("the email is delivered to TO_EMAIL", _msg["To"] == "me@example.com")
check("it is never delivered to the contact", "riya@acme.io" not in _msg["To"])
check("it names the contact in a demo banner", "[Demo redirect]" in _msg.get_content())
check("it carries the intended recipient header",
      _msg["X-Intended-Recipient"] == "riya@acme.io")
check("the stored draft stays free of the banner",
      "[Demo redirect]" not in (db.get_company(company_id)["email_body"] or ""))

_no_contact = db.insert_company(run_id, "nopoc.io", "queued", email_subject="s",
                                email_body="b")
mailer.send(_no_contact, "Subject", "Body with no contact.")
_plain = _sent[-1]
check("with no contact there is no banner", "[Demo redirect]" not in _plain.get_content())
check("and no intended-recipient header", _plain["X-Intended-Recipient"] is None)
check("but it still goes to TO_EMAIL", _plain["To"] == "me@example.com")

check("the card shows who the draft is addressed to", "Addressed to:" in html)
_blank = main._row_to_card(db.get_company(_no_contact))
_html2 = main.templates.get_template("index.html").render(
    request=None, message="", error="", run_id=run_id, review=[_blank], drops=[],
    cap=mailer.cap_state(), missing_keys=[], missing_send_keys=[], sent=[],
    demo_domains={}, max_domains=config.MAX_DOMAINS_PER_RUN)
check("with no contact the card says nothing about one", "Addressed to:" not in _html2)

# --- cleaning vectors, the ones the chip input mirrors -----------------------
print("cleaning vectors")
for raw, want in [
    ("https://www.Example.com/pricing", "example.com"),
    ("HTTP://ACME.IO", "acme.io"),
    ("www.beta.co.uk/careers?x=1", "beta.co.uk"),
    ("gamma.dev:8443", "gamma.dev"),
    ("  delta.ai/  ", "delta.ai"),
    ("banana", ""),
    ("not a domain", ""),
]:
    check(f"{raw!r} cleans to {want!r}", clean.clean_domain(raw) == want)

# --- the endpoints -----------------------------------------------------------
print("endpoints")
from fastapi.testclient import TestClient  # noqa: E402

os.environ["REVIEW_PASSCODE"] = "letmein"
os.environ["SESSION_SECRET"] = "test-secret"
config._ENV_LOADED = True
pipeline.process_domain_safely = lambda rid, d, budget=None: {
    "company_id": db.insert_company(rid, d, "dropped", drop_rule="not SaaS"),
    "domain": d, "status": "dropped", "rule": "not SaaS"}

client = TestClient(main.app)
check("the review page is closed without the cookie",
      client.get("/", follow_redirects=False).status_code == 303)
check("and it points at the passcode screen",
      client.get("/", follow_redirects=False).headers["location"] == "/login")
check("every response tells search engines to stay away",
      client.get("/login").headers.get("X-Robots-Tag") == "noindex, nofollow")
check("a wrong passcode is refused",
      client.post("/login", data={"passcode": "nope"}).status_code == 401)
check("the right passcode opens the page",
      client.post("/login", data={"passcode": "letmein"},
                  follow_redirects=False).status_code == 303)

_fresh = TestClient(main.app)
for _ in range(config.LOGIN_MAX_FAILURES):
    _fresh.post("/login", data={"passcode": "nope"})
check("too many wrong tries are throttled",
      _fresh.post("/login", data={"passcode": "letmein"}).status_code == 429)
db.clear_login_failures("testclient")

check("run-domain refuses a stranger",
      TestClient(main.app).post("/run-domain",
                                data={"domain": "x.com"}).status_code == 403)

_in = TestClient(main.app)
_in.post("/login", data={"passcode": "letmein"})
_r = _in.post("/run-domain", data={"domain": "https://www.One.com/x"})
check("run-domain researches one domain for a signed-in reviewer", _r.status_code == 200)
check("and cleans the domain on the server", _r.json()["domain"] == "one.com")
_rid = _r.json()["run_id"]
check("and writes it to the database",
      any(c["domain"] == "one.com" for c in db.companies_for_run(_rid)))

for i in range(config.MAX_DOMAINS_PER_RUN - 1):
    _in.post("/run-domain", data={"domain": f"d{i}.com", "run_id": str(_rid)})
_over = _in.post("/run-domain", data={"domain": "sixteenth.com", "run_id": str(_rid)})
check(f"the {config.MAX_DOMAINS_PER_RUN + 1}th domain in a run is refused",
      _over.status_code == 400)
check("and the run still holds exactly the limit",
      db.count_companies(_rid) == config.MAX_DOMAINS_PER_RUN)


# --- a misconfigured deployment must say so, not crash -----------------------
print("deployment guard")


def _as_vercel(fn):
    os.environ["VERCEL"] = "1"
    config._ENV_LOADED = True
    try:
        return fn()
    finally:
        os.environ.pop("VERCEL", None)


_saved_pass = os.environ.get("REVIEW_PASSCODE", "")
os.environ["REVIEW_PASSCODE"] = ""
_r = _as_vercel(lambda: TestClient(main.app).get("/", follow_redirects=False))
check("production without a passcode refuses to serve", _r.status_code == 503)
check("and the reason is readable, not a stack trace",
      "REVIEW_PASSCODE" in _r.text and "environment variables" in _r.text)
check("even a refusal keeps search engines away",
      _r.headers.get("X-Robots-Tag") == "noindex, nofollow")
os.environ["REVIEW_PASSCODE"] = _saved_pass
config._ENV_LOADED = True
check("with both set, production serves normally",
      _as_vercel(lambda: TestClient(main.app).get("/", follow_redirects=False)
                 ).status_code == 303)


# --- one slow AI endpoint must not kill the domain ---------------------------
print("ai fallback")
import requests as _rq  # noqa: E402
from app import gemini  # noqa: E402


def _endpoints(first_raises, second_returns):
    calls = []

    def a(prompt, temperature):
        calls.append("interactions")
        raise first_raises

    def b(prompt, temperature):
        calls.append("generate")
        if isinstance(second_returns, Exception):
            raise second_returns
        return second_returns

    gemini._call_interactions, gemini._call_generate = a, b
    gemini._WORKING_ENDPOINT = ""
    return calls


_real = (gemini._call_interactions, gemini._call_generate)
_calls = _endpoints(_rq.Timeout("slow"), "it worked")
check("a timeout on one endpoint falls through to the other",
      gemini.call_model("x") == "it worked" and _calls == ["interactions", "generate"])
_endpoints(_rq.Timeout("slow"), _rq.Timeout("also slow"))
try:
    gemini.call_model("x")
    check("both timing out raises", False)
except RuntimeError as e:
    check("both timing out gives one readable reason",
          str(e) == "the AI did not answer in time")
check("the ceiling leaves room for a slow answer", gemini.TIMEOUT >= 60)
gemini._call_interactions, gemini._call_generate = _real


# --- Hunter: ask for what the plan allows, and repeat what it says -----------
print("hunter request")
import requests as _rq2  # noqa: E402
from app import hunter as _h  # noqa: E402


class _Resp:
    def __init__(self, code, payload): self.status_code, self._p = code, payload
    def json(self): return self._p


_seen = {}


def _fake_get(url, params=None, timeout=None):
    _seen.update(params or {})
    return _Resp(200, {"data": {"emails": []}})


# The pipeline block above replaced hunter.search with a stub. Put the real one
# back, or this tests the stub and passes whatever the code does.
_h.search = _REAL_HUNTER_SEARCH
_real_get = _rq2.get
_rq2.get = _fake_get
os.environ["HUNTER_API_KEY"] = "test-key"
config._ENV_LOADED = True
_h.search("limitcheck.test", force=True)
check("the real request was made, not a stub", bool(_seen))
check("no limit parameter is sent, because the free plan rejects one",
      "limit" not in _seen)
check("the domain and key are sent", _seen.get("domain") == "limitcheck.test")

_rq2.get = lambda url, params=None, timeout=None: _Resp(
    400, {"errors": [{"id": "pagination_error",
                      "details": "The search results are limited to 10 email addresses."}]})
try:
    _h.search("err.test", force=True)
    check("a Hunter error raises", False)
except RuntimeError as e:
    check("the error repeats what Hunter said, not just the status code",
          "limited to 10 email addresses" in str(e) and "400" in str(e))
    check("and that reaches the reviewer in plain words",
          "limited to 10" in pipeline.plain_reason(e))
_rq2.get = _real_get


# --- title matching is whole-word, and a draft is never wiped ----------------
print("title matching")


def _tier(title):
    person, _ = hunter.choose({"data": {"emails": [
        {"first_name": "X", "last_name": "Y", "position": title, "value": "x@y.com"}]}})
    return person["title_tier"]


hunter.choose = _REAL_HUNTER_CHOOSE
check("a product director is not an engineering leader",
      _tier("Director of Product Management") == "other")
check("nor is a marketing director",
      _tier("Director of Marketing") == "other")
check("an engineering director still is", _tier("Director of Engineering") == "engineering")
check("so does a plain CTO", _tier("CTO") == "engineering")
check("security titles still win", _tier("Head of Security") == "security_or_grc")
check("GRC counts as security", _tier("GRC Manager") == "security_or_grc")
check("founders are still found", _tier("Co-Founder and CEO") == "founder_or_ceo")
check("a security lead outranks a founder", hunter.choose({"data": {"emails": [
    {"first_name": "A", "last_name": "B", "position": "Founder", "value": "a@b.com"},
    {"first_name": "C", "last_name": "D", "position": "CISO", "value": "c@d.com"},
]}})[0]["email"] == "c@d.com")

print("drafts are not wiped")
_draft = db.insert_company(run_id, "draft.test", "queued", company_name="Draft Test",
                           email_subject="Real subject", email_body="The generated body.")
_in.post("/save", data={"company_id": _draft, "subject": "", "body": ""})
_after = db.get_company(_draft)
check("an empty body does not replace the draft",
      _after["email_body"] == "The generated body.")
check("nor does an empty subject", _after["email_subject"] == "Real subject")
_in.post("/save", data={"company_id": _draft, "subject": "Edited", "body": "My edit."})
_after = db.get_company(_draft)
check("a real edit is still saved",
      _after["email_body"] == "My edit." and _after["email_subject"] == "Edited")


# --- the generated draft survives an edit ------------------------------------
print("draft is kept")
check("the pipeline stores what the model wrote",
      row["draft_body"] == row["email_body"] and bool(row["draft_body"]))
_edited = db.insert_company(run_id, "keepdraft.test", "queued",
                            draft_subject="Model subject", draft_body="What the model wrote.",
                            email_subject="Model subject", email_body="What the model wrote.")
_in.post("/save", data={"company_id": _edited, "subject": "Mine", "body": "What I sent."})
_after = db.get_company(_edited)
check("an edit changes the live version", _after["email_body"] == "What I sent.")
check("and leaves the original intact",
      _after["draft_body"] == "What the model wrote.")
check("so the before-and-after pair exists to learn from",
      _after["draft_body"] != _after["email_body"])

print("new columns reach an existing table")
_stmt = [s for s in db.schema_statements() if "companies" in s.split("(")[0]][0]
_declared = {n for n, _ in db.declared_columns(_stmt)}
check("draft columns are declared", {"draft_subject", "draft_body"} <= _declared)
check("constraint lines are not read as columns",
      all(not c.upper().startswith(("PRIMARY", "FOREIGN")) for c in _declared))
with db.connect() as _c:
    check("and they exist in the live table",
          {"draft_subject", "draft_body"} <= db.existing_columns(_c, "companies"))

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
