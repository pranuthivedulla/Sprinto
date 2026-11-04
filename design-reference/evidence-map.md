# Sprinto Cold Outreach - Evidence Map
Fill-before-you-build table (MESA Term 2, AI Case 2). Rule: each row asks for a FACT code can check, not a topic.

## ICP (from the case PDF)
Series A-C SaaS companies (in fintech, healthtech, cleantech; 10-100 employees as our targeting filter) that are preparing for a compliance audit OR under pressure from enterprise customers to get certified.

| # | The question | Data that answers it | Where it lives | Sufficient when | Limit | If unanswered | Short-circuit |
|---|---|---|---|---|---|---|---|
| 1 | Is it a SaaS company? | Subscription pricing or a "Book a demo" CTA, plus a software product description | Homepage, pricing page | Either pricing tiers or demo CTA is present | 1 fetch | Drop | YES: clear "no" ends the run |
| 1b | Which vertical is it in? | What the company says it does, in its own words | Homepage, about page (already scraped) | Gemini Flash picks one of fintech, healthtech, cleantech AND quotes the sentence it based that on | 1 (no extra fetch) | Flag as "vertical unclear", do not drop | YES: none of the three -> drop (hard gate, code applies it) |
| 2 | What is the employee count? | A stated number or range ("team of 80", "50-200 employees") | About page | A number or range is stated | 1 fetch | Flag | YES: stated count outside 10-100 -> drop (hard gate, code applies it). Unknown count -> flag, do not drop |
| 3 | What funding stage is it at? | A named round (Seed, Series A/B/C) | Blog/newsroom post, then Google News RSS headline | A named round with a date | 2 fetches, then 1 search | Flag, do not drop | No |
| 4 | Is it hiring for compliance roles? | At least 1 open posting titled GRC, security compliance, InfoSec, Trust, or similar | Careers page, plus Google News headline saying the company is preparing for SOC 2 / ISO | 1 matching posting or 1 such headline | 2 fetches | Flag as "unknown" | No |
| 5 | Which certifications does the site show? | A framework (SOC 2, ISO 27001, GDPR) shown as active or completed | Trust/security page, footer badges, plus Google News headline announcing a certification | A framework named with active status | 2 fetches (/trust, /security) | Record as "not shown on site" (never "missing"), flag | YES: SOC 2 and ISO 27001 both active on the trust page -> drop. A Google News certification headline alone only flags "likely already certified" for the reviewer; code drops only when the trust page agrees |
| 6 | Is it under enterprise-customer pressure? | Enterprise logos, an Enterprise plan, or a "security questionnaire" mention | Customers page, pricing page | At least 1 concrete hit | 2 fetches | Flag | No |
| 7 | Any negative news (breach, security incident)? | A dated item from the last 12 months | Google News RSS (agent loop) | A dated, sourced item | 1 search | Ignore | No |

## Google News RSS: what it feeds (decision approved)
One query per company (name + keywords, last 2 years). Plain code fetches the feed and date-filters per category; Gemini Flash only classifies each headline as funding, compliance, negative or irrelevant. It feeds rows 3 (funding stage), 4 (audit-prep headline), 5 (certification announced) and 7 (negative news).
- Funding: latest named round, any date.
- Compliance: headline announcing a certification flags "likely already certified" (drop only if the trust page agrees); "preparing for / starting audit" counts as the row 4 signal.
- Negative news: last 12 months only, buying signal only.
- A headline counts only if it names the right company; the email may quote a headline-sourced fact only if the source is stored with it.
- No result = unknown, flag (never "no news, so clean").

## Rules that follow from the table
- "Preparing for an audit" is a verdict the code derives from rows 4, 5 and 6. It is not a row of its own.
- "Not shown on site" is not "not certified". It only becomes a strong lead when combined with a hiring or enterprise-pressure signal.
- Row 7 is a buying signal only (decision approved). It raises priority for the human reviewer. It is never quoted in the email.
- Funding stage (row 3) is often not on the company's own site, so it flags rather than drops.

## Vertical focus (decision approved)
Target verticals: fintech, healthtech, cleantech (cleantech kept deliberately, weakest rationale: many cleantech firms are hardware/services and fail the SaaS gate anyway). Rationale for fintech and healthtech: enterprise buyers (banks, hospitals) require SOC 2 / ISO 27001 in security reviews. Row 1b is a hard drop applied by code; Flash only classifies from a fixed list and must quote evidence.
Risk: fuzzy edges (insurtech, medical devices, payments infra) and a smaller weekly pool.

## Worst case
The agent qualifies a company that already holds SOC 2 and writes "congrats on starting your audit". Guards: rows 4-6, short-circuit on row 5, and the human approval step before sending.

## One final question: two of three answered, one unknown
Qualify-and-flag. If the unknown is the audit-intent signal (rows 4-6), qualify and flag it. If the unknown is SaaS or a PoC, drop. The email leads with the signal that WAS found and never claims the missing one.

## Open items
- Employee range is 10-100 (decision approved). ICP wording stays "Series A-C" (decision approved, Option 2). Tension: 10-100 covers Seed, Series A and early Series B, so most Series C companies will drop on row 2. Defence line to use in the write-up: "Series A to early Series B, up to about 100 people, is where audits start to block enterprise deals and a dedicated compliance team usually does not exist yet."
- Confirm which rows run in step 1 (scrape) and which only in the step 3 agent loop (rows 3 and 7 need search).
