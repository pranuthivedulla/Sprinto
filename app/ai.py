"""The six Gemini Flash steps, and the code check that every quote is real.

The AI only reads messy text, classifies from a fixed list with a quote, and writes.
It never filters, ranks, does date arithmetic, picks a person or sends anything.
"""
import re

from . import gemini

UNKNOWN = "unknown"

EVIDENCE_RULES = """Rules you must follow:
- Quote only sentences that appear verbatim in the text given to you. Copy them exactly.
- If the text does not state something, answer "unknown". Never infer, estimate or
  fill a value from what similar companies usually look like.
- "Not shown on the site" is not the same as "does not exist". Say unknown.
- Never invent a person, a number, a certification, a funding round or a date."""


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def quote_is_real(quote, haystack, min_chars=40):
    """True when the quote actually appears in the scraped text."""
    q, h = _norm(quote), _norm(haystack)
    if not q or not h:
        return False
    if q in h:
        return True
    head = q[:min_chars]
    return len(q) >= min_chars and head in h


def verify_fields(fields, haystack):
    """Mark each field verified or not. An unverified quote can never cause a drop."""
    for key, value in list(fields.items()):
        if key == "certifications" and isinstance(value, list):
            for cert in value:
                if isinstance(cert, dict):
                    cert["verified"] = quote_is_real(cert.get("quote"), haystack)
            continue
        if isinstance(value, dict):
            value["verified"] = quote_is_real(value.get("quote"), haystack)
    return fields


# --- (a) extract fields ------------------------------------------------------

EXTRACT_PROMPT = """You are reading scraped text from one company's website.
Fill the JSON below from that text only.

{rules}

Text:
---
{blob}
---

Return exactly this JSON shape. Every field carries the sentence you based it on and
the page URL that sentence came from (use the "### ... PAGE (url)" headers above):
{{
 "company_name": {{"value": "...", "quote": "...", "source": "..."}},
 "what_it_does": {{"value": "one sentence", "quote": "...", "source": "..."}},
 "is_saas": {{"value": "yes|no|unknown", "quote": "...", "source": "..."}},
 "employee_count": {{"value": "the stated number or range, or unknown",
                     "quote": "...", "source": "..."}},
 "funding_stage": {{"value": "named round e.g. Series A, or unknown",
                    "quote": "...", "source": "..."}},
 "compliance_hiring": {{"value": "yes|unknown",
    "quote": "the job title line if a GRC, security, compliance, InfoSec or Trust role is open",
    "source": "..."}},
 "enterprise_pressure": {{"value": "yes|unknown",
    "quote": "enterprise logos, an Enterprise plan, or a security-questionnaire mention",
    "source": "..."}},
 "certifications": [
   {{"framework": "SOC 2|ISO 27001|GDPR|other",
     "status": "active|in progress|mentioned only",
     "quote": "...", "source": "..."}}
 ]
}}
is_saas is "yes" when the text describes a software product AND shows either of these:
 - pricing tiers, a per-month or per-year price, a plan name, or a free trial
 - a call to action such as "Book a demo", "Request a demo", "Get started", "Sign up",
   "Start free", or a Log in link
Either one is enough; you do not need both. Quote whichever line you used. Answer "no"
only when the text shows this is not a software product, for example an agency, a
consultancy, a hardware maker or a physical service. Answer "unknown" only when the
text says nothing either way.
certifications is an empty list if none are named."""


def extract_fields(blob):
    data = gemini.call_json(EXTRACT_PROMPT.format(rules=EVIDENCE_RULES, blob=blob))
    if not isinstance(data, dict):
        raise RuntimeError("extraction did not return an object")
    data.setdefault("certifications", [])
    return data


# --- (b) vertical ------------------------------------------------------------

VERTICAL_PROMPT = """Classify this company into exactly one of: fintech, healthtech,
cleantech, none. "none" means it is not in any of those three.

{rules}

Text:
---
{blob}
---

Return: {{"vertical": "fintech|healthtech|cleantech|none",
          "quote": "the sentence that shows it", "source": "page url",
          "certain": true|false}}
Set certain to false if the text is too thin to tell; the quote must still be real."""


def classify_vertical(blob):
    data = gemini.call_json(VERTICAL_PROMPT.format(rules=EVIDENCE_RULES, blob=blob))
    vertical = str(data.get("vertical", "")).lower().strip()
    if vertical not in ("fintech", "healthtech", "cleantech", "none"):
        vertical = UNKNOWN
    return {
        "value": vertical,
        "quote": data.get("quote", ""),
        "source": data.get("source", ""),
        "certain": bool(data.get("certain")),
    }


# --- (c) headline classification --------------------------------------------

HEADLINES_PROMPT = """Classify each news headline for the company "{company}"
(domain {domain}).

Categories:
- funding: announces a named funding round for this company
- compliance_certified: says this company has achieved or completed SOC 2 or ISO 27001
- compliance_preparing: says this company is preparing for, starting or working towards
  an audit or certification
- negative: a breach, security incident, outage, fine or lawsuit at this company
- irrelevant: anything else, or about a different company with a similar name

{rules}

Headlines:
{items}

Return a JSON array, one object per headline, in the same order:
[{{"index": 0, "category": "...", "names_this_company": true|false}}]"""


def classify_headlines(company, domain, headlines):
    if not headlines:
        return []
    items = "\n".join(
        f"{i}. {h['title']} ({h.get('published', '')})" for i, h in enumerate(headlines)
    )
    data = gemini.call_json(
        HEADLINES_PROMPT.format(
            company=company or domain, domain=domain, rules=EVIDENCE_RULES, items=items
        )
    )
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(headlines):
            out.append(
                {
                    "index": idx,
                    "category": str(row.get("category", "irrelevant")).lower().strip(),
                    "names_this_company": bool(row.get("names_this_company")),
                }
            )
    return out


# --- (d) agent loop: is more information needed? ----------------------------

GAP_PROMPT = """You are deciding whether one more page fetch would answer a gap.

Unknown so far: {unknowns}

Pages already read: {read}

Pages available but not read yet, on the same site:
{candidates}

{rules}

Pick at most {budget} URLs from the available list that are most likely to state one of
the unknowns. If none of them would help, return an empty list.
Return: {{"need_more": true|false, "urls": ["..."], "why": "one sentence"}}"""


def needs_more_info(unknowns, read_urls, candidates, budget):
    if not unknowns or not candidates or budget <= 0:
        return {"need_more": False, "urls": [], "why": "nothing left to fetch"}
    data = gemini.call_json(
        GAP_PROMPT.format(
            unknowns=", ".join(unknowns),
            read=", ".join(read_urls),
            candidates="\n".join(candidates[:30]),
            rules=EVIDENCE_RULES,
            budget=budget,
        )
    )
    urls = [u for u in (data.get("urls") or []) if u in candidates][:budget]
    return {
        "need_more": bool(data.get("need_more")) and bool(urls),
        "urls": urls,
        "why": data.get("why", ""),
    }


# --- (e) two pain points -----------------------------------------------------

PAINS_PROMPT = """Write exactly two pain points that {name}, {title} at {company},
feels about security compliance (SOC 2, ISO 27001, GDPR) in their own day-to-day work.

What the company does: {what}
Signals we actually found about this company: {signals}

{rules}

Each pain point is one sentence, specific to this person's role, and must not claim any
fact about this company that is not in the signals above.
Return: {{"pains": ["...", "..."]}}"""


def pain_points(person, company, what_it_does, signals):
    data = gemini.call_json(
        PAINS_PROMPT.format(
            name=person["name"],
            title=person["title"],
            company=company,
            what=what_it_does or "unknown",
            signals="; ".join(signals) if signals else "none beyond passing our filters",
            rules=EVIDENCE_RULES,
        ),
        temperature=0.3,
    )
    pains = [str(p).strip() for p in (data.get("pains") or []) if str(p).strip()]
    return pains[:2]


# --- (f) draft the email -----------------------------------------------------

EMAIL_PROMPT = """Write one cold email from a Sprinto sales rep to {name}, {title} at
{company}. Sprinto automates security compliance (SOC 2, ISO 27001, GDPR) for SaaS
companies.

The single hook you may use, which we verified ourselves:
{hook}

The two pain points for this person's role:
1. {pain1}
2. {pain2}

Hard rules:
- About 120 words or fewer in the body. Address them by first name.
- Use the hook once, early, as the reason you are writing. Do not embellish it.
- Do not claim any certification, funding round, hire, customer or incident other than
  the hook above. Do not mention any breach, outage, incident, fine or lawsuit at all.
- Do not say you "noticed" anything that is not stated in the hook.
- One clear ask at the end: a short reply, or 15 minutes. No attachments, no links.
- Plain sentences. No em dashes. No "I hope this finds you well".
- The subject line names something specific to {company}.

Return: {{"subject": "...", "body": "..."}}"""


def draft_email(person, company, hook_text, pains):
    data = gemini.call_json(
        EMAIL_PROMPT.format(
            name=person["name"],
            title=person["title"],
            company=company,
            hook=hook_text,
            pain1=pains[0] if pains else "audit preparation eats engineering time",
            pain2=pains[1] if len(pains) > 1 else "security questionnaires slow deals",
        ),
        temperature=0.4,
    )
    return str(data.get("subject", "")).strip(), str(data.get("body", "")).strip()
