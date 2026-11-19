"""Input cleaning: a pasted blob of domains in, a deduplicated domain list out."""
import re

_SPLIT = re.compile(r"[\s,;]+")

# A name has to be one a resolver could answer: 253 characters at the outside,
# 63 per label, no label opening or closing on a hyphen. Without this, 5,000
# letters and a dot read as a domain and cost a Hunter search to find out.
MAX_DOMAIN = 253
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{2,59}")


def _punycode(name):
    """A domain written in its own script is a real domain; make it ASCII."""
    try:
        return name.encode("idna").decode("ascii")
    except Exception:
        return ""


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
    if not d or "." not in d or " " in d:
        return ""
    if not d.isascii():
        d = _punycode(d)
        if not d:
            return ""
    if len(d) > MAX_DOMAIN:
        return ""
    labels = d.split(".")
    if len(labels) < 2 or not all(_LABEL.fullmatch(p) for p in labels):
        return ""
    if not _TLD.fullmatch(labels[-1]):
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
