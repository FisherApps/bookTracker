"""SQLite database for BSR snapshots and failures."""

import sqlite3
from pathlib import Path

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asin          TEXT    NOT NULL,
    captured_at   TEXT    NOT NULL,
    capture_date  TEXT    NOT NULL,
    category_id   TEXT    NOT NULL,
    category_name TEXT    NOT NULL,
    rank          INTEGER NOT NULL,
    UNIQUE (asin, capture_date, category_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_asin_date ON snapshots (asin, capture_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_category  ON snapshots (category_id, capture_date);

CREATE TABLE IF NOT EXISTS failures (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asin          TEXT    NOT NULL,
    attempted_at  TEXT    NOT NULL,
    reason        TEXT    NOT NULL,
    http_status   INTEGER,
    detail        TEXT
);

CREATE INDEX IF NOT EXISTS idx_failures_asin_date ON failures (asin, attempted_at);
"""


def get_connection(db_path: str | Path = "bsr.db") -> sqlite3.Connection:
    """Open (or create) the database and ensure schema exists."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    return conn


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    asin: str,
    captured_at: str,
    capture_date: str,
    category_id: str,
    category_name: str,
    rank: int,
) -> bool:
    """Insert a snapshot row. Returns True if inserted, False if duplicate."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO snapshots "
        "(asin, captured_at, capture_date, category_id, category_name, rank) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (asin, captured_at, capture_date, category_id, category_name, rank),
    )
    conn.commit()
    return cursor.rowcount == 1


def insert_failure(
    conn: sqlite3.Connection,
    *,
    asin: str,
    attempted_at: str,
    reason: str,
    http_status: int | None = None,
    detail: str | None = None,
) -> None:
    """Insert a failure row."""
    conn.execute(
        "INSERT INTO failures (asin, attempted_at, reason, http_status, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (asin, attempted_at, reason, http_status, detail),
    )
    conn.commit()


def query_snapshots(conn: sqlite3.Connection, asin: str) -> list[sqlite3.Row]:
    """Return all snapshots for an ASIN, ordered by capture_date."""
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM snapshots WHERE asin = ? ORDER BY capture_date",
        (asin,),
    )
    return cursor.fetchall()
