"""SQLite storage. Tables match section 8 of the build prompt. All times stored UTC."""
import json
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    domain_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    company_name TEXT,
    status TEXT NOT NULL,
    drop_rule TEXT,
    drop_quote TEXT,
    drop_source TEXT,
    fields_json TEXT,
    signals_json TEXT,
    tier TEXT,
    flags_json TEXT,
    poc_name TEXT,
    poc_title TEXT,
    poc_email TEXT,
    poc_confidence INTEGER,
    poc_reason TEXT,
    pains_json TEXT,
    hook_json TEXT,
    email_subject TEXT,
    email_body TEXT,
    check_flags_json TEXT,
    reviewer_action TEXT,
    reject_reason TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS hunter_cache (
    domain TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_cache (
    company TEXT NOT NULL,
    query TEXT NOT NULL,
    headlines_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (company, query)
);
CREATE TABLE IF NOT EXISTS send_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    to_address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    run_id INTEGER,
    at TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT
);
"""


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)


def log(event, detail="", company_id=None, run_id=None):
    with connect() as conn:
        conn.execute(
            "INSERT INTO decision_log (company_id, run_id, at, event, detail)"
            " VALUES (?,?,?,?,?)",
            (company_id, run_id, utcnow(), event, detail),
        )


def create_run(domain_count):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, domain_count) VALUES (?,?)",
            (utcnow(), domain_count),
        )
        return cur.lastrowid


def latest_run_id():
    with connect() as conn:
        row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"] if row else None


def insert_company(run_id, domain, status, **fields):
    cols = ["run_id", "domain", "status", "created_at"]
    vals = [run_id, domain, status, utcnow()]
    for key, value in fields.items():
        cols.append(key)
        vals.append(json.dumps(value) if key.endswith("_json") else value)
    placeholders = ",".join("?" for _ in cols)
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO companies ({','.join(cols)}) VALUES ({placeholders})", vals
        )
        return cur.lastrowid


def update_company(company_id, **fields):
    if not fields:
        return
    sets, vals = [], []
    for key, value in fields.items():
        sets.append(f"{key}=?")
        vals.append(json.dumps(value) if key.endswith("_json") else value)
    vals.append(company_id)
    with connect() as conn:
        conn.execute(f"UPDATE companies SET {','.join(sets)} WHERE id=?", vals)


def get_company(company_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()


def companies_for_run(run_id):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM companies WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()


# --- caches -----------------------------------------------------------------

def hunter_cached(domain):
    with connect() as conn:
        row = conn.execute(
            "SELECT response_json, fetched_at FROM hunter_cache WHERE domain=?", (domain,)
        ).fetchone()
        return (json.loads(row["response_json"]), row["fetched_at"]) if row else (None, None)


def hunter_store(domain, response):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO hunter_cache (domain, response_json, fetched_at)"
            " VALUES (?,?,?)",
            (domain, json.dumps(response), utcnow()),
        )


def news_cached(company, query):
    with connect() as conn:
        row = conn.execute(
            "SELECT headlines_json FROM news_cache WHERE company=? AND query=?",
            (company, query),
        ).fetchone()
        return json.loads(row["headlines_json"]) if row else None


def news_store(company, query, headlines):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO news_cache (company, query, headlines_json, fetched_at)"
            " VALUES (?,?,?,?)",
            (company, query, json.dumps(headlines), utcnow()),
        )


# --- sending ----------------------------------------------------------------

def record_send(company_id, to_address):
    now = utcnow()
    with connect() as conn:
        conn.execute(
            "INSERT INTO send_log (company_id, sent_at, to_address) VALUES (?,?,?)",
            (company_id, now, to_address),
        )
    return now


def sends_today(day_start_utc):
    """Count sends since the given UTC timestamp (the start of today in India time)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM send_log WHERE sent_at >= ?", (day_start_utc,)
        ).fetchone()
        return row["n"]


def sent_rows(limit=50):
    with connect() as conn:
        return conn.execute(
            "SELECT s.sent_at, s.to_address, c.domain, c.email_subject"
            " FROM send_log s LEFT JOIN companies c ON c.id = s.company_id"
            " ORDER BY s.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
