# Sprinto cold outreach pipeline

Paste a list of company domains. For each one the pipeline scrapes the site, extracts
fields with a quote behind every value, applies the hard filters, finds a contact,
writes two pain points and drafts a cold email. A human approves each draft before
anything is sent, and every approved email goes to `TO_EMAIL` and nowhere else.

Built for MESA Term 2, AI Case 2, from `CLAUDE_CODE_BUILD_PROMPT.md` and the three
files in `design-reference/`. Those files are the source of truth for every rule here.

## Run it

```bash
pip install -r requirements-dev.txt
cp .env.example .env        # then fill it in; .env is gitignored
python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000. It asks for `REVIEW_PASSCODE` before showing anything.

Offline checks, which need no key and spend nothing:

```bash
python -m tests.test_offline
```

Leave `DATABASE_URL` empty locally and it uses SQLite in `data/`.

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

## Deploying to Vercel

The app is one Python function. `app/main.py` is one of the entrypoint names Vercel
detects automatically, so there is no wrapper file; `vercel.json` only sets the
duration limit and bundles the templates and `demo_domains.txt`.

**1. Create the database first.** In the Vercel dashboard, Storage → Marketplace →
Neon → create a Postgres database and connect it to the project. Neon gives two
connection strings: use the **pooled** one. A page render opens several short
connections and serverless keeps no pool between invocations, so the direct string
will exhaust connections under any real use.

**2. Create the project** from the GitHub repository. Vercel reads `requirements.txt`
and `vercel.json` on its own.

**3. Set the environment variables** in Project Settings → Environment Variables.
Never in the repository: this repository is public.

| Name | Notes |
|------|-------|
| `GEMINI_API_KEY` | |
| `GEMINI_MODEL` | optional |
| `HUNTER_API_KEY` | |
| `GMAIL_SENDER_ADDRESS` | the throwaway sender |
| `GMAIL_APP_PASSWORD` | 16 characters, no spaces |
| `TO_EMAIL` | the only address this app will send to |
| `DAILY_SEND_CAP` | 15 |
| `REVIEW_PASSCODE` | the app refuses to start in production without it |
| `SESSION_SECRET` | any long random string; signs the review cookie |
| `DATABASE_URL` | Neon's **pooled** connection string |

`maxDuration` in `vercel.json` is 300, and a Hobby deployment accepted it. One
domain is given 240 seconds of that (`DOMAIN_TIME_BUDGET` in `app/config.py`),
leaving a minute of margin. The first deployed run proved 55 seconds was not
enough: the scrape used all of it and the AI call had nothing left.

**4. Deploy a preview, not production**, and run these five checks on the preview URL:

| | Check | How |
|---|---|---|
| a | The page asks for the passcode | open the URL in a private window; it should redirect to `/login` |
| b | One domain runs end to end inside the time limit | add one chip, Run, watch the row reach a verdict |
| c | The Hunter cache survives a cold start | run the same domain twice, minutes apart; the second card is flagged "contact came from the Hunter cache" and your Hunter search count does not move |
| d | An approved send lands in `TO_EMAIL` | approve one draft; the email should carry the `[Demo redirect]` banner naming the contact |
| e | The caps work | approve past the daily cap and confirm the refusal; add a 16th domain to a run and confirm it is refused |

Check (d) is the one most likely to fail: outbound SMTP from serverless is sometimes
blocked. If it does fail, stop rather than switching to the Gmail API.

## Testing

`python -m tests.test_offline` stubs every external call, so it needs no keys and
spends nothing. It covers the filters, ranking, the email code check, the chip
cleaning, the passcode gate and throttle, the `/run-domain` endpoint, the demo
redirect, and the SQL both database engines generate.

The Postgres path has been checked structurally but has never run against a live
server. Set `DATABASE_URL` to a Neon database and run the suite again to close that.
