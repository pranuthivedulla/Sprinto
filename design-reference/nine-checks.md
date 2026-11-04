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
