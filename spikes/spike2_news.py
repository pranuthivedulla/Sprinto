"""Spike 2: one Google News RSS query for a known SaaS company.

Reports whether the feed returns dated headlines, and whether they name the right
company. No AI is involved here: this is the plain-code fetch and date filter.

    python -m spikes.spike2_news "Razorpay" razorpay.com
"""
import sys

from app import db, news


def main(company, domain):
    db.init()
    print(f"query: {news.build_query(company, domain)}")
    headlines, source = news.fetch(company, domain, force=True)
    print(f"source: {source}")
    print(f"dated headlines inside the {news.LOOKBACK_DAYS}-day window: {len(headlines)}")
    named = 0
    for h in headlines[:12]:
        hit = news.names_company(h["title"], company, domain)
        named += 1 if hit else 0
        print(f"  [{h['published']}] {'NAMES IT' if hit else 'other   '} | {h['title']}")
    print()
    if not headlines:
        print("VERDICT: no result. Treated as unknown, never as 'no news'.")
    else:
        print(f"VERDICT: feed works. {named} of {len(headlines[:12])} shown headlines "
              f"clearly name this company.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit('usage: python -m spikes.spike2_news "<Company Name>" <domain>')
    main(sys.argv[1], sys.argv[2].strip().lower())
