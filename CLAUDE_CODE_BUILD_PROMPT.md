# Build prompt: Sprinto cold outreach pipeline (MESA Term 2, AI Case 2)

Read this whole file, then read `design-reference/evidence-map.md`, `design-reference/rubric-and-rules.md` and look at `design-reference/components-map-final.png` before writing any code. Those three files are the source of truth for every rule below. Ask before choosing anything not covered here, and do not add features that are not in this file.

## 1. The problem and the success measure
Sprinto sells compliance automation (SOC 2, ISO 27001, GDPR) to SaaS companies. Its Growth Lead spends 15-20 minutes per company researching, finding a contact and writing a cold email, for 8-15 companies a week, and quality drops late in the list. Build a repeatable pipeline: paste a list of domains, and for each one the system scrapes, extracts, qualifies, finds a contact, finds two pain points, and drafts a personalised email. A human approves each draft before it is sent.

Done means: a personalised email lands in the user's inbox, addressed to a real person by name, with a hook a human would answer, and every decision (why this company qualified, why this person, why the email says what it says) can be defended from stored evidence.

## 2. Hard constraints
- Pipeline has these 7 steps: scrape, extract, qualify (with an agent loop that fetches more when data is thin), find the contact, two pain points, draft email, send via Gmail.
- Contact lookup is Hunter.io Domain Search (free tier, 25 searches a month). Cache every result per domain; never search a domain twice.
- AI is Gemini Flash only, for every AI step.
- Send to one hardcoded address from the `TO_EMAIL` env var (the user's own address). Do not write the address into code or this repo.
- A human approves every email before it is sent. There is no automatic sending.
- Secrets only in `.env`. Put `.env` in `.gitignore` before the first commit. Never print keys. Use a dedicated throwaway Gmail account for sending (not the user's main account).
- Admin actions (Run, Approve and send) are protected by a server-side passcode and the daily cap.
- Time budget is short (the exam is 1.5 hours). Prefer the simplest thing that works.

## 3. Stack (confirm before changing)
- Python with FastAPI and one plain HTML page (no frontend framework). Run locally; do not choose a hosting platform without asking.
- SQLite for runs, caches and logs.
- Scraping: plain code (requests plus an HTML-to-text step). No AI at runtime in the scraper.
- AI: Gemini Flash through the Gemini API. Confirm the exact current Flash model name against the user's key in spike test 3.
- Contact: Hunter.io Domain Search API.
- News: Google News RSS search feed (unofficial endpoint; spike test 2 confirms it works).
- Email: Gmail SMTP with an app password from the throwaway sender account.

## 4. Workflow (matches the Components Map, column by column)
- **Trigger:** the Growth Lead pastes domains into a text box on the page and clicks Run (passcode required).
- **Input:** the code cleans the list: strip `https://`, `www.`, paths and spaces, lowercase, remove duplicates.
- **Context:**
  1. Scrape home, pricing, about, careers, trust/security and customers pages per domain (try known paths, fall back to links on the homepage). Plain code, short timeouts, polite delay.
  2. Hunter Domain Search, cache first.
  3. Google News RSS: one query per company (company name plus keywords for funding, compliance and security incident; last 2 years). Code fetches and date-filters it.
- **Processing (code):** apply the hard filters and ranking exactly as in `rubric-and-rules.md`. Code picks the person from Hunter results by title order and applies the daily cap.
- **AI (Gemini Flash):** (a) clean page text into fields where every field carries a quoted sentence; (b) classify vertical from the fixed list (fintech, healthtech, cleantech, none) with a quote; (c) classify each news headline as funding, compliance, negative or irrelevant; (d) say whether more information is needed (loop, max 2 extra fetches); (e) write two pain points for the chosen person's role; (f) draft the email.
- **Output:** a review screen card per company, then Approve, Edit or Reject. Only Approve triggers the Gmail send, and only inside the daily cap. Every decision is logged.

## 5. Judgment calls already made (do not re-decide)
- **AI versus code:** AI only reads messy text, classifies with a quote, and writes. Filters, ranking, date arithmetic, caps, contact choice and sending are plain code.
- **Hard filters (any no = drop):** not SaaS; vertical is none of fintech, healthtech, cleantech; stated employee count outside 10-100; SOC 2 and ISO 27001 both active on the trust page; no usable contact. Unknown on any other row = flag, never drop.
- **ICP wording:** Series A-C SaaS in fintech, healthtech, cleantech; 10-100 employees is the targeting filter inside it.
- **Ranking:** only decides review order. High = 2 or more intent signals, Medium = 1, Low = 0 but passes filters. A "likely already certified" headline counts against it.
- **Google News:** feeds funding (row 3), audit-prep (row 4), certification announced (row 5) and negative news (row 7). A certification headline only flags "likely already certified"; the drop needs the trust page to agree. Negative news is a buying signal only and is never quoted in the email. No result = unknown, flag.
- **Contact choice:** Head of Security / CISO / GRC lead, then CTO / VP Engineering, then Founder / CEO. Use Hunter data only. Never guess an email address.
- **Email:** about 120 words or fewer, addressed by name, one hook citing a signal we actually found, two pain points from the role, one clear ask. A code check confirms every signal named in the email exists in the stored fields; a mismatch is a flag, not a block.
- **Caps:** daily send cap 15 (from `DAILY_SEND_CAP`); one email per company per run; Hunter once per domain; Google News once per company; loop max 2.
- **Dropped:** dashboard mockup was not built. Keep the UI plain and functional.

## 6. What the agent must NOT do
- Send any email without human approval, or to any address other than `TO_EMAIL`.
- Claim a certification, funding round, hire or incident it did not find, or state any fact without a stored source (page URL or headline link).
- Turn "not shown on site" into "not certified", or "no news result" into "no negative news".
- Guess funding stage from headcount, or invent a person, title or email.
- Quote negative news in the email.
- Search the same domain twice on Hunter.
- Print or commit secrets.

## 7. Human in the loop
- The Growth Lead decides: approves, edits or rejects each draft. Rejects log a reason.
- The Growth Lead owns the domain list and the ICP rules. One named person owns the API keys.
- Run and Approve are admin actions behind `REVIEW_PASSCODE` (checked on the server) and the daily cap.
- Autonomy level L3: AI drafts, human approves.

## 8. Data tables (SQLite)
- `runs`: id, started_at, domain_count.
- `companies`: id, run_id, domain, status (dropped, queued, approved, rejected, sent), drop_rule, drop_quote, fields_json (each field with its quote and source URL), signals_json (each signal with its source), tier, flags_json, poc_name, poc_title, poc_email, poc_confidence, pains_json, email_subject, email_body, reviewer_action, reject_reason, created_at, sent_at.
- `hunter_cache`: domain (unique), response_json, fetched_at.
- `news_cache`: company, query, headlines_json, fetched_at.
- `send_log`: id, company_id, sent_at, to_address.

## 9. Dashboard and design reference
No mockup exists. One page with three parts: a text box and Run button; a review list sorted High to Low where each card shows tier, then flags, then the draft, then why the company qualified and why this person, with Approve / Edit / Reject; and a small log of drops with the rule and quote. `design-reference/components-map-final.png` is the workflow reference.

## 10. Operational notes and likely traps
- JavaScript-heavy sites return almost no text to a plain fetch; record "page not readable" as unknown, do not guess.
- Some pages are blocked or slow: use timeouts and move on.
- About pages often give no headcount; unknown = flag.
- Funding stage is often absent from the company's own site.
- Google News RSS is unofficial and may change or throttle; handle failure as unknown. Company names can collide with unrelated news: only accept a headline that clearly names the right company or domain.
- Hunter free tier is 25 searches a month: test on 3-4 domains only.
- Gmail SMTP needs 2-step verification and an app password on the throwaway sender account.
- Keep timezones in UTC in storage, show India time in the UI.

## 11. Environment variables (names only)
`GEMINI_API_KEY`, `HUNTER_API_KEY`, `GMAIL_SENDER_ADDRESS`, `GMAIL_APP_PASSWORD`, `TO_EMAIL`, `DAILY_SEND_CAP`, `REVIEW_PASSCODE`

## 12. Build order (stop and report after each spike before any app code)
1. **Spike 1, Hunter:** one Domain Search on one known domain. Report whether it returns a usable named person with a title and email. Cache the result.
2. **Spike 2, Google News RSS:** one query for a known SaaS company. Report whether it returns dated headlines and the right company.
3. **Spike 3, Gemini Flash:** give it one scraped page and get back JSON fields with quoted evidence and the vertical classification. Report the model name used and whether the quotes are real.
4. **Spike 4, Scraper:** run the scraper on 3 domains. Report which pages were readable.
5. **Spike 5, Gmail:** send one test email to `TO_EMAIL`. Report delivery.
Then build: cleaning and hard filters; the pipeline per domain; ranking and contact choice; the code check on the email; the review page with approve, edit, reject and the passcode; sending within the cap; logs. Test end to end with 3 domains.

## 13. Definition of done
- Pasting a list of domains runs the full pipeline without further decisions until the review screen.
- A real personalised email, addressed to a named person with a hook from a found signal, is approved and lands in the inbox at `TO_EMAIL`.
- Every card shows why the company qualified, why this person, and any flags; drops are logged with rule and quote.
- Caps and passcode work; no secrets in the repo; `.env` is ignored.
- Repo has a clean README that says how to run it.
