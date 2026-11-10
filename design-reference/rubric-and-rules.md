# Sprinto Cold Outreach - Rubric and Rules
Built from nine-checks.md and evidence-map.md. Rule of thumb: AI only reads messy text, classifies it with a quote, and writes. Plain code does filters, ranking, dates, caps and sending.

## 1. Who does what
| Step | Code | Gemini Flash |
|---|---|---|
| Input | Clean pasted list: strip https://, www, paths, spaces, duplicates | - |
| 1 Scrape | Fetch home, pricing, about, careers, trust, customers pages | - |
| 2 Extract | Store raw text | Clean text into fields; each field carries a quoted sentence |
| 3 Qualify | Apply hard filters, date filters, priority | Classify vertical (fixed list), classify headlines, say whether more info is needed (max 2 rounds) |
| 4 PoC | Hunter lookup (cached), rank people by title, pick one | - |
| 5 Pain points | - | Two pain points for that person's role |
| 6 Draft | Check the email cites only stored signals | Write the email |
| 7 Send | Send via Gmail only after human approval, within the daily cap | - |

## 2. Hard filters (any "no" = drop; code applies them)
1. Not SaaS (row 1)
2. Vertical is none of fintech, healthtech, cleantech (row 1b)
3. Stated employee count outside 10-100 (row 2)
4. SOC 2 and ISO 27001 both active on the trust page (row 5)
5. No usable contact found by Hunter (row: PoC)
Unknown on rows 1b, 2, 3, 4, 6, 7 = flag, never drop.

## 2b. Dropped but logged
Every drop stores the company, the rule and the quote that triggered it.

## 3. Ranking (only decides review order; never drops)
| Signal | Where it comes from |
|---|---|
| Compliance job posting | Careers page (row 4) |
| Audit-prep headline | Google News (row 4) |
| Enterprise-pressure sign (logos, Enterprise plan, questionnaire mention) | Customers/pricing page (row 6) |
| Named round (Seed to Series B) | Blog or Google News (row 3) |
| Negative news, last 12 months (buying signal only) | Google News (row 7) |
| Minus: "likely already certified" headline | Google News (row 5) |
Tiers: High = 2 or more intent signals; Medium = 1; Low = 0 but passes all filters (always flagged). Review screen sorts High to Low.

## 4. Choosing the person (code, not AI)
Rank Hunter results by title: Head of Security / CISO / GRC lead > CTO / VP Engineering > Founder / CEO. At 10-100 employees a security title is often absent, so the fallback is normal. Use the first person with a name, title and email. Never guess an email address.

## 5. Caps
- Daily send cap: 15 (matches 8-15 companies a week); enforced in code on the send step
- Hunter: one search per domain, cached; 3-4 domains for testing, keep the rest of the 25 a month for the demo
- Google News: one query per company
- Agent loop: max 2 extra fetches per company
- One email per company per run

## 6. What the AI must never infer or guess
- Unknown stays unknown; no value is filled from "typical" companies
- "Not shown on site" is not "not certified"
- A news query with no result is not "no negative news"
- Funding stage is never guessed from headcount
- No names, titles or emails that did not come from Hunter
- No fact in the email without a stored source (page URL or headline link)

## 7. Email rules
- Addressed to the person by name; subject line is specific to the company
- When a contact was found, the review card shows who the draft is addressed to (name, title, email) and the demo email carries a banner naming that person. Delivery is always TO_EMAIL, never the contact. No contact found = no draft (the company is dropped)
- One hook that cites a signal we actually found
- The two pain points come from the person's role (security lead: questionnaires and audit time; founder: deals blocked by missing certification)
- About 120 words or fewer, one clear ask, no attachments
- Never quotes negative news; never claims a certification, round or hire we did not find
- Code check: every signal named in the email must exist in the stored fields; if not, flag the draft for the reviewer (flag, not block)

## 8. What the reviewer sees at the top of each card
Priority tier, then any flags (unknown size, vertical unclear, likely already certified, funding unknown, hook not matched to a stored signal), then the draft, then why the company qualified and why this person.

## 9. Human in the loop
Autonomy level L3: AI drafts, human approves. Growth Lead approves, edits or rejects each draft; a reject reason is logged. Exam demo sends to your own address (hardcoded `to:`).

## Defaults chosen without asking (change if you want)
- Daily send cap 15
- Priority tiers by signal count, not weighted points
- Title order: security > CTO/engineering > founder
- Email length about 120 words
- Code-check mismatch is a flag, not a block
