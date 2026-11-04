"""Hard filters, signals, ranking, hook choice and the email code check.

All of this is plain code. The AI is not consulted anywhere in this file.
"""
import re

from . import config, news

HARD_FILTERS = (
    "not SaaS",
    "vertical is not fintech, healthtech or cleantech",
    "stated employee count outside 10-100",
    "SOC 2 and ISO 27001 both active on the trust page",
    "no usable contact from Hunter",
)


# --- field helpers -----------------------------------------------------------

def field(fields, key):
    value = (fields or {}).get(key)
    return value if isinstance(value, dict) else {}


def value_of(fields, key):
    return str(field(fields, key).get("value", "")).strip()


def verified(fields, key):
    return bool(field(fields, key).get("verified"))


def parse_headcount(raw):
    """Return (low, high) from a stated count, or (None, None) if nothing is stated."""
    text = (raw or "").lower()
    if not text or "unknown" in text:
        return None, None
    text = text.replace(",", "")
    span = re.search(r"(\d{1,6})\s*(?:-|to|–)\s*(\d{1,6})", text)
    if span:
        return int(span.group(1)), int(span.group(2))
    plus = re.search(r"(\d{1,6})\s*\+", text)
    if plus:
        return int(plus.group(1)), None
    single = re.search(r"(\d{1,6})", text)
    if single:
        n = int(single.group(1))
        return n, n
    return None, None


def certs_active(fields):
    """Frameworks the trust page shows as active, from a verified quote only."""
    out = []
    for cert in (fields or {}).get("certifications", []) or []:
        if not isinstance(cert, dict) or not cert.get("verified"):
            continue
        status = str(cert.get("status", "")).lower()
        framework = str(cert.get("framework", "")).lower()
        if "active" in status or "complete" in status or "certified" in status:
            if "soc 2" in framework or "soc2" in framework:
                out.append(("SOC 2", cert))
            elif "27001" in framework:
                out.append(("ISO 27001", cert))
            else:
                out.append((cert.get("framework", "other"), cert))
    return out


# --- hard filters ------------------------------------------------------------

def site_filters(fields, vertical):
    """Filters 1-4 (the site-based ones). Returns (drop_rule, quote, source) or None.

    A drop needs a verified quote. An unverified or missing quote means unknown,
    and unknown never drops.
    """
    # Row 1 is the only row where "unanswered" also drops (evidence-map.md row 1).
    f = field(fields, "is_saas")
    if value_of(fields, "is_saas").lower() != "yes" or not verified(fields, "is_saas"):
        quote = f.get("quote", "") if verified(fields, "is_saas") else ""
        if not quote:
            quote = (
                "Absence, not a claim: no readable page stated a software product with "
                "subscription pricing or a book-a-demo CTA."
            )
        return HARD_FILTERS[0], quote, f.get("source", "")

    if vertical.get("value") == "none" and vertical.get("verified"):
        return HARD_FILTERS[1], vertical.get("quote", ""), vertical.get("source", "")

    if verified(fields, "employee_count"):
        low, high = parse_headcount(value_of(fields, "employee_count"))
        f = field(fields, "employee_count")
        if low is not None:
            below = high is not None and high < config.EMPLOYEE_MIN
            above = low > config.EMPLOYEE_MAX
            if below or above:
                return HARD_FILTERS[2], f.get("quote", ""), f.get("source", "")

    active = {name for name, _ in certs_active(fields)}
    if "SOC 2" in active and "ISO 27001" in active:
        quotes = "; ".join(
            c.get("quote", "") for name, c in certs_active(fields)
            if name in ("SOC 2", "ISO 27001")
        )
        source = next(
            (c.get("source", "") for name, c in certs_active(fields) if name == "SOC 2"),
            "",
        )
        return HARD_FILTERS[3], quotes, source

    return None


# --- news -> signals ---------------------------------------------------------

def news_signals(company_name, domain, headlines, classifications):
    """Turn classified headlines into signals. Code does every date check."""
    out = {"funding": None, "audit_prep": None, "certified": None, "negative": None}
    for row in classifications:
        head = headlines[row["index"]]
        if not row.get("names_this_company"):
            continue
        if not news.names_company(head["title"], company_name, domain):
            continue  # code double-checks the model's "this is the right company"
        category = row["category"]
        item = {
            "headline": head["title"],
            "published": head.get("published", ""),
            "source": head.get("link", ""),
        }
        if category == "funding" and out["funding"] is None:
            out["funding"] = item
        elif category == "compliance_preparing" and out["audit_prep"] is None:
            out["audit_prep"] = item
        elif category == "compliance_certified" and out["certified"] is None:
            out["certified"] = item
        elif category == "negative" and out["negative"] is None:
            if news.within_days(item["published"], news.NEGATIVE_WINDOW_DAYS):
                out["negative"] = item
    return out


def build_signals(fields, vertical, news_sig):
    """The ranking signals, each with the source that proves it."""
    signals = []
    if value_of(fields, "compliance_hiring").lower() == "yes" and verified(
        fields, "compliance_hiring"
    ):
        f = field(fields, "compliance_hiring")
        signals.append(
            {
                "key": "compliance_job",
                "label": "Open compliance or security role on the careers page",
                "quote": f.get("quote", ""),
                "source": f.get("source", ""),
                "counts": True,
            }
        )
    if news_sig.get("audit_prep"):
        item = news_sig["audit_prep"]
        signals.append(
            {
                "key": "audit_prep_headline",
                "label": "News headline: preparing for an audit or certification",
                "quote": item["headline"],
                "source": item["source"],
                "date": item["published"],
                "counts": True,
            }
        )
    if value_of(fields, "enterprise_pressure").lower() == "yes" and verified(
        fields, "enterprise_pressure"
    ):
        f = field(fields, "enterprise_pressure")
        signals.append(
            {
                "key": "enterprise_pressure",
                "label": "Enterprise-customer pressure on the site",
                "quote": f.get("quote", ""),
                "source": f.get("source", ""),
                "counts": True,
            }
        )
    round_name = value_of(fields, "funding_stage")
    if round_name and round_name.lower() != "unknown" and verified(fields, "funding_stage"):
        f = field(fields, "funding_stage")
        signals.append(
            {
                "key": "funding_round",
                "label": f"Named funding round on the site: {round_name}",
                "quote": f.get("quote", ""),
                "source": f.get("source", ""),
                "counts": True,
            }
        )
    elif news_sig.get("funding"):
        item = news_sig["funding"]
        signals.append(
            {
                "key": "funding_round",
                "label": "News headline: named funding round",
                "quote": item["headline"],
                "source": item["source"],
                "date": item["published"],
                "counts": True,
            }
        )
    if news_sig.get("negative"):
        item = news_sig["negative"]
        signals.append(
            {
                "key": "negative_news",
                "label": "Negative news in the last 12 months (buying signal only, "
                         "never quoted in the email)",
                "quote": item["headline"],
                "source": item["source"],
                "date": item["published"],
                "counts": True,
                "never_in_email": True,
            }
        )
    if news_sig.get("certified"):
        item = news_sig["certified"]
        signals.append(
            {
                "key": "likely_already_certified",
                "label": "News headline announcing a certification (counts against)",
                "quote": item["headline"],
                "source": item["source"],
                "date": item["published"],
                "counts": False,
                "against": True,
            }
        )
    return signals


def tier_for(signals):
    score = sum(1 for s in signals if s.get("counts"))
    if any(s.get("against") for s in signals):
        score -= 1
    score = max(score, 0)
    if score >= 2:
        return "High", score
    if score == 1:
        return "Medium", score
    return "Low", score


def audit_verdict(fields, signals):
    """Rows 4, 5 and 6 together. A derived verdict, never a stored row."""
    has_hiring = any(s["key"] == "compliance_job" for s in signals)
    has_headline = any(s["key"] == "audit_prep_headline" for s in signals)
    has_pressure = any(s["key"] == "enterprise_pressure" for s in signals)
    active = {name for name, _ in certs_active(fields)}
    if active:
        shown = ", ".join(sorted(active))
        base = f"Trust page shows {shown} as active."
    else:
        base = "No certification shown on the site (not the same as none held)."
    if has_hiring or has_headline:
        return base + " Preparing for an audit: yes, from a found signal."
    if has_pressure:
        return base + " Enterprise pressure found, audit intent not stated."
    return base + " Audit intent unknown."


# --- flags -------------------------------------------------------------------

def build_flags(fields, vertical, signals, hunter_source):
    flags = []
    if not verified(fields, "employee_count") or not parse_headcount(
        value_of(fields, "employee_count")
    )[0]:
        flags.append("employee count unknown")
    if vertical.get("value") in ("unknown", "") or not vertical.get("certain") or not vertical.get(
        "verified"
    ):
        flags.append("vertical unclear")
    if not any(s["key"] == "funding_round" for s in signals):
        flags.append("funding stage unknown")
    if any(s.get("against") for s in signals):
        flags.append("likely already certified")
    if any(s["key"] == "negative_news" for s in signals):
        flags.append("negative news found (reviewer only, not in the email)")
    if not any(s.get("counts") for s in signals):
        flags.append("no intent signal found - hook is descriptive only")
    for key in ("is_saas", "what_it_does", "compliance_hiring", "enterprise_pressure"):
        f = field(fields, key)
        if f.get("quote") and not f.get("verified"):
            flags.append(f"quote for {key} not found in the scraped text - treated as unknown")
    if hunter_source == "cache":
        flags.append("contact came from the Hunter cache, not a new search")
    return flags


# --- hook --------------------------------------------------------------------

HOOK_ORDER = ["compliance_job", "audit_prep_headline", "enterprise_pressure", "funding_round"]


def choose_hook(fields, signals):
    """Pick the one signal the email may cite. Negative news is never eligible."""
    for key in HOOK_ORDER:
        for signal in signals:
            if signal["key"] == key and not signal.get("never_in_email"):
                return {
                    "key": key,
                    "text": f"{signal['label']}: \"{signal['quote']}\"",
                    "quote": signal["quote"],
                    "source": signal.get("source", ""),
                    "date": signal.get("date", ""),
                    "descriptive_only": False,
                }
    what = field(fields, "what_it_does")
    return {
        "key": "what_it_does",
        "text": (
            "No intent signal was found. You may only refer to what the company says it "
            f"does: \"{what.get('value', '')}\""
        ),
        "quote": what.get("quote", ""),
        "source": what.get("source", ""),
        "date": "",
        "descriptive_only": True,
    }


# --- email code check --------------------------------------------------------

NEGATIVE_WORDS = [
    "breach", "breached", "hack", "hacked", "incident", "outage", "lawsuit", "fine",
    "leak", "leaked", "ransomware", "compromised",
]

CLAIM_PATTERNS = [
    ("funding_round", r"\b(series\s+[a-d]|seed round|raised|funding round|fundraise)\b"),
    ("certification", r"\b(soc\s*2|iso\s*27001)\b.{0,40}\b(certified|compliant|achieved|completed)\b"),
    ("compliance_job", r"\b(hiring|job post|open role|recruiting|new hire)\b"),
    ("enterprise_pressure", r"\b(enterprise (customers|clients|deals)|security questionnaire)\b"),
]


def check_email(subject, body, person, signals, hook):
    """Every claim in the draft must exist in the stored signals. A miss flags, never blocks."""
    flags = []
    text = f"{subject}\n{body}"
    lowered = text.lower()
    present = {s["key"] for s in signals}

    first_name = (person.get("name", "").split() or [""])[0]
    if first_name and first_name.lower() not in lowered:
        flags.append("draft does not address the person by first name")

    words = len(re.findall(r"\b[\w'-]+\b", body))
    if words > config.EMAIL_WORD_LIMIT:
        flags.append(f"draft is {words} words, over the ~120 word limit")

    for word in NEGATIVE_WORDS:
        if re.search(rf"\b{word}\b", lowered):
            flags.append(f'draft mentions "{word}" - negative news must never be quoted')
            break

    for key, pattern in CLAIM_PATTERNS:
        if re.search(pattern, lowered):
            if key == "certification":
                if not certs_active_claimable(signals):
                    flags.append(
                        "draft claims a certification that is not in the stored signals"
                    )
            elif key not in present:
                flags.append(f"draft refers to {key.replace('_', ' ')} with no stored signal")

    hook_quote = (hook or {}).get("quote", "")
    if hook_quote:
        keywords = [w for w in re.findall(r"[a-z]{5,}", hook_quote.lower())][:6]
        if keywords and not any(k in lowered for k in keywords):
            flags.append("hook not matched to a stored signal in the draft text")
    return flags


def certs_active_claimable(signals):
    return any(s["key"] == "likely_already_certified" for s in signals)
