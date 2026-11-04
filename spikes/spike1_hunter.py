"""Spike 1: one Hunter Domain Search on one domain.

Reports whether it returns a usable named person with a title and an email.
The result is cached, so re-running this spike on the same domain costs nothing.

    python -m spikes.spike1_hunter stripe.com
"""
import sys

from app import db, hunter


def main(domain):
    db.init()
    cached, when = db.hunter_cached(domain)
    if cached is not None:
        print(f"Already cached from {when} UTC - no credit spent.")
    data, source = hunter.search(domain)
    found = hunter.people(data)
    person, reason = hunter.choose(data)

    print(f"domain: {domain}")
    print(f"source: {source}")
    print(f"records with name + title + email: {len(found)}")
    for p in found[:8]:
        print(f"  - {p['name']} | {p['title']} | {p['email']} | confidence {p['confidence']}")
    print()
    if person:
        print(f"VERDICT: usable contact. {person['name']} ({person['title']})")
        print(f"reason: {reason}")
    else:
        print(f"VERDICT: no usable contact. {reason}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m spikes.spike1_hunter <domain>")
    main(sys.argv[1].strip().lower())
