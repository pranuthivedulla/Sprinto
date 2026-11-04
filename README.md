# Sprinto cold outreach pipeline

Paste a list of company domains. For each one the pipeline scrapes the site, extracts
fields with a quote behind every value, applies the hard filters, finds a contact,
writes two pain points and drafts a cold email. A human approves each draft before
anything is sent, and every approved email goes to `TO_EMAIL` and nowhere else.

Built for MESA Term 2, AI Case 2, from `CLAUDE_CODE_BUILD_PROMPT.md` and the three
files in `design-reference/`. Those files are the source of truth for every rule here.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill it in; .env is gitignored
python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000.

Offline checks, which need no key and spend nothing:

```bash
python -m tests.test_offline
```

## The seven steps

| # | Step | Who does it |
|---|------|-------------|
| 1 | Scrape home, pricing, about, careers, trust, customers | plain code (`app/scrape.py`) |
| 2 | Extract fields, each with a quoted sentence and a source URL | Gemini Flash (`app/ai.py`) |
| 3 | Qualify: hard filters, ranking, agent loop (max 2 extra fetches) | code filters, Flash classifies (`app/qualify.py`) |
| 4 | Find the contact | Hunter.io, cached; code picks the person (`app/hunter.py`) |
| 5 | Two pain points for that person's role | Gemini Flash |
| 6 | Draft the email, then check every claim against stored signals | Flash writes, code checks |
| 7 | Send via Gmail | code, only after a human approval, only within the cap |

Gemini Flash is the only AI anywhere in this repo at runtime. It reads messy text,
classifies from a fixed list with a quote, and writes. It never filters, ranks, does
date arithmetic, picks a person, or sends.

## The rules the code enforces

Hard filters (any one drops the company, and the drop is logged with the rule and the
quote that triggered it):

1. Not SaaS, or nothing readable says it is one
2. Vertical is not fintech, healthtech or cleantech
3. A *stated* employee count outside 10-100
4. SOC 2 **and** ISO 27001 both shown active on the trust page
5. No usable contact from Hunter

Unknown on any other row flags the company; it never drops it. A drop needs a quote
that was actually found in the scraped text: the code re-checks every quote the model
returns, and an unverified quote is treated as unknown.

Ranking only decides review order. High is 2 or more intent signals, Medium is 1,
Low is 0 but passing the filters. A "likely already certified" headline counts against.

Negative news is a buying signal for the reviewer only. It raises the tier, it is never
the hook, and the code check flags any draft that mentions a breach, outage, incident,
fine or lawsuit.

## What it never does

- Send without a human approval, or to any address other than `TO_EMAIL`
- Claim a certification, round, hire or incident it did not find
- Turn "not shown on the site" into "not certified", or "no news result" into "no news"
- Guess funding stage from headcount, or invent a person, title or email
- Search the same domain on Hunter twice (every response is cached in SQLite)
- Print or commit a secret

## Environment

Copy `.env.example` to `.env`. `.env` is in `.gitignore`.

| Name | What it is |
|------|------------|
| `GEMINI_API_KEY` | Gemini key |
| `GEMINI_MODEL` | optional; confirm the Flash model name in spike 3 |
| `HUNTER_API_KEY` | Hunter.io key (free tier: 25 searches a month) |
| `GMAIL_SENDER_ADDRESS` | a throwaway Gmail account, not your main one |
| `GMAIL_APP_PASSWORD` | app password from that account (needs 2-step verification) |
| `TO_EMAIL` | your own inbox: the only address this app will ever send to |
| `DAILY_SEND_CAP` | default 15 |
| `REVIEW_PASSCODE` | checked on the server for Run, Approve, Save and Reject |

## Spikes

Run these before the first full run. Each prints a verdict.

```bash
python -m spikes.spike4_scrape vanta.com drata.com        # free, no key
python -m spikes.spike2_news "Vanta" vanta.com            # free, no key
python -m spikes.spike3_gemini vanta.com                  # Gemini key
python -m spikes.spike1_hunter vanta.com                  # spends 1 of 25 Hunter searches
python -m spikes.spike5_gmail                             # sends one real test email
```

Spike 1 caches its result, so re-running it on the same domain spends nothing.
Test on 3-4 domains only and keep the rest of the month's 25 searches for the demo.

## Storage

SQLite at `data/sprinto.db` (gitignored): `runs`, `companies`, `hunter_cache`,
`news_cache`, `send_log` and a `decision_log` of every queue, edit, reject and send.
Times are stored in UTC and shown in India time.

## Traps worth knowing

- JavaScript-heavy sites return almost nothing to a plain fetch. That is recorded as
  "page not readable" and the company drops on filter 1 rather than being guessed at.
- Google News RSS is unofficial. A failure is recorded as unknown, never as "no news".
- About pages usually do not state a headcount. Unknown flags; it does not drop.
