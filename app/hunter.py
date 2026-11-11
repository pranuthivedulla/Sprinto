"""Hunter.io Domain Search. One search per domain, ever - the cache is checked first."""
import requests

from . import config, db

API_URL = "https://api.hunter.io/v2/domain-search"
TIMEOUT = 15

# Title order from rubric-and-rules.md section 4. Code picks the person, not the AI.
TITLE_TIERS = [
    (
        "security_or_grc",
        ["chief information security", "ciso", "head of security", "security lead",
         "vp security", "director of security", "head of grc", "grc", "governance risk",
         "compliance lead", "head of compliance", "director of compliance",
         "information security", "infosec", "head of trust", "security manager"],
    ),
    (
        "engineering",
        ["chief technology", "cto", "vp engineering", "vp of engineering",
         "head of engineering", "director of engineering", "engineering manager",
         "head of platform", "head of infrastructure"],
    ),
    (
        "founder_or_ceo",
        ["founder", "co-founder", "cofounder", "chief executive", "ceo",
         "managing director"],
    ),
]


def search(domain, force=False):
    """Return (data, source) where source is 'cache' or 'api'.

    Raises RuntimeError if the key is missing or the call fails.
    """
    cached, _ = db.hunter_cached(domain)
    if cached is not None and not force:
        return cached, "cache"

    key = config.get("HUNTER_API_KEY")
    if not key:
        raise RuntimeError("HUNTER_API_KEY is not set")
    resp = requests.get(
        API_URL,
        # No limit parameter: the free plan caps results at 10 and rejects any
        # explicit limit with a 400. Ten is plenty to pick one person by title.
        params={"domain": domain, "api_key": key},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        # Hunter says what is wrong in the body. Carry it through: a bare status
        # code sent us looking at the key when the problem was a parameter.
        detail = ""
        try:
            detail = resp.json()["errors"][0].get("details", "")
        except Exception:
            pass
        raise RuntimeError(
            f"Hunter HTTP {resp.status_code}: {detail}" if detail
            else f"Hunter HTTP {resp.status_code}"
        )
    data = resp.json()
    db.hunter_store(domain, data)
    db.log("hunter_search", f"domain={domain}", None, None)
    return data, "api"


def people(data):
    """Flatten a Hunter response into people who have a name, a title and an email."""
    out = []
    for email in (data or {}).get("data", {}).get("emails", []) or []:
        first = (email.get("first_name") or "").strip()
        last = (email.get("last_name") or "").strip()
        name = " ".join(p for p in (first, last) if p)
        title = (email.get("position") or "").strip()
        address = (email.get("value") or "").strip()
        if not (name and title and address):
            continue
        out.append(
            {
                "name": name,
                "title": title,
                "email": address,
                "confidence": email.get("confidence"),
                "source": "hunter.io domain-search",
            }
        )
    return out


def choose(data):
    """Pick one person by title order. Returns (person|None, reason)."""
    candidates = people(data)
    if not candidates:
        return None, "Hunter returned no record with a name, a title and an email."
    for tier_name, keywords in TITLE_TIERS:
        for person in candidates:
            lowered = person["title"].lower()
            if any(k in lowered for k in keywords):
                person["title_tier"] = tier_name
                return person, (
                    f"Title order: {tier_name.replace('_', ' ')} is the highest tier "
                    f"present in Hunter's records for this domain "
                    f"(\"{person['title']}\")."
                )
    person = candidates[0]
    person["title_tier"] = "other"
    return person, (
        "No security, engineering or founder title in Hunter's records; used the first "
        f"complete record (\"{person['title']}\")."
    )
