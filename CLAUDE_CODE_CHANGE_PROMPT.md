# Change prompt: Sprinto cold outreach app, before it goes to Vercel

This is a change request on top of the app that already exists in this repo. Read these first, in order: `CLAUDE_CODE_BUILD_PROMPT.md` (original build), `design-reference/evidence-map.md`, `design-reference/rubric-and-rules.md`, `design-reference/nine-checks.md` (13+ decisions, newest at the bottom), and look at `design-reference/components-map-final.png` (the v8 map: five lanes, Actor column). Those files are the source of truth. Make the changes below, keep diffs small, keep every existing rule, and ask before choosing anything not covered here. Do not add features that are not in this file. Do not push, do not deploy to production, and do not commit anything under `.env`, `data/` or `*.db`.

## 1. What has changed since the original build
- The map now has five lanes: Growth Lead, System, Hunter.io / Apollo, AI (Gemini Flash), Gmail. Hunter.io / Apollo is used only to find the contact. The company website and Google News (read inside the System lane) supply the startup information: what the company does, size, funding, compliance and negative news. The app already works this way; change nothing in the pipeline logic.
- The draft shows the scraped contact. Already done in the app: when Hunter returned a person, the review card shows "Addressed to: name, title, email" and the demo email carries a "[Demo redirect]" banner plus an `X-Intended-Recipient` header. Delivery is always `TO_EMAIL`, never the contact. No contact = no draft (the company is dropped). Keep this exactly; only add the tests listed in section 2D.
- The input should be more interactive than a plain text box (section 2A).
- The app will be deployed to Vercel, which breaks two things as built (section 2C).

## 2. Changes to make

### 2A. Interactive domain input (replaces the textarea)
Build a chip input in plain HTML and JavaScript, no framework.
- Paste, type, or drop text containing many domains; split on newlines, commas, spaces and semicolons; each becomes a chip.
- Each chip is cleaned live to match `app/clean.py` (strip `https://`, `www.`, paths, ports, spaces; lowercase). `https://www.x.com/pricing` becomes `x.com`. The server stays the source of truth and re-cleans everything; the client cleaning is only for display.
- Duplicates merge into one chip. An entry that is not a plausible domain turns red with a short reason and is excluded from the run. Every chip has a remove button; a "Clear all" button resets.
- Show a live count ("6 domains ready, 1 invalid") and a maximum of 15 domains per run (matches the daily cap). The Run button is disabled until there is at least 1 valid domain and the passcode is filled.
- "Load demo list" button: reads `demo_domains.txt` at the repo root (one domain per line, committed to git, filled in by the user). If the file is missing or empty, hide the button. Do not invent company names.
- Keyboard and accessibility: Enter or comma creates a chip, Backspace removes the last chip when the input is empty, chips have labels for screen readers.

### 2B. Per-domain progress
Replace the "Running: x of y" text with one row per domain: waiting, working, queued for review (with tier), or dropped (with the rule). Rows update as each domain finishes (see 2C-1).

### 2C. Make it work on Vercel
Facts to verify against the current Vercel docs before relying on them: functions have a maximum duration (Hobby 300 s at the time of writing), the filesystem is ephemeral and effectively read-only except `/tmp`, work after a response is not guaranteed to finish, request and response bodies are limited to 4.5 MB. The Python runtime serves a FastAPI `app`; follow the current Vercel Python docs for the entrypoint and `vercel.json`.

1. **No background thread.** The pipeline currently runs in a background job and the page polls `/job`. That will not survive serverless. Add `POST /run-domain` (passcode required) that processes exactly one domain end to end (scrape, extract, filters, Hunter, news, pain points, draft, code check) and returns its result. The page calls it for each chip one at a time, in order, and shows progress (2B). Remove the job thread and `/job` polling. Set the function `maxDuration` to the plan maximum and aim for well under 60 s per domain. Every network call needs a timeout; the agent loop stays at max 2 extra fetches. If a call times out, record the domain as "unknown, flagged" or "failed, retry", never as passed.
2. **Durable storage.** A SQLite file will not persist on Vercel. Add Postgres support behind the existing `app/db.py` functions, selected by `DATABASE_URL`; when it is unset, keep SQLite for local runs and tests. Recommended: Neon Postgres through the Vercel Marketplace. Keep the same tables and columns from the build prompt (section 8). The Hunter cache must live in this durable database, otherwise every cold start can spend another of the 25 monthly searches. Stop and report before choosing a different database.
3. **The page is now public, so protect the review page itself.** It shows scraped contact names, titles and emails. Require the passcode to view `/` (a signed, HttpOnly, SameSite cookie after a correct passcode; no passcode in URLs). Keep the passcode check on Run, Save, Approve and Reject. Add a simple throttle on wrong attempts (for example 5 failures per 10 minutes per IP, stored in the database). Refuse to start in production if `REVIEW_PASSCODE` is unset. Send `X-Robots-Tag: noindex`.
4. **Secrets.** Only Vercel environment variables in production, never in the repo. Never log keys, the passcode, or full email bodies.
5. **Entrypoint and config.** Add `vercel.json` and whatever the Python runtime needs so the app, `app/templates` and `demo_domains.txt` are bundled. Update `requirements.txt` (for example a Postgres driver). Keep local `uvicorn` running as it does today.
6. **Gmail SMTP from Vercel.** Outbound SMTP may be blocked or unreliable from serverless. Do not switch to the Gmail API silently. Test a real approved send from a preview deployment and report the result; if SMTP fails, stop and ask.
7. **Time.** Store UTC, show India time in the UI (already the rule).

### 2D. Tests to add (keep all existing tests passing)
- The review card shows "Addressed to: name, title, email" when a contact exists, and shows nothing when none was found.
- The sent message always has `To` equal to `TO_EMAIL`, carries the "[Demo redirect]" banner and the `X-Intended-Recipient` header when a contact exists, and has neither when none exists. The stored draft body stays free of the banner.
- Client-side cleaning examples (as test vectors for the server cleaner): full URLs, `www.`, trailing paths, uppercase, ports, duplicates, junk.
- `/run-domain` returns a result for one domain and writes it to the database; a wrong passcode is refused; the 16th domain in a run is refused.
- The view page redirects to the passcode screen without the cookie.
Offline tests must still run with no keys: `python -m tests.test_offline`.

## 3. Do not change (already decided)
- Hard filters, ranking tiers, the 10-100 employee range, the three verticals, the "unknown = flag, never drop" rule, the certification rule (the trust page must agree before a drop; a Google News headline only flags), title order for the contact, and the email rules.
- Gemini Flash is the only AI. Code, not the AI, filters, ranks, picks the person and sends.
- A human approves every email. Delivery is only to `TO_EMAIL`. Daily cap 15. Hunter once per domain, cached. Google News once per company; no result means unknown and flagged.
- What the agent never does: send without approval, state a fact it did not find, quote negative news, search the same domain twice on Hunter, turn "not shown" into "not certified".

## 4. Environment variables (names only)
`GEMINI_API_KEY`, `GEMINI_MODEL`, `HUNTER_API_KEY`, `GMAIL_SENDER_ADDRESS`, `GMAIL_APP_PASSWORD`, `TO_EMAIL`, `DAILY_SEND_CAP`, `REVIEW_PASSCODE`, `DATABASE_URL` (new), `SESSION_SECRET` (new, signs the cookie). Update `.env.example` with the two new names only.

## 5. Order of work (stop and report at each STOP)
1. Baseline: run `python -m tests.test_offline`, then list any place where the code differs from `rubric-and-rules.md` or `evidence-map.md`. Report only; fix nothing. STOP.
2. 2A and 2B locally with the new `/run-domain` flow (2C-1). Show a screenshot or description of the page. STOP.
3. 2C-2 database layer with SQLite fallback; run the full tests on both. STOP.
4. 2C-3 passcode gate and throttle.
5. 2D tests. All green.
6. 2C-5 `vercel.json`, README deploy steps (project creation, Neon database, environment variables, passcode, how to run the five checks below). STOP. The user creates the Vercel project and sets the variables; do not deploy to production.
7. After a preview deployment exists: run these checks and report each: (a) the page asks for the passcode; (b) one domain runs end to end under the time limit; (c) the Hunter cache row survives a second request and a cold start; (d) one approved send lands in `TO_EMAIL` with the banner (2C-6); (e) the daily cap and the 16th-domain refusal work.

## 6. Definition of done
- Chip input works locally and on the preview deployment; invalid and duplicate entries are handled.
- A full run of 3 domains on the preview deployment finishes with per-domain progress and review cards for those that qualify.
- Nothing persists in the local filesystem in production; the Hunter cache and send log survive redeploys.
- The review page is not viewable without the passcode; wrong attempts are throttled.
- Approved email arrives at `TO_EMAIL` only, with the contact named in it.
- All offline tests pass; README explains local and Vercel setup; no secrets in the repo.

Ask before choosing anything not covered here, and do not add features that are not in this file.
