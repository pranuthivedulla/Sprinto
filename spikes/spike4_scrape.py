"""Spike 4: run the scraper on a few domains and report which pages were readable.

No AI and no paid API here, so this one is free to re-run.

    python -m spikes.spike4_scrape vanta.com drata.com razorpay.com
"""
import sys

from app import scrape


def main(domains):
    for domain in domains:
        print(f"\n=== {domain} ===")
        scraped = scrape.scrape_company(domain)
        for kind, page in scraped["pages"].items():
            status = page.get("status")
            note = page.get("note", "")
            chars = len(page.get("text", ""))
            print(f"  {kind:<10} {status:<13} {chars:>5} chars  {page.get('url','')}"
                  f"{'  ' + note if note else ''}")
        ok = sum(1 for p in scraped["pages"].values() if p.get("status") == "ok")
        print(f"  readable pages: {ok} of {len(scraped['pages'])}")
        print(f"  extra URLs available to the agent loop: {len(scraped['unfetched'])}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m spikes.spike4_scrape <domain> [domain ...]")
    main([a.strip().lower() for a in sys.argv[1:]])
