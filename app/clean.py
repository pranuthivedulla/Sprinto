"""Input cleaning: a pasted blob of domains in, a deduplicated domain list out."""
import re

_SPLIT = re.compile(r"[\s,;]+")


def clean_domain(raw):
    """Strip scheme, www, path, query, port, spaces; lowercase. Returns '' if unusable."""
    d = (raw or "").strip().strip("<>\"'").lower()
    if not d:
        return ""
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = d.split("@")[-1]          # someone pastes an email address
    d = d.split(":")[0]           # port
    if d.startswith("www."):
        d = d[4:]
    d = d.strip(".")
    if "." not in d or " " in d:
        return ""
    if not re.fullmatch(r"[a-z0-9.-]+", d):
        return ""
    return d


def clean_list(blob):
    """Split a pasted blob into cleaned, deduplicated domains, order preserved."""
    out, seen = [], set()
    for token in _SPLIT.split(blob or ""):
        d = clean_domain(token)
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out
