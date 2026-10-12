"""SQLite stand-in for the utility's meter database. [provided]

This is the off-chain store, and the thing the insider attack edits.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Reading

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    record_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id       TEXT    NOT NULL,
    interval_start TEXT    NOT NULL,
    value_wh       INTEGER NOT NULL,
    unit           TEXT    NOT NULL,
    seq            INTEGER NOT NULL,
    stored_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (meter_id, interval_start)
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (or create) the database. Use ':memory:' for tests."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def insert_reading(conn: sqlite3.Connection, r: Reading) -> int:
    """Store one reading and return its record_id."""
    cur = conn.execute(
        "INSERT INTO readings (meter_id, interval_start, value_wh, unit, seq) VALUES (?, ?, ?, ?, ?)",
        (r.meter_id, r.interval_start, r.value_wh, r.unit, r.seq),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_reading(conn: sqlite3.Connection, meter_id: str, interval_start: str) -> Reading | None:
    """Read back one stored reading, exactly as the database holds it now."""
    row = conn.execute(
        "SELECT meter_id, interval_start, value_wh, unit, seq FROM readings "
        "WHERE meter_id = ? AND interval_start = ?",
        (meter_id, interval_start),
    ).fetchone()
    if row is None:
        return None
    return Reading(row["meter_id"], row["interval_start"], int(row["value_wh"]), row["unit"], int(row["seq"]))


def all_keys(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every (meter_id, interval_start) pair in storage order."""
    rows = conn.execute("SELECT meter_id, interval_start FROM readings ORDER BY record_id").fetchall()
    return [(row["meter_id"], row["interval_start"]) for row in rows]
