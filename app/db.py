"""Storage. SQLite locally, Postgres when DATABASE_URL is set.

Same tables, same columns, same function names either way: nothing outside this file
knows which database it is talking to. All times are stored UTC as text, so the two
behave identically when the code compares timestamps.
"""
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
    draft_subject TEXT,
    draft_body TEXT,
    email_subject TEXT,
    email_body TEXT,
    check_flags_json TEXT,
    reviewer_action TEXT,
    reject_reason TEXT,
    sent_message_id TEXT,
    reply_status TEXT,
    reply_quote TEXT,
    reply_checked_at TEXT,
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
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    at TEXT NOT NULL
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


# --- dialect ----------------------------------------------------------------

def is_postgres():
    return bool(config.get("DATABASE_URL"))


def _q(sql):
    """SQLite takes ? placeholders, Postgres takes %s. One source of truth above."""
    return sql.replace("?", "%s") if is_postgres() else sql


def schema_statements():
    sql = SCHEMA
    if is_postgres():
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    return [s.strip() for s in sql.split(";") if s.strip()]


def _insert_id(conn, sql, vals):
    """Insert and return the new row's id, whichever database this is."""
    if is_postgres():
        return conn.execute(_q(sql) + " RETURNING id", vals).fetchone()["id"]
    return conn.execute(sql, vals).lastrowid


def _upsert(conn, table, keys, cols, vals):
    """INSERT OR REPLACE on SQLite, ON CONFLICT DO UPDATE on Postgres."""
    names = ",".join(keys + cols)
    marks = ",".join("?" for _ in range(len(keys) + len(cols)))
    if is_postgres():
        sets = ",".join(f"{c}=EXCLUDED.{c}" for c in cols)
        sql = (f"INSERT INTO {table} ({names}) VALUES ({marks})"
               f" ON CONFLICT ({','.join(keys)}) DO UPDATE SET {sets}")
    else:
        sql = f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({marks})"
    conn.execute(_q(sql), vals)


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect():
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            config.get("DATABASE_URL"), row_factory=dict_row, connect_timeout=10
        )
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


_SCHEMA_READY = False


def declared_columns(statement):
    """The (name, type) pairs a CREATE TABLE statement declares."""
    body = statement.split("(", 1)[1].rsplit(")", 1)[0]
    out = []
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.upper().startswith(("PRIMARY", "FOREIGN", "UNIQUE", "CHECK")):
            continue
        parts = line.split()
        out.append((parts[0], " ".join(parts[1:])))
    return out


def existing_columns(conn, table):
    if is_postgres():
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns WHERE table_name=%s",
            (table,),
        ).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def init():
    """Create the tables, then add any column a release has since introduced.

    CREATE TABLE IF NOT EXISTS does nothing to a table that already exists, so a new
    column would never reach a database that had already been created. Only nullable
    columns are added this way; anything NOT NULL needs a deliberate migration.
    """
    with connect() as conn:
        for statement in schema_statements():
            conn.execute(statement)
            table = statement.split("IF NOT EXISTS")[1].split("(")[0].strip()
            present = existing_columns(conn, table)
            for name, coltype in declared_columns(statement):
                if name in present or "NOT NULL" in coltype.upper():
                    continue
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")


def ensure_schema():
    """Create the tables once per process, on first use rather than at startup.

    A serverless cold start that cannot reach the database must fail as a readable
    error on the request, not as a dead function with no explanation.
    """
    global _SCHEMA_READY
    if not _SCHEMA_READY:
        init()
        _SCHEMA_READY = True


def log(event, detail="", company_id=None, run_id=None):
    with connect() as conn:
        conn.execute(
            _q("INSERT INTO decision_log (company_id, run_id, at, event, detail)"
               " VALUES (?,?,?,?,?)"),
            (company_id, run_id, utcnow(), event, detail),
        )


def create_run(domain_count):
    with connect() as conn:
        return _insert_id(
            conn,
            "INSERT INTO runs (started_at, domain_count) VALUES (?,?)",
            (utcnow(), domain_count),
        )


def latest_run_id():
    with connect() as conn:
        row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"] if row else None


def count_companies(run_id):
    with connect() as conn:
        row = conn.execute(
            _q("SELECT COUNT(*) AS n FROM companies WHERE run_id=?"), (run_id,)
        ).fetchone()
        return row["n"]


def set_run_count(run_id, count):
    with connect() as conn:
        conn.execute(_q("UPDATE runs SET domain_count=? WHERE id=?"), (count, run_id))


def run_exists(run_id):
    with connect() as conn:
        return conn.execute(
            _q("SELECT 1 FROM runs WHERE id=?"), (run_id,)
        ).fetchone() is not None


def insert_company(run_id, domain, status, **fields):
    cols = ["run_id", "domain", "status", "created_at"]
    vals = [run_id, domain, status, utcnow()]
    for key, value in fields.items():
        cols.append(key)
        vals.append(json.dumps(value) if key.endswith("_json") else value)
    placeholders = ",".join("?" for _ in cols)
    with connect() as conn:
        return _insert_id(
            conn,
            f"INSERT INTO companies ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )


def update_company(company_id, **fields):
    if not fields:
        return
    sets, vals = [], []
    for key, value in fields.items():
        sets.append(f"{key}=?")
        vals.append(json.dumps(value) if key.endswith("_json") else value)
    vals.append(company_id)
    with connect() as conn:
        conn.execute(_q(f"UPDATE companies SET {','.join(sets)} WHERE id=?"), vals)


def get_company(company_id):
    with connect() as conn:
        return conn.execute(
            _q("SELECT * FROM companies WHERE id=?"), (company_id,)
        ).fetchone()


def companies_for_run(run_id):
    with connect() as conn:
        return conn.execute(
            _q("SELECT * FROM companies WHERE run_id=? ORDER BY id"), (run_id,)
        ).fetchall()


# --- caches -----------------------------------------------------------------
# These live in the durable database on purpose: a cold start must not spend
# another of the month's Hunter searches on a domain we have already looked up.

def hunter_cached(domain):
    with connect() as conn:
        row = conn.execute(
            _q("SELECT response_json, fetched_at FROM hunter_cache WHERE domain=?"),
            (domain,),
        ).fetchone()
        return (json.loads(row["response_json"]), row["fetched_at"]) if row else (None, None)


def hunter_store(domain, response):
    with connect() as conn:
        _upsert(conn, "hunter_cache", ["domain"], ["response_json", "fetched_at"],
                (domain, json.dumps(response), utcnow()))


def news_cached(company, query):
    with connect() as conn:
        row = conn.execute(
            _q("SELECT headlines_json FROM news_cache WHERE company=? AND query=?"),
            (company, query),
        ).fetchone()
        return json.loads(row["headlines_json"]) if row else None


def news_store(company, query, headlines):
    with connect() as conn:
        _upsert(conn, "news_cache", ["company", "query"], ["headlines_json", "fetched_at"],
                (company, query, json.dumps(headlines), utcnow()))


# --- the passcode gate ------------------------------------------------------

def record_login_failure(ip):
    with connect() as conn:
        conn.execute(_q("INSERT INTO login_attempts (ip, at) VALUES (?,?)"),
                     (ip, utcnow()))


def recent_login_failures(ip, since):
    with connect() as conn:
        row = conn.execute(
            _q("SELECT COUNT(*) AS n FROM login_attempts WHERE ip=? AND at >= ?"),
            (ip, since),
        ).fetchone()
        return row["n"]


def clear_login_failures(ip):
    with connect() as conn:
        conn.execute(_q("DELETE FROM login_attempts WHERE ip=?"), (ip,))


# --- sending ----------------------------------------------------------------

def record_send(company_id, to_address):
    now = utcnow()
    with connect() as conn:
        conn.execute(
            _q("INSERT INTO send_log (company_id, sent_at, to_address) VALUES (?,?,?)"),
            (company_id, now, to_address),
        )
    return now


def sent_awaiting_reply():
    """Companies whose email went out and whose reply we have not classified yet."""
    with connect() as conn:
        return conn.execute(
            _q("SELECT * FROM companies WHERE status='sent'"
               " AND (reply_status IS NULL OR reply_status='no_reply')"
               " ORDER BY id")
        ).fetchall()


def sends_today(day_start_utc):
    """Count sends since the given UTC timestamp (the start of today in India time)."""
    with connect() as conn:
        row = conn.execute(
            _q("SELECT COUNT(*) AS n FROM send_log WHERE sent_at >= ?"), (day_start_utc,)
        ).fetchone()
        return row["n"]


def sent_rows(limit=50):
    with connect() as conn:
        return conn.execute(
            _q("SELECT s.sent_at, s.to_address, c.id AS company_id, c.domain,"
               " c.company_name, c.email_subject, c.reply_status, c.reply_quote,"
               " c.reply_checked_at"
               " FROM send_log s LEFT JOIN companies c ON c.id = s.company_id"
               " ORDER BY s.id DESC LIMIT ?"),
            (limit,),
        ).fetchall()
