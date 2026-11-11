"""Environment and paths. Secrets live in .env only; nothing here prints a key."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "sprinto.db"

_ENV_LOADED = False


def load_env():
    """Minimal .env reader so the repo needs no dotenv dependency.

    Values already present in the real environment win.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get(name, default=""):
    load_env()
    return os.environ.get(name, default).strip()


def get_int(name, default):
    raw = get(name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def is_production():
    """True on Vercel. Used to refuse to start without a passcode or a cookie secret."""
    load_env()
    return bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))


def missing_keys(names):
    """Return the names that are not set. Never returns the values."""
    return [n for n in names if not get(n)]


# Fixed, non-secret settings. These are decisions, not configuration knobs.
TARGET_VERTICALS = ("fintech", "healthtech", "cleantech")
EMPLOYEE_MIN = 10
EMPLOYEE_MAX = 100
MAX_LOOP_FETCHES = 2
EMAIL_WORD_LIMIT = 130  # "about 120 words or fewer" with a little slack before flagging
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"
MAX_DOMAINS_PER_RUN = 15   # one run of the chip input; not the daily send cap
# One serverless invocation handles one domain, so the work has to fit inside it.
# vercel.json allows 300s; this leaves a minute of margin. 55s was the original
# target and it was wrong: on Vercel the scrape alone used all of it and the AI
# call then had nothing left, so a real company came back as "retry".
DOMAIN_TIME_BUDGET = 240   # seconds of wall clock for a single domain
DEMO_DOMAINS_FILE = "demo_domains.txt"

# Sequence 2. Stated availability rather than a real calendar: no OAuth, and the
# booked meeting is still real inside this app.
WORKING_DAYS = (0, 1, 2, 3, 4)        # Monday to Friday
WORKING_HOURS = (10, 17)              # 10:00 to 17:00 India time
SLOT_MINUTES = 30
SLOTS_TO_PROPOSE = 3
MAX_REPLY_ROUNDS = 2                  # then escalate
REPLY_DEADLINE_HOURS = 48             # silence for this long escalates
SESSION_MAX_AGE = 12 * 60 * 60   # how long one passcode entry lasts
LOGIN_MAX_FAILURES = 5           # per window, per IP
LOGIN_WINDOW_SECONDS = 10 * 60
