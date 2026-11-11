# Sprinto Cold Outreach - Nine Checks Log
MESA Term 2, AI Case 2 (3 Nov 2026). Only the nine checks are in scope for now.

## Course constraints (from the case PDF)
- 7-step pipeline: scrape, extract, qualify (with agent loop), find PoC, 2 pain points, draft email, send via Gmail
- Send to your own address (hardcoded `to:`)
- PoC: Hunter.io Domain Search (25 searches/month) or Apollo (web UI, hardcoded input)
- Done = a real personalised email lands, addressed to a named person, and every decision is defensible

## Group 1: Kill switches
| Check | Verdict | Risk | Guardrail |
|---|---|---|---|
| 01 Real problem | YES | Real problem is consistent quality across a batch, not typing speed | Judge on the last email in a batch |
| 02 Repeated workflow | YES | None | None |
| 03 Inputs available | YES, with a risk | Intent signals (audit prep, enterprise pressure) and funding stage are rarely on the site | Use proxy signals (trust page, careers, badges, Enterprise tier); "unknown" is a valid output; agent loop fetches careers/trust/funding before deciding; already-certified = disqualify |

## Decision 1 (approved)
PoC source: Hunter.io Domain Search with per-domain caching to a file (never search the same domain twice). Test on 3-4 domains, keep the rest of the 25/month for the demo.

## Note
The course deck's checklist has 10 items (it splits "Impact measurable" and "Data reliable" out). This log follows the 9-check grouping from the build skill; map as needed.

## Group 2: Sizing
| Check | Verdict | Risk | Guardrail |
|---|---|---|---|
| 04 Output | YES | Output is one personalised email, but quality depends on a real hook | Hook must cite a specific signal from the site; no signal = no send |
| 05 Impact | YES | 15-20 min per company x 8-15 a week = 2-5 hrs/week saved | Measure: minutes per company before vs after, and last-email quality |
| 08 Cost | YES, with a risk | Hunter capped at 25/month; AI calls are cheap at 8-15 companies a week | Cache Hunter; use a cheap model for extraction, a stronger one only for the email draft |

## Decision 2 (approved)
No automatic sending. A human approves each email before it goes out. The agent drafts and queues; the Growth Lead approves, edits or rejects. Exam demo: the approved email is sent via Gmail to your own address (hardcoded `to:`).

## Group 3: Boundary
| Check | Verdict | Risk | Guardrail |
|---|---|---|---|
| 06 Where it must not act alone | YES | An unsupported claim (e.g. "congrats on your SOC 2") to the wrong company hurts Sprinto's reputation | Send step only runs after human approval; every email shows the signal that justified it; "unknown" stays unknown; never claims a certification, funding round or hiring fact it did not find |
| 07 Who decides | YES | Case wording says "automatically"; approval step could look like a deviation | Growth Lead approves/edits/rejects each draft; qualification reason and PoC reason shown beside the draft so the decision is fast |
| 09 Who owns it | YES, with a risk | Nobody owns the ICP rules or the Hunter key after the exam | Growth Lead owns the domain list and ICP rules; one named owner for the API keys; rejected drafts logged so rules can be tuned |

## Status
Nine checks complete. Next step in the skill: Step 2 (rubric and rules), when you want it.

## Decision 3 (approved)
Negative news (evidence map row 7) is a buying signal only. Shown to the reviewer, never quoted in the email.

## Decision 4 (approved)
Claude Code writes the scraper (build tool, not a runtime component; the scraper is plain code). Gemini Flash is the single AI at runtime: cleans/extracts page text, judges gaps in the agent loop, writes two pain points and drafts the email. Hard gates (SaaS, size flag, cert short-circuit, caps) stay in code. Components map updated to v2 (one AI lane).

## Decision 5 (approved)
Search source for evidence-map rows 3 (funding stage) and 7 (negative news) is Google News RSS, one query per company (name + keywords, last 12 months). Plain code fetches and date-filters the feed; Gemini Flash only classifies headlines. Components map v3. Spike test: one real query returns dated headlines for a known SaaS company.

## Decision 6 (approved)
Vertical focus: fintech, healthtech, cleantech only. Evidence map row 1b, hard drop in code, Flash classifies from a fixed list with a quoted sentence. Components map v4.

## Decision 7 (approved)
Employee count range 10-100 (evidence map row 2). Stated count outside range = drop, unknown = flag. Open tension with the case's 'Series A-C' ICP.

## Decision 8 (approved)
ICP wording stays 'Series A-C' (Option 2); 10-100 employees is the targeting filter inside it. Write-up must state the 10-100 filter as a deliberate choice (small teams have no compliance hire), not leave the mismatch for a grader to find.

## Decision 9 (approved)
Domain list input is a pasted text box (not file upload). Code cleans each entry: strips https://, www, paths, spaces, duplicates. Components map v5.

## Decision 10 (approved)
Google News RSS is a source for funding, compliance and negative headlines (evidence map rows 3, 4, 5, 7), not only negative news. One query per company, code date-filters, Flash classifies headlines. No result = unknown, flag. Components map v6.

## Decision 11 (approved)
A Google News certification headline only flags 'likely already certified' for the reviewer. The drop (row 5 short-circuit) needs the trust page to agree.

## Decision 12
Rubric and rules written to rubric-and-rules.md (defaults listed at the bottom of that file). Defence line in evidence-map.md replaced with the 10-100 wording.

## Decision 13
Build prompt written to CLAUDE_CODE_BUILD_PROMPT.md; references copied to design-reference/ (components-map-final.png = v6).

## Decision 14 (approved)
Components map redrawn as v7: five lanes (Growth Lead, System, Hunter.io / Apollo, AI, Gmail), first column "Actor", three flow styles (main, conditional, hand-off). Website and Google News are read inside the System lane (startup info); Hunter/Apollo is used only to find the contact. Map shows the send going to the identified contact; the demo redirects it to TO_EMAIL as the case requires. components-map-final.png is now v7.

## Decision 15 (approved)
The draft shows the scraped contact (name, title, email) on the review card and in a banner on the demo email, only when Hunter/Apollo returned one. Delivery stays TO_EMAIL. App edited (app/templates/index.html, app/mailer.py); offline tests 79 passed. Components map v8 = final.

## Decision 16
Change prompt for Claude Code written to CLAUDE_CODE_CHANGE_PROMPT.md: interactive chip input (default option B: chips plus optional demo list, still to be confirmed by the user), per-domain /run-domain flow, Postgres via DATABASE_URL, passcode gate on the public page, Vercel config, tests. Stop points before any production deploy.

## Decision 17 (approved)
Discovery step added: clicking a vertical finds the companies, instead of loading a
fixed list. The Growth Lead still owns the ICP rules and still approves the list
before anything runs; what changes is that she no longer has to supply the names.

Candidates come from Google News, not from Hunter Discover. Both were tested
against the real key on 11 Nov 2026, and the difference is not marginal. Discover
asked for healthtech SaaS returns Cerner, Athenahealth, Cipla, Dr. Reddy's and
HDFC Life; its headcount filter is silently ignored on the free plan (identical
results with and without it) and its structured industry filter is rejected
outright. A funding-news query returns CARPL.ai (Series A, $10M), CURAPOD (INR 20
Cr pre-Series A) and Pulse ($4M). Discover's index is biased towards large
established companies; a funding feed is biased towards small recently funded ones,
which is the ICP. Discover remains in the chain for the contact lookup only.

Discovery window is 12 months. Funding older than that is a weak trigger.

One query per vertical, written down here because it is a rule, not a detail:
  healthtech  "healthtech" (raises OR "Series A" OR "Series B" OR funding) India
  fintech     "fintech" (raises OR "Series A" OR "Series B" OR funding) India
  cleantech   "cleantech" (raises OR "Series A" OR "Series B" OR funding) India
India scope follows the accounts targeted so far; change it here if that changes.
Code fetches and date-filters the feed. Flash only classifies each headline: does it
name exactly one company, and which. A headline naming no single company (listicles,
market reports, ecosystem pieces) is discarded.

A headline gives a company name, and the pipeline needs a domain. Nothing may invent
one: a guessed domain fails silently, researching the wrong company. Resolution is
(1) the outbound links of the article that named the company, then (2) a
search-grounded lookup whose citation is the source, and in both cases (3) a check
that the company name actually appears on that homepage before the domain is
accepted. A name that will not resolve becomes a greyed chip reading "no domain
found", visible and typeable over, never silently dropped.

Discovery spends nothing: Hunter Discover queries cost no searches and no credits
(verified, quota unchanged across every test), and Google News RSS is free.

Expected yield is 4 to 6 usable candidates per click out of about 15 headlines, so
this fills a weekly list rather than a daily one. The 15-domain run cap is not the
binding constraint; at roughly 90 seconds per company, patience is.

Unchanged: everything after the chips. The hard filters, ranking, contact choice,
drafting and the human approval all run exactly as they do today on a typed domain.
Components map needs a v9 redraw with the discovery box in front of step 1.
