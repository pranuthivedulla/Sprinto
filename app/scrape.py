"""Plain-code scraper. No AI here: fetch pages, turn HTML into text, collect links.

Anything we cannot read is recorded as "page not readable" - never guessed at.
"""
import re
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (compatible; SprintoOutreachBot/1.0; MESA coursework; "
    "contact via sender address)"
)
TIMEOUT = 8
POLITE_DELAY = 0.7
MIN_READABLE_CHARS = 200
MAX_TEXT_CHARS = 6000

# Known paths tried per page kind, in order. First readable one wins.
PAGE_PATHS = {
    "home": ["/"],
    "pricing": ["/pricing", "/plans", "/pricing/"],
    "about": ["/about", "/about-us", "/company", "/about/"],
    "careers": ["/careers", "/jobs", "/careers/", "/company/careers"],
    "trust": ["/trust", "/security", "/trust-center", "/compliance", "/security/"],
    "customers": ["/customers", "/case-studies", "/clients", "/customers/"],
}

LINK_HINTS = {
    "pricing": ["pricing", "plans"],
    "about": ["about", "company", "team"],
    "careers": ["career", "jobs", "hiring", "join us"],
    "trust": ["trust", "security", "compliance", "soc 2", "iso 27001"],
    "customers": ["customer", "case stud", "clients"],
}

# A site may redirect /trust to a campaign landing page. The page we end up on has to
# still look like the kind we asked for, or we did not find that page at all.
URL_HINTS = {
    "pricing": ["pricing", "plans", "price"],
    "about": ["about", "company", "team", "who-we-are"],
    "careers": ["career", "jobs", "hiring", "join"],
    "trust": ["trust", "security", "compliance", "privacy", "soc-2", "soc2",
              "iso-27001", "iso27001", "certification"],
    "customers": ["customer", "case-stud", "case_stud", "casestud", "clients",
                  "stories", "testimonial"],
}


def url_matches_kind(url, kind):
    """True when the URL we landed on still looks like the page kind we asked for."""
    if kind == "home":
        return True
    path = urlparse(url or "").path.lower()
    if path in ("", "/"):
        return False  # redirected to the homepage: that page does not exist
    return any(hint in path for hint in URL_HINTS.get(kind, []))


class _Extractor(HTMLParser):
    """Collect visible text and anchors. Stdlib only - no bs4 dependency."""

    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []  # (href, anchor text)
        self._skip_depth = 0
        self._href = None
        self._anchor = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []
        elif tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "a":
            if self._href:
                self.links.append((self._href, " ".join(self._anchor).strip()))
            self._href, self._anchor = None, []

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        self.parts.append(text + " ")
        if self._href is not None:
            self._anchor.append(text)


def html_to_text(html):
    parser = _Extractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = unescape("".join(parser.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip(), parser.links


def fetch(url):
    """Return a page dict. status is 'ok', 'not_readable' or 'error'."""
    page = {"url": url, "status": "error", "text": "", "links": [], "note": ""}
    try:
        resp = requests.get(
            url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True
        )
    except requests.RequestException as exc:
        page["note"] = f"{type(exc).__name__}"
        return page
    page["url"] = resp.url
    page["http_status"] = resp.status_code
    if resp.status_code >= 400:
        page["note"] = f"HTTP {resp.status_code}"
        return page
    if "html" not in resp.headers.get("Content-Type", "").lower():
        page["note"] = "not an HTML page"
        return page
    text, links = html_to_text(resp.text)
    page["links"] = links
    if len(text) < MIN_READABLE_CHARS:
        page["status"] = "not_readable"
        page["note"] = "page not readable (likely JavaScript-rendered)"
        page["text"] = text[:MAX_TEXT_CHARS]
        return page
    page["status"] = "ok"
    page["text"] = text[:MAX_TEXT_CHARS]
    return page


def _accept(candidate, kind):
    """A candidate counts only if it is readable AND still the kind we asked for.

    A redirect to a campaign landing page or the homepage is recorded as a redirect,
    not as that page's content.
    """
    if candidate.get("status") != "ok":
        return False
    if url_matches_kind(candidate.get("url"), kind):
        return True
    candidate["status"] = "redirected"
    candidate["note"] = f"redirected away from the {kind} page to {candidate.get('url')}"
    candidate["text"] = ""
    return False


def _links_for(kind, base, links):
    """Find candidate URLs on the homepage for a page kind we could not guess."""
    hints = LINK_HINTS.get(kind, [])
    found = []
    for href, anchor in links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        blob = f"{href} {anchor}".lower()
        if any(h in blob for h in hints):
            url = urljoin(base, href)
            if urlparse(url).netloc.endswith(urlparse(base).netloc) and url not in found:
                found.append(url)
    return found[:2]


def scrape_company(domain, kinds=None):
    """Scrape the six page kinds for a domain.

    Returns {"pages": {kind: page}, "unfetched": [urls]} where unfetched is the
    pool the agent loop may draw two extra fetches from.
    """
    kinds = kinds or list(PAGE_PATHS)
    base = f"https://{domain}"
    pages, unfetched = {}, []

    home = fetch(base + "/")
    if home["status"] == "error":
        home = fetch(f"http://{domain}/")
    pages["home"] = home
    home_links = home.get("links", [])

    for kind in kinds:
        if kind == "home":
            continue
        page = None
        for path in PAGE_PATHS[kind]:
            time.sleep(POLITE_DELAY)
            candidate = fetch(urljoin(base, path))
            if _accept(candidate, kind):
                page = candidate
                break
            page = page or candidate
        if page is None or page["status"] != "ok":
            for url in _links_for(kind, home["url"] or base, home_links):
                time.sleep(POLITE_DELAY)
                candidate = fetch(url)
                if _accept(candidate, kind):
                    page = candidate
                    break
        pages[kind] = page or {
            "url": urljoin(base, PAGE_PATHS[kind][0]),
            "status": "error",
            "text": "",
            "links": [],
            "note": "no readable page found",
        }

    # Pool of extra URLs the loop can ask for: homepage links we have not fetched.
    fetched_urls = {p.get("url") for p in pages.values() if p}
    for href, anchor in home_links[:120]:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(home["url"] or base, href)
        if urlparse(url).netloc.endswith(domain) and url not in fetched_urls:
            if url not in unfetched:
                unfetched.append(url)
    return {"pages": pages, "unfetched": unfetched[:40]}


def pages_blob(pages, limit=5000):
    """Readable page text, labelled by kind and URL, for the extraction prompt."""
    chunks = []
    for kind, page in pages.items():
        if not page or page.get("status") != "ok":
            continue
        chunks.append(f"### {kind.upper()} PAGE ({page['url']})\n{page['text'][:limit]}")
    return "\n\n".join(chunks)


def all_text(pages):
    return "\n".join(p.get("text", "") for p in pages.values() if p)
