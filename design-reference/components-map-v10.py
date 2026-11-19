"""Draw components-map-v10.svg: the workflow in the order pipeline.py runs it.

v9 was checked against the build and three things were wrong with it: the
scraper was never named (it is ours, and it is the second largest module),
the two things it reads were not on the map at all, and the news step was
drawn inside research when the code runs it after the hard filters. v8's
agent loop had also been dropped. All four are fixed here.

    python design-reference/components-map-v10.py
"""
import textwrap

OUT = r"C:\Users\vedul\OneDrive\Desktop\term 2\Sprinto\components-map-v10.svg"

NAVY, INK, GREY = "#152a52", "#15233a", "#6b7a90"
PINK = "#d94f8c"

FILL = {
    "user":   ("#efe6ff", "#8b5cf6"),
    "code":   ("#fdefc8", "#e0a21a"),
    "web":    ("#ffe9d6", "#d9742a"),
    "hunter": ("#cdf3ea", "#19a98c"),
    "ai":     ("#d5f5dd", "#2fa75a"),
    "mail":   ("#d8e9fb", "#2f7fd0"),
    "agent":  ("#e6e2fb", "#6246c7"),
    "card":   ("#fbd9e8", "#d94f8c"),
    "store":  ("#e7edf6", "#5b6b85"),
}

LANES = [
    ("Growth Lead", "(you, or a grader's script)", 196, "#f8f6ff"),
    ("The app", "(our code: it decides)", 252, "#fffdf2"),
    ("What it reads", "(nothing else is a source)", 136, "#fff8f1"),
    ("Hunter.io", "(the contact)", 126, "#f2fdfa"),
    ("Gemini Flash", "(the only AI, anywhere)", 212, "#f4fdf6"),
    ("Gmail", "(sends, and reads replies)", 136, "#f4f9fe"),
    ("Scheduling agent", "(LangGraph, Sequence 2)", 136, "#f7f6fe"),
    ("The store", "(one layer, two engines)", 104, "#f6f8fb"),
]

STAGES = ["Entry", "Research", "Qualify", "Signals and tier", "Contact",
          "Draft", "Review and send", "Reply and meeting"]

M, ACTOR_W, COL_W = 26, 212, 272
HEAD_H, TITLE_H = 46, 88
W = M * 2 + ACTOR_W + COL_W * len(STAGES)

col_x = [M + ACTOR_W + i * COL_W for i in range(len(STAGES))]
lane_y, _y = [], TITLE_H + HEAD_H
for *_rest, h, _bg in LANES:
    lane_y.append(_y)
    _y += h
GRID_BOTTOM = _y

out = []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Box:
    def __init__(self, col, lane, text, kind, span=1, pad=14, top=None, wfrac=1.0):
        self.x = col_x[col] + pad
        self.w = (COL_W * span - pad * 2) * wfrac
        chars = max(14, int((self.w - 20) / 6.55))
        self.lines = []
        for para in text.split("\n"):
            self.lines += textwrap.wrap(para, chars) or [""]
        self.h = len(self.lines) * 17 + 24
        self.y = top if top is not None else (
            lane_y[lane] + (LANES[lane][2] - self.h) / 2)
        self.kind = kind
        out.append(self)

    x2 = property(lambda s: s.x + s.w)
    y2 = property(lambda s: s.y + s.h)
    cx = property(lambda s: s.x + s.w / 2)
    cy = property(lambda s: s.y + s.h / 2)

    def svg(self):
        fill, stroke = FILL[self.kind]
        parts = [f'<rect x="{self.x:.0f}" y="{self.y:.0f}" width="{self.w:.0f}" '
                 f'height="{self.h:.0f}" rx="9" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="2"/>']
        ty = self.y + 21
        for line in self.lines:
            parts.append(f'<text x="{self.cx:.0f}" y="{ty:.0f}" text-anchor="middle" '
                         f'font-size="13" fill="{INK}">{esc(line)}</text>')
            ty += 17
        return parts


arrows = []


def path(d, colour=NAVY, dashed=False, marker="arrow"):
    dash = ' stroke-dasharray="8 6"' if dashed else ""
    arrows.append(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="2.4"'
                  f'{dash} marker-end="url(#{marker})"/>')


def tag(x, y, text, colour=INK):
    width = len(text) * 6.2 + 14
    arrows.append(f'<rect x="{x - width / 2:.0f}" y="{y - 11:.0f}" width="{width:.0f}" '
                  f'height="18" rx="4" fill="#ffffff" opacity="0.95"/>')
    arrows.append(f'<text x="{x:.0f}" y="{y + 3:.0f}" text-anchor="middle" '
                  f'font-size="11.5" font-weight="600" fill="{colour}">'
                  f'{esc(text)}</text>')


def G(i):       # the gutter just left of column i
    return col_x[i] - 7


def CH(i, off):  # a clear vertical channel inside column i
    return col_x[i] + off


# --- entry -------------------------------------------------------------------
you_in = Box(0, 0, "Types domains, or clicks Healthtech, Fintech or Devtools", "user",
             top=lane_y[0] + 26)
script = Box(0, 0, "Or a script posts JSON to /run-domain: same endpoint, same answers",
             "code", top=lane_y[0] + 110)
clean = Box(0, 1, "1 Cleans each one. 253 characters, 63 a label, punycode for other "
                  "scripts. One domain per request", "code")

# --- research ----------------------------------------------------------------
scraper = Box(1, 1, "2 Our scraper, not a library: six pages one at a time, follows the "
                    "homepage's own links when a path is missing, refuses a page that "
                    "redirected elsewhere, and records \"not readable\" rather than "
                    "guessing", "code", top=lane_y[1] + 18)
site = Box(1, 2, "The company's own site: home, pricing, about, careers, trust, "
                 "customers", "web", wfrac=0.62)
extract = Box(1, 4, "3 Pulls each field with a quote and the URL it came from",
              "ai", top=lane_y[4] + 22)
decide = Box(1, 4, "4 Says whether one more page would settle an unknown",
             "ai", top=lane_y[4] + 120)

# --- qualify -----------------------------------------------------------------
recheck = Box(2, 1, "5 Re-checks every quote word for word against the page. "
                    "Unverified counts as unknown", "code", top=lane_y[1] + 26)
filters = Box(2, 1, "6 Five hard filters. A drop carries the rule and the sentence "
                    "that fired it", "code", top=lane_y[1] + 142)

# --- signals -----------------------------------------------------------------
dates = Box(3, 1, "8 Dates every headline itself, keeps the window, then sets the tier",
            "code")
news = Box(3, 2, "Google News RSS, unofficial. A failure is unknown, never \"no news\"",
           "web", wfrac=0.62)
heads = Box(3, 4, "7 Reads up to ten headlines: funding, hiring, a breach", "ai")

# --- contact -----------------------------------------------------------------
pick = Box(4, 1, "10 Picks the person by title, or drops the company", "code")
hunter = Box(4, 3, "9 Hunter domain search, cached, so a domain is never searched twice",
             "hunter")

# --- draft -------------------------------------------------------------------
check = Box(5, 1, "12 Re-reads the draft against the stored signals and flags any claim "
                  "they do not carry", "code")
write = Box(5, 4, "11 Two pain points for that role, then the email", "ai")

# --- review and send ---------------------------------------------------------
review = Box(6, 0, "Reads the card, edits, approves or rejects", "user")
card = Box(6, 1, "13 One card per company: funnel, tabs, flags, evidence. Daily cap "
                 "of 15", "card")
send = Box(6, 5, "14 Sends over SMTP, always to TO_EMAIL, with the contact named in a "
                 "banner", "mail")

# --- reply and meeting -------------------------------------------------------
handover = Box(7, 0, "Takes over when the agent gives up", "user")
match = Box(7, 1, "16 Matches each reply to its company by Message-ID, then by the "
                  "whole subject", "code")
intent = Box(7, 4, "17 Reads the reply: interested or not, and picks one of the slots "
                   "code offered", "ai")
inbox = Box(7, 5, "15 IMAP reads INBOX and Spam", "mail", wfrac=0.62)
graph = Box(7, 6, "18 check_calendar, propose_time, handle_reply, book_meeting, else "
                  "escalate", "agent")

store = Box(0, 7, "Postgres on Neon deployed, SQLite on your laptop, one layer over "
                  "both: runs, companies, hunter_cache, news_cache, send_log, "
                  "login_attempts, decision_log. Every field keeps its quote and its "
                  "source, which is what the card shows you and what the traceability "
                  "check reads back.", "store", span=len(STAGES))

# --- the flow ----------------------------------------------------------------
path(f"M {clean.cx - 70:.0f} {you_in.y2:.0f} V {clean.y:.0f}")
path(f"M {clean.cx + 70:.0f} {script.y2:.0f} V {clean.y:.0f}")
path(f"M {clean.x2:.0f} {clean.cy:.0f} H {G(1):.0f} V {scraper.cy:.0f} "
     f"H {scraper.x:.0f}")
path(f"M {site.cx:.0f} {site.y:.0f} V {scraper.y2:.0f}")
tag(site.cx, site.y - 26, "six pages, eight seconds each")
path(f"M {CH(1, 196):.0f} {scraper.y2:.0f} V {extract.y:.0f}")
tag(CH(1, 196) + 12, scraper.y2 + 17, "the page text")
path(f"M {decide.x2:.0f} {decide.cy:.0f} H {CH(1, 246):.0f} V {scraper.y + 22:.0f} "
     f"H {scraper.x2:.0f}", colour=PINK, dashed=True)
tag(CH(1, 246) - 4, decide.y2 + 18, "one more page, at most two", colour="#b03a6e")
path(f"M {extract.x2:.0f} {extract.cy:.0f} H {G(2):.0f} V {recheck.cy:.0f} "
     f"H {recheck.x:.0f}")
tag(G(2), lane_y[3] + 62, "fields and quotes")
path(f"M {recheck.cx:.0f} {recheck.y2:.0f} V {filters.y:.0f}")
path(f"M {filters.x2:.0f} {filters.cy:.0f} H {G(3):.0f} V {dates.cy:.0f} "
     f"H {dates.x:.0f}")
path(f"M {news.cx:.0f} {news.y:.0f} V {dates.y2:.0f}")
tag(news.cx, news.y - 26, "headlines")
path(f"M {CH(3, 196):.0f} {dates.y2:.0f} V {heads.y:.0f}")
path(f"M {CH(3, 246):.0f} {heads.y:.0f} V {dates.y2:.0f}")
tag(CH(3, 221), lane_y[3] + 94, "what each one is")
path(f"M {dates.x2:.0f} {dates.cy:.0f} H {G(4):.0f} V {hunter.cy:.0f} "
     f"H {hunter.x:.0f}")
path(f"M {hunter.cx:.0f} {hunter.y:.0f} V {pick.y2:.0f}")
tag(hunter.cx + 74, hunter.y - 16, "a name, a title, an email")
path(f"M {pick.x2:.0f} {pick.cy:.0f} H {G(5):.0f} V {write.cy:.0f} H {write.x:.0f}")
path(f"M {write.cx:.0f} {write.y:.0f} V {check.y2:.0f}")
tag(write.cx + 62, write.y - 16, "subject and body")
path(f"M {check.x2:.0f} {check.cy:.0f} H {card.x:.0f}")
path(f"M {card.cx:.0f} {card.y:.0f} V {review.y2:.0f}")
tag(card.cx + 56, review.y2 + 17, "you decide")
path(f"M {review.x:.0f} {review.cy:.0f} H {G(6):.0f} V {send.cy:.0f} H {send.x:.0f}")
tag(G(6) + 54, send.y - 15, "approved only")
path(f"M {send.x2:.0f} {send.cy:.0f} H {inbox.x:.0f}")
path(f"M {inbox.cx:.0f} {inbox.y:.0f} V {match.y2:.0f}")
tag(inbox.cx, inbox.y - 26, "a reply came back")
path(f"M {match.cx + 66:.0f} {match.y2:.0f} V {intent.y:.0f}")
path(f"M {intent.cx + 92:.0f} {intent.y2:.0f} V {graph.y:.0f}")
path(f"M {graph.x:.0f} {graph.cy:.0f} H {G(7):.0f} V {handover.cy:.0f} "
     f"H {handover.x:.0f}", colour=PINK, dashed=True)
tag(G(7) + 62, handover.y2 + 16, "only if it gives up", colour="#b03a6e")
DROP_Y = lane_y[1] + 14
path(f"M {filters.x2:.0f} {filters.y + 20:.0f} H {G(3):.0f} V {DROP_Y:.0f} "
     f"H {card.cx:.0f} V {card.y:.0f}", colour=GREY, dashed=True,
     marker="arrowgrey")
tag((filters.cx + card.cx) / 2, DROP_Y, "dropped: the rule and the quote", colour=GREY)

# --- grid --------------------------------------------------------------------
grid = []
for i, (name, sub, h, bg) in enumerate(LANES):
    grid.append(f'<rect x="{M + ACTOR_W}" y="{lane_y[i]}" '
                f'width="{COL_W * len(STAGES)}" height="{h}" fill="{bg}"/>')
    grid.append(f'<rect x="{M}" y="{lane_y[i]}" width="{ACTOR_W}" height="{h}" '
                f'fill="{NAVY}"/>')
    grid.append(f'<text x="{M + ACTOR_W / 2:.0f}" y="{lane_y[i] + h / 2 - 2:.0f}" '
                f'text-anchor="middle" font-size="15" font-weight="700" '
                f'fill="#ffffff">{esc(name)}</text>')
    grid.append(f'<text x="{M + ACTOR_W / 2:.0f}" y="{lane_y[i] + h / 2 + 17:.0f}" '
                f'text-anchor="middle" font-size="11.5" fill="#c3cde0">{esc(sub)}</text>')
    grid.append(f'<line x1="{M}" y1="{lane_y[i]}" x2="{W - M}" y2="{lane_y[i]}" '
                f'stroke="#dfe5ee"/>')
for x in col_x[1:]:
    grid.append(f'<line x1="{x}" y1="{TITLE_H + HEAD_H}" x2="{x}" y2="{GRID_BOTTOM}" '
                f'stroke="#e7ecf3"/>')
grid.append(f'<rect x="{M}" y="{TITLE_H}" width="{ACTOR_W + COL_W * len(STAGES)}" '
            f'height="{HEAD_H}" fill="{NAVY}"/>')
grid.append(f'<text x="{M + ACTOR_W / 2:.0f}" y="{TITLE_H + 29}" text-anchor="middle" '
            f'font-size="15" font-weight="700" fill="#ffffff">Actor</text>')
for i, stage in enumerate(STAGES):
    grid.append(f'<text x="{col_x[i] + COL_W / 2:.0f}" y="{TITLE_H + 29}" '
                f'text-anchor="middle" font-size="15" font-weight="700" '
                f'fill="#ffffff">{esc(stage)}</text>')

# --- legend and notes --------------------------------------------------------
ly = GRID_BOTTOM + 22
legend = [f'<rect x="{M}" y="{ly}" width="{W - 2 * M}" height="42" rx="8" '
          f'fill="#f6f8fb"/>',
          f'<text x="{M + 20}" y="{ly + 26}" font-size="13" font-weight="700" '
          f'fill="{INK}">Legend:</text>']


def chip(x, colour, text, dashed=False, line=True):
    if line:
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        legend.append(f'<line x1="{x}" y1="{ly + 21}" x2="{x + 40}" y2="{ly + 21}" '
                      f'stroke="{colour}" stroke-width="2.4"{dash}/>')
        legend.append(f'<path d="M {x + 40} {ly + 15} L {x + 52} {ly + 21} '
                      f'L {x + 40} {ly + 27} Z" fill="{colour}"/>')
    else:
        fill, stroke = FILL[colour]
        legend.append(f'<rect x="{x}" y="{ly + 12}" width="20" height="18" rx="4" '
                      f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    legend.append(f'<text x="{x + (60 if line else 27)}" y="{ly + 26}" '
                  f'font-size="12.5" fill="{INK}">{esc(text)}</text>')


chip(110, NAVY, "The main flow")
chip(276, GREY, "Dropped, with the reason", dashed=True)
chip(498, PINK, "Only when it has to", dashed=True)
chip(700, "code", "Our code decides", line=False)
chip(858, "ai", "Gemini Flash", line=False)
chip(988, "web", "What it reads", line=False)
chip(1122, "hunter", "Hunter.io", line=False)
chip(1236, "mail", "Gmail", line=False)
chip(1330, "agent", "LangGraph", line=False)
chip(1450, "user", "You", line=False)
chip(1528, "card", "What you read", line=False)
chip(1662, "store", "Stored", line=False)

notes = [
    ("Read it in order:", " 1 to 18 is the order pipeline.py runs them. The hard "
     "filters fire before any news is fetched, and the contact is looked up last of "
     "the three, so a company that fails a filter costs no Hunter search."),
    ("Set once:", " ICP is fintech, healthtech or devtools, 10-100 people, Series A "
     "to C. Daily send cap 15, at most 15 domains a run, 240 seconds a domain. Every "
     "send goes to TO_EMAIL and nowhere else."),
    ("Never:", " sends without a human approval, states a fact it did not find, quotes "
     "negative news in the email, searches the same domain on Hunter twice, or turns "
     "\"not shown on the site\" into \"not certified\"."),
    ("Not built:", " discovery (the companies are still your list, not found from the "
     "signals) and the feedback loop (your edits are stored and nothing reads them)."),
]
ny = ly + 66
for head, rest in notes:
    legend.append(f'<text x="{M}" y="{ny}" font-size="12.5" fill="{INK}">'
                  f'<tspan font-weight="700">{esc(head)}</tspan>{esc(rest)}</text>')
    ny += 19

H = ny + 8
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
       f'viewBox="0 0 {W} {H}" font-family="Segoe UI, Inter, Helvetica, Arial, '
       f'sans-serif">',
       f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
       '<defs>',
       f'<marker id="arrow" markerWidth="11" markerHeight="9" refX="10" refY="4.5" '
       f'orient="auto"><path d="M0,0 L11,4.5 L0,9 Z" fill="{NAVY}"/></marker>',
       f'<marker id="arrowgrey" markerWidth="11" markerHeight="9" refX="10" refY="4.5" '
       f'orient="auto"><path d="M0,0 L11,4.5 L0,9 Z" fill="{GREY}"/></marker>',
       '</defs>',
       f'<text x="{W / 2:.0f}" y="46" text-anchor="middle" font-size="27" '
       f'font-weight="700" fill="{INK}">Build 2 &#183; Sprinto Cold Outreach: '
       f'Components Map</text>',
       f'<text x="{W / 2:.0f}" y="71" text-anchor="middle" font-size="14" '
       f'fill="{GREY}">v10 &#183; 19 November 2026 &#183; the order the code actually '
       f'runs, with every source it reads</text>']
svg += grid
for box in out:
    svg += box.svg()
svg += arrows + legend + ["</svg>"]

open(OUT, "w", encoding="utf-8").write("\n".join(svg))
print("wrote", OUT, f"({W} x {H})")
