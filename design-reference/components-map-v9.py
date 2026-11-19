"""Draw components-map-v9.svg: the build as it stands on 19 Nov 2026.

Same visual language as v8 (swimlanes by actor, stages across, a legend and
the set-once / never lines). What is new is a seventh column for everything
that happens after the send, a row for the scheduling agent, the script entry
beside the page entry, and two dashed boxes for the parts that are designed
and not built.
"""
import textwrap

OUT = r"C:\Users\vedul\OneDrive\Desktop\term 2\Sprinto\components-map-v9.svg"

NAVY = "#152a52"
INK = "#15233a"
GREY = "#6b7a90"

FILL = {
    "user":   ("#efe6ff", "#8b5cf6"),   # what you do
    "code":   ("#fdefc8", "#e0a21a"),   # plain code
    "hunter": ("#cdf3ea", "#19a98c"),   # Hunter.io
    "ai":     ("#d5f5dd", "#2fa75a"),   # Gemini Flash
    "mail":   ("#d8e9fb", "#2f7fd0"),   # Gmail
    "agent":  ("#e6e2fb", "#6246c7"),   # LangGraph
    "card":   ("#fbd9e8", "#d94f8c"),   # what you end up reading
    "ghost":  ("#f4f6f9", "#aab6c6"),   # designed, not built
    "store":  ("#e7edf6", "#5b6b85"),   # the database
}

LANES = [
    ("Growth Lead", "(you, or a grader's script)", 168, "#f8f6ff"),
    ("The app", "(plain code: it decides)", 214, "#fffdf2"),
    ("Hunter.io", "(the contact)", 132, "#f2fdfa"),
    ("Gemini Flash", "(the only AI, anywhere)", 176, "#f4fdf6"),
    ("Gmail", "(sends, and reads replies)", 150, "#f4f9fe"),
    ("Scheduling agent", "(LangGraph, Sequence 2)", 150, "#f7f6fe"),
    ("The store", "(one layer, two engines)", 104, "#f6f8fb"),
]

STAGES = ["Trigger", "Input", "Research", "Qualify", "Draft",
          "Review and send", "Reply and meeting"]

M = 26
ACTOR_W = 206
COL_W = 272
HEAD_H = 46
TITLE_H = 86
W = M * 2 + ACTOR_W + COL_W * len(STAGES)

col_x = [M + ACTOR_W + i * COL_W for i in range(len(STAGES))]
lane_y, y = [], TITLE_H + HEAD_H
for *_, h, _bg in LANES:
    lane_y.append(y)
    y += h
GRID_BOTTOM = y
H = GRID_BOTTOM + 128

out = []


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class Box:
    def __init__(self, col, lane, text, kind, span=1, pad=14, top=None, height=None,
                 wfrac=1.0):
        self.x = col_x[col] + pad
        self.w = (COL_W * span - pad * 2) * wfrac
        chars = max(14, int((self.w - 20) / 6.55))
        self.lines = []
        for para in text.split("\n"):
            self.lines += textwrap.wrap(para, chars) or [""]
        self.h = height or (len(self.lines) * 17 + 24)
        lane_top, lane_h = lane_y[lane], LANES[lane][2]
        self.y = top if top is not None else lane_top + (lane_h - self.h) / 2
        self.kind = kind

    @property
    def x2(self):
        return self.x + self.w

    @property
    def y2(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def draw(self):
        fill, stroke = FILL[self.kind]
        dash = ' stroke-dasharray="7 5"' if self.kind == "ghost" else ""
        out.append(f'<rect x="{self.x:.0f}" y="{self.y:.0f}" width="{self.w:.0f}" '
                   f'height="{self.h:.0f}" rx="9" fill="{fill}" stroke="{stroke}" '
                   f'stroke-width="2"{dash}/>')
        colour = GREY if self.kind == "ghost" else INK
        ty = self.y + 21
        for line in self.lines:
            out.append(f'<text x="{self.cx:.0f}" y="{ty:.0f}" text-anchor="middle" '
                       f'font-size="13" fill="{colour}">{esc(line)}</text>')
            ty += 17
        return self


def label(x, y, text, colour=INK, size=11.5, anchor="middle", weight="600"):
    width = len(text) * 6.2 + 14
    out.append(f'<rect x="{x - width / 2:.0f}" y="{y - 11:.0f}" width="{width:.0f}" '
               f'height="18" rx="4" fill="#ffffff" opacity="0.94"/>')
    out.append(f'<text x="{x:.0f}" y="{y + 3:.0f}" text-anchor="{anchor}" '
               f'font-size="{size}" font-weight="{weight}" fill="{colour}">'
               f'{esc(text)}</text>')


def path(d, colour=NAVY, dashed=False, marker="arrow"):
    dash = ' stroke-dasharray="8 6"' if dashed else ""
    out.append(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="2.4"'
               f'{dash} marker-end="url(#{marker})"/>')


# --- the boxes ---------------------------------------------------------------
you_in = Box(0, 0, "Types domains, or clicks Healthtech, Fintech or Devtools", "user")
script = Box(0, 1, "A script posts JSON to /run-domain. Same endpoint, same answers", "code")
clean = Box(1, 1, "1 Cleans each one. 253 characters, 63 a label, punycode for other "
                  "scripts. One domain per request", "code")
read = Box(2, 1, "2 Reads home, pricing, about, careers, trust, customers. Dates every "
                 "headline itself", "code")
filters = Box(3, 1, "4 Five hard filters, then the tier. A drop carries the rule and the "
                    "sentence that fired it", "code")
check = Box(4, 1, "6 Re-reads the draft against the stored signals and flags any claim "
                  "they do not carry", "code")
page = Box(5, 1, "7 One card per company: funnel, tabs, flags, evidence. Daily cap of 15", "card")
match = Box(6, 1, "9 Matches each reply to its company by Message-ID, then by the whole "
                  "subject", "code")

hunter = Box(3, 2, "5 One contact: name, title, email. Cached, so a domain is never "
                   "searched twice", "hunter")

extract = Box(2, 3, "3 Pulls each field with a quote, re-checked word for word against "
                    "the page", "ai")
write = Box(4, 3, "6 Two pain points for that role, then the email", "ai")
intent = Box(6, 3, "10 Reads the reply: interested or not. Picks one slot from the list "
                   "code gave it", "ai")

send = Box(5, 4, "8 Sends over SMTP, always to TO_EMAIL, with the contact named in a "
                 "banner", "mail")
inbox = Box(6, 4, "9 IMAP reads INBOX and Spam", "mail", wfrac=0.62)

review = Box(5, 0, "Reads the card, edits, approves or rejects", "user")
handover = Box(6, 0, "Takes over when the agent gives up", "user")

graph = Box(6, 5, "11 check_calendar, propose_time, handle_reply, book_meeting, else "
                  "escalate", "agent")
store = Box(0, 6, "Postgres on Neon deployed, SQLite on your laptop, one layer over "
                  "both: runs, companies, hunter_cache, news_cache, send_log, "
                  "login_attempts, decision_log. Every field keeps its quote and its "
                  "source, which is what the card shows you and what the "
                  "traceability check reads back.", "store", span=7)

for b in (you_in, script, clean, read, filters, check, page, match, hunter,
          extract, write, intent, send, inbox, review, handover, graph, store):
    b.draw()

GUT5, GUT6 = col_x[5] - 7, col_x[6] - 7
RIGHT6 = col_x[6] + COL_W - 30

# --- arrows ------------------------------------------------------------------
path(f"M {you_in.x2:.0f} {you_in.cy:.0f} H {col_x[1] - 7:.0f} V {clean.cy:.0f} "
     f"H {clean.x:.0f}")
path(f"M {script.x2:.0f} {script.cy:.0f} H {clean.x:.0f}")
path(f"M {clean.x2:.0f} {clean.cy:.0f} H {read.x:.0f}")
path(f"M {read.cx:.0f} {read.y2:.0f} V {extract.y:.0f}")
label(read.cx + 64, lane_y[2] + 42, "pages and headlines")
path(f"M {extract.x2:.0f} {extract.cy:.0f} H {col_x[3] - 7:.0f} V {filters.cy:.0f} "
     f"H {filters.x:.0f}")
label(col_x[3] - 7 - 68, lane_y[2] + 42, "facts, each with a quote")
path(f"M {filters.cx + 58:.0f} {filters.y2:.0f} V {hunter.y:.0f}")
label(filters.cx + 100, filters.y2 + 18, "it fits")
path(f"M {hunter.x2:.0f} {hunter.cy:.0f} H {write.cx - 52:.0f} V {write.y:.0f}")
label(hunter.x2 + 62, hunter.cy - 13, "the contact")
path(f"M {write.cx + 52:.0f} {write.y:.0f} V {check.y2:.0f}")
label(write.cx + 94, check.y2 + 18, "the draft")
path(f"M {check.x2:.0f} {check.cy:.0f} H {page.x:.0f}")
path(f"M {page.cx:.0f} {page.y:.0f} V {review.y2:.0f}")
label(page.cx + 52, review.y2 + 17, "you decide")
path(f"M {review.x:.0f} {review.cy:.0f} H {GUT5:.0f} V {send.cy:.0f} H {send.x:.0f}")
label(GUT5 + 52, send.y - 15, "approved only")
path(f"M {send.x2:.0f} {send.cy:.0f} H {inbox.x:.0f}")
path(f"M {inbox.x:.0f} {inbox.y2:.0f} V {match.cy:.0f} H {match.x:.0f}"
     if False else f"M {inbox.cx - 70:.0f} {inbox.y:.0f} V {match.y2:.0f}")
label(inbox.cx - 70, match.y2 + 18, "a reply came back")
path(f"M {match.cx + 70:.0f} {match.y2:.0f} V {intent.y:.0f}")
path(f"M {intent.x2:.0f} {intent.cy:.0f} H {RIGHT6:.0f} V {graph.cy:.0f} H {graph.x2:.0f}")
path(f"M {graph.x:.0f} {graph.cy:.0f} H {GUT6:.0f} V {handover.cy:.0f} "
     f"H {handover.x:.0f}", colour="#d94f8c", dashed=True)
label(GUT6 + 58, handover.y2 + 16, "only if it gives up", colour="#b03a6e")
DROP_Y = lane_y[1] + 20
path(f"M {filters.cx:.0f} {filters.y:.0f} V {DROP_Y:.0f} H {page.cx:.0f} "
     f"V {page.y:.0f}", colour=GREY, dashed=True, marker="arrowgrey")
label((filters.cx + page.cx) / 2, DROP_Y, "dropped: the rule and the quote", colour=GREY)

# --- grid, lanes, headers ----------------------------------------------------
grid = []
for i, (name, sub, h, bg) in enumerate(LANES):
    grid.append(f'<rect x="{M + ACTOR_W}" y="{lane_y[i]}" width="{COL_W * len(STAGES)}" '
                f'height="{h}" fill="{bg}"/>')
    grid.append(f'<rect x="{M}" y="{lane_y[i]}" width="{ACTOR_W}" height="{h}" '
                f'fill="{NAVY}"/>')
    grid.append(f'<text x="{M + ACTOR_W / 2:.0f}" y="{lane_y[i] + h / 2 - 2:.0f}" '
                f'text-anchor="middle" font-size="15" font-weight="700" fill="#ffffff">'
                f'{esc(name)}</text>')
    grid.append(f'<text x="{M + ACTOR_W / 2:.0f}" y="{lane_y[i] + h / 2 + 17:.0f}" '
                f'text-anchor="middle" font-size="11.5" fill="#c3cde0">{esc(sub)}</text>')
    grid.append(f'<line x1="{M}" y1="{lane_y[i]}" x2="{W - M}" y2="{lane_y[i]}" '
                f'stroke="#dfe5ee" stroke-width="1"/>')
for x in col_x[1:]:
    grid.append(f'<line x1="{x}" y1="{TITLE_H + HEAD_H}" x2="{x}" y2="{GRID_BOTTOM}" '
                f'stroke="#e7ecf3" stroke-width="1"/>')
grid.append(f'<rect x="{M}" y="{TITLE_H}" width="{ACTOR_W + COL_W * len(STAGES)}" '
            f'height="{HEAD_H}" fill="{NAVY}"/>')
grid.append(f'<text x="{M + ACTOR_W / 2:.0f}" y="{TITLE_H + 29}" text-anchor="middle" '
            f'font-size="15" font-weight="700" fill="#ffffff">Actor</text>')
for i, stage in enumerate(STAGES):
    grid.append(f'<text x="{col_x[i] + COL_W / 2:.0f}" y="{TITLE_H + 29}" '
                f'text-anchor="middle" font-size="15" font-weight="700" '
                f'fill="#ffffff">{esc(stage)}</text>')
    if i:
        grid.append(f'<line x1="{col_x[i]}" y1="{TITLE_H}" x2="{col_x[i]}" '
                    f'y2="{TITLE_H + HEAD_H}" stroke="#2c4madd" stroke-width="1"/>')

# --- legend and footnotes ----------------------------------------------------
ly = GRID_BOTTOM + 22
legend = [f'<rect x="{M}" y="{ly}" width="{W - 2 * M}" height="42" rx="8" '
          f'fill="#f6f8fb"/>']
legend.append(f'<text x="{M + 20}" y="{ly + 26}" font-size="13" font-weight="700" '
              f'fill="{INK}">Legend:</text>')


def chip(x, colour, text, dashed=False, line=True):
    if line:
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        legend.append(f'<line x1="{x}" y1="{ly + 21}" x2="{x + 42}" y2="{ly + 21}" '
                      f'stroke="{colour}" stroke-width="2.4"{dash}/>')
        legend.append(f'<path d="M {x + 42} {ly + 15} L {x + 54} {ly + 21} '
                      f'L {x + 42} {ly + 27} Z" fill="{colour}"/>')
    else:
        fill, stroke = FILL[colour]
        d = ' stroke-dasharray="6 4"' if colour == "ghost" else ""
        legend.append(f'<rect x="{x}" y="{ly + 12}" width="20" height="18" rx="4" '
                      f'fill="{fill}" stroke="{stroke}" stroke-width="2"{d}/>')
    legend.append(f'<text x="{x + (62 if line else 28)}" y="{ly + 26}" font-size="12.5" '
                  f'fill="{INK}">{esc(text)}</text>')


chip(112, NAVY, "The main flow")
chip(292, GREY, "Dropped, with the reason", dashed=True)
chip(528, "#d94f8c", "Only when it gives up", dashed=True)
chip(754, "code", "Plain code decides", line=False)
chip(930, "ai", "Gemini Flash", line=False)
chip(1066, "hunter", "Hunter.io", line=False)
chip(1186, "mail", "Gmail", line=False)
chip(1286, "agent", "LangGraph", line=False)
chip(1406, "user", "You", line=False)
chip(1486, "ghost", "Designed, not built", line=False)

notes = [
    ("Set once:", " ICP is fintech, healthtech or devtools, 10-100 people, Series A to C. "
                  "Daily send cap 15, at most 15 domains a run, 240 seconds a domain. "
                  "Every send goes to TO_EMAIL and nowhere else."),
    ("Never:", " sends without a human approval, states a fact it did not find, quotes "
               "negative news in the email, searches the same domain on Hunter twice, or "
               "turns \"not shown on the site\" into \"not certified\"."),
    ("Not built:", " discovery (the companies are still your list, not found from the "
                   "signals) and the feedback loop (your edits are stored and nothing "
                   "reads them)."),
]
ny = ly + 66
for head, rest in notes:
    legend.append(f'<text x="{M}" y="{ny}" font-size="12.5" fill="{INK}">'
                  f'<tspan font-weight="700">{esc(head)}</tspan>{esc(rest)}</text>')
    ny += 19

svg = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{ny + 6}" '
    f'viewBox="0 0 {W} {ny + 6}" font-family="Segoe UI, Inter, Helvetica, Arial, '
    f'sans-serif">',
    f'<rect width="{W}" height="{ny + 6}" fill="#ffffff"/>',
    '<defs>',
    f'<marker id="arrow" markerWidth="11" markerHeight="9" refX="10" refY="4.5" '
    f'orient="auto"><path d="M0,0 L11,4.5 L0,9 Z" fill="{NAVY}"/></marker>',
    f'<marker id="arrowgrey" markerWidth="11" markerHeight="9" refX="10" refY="4.5" '
    f'orient="auto"><path d="M0,0 L11,4.5 L0,9 Z" fill="{GREY}"/></marker>',
    '</defs>',
    f'<text x="{W / 2:.0f}" y="46" text-anchor="middle" font-size="27" '
    f'font-weight="700" fill="{INK}">Build 2 &#183; Sprinto Cold Outreach: '
    f'Components Map</text>',
    f'<text x="{W / 2:.0f}" y="70" text-anchor="middle" font-size="14" fill="{GREY}">'
    f'v9 &#183; 19 November 2026 &#183; what is deployed, not what was drawn</text>',
]
svg += grid + out + legend + ["</svg>"]

open(OUT, "w", encoding="utf-8").write("\n".join(svg))
print("wrote", OUT, f"({W} x {ny + 6})")
