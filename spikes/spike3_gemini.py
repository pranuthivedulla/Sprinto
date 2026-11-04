"""Spike 3: give Gemini Flash one scraped page and check the JSON it returns.

Reports the model name and endpoint actually used, and - the point of the spike -
whether each quote it returned really appears in the scraped text.

    python -m spikes.spike3_gemini vanta.com
"""
import json
import sys

from app import ai, gemini, scrape


def main(domain):
    scraped = scrape.scrape_company(domain, kinds=["home", "about", "pricing"])
    blob = scrape.pages_blob(scraped["pages"])
    haystack = scrape.all_text(scraped["pages"])
    if not blob.strip():
        print(f"VERDICT: nothing readable on {domain}; cannot test extraction here.")
        return

    print(f"model: {gemini.model_name()}")
    fields = ai.verify_fields(ai.extract_fields(blob), haystack)
    vertical = ai.classify_vertical(blob)
    vertical["verified"] = ai.quote_is_real(vertical.get("quote"), haystack)
    print(f"endpoint that answered: {gemini.LAST_ENDPOINT}")
    print()
    print(json.dumps({"fields": fields, "vertical": vertical}, indent=2)[:4000])
    print()

    checked = [(k, v) for k, v in fields.items()
               if isinstance(v, dict) and v.get("quote")]
    real = sum(1 for _, v in checked if v.get("verified"))
    print(f"VERDICT: {real} of {len(checked)} field quotes were found verbatim in the "
          f"scraped text. Vertical: {vertical['value']} "
          f"(quote real: {vertical['verified']}).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m spikes.spike3_gemini <domain>")
    main(sys.argv[1].strip().lower())
