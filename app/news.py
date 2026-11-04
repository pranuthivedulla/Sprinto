"""Google News RSS. Plain code fetches and date-filters; Gemini Flash only classifies."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from . import db

FEED = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
TIMEOUT = 12
LOOKBACK_DAYS = 730          # "last 2 years" for the single query
NEGATIVE_WINDOW_DAYS = 365   # row 7 counts only within 12 months
KEYWORDS = "funding OR raises OR \"Series A\" OR \"Series B\" OR SOC 2 OR ISO 27001 OR compliance OR security breach"


def build_query(company_name, domain):
    name = company_name or domain.split(".")[0]
    return f'"{name}" ({KEYWORDS})'


def fetch(company_name, domain, force=False):
    """Return (headlines, source). Never raises on a feed problem: returns []."""
    query = build_query(company_name, domain)
    key = company_name or domain
    cached = db.news_cached(key, query)
    if cached is not None and not force:
        return cached, "cache"
    try:
        resp = requests.get(FEED.format(query=quote_plus(query)), timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        db.log("news_failed", f"{key}: {type(exc).__name__}")
        return [], "failed"

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        when = None
        if pub:
            try:
                when = parsedate_to_datetime(pub)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except Exception:
                when = None
        if when is None or when < cutoff:
            continue
        source = item.findtext("{http://news.google.com/rss}source") or ""
        items.append(
            {
                "title": title,
                "link": link,
                "published": when.astimezone(timezone.utc).strftime("%Y-%m-%d"),
                "source": source.strip(),
            }
        )
        if len(items) >= 20:
            break
    db.news_store(key, query, items)
    return items, "api"


def names_company(title, company_name, domain):
    """A headline counts only if it clearly names the right company."""
    blob = (title or "").lower()
    stem = domain.split(".")[0].lower()
    if stem and len(stem) > 3 and stem in re.sub(r"[^a-z0-9]+", "", blob):
        return True
    if company_name:
        name = company_name.lower().strip()
        if len(name) > 2 and name in blob:
            return True
    return False


def within_days(published, days):
    try:
        when = datetime.strptime(published, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return when >= datetime.now(timezone.utc) - timedelta(days=days)
