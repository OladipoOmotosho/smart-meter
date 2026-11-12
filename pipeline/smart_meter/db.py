"""SQLite readings store and submission journal (Task 7.1, R5.1-R5.2).

`readings` is the off-chain store the insider attack edits; its definition is
unchanged so attack scenarios can still alter values. The journal records each
intended commitment and every signed attempt before network submission, so an
interrupted run can be reconciled. Schema versions use `PRAGMA user_version`
and ordered migrations that run in one transaction each.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import Reading, SubmissionState

READINGS_TABLE = """
CREATE TABLE IF NOT EXISTS readings (
    record_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id       TEXT    NOT NULL,
    interval_start TEXT    NOT NULL,
    value_wh       INTEGER NOT NULL,
    unit           TEXT    NOT NULL,
    seq            INTEGER NOT NULL,
    stored_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (meter_id, interval_start)
)
"""
LEGACY_READINGS_COLUMNS = (
    "record_id",
    "meter_id",
    "interval_start",
    "value_wh",
    "unit",
    "seq",
    "stored_at",
)
_STATES = ", ".join(f"'{state.value}'" for state in SubmissionState)
_NOW = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"

# Ordered migrations: (target version, statements). Never edit a released step.
MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            READINGS_TABLE,
            f"""
            CREATE TABLE submissions (
                submission_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id            TEXT    NOT NULL
                    CHECK (typeof(run_id) = 'text' AND length(run_id) BETWEEN 1 AND 64),
                record_key        BLOB    NOT NULL
                    CHECK (typeof(record_key) = 'blob' AND length(record_key) = 32),
                digest            BLOB    NOT NULL
                    CHECK (typeof(digest) = 'blob' AND length(digest) = 32),
                canonical_version TEXT    NOT NULL CHECK (length(canonical_version) > 0),
                meter_id          TEXT    NOT NULL CHECK (typeof(meter_id) = 'text'),
                interval_start    TEXT    NOT NULL CHECK (typeof(interval_start) = 'text'),
                seq               INTEGER NOT NULL
                    CHECK (typeof(seq) = 'integer' AND seq >= 0),
                state             TEXT    NOT NULL CHECK (state IN ({_STATES})),
                reason            TEXT    CHECK (reason IS NULL OR length(reason) <= 500),
                created_at        TEXT    NOT NULL DEFAULT {_NOW},
                updated_at        TEXT    NOT NULL DEFAULT {_NOW},
                UNIQUE (run_id, record_key)
            )
            """,
            f"""
            CREATE TABLE submission_attempts (
                attempt_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id  INTEGER NOT NULL REFERENCES submissions (submission_id),
                tx_hash        TEXT    NOT NULL UNIQUE
                    CHECK (length(tx_hash) = 66 AND tx_hash LIKE '0x%'),
                sender         TEXT    NOT NULL CHECK (length(sender) = 42),
                nonce          INTEGER NOT NULL
                    CHECK (typeof(nonce) = 'integer' AND nonce >= 0),
                raw_tx         BLOB    NOT NULL CHECK (typeof(raw_tx) = 'blob'),
                outcome        TEXT    CHECK (outcome IS NULL OR outcome IN
                    ('SUCCEEDED', 'REVERTED', 'REPLACED', 'UNCERTAIN', 'REJECTED')),
                receipt_status INTEGER CHECK (receipt_status IS NULL OR receipt_status IN (0, 1)),
                block_number   INTEGER CHECK (block_number IS NULL OR block_number >= 0),
                block_hash     TEXT    CHECK (block_hash IS NULL OR length(block_hash) = 66),
                gas_used       INTEGER CHECK (gas_used IS NULL OR gas_used >= 0),
                reason         TEXT    CHECK (reason IS NULL OR length(reason) <= 500),
                created_at     TEXT    NOT NULL DEFAULT {_NOW},
                updated_at     TEXT    NOT NULL DEFAULT {_NOW}
            )
            """,
            "CREATE INDEX attempts_by_submission ON submission_attempts (submission_id)",
        ),
    ),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]
MAX_REASON = 500

# Allowed journal transitions (design section 6).
TRANSITIONS: dict[SubmissionState, frozenset[SubmissionState]] = {
    SubmissionState.PREPARED: frozenset(
        {
            SubmissionState.SUBMITTED,
            SubmissionState.CONFIRMED,  # reconciled: identical commitment already exists
            SubmissionState.FAILED,  # definite preflight rejection
        }
    ),
    SubmissionState.SUBMITTED: frozenset(
        {SubmissionState.CONFIRMED, SubmissionState.FAILED, SubmissionState.UNCERTAIN}
    ),
    SubmissionState.UNCERTAIN: frozenset(
        {
            SubmissionState.CONFIRMED,
            SubmissionState.FAILED,
            SubmissionState.UNCERTAIN,
            SubmissionState.SUBMITTED,  # rebroadcast of the same signed transaction
        }
    ),
    SubmissionState.FAILED: frozenset(
        {
            SubmissionState.SUBMITTED,  # explicit retry
            SubmissionState.CONFIRMED,  # retry finds the exact commitment on chain
        }
    ),
    SubmissionState.CONFIRMED: frozenset(),
}


class SchemaError(RuntimeError):
    """The database schema is newer, unrecognized or failed to migrate."""


class ConflictError(ValueError):
    """Stored data differs from what this run intends; nothing was replaced."""


class JournalError(ValueError):
    """A journal operation is invalid for the submission's current state."""


@dataclass(frozen=True)
class Submission:
    run_id: str
    record_key: bytes
    digest: bytes
    canonical_version: str
    meter_id: str
    interval_start: str
    seq: int
    state: SubmissionState
    reason: str | None


@dataclass(frozen=True)
class Attempt:
    tx_hash: str
    sender: str
    nonce: int
    raw_tx: bytes
    outcome: str | None
    receipt_status: int | None
    block_number: int | None
    block_hash: str | None
    gas_used: int | None
    reason: str | None


def _bounded(reason: str | None) -> str | None:
    return None if reason is None else reason[:MAX_REASON]


# --- Connection and migrations ----------------------------------------------


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (or create) and migrate the database. Use ':memory:' for tests.

    The connection is in autocommit mode; multi-statement changes use explicit
    transactions so a failure leaves no partial state.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _check_unversioned(conn: sqlite3.Connection) -> None:
    """Accept only an empty file or the original readings-only schema."""
    tables = _tables(conn)
    if not tables:
        return
    if tables != {"readings"}:
        raise SchemaError(
            f"unversioned database has unexpected tables: {sorted(tables)}"
        )
    columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(readings)"))
    if columns != LEGACY_READINGS_COLUMNS:
        raise SchemaError(
            f"unversioned readings table has unexpected columns: {columns}"
        )


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order; refuse newer or unrecognized schemas."""
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise SchemaError(
            f"database schema version {current} is newer than supported {SCHEMA_VERSION}"
        )
    if current == 0:
        _check_unversioned(conn)
    for version, statements in MIGRATIONS:
        if version <= current:
            continue
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
        except sqlite3.Error as error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise SchemaError(
                f"migration to version {version} failed: {error}"
            ) from error
        current = version
    return current


# --- Readings ---------------------------------------------------------------


def insert_reading(conn: sqlite3.Connection, r: Reading) -> int:
    """Store one reading and return its record_id. Never replaces a row."""
    cur = conn.execute(
        "INSERT INTO readings (meter_id, interval_start, value_wh, unit, seq) "
        "VALUES (?, ?, ?, ?, ?)",
        (r.meter_id, r.interval_start, r.value_wh, r.unit, r.seq),
    )
    return int(cur.lastrowid)


def get_reading(
    conn: sqlite3.Connection, meter_id: str, interval_start: str
) -> Reading | None:
    """Read back one stored reading, exactly as the database holds it now."""
    row = conn.execute(
        "SELECT meter_id, interval_start, value_wh, unit, seq FROM readings "
        "WHERE meter_id = ? AND interval_start = ?",
        (meter_id, interval_start),
    ).fetchone()
    if row is None:
        return None
    for column in ("meter_id", "interval_start", "unit"):
        if not isinstance(row[column], str):
            raise TypeError(f"stored {column} must be text")
    for column in ("value_wh", "seq"):
        if type(row[column]) is not int:
            raise TypeError(f"stored {column} must be an integer")
    return Reading(
        row["meter_id"],
        row["interval_start"],
        row["value_wh"],
        row["unit"],
        row["seq"],
    )


def all_keys(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every (meter_id, interval_start) pair in storage order."""
    rows = conn.execute(
        "SELECT meter_id, interval_start FROM readings ORDER BY record_id"
    ).fetchall()
    return [(row["meter_id"], row["interval_start"]) for row in rows]


# --- Submission journal -----------------------------------------------------


def _submission(row: sqlite3.Row) -> Submission:
    return Submission(
        row["run_id"],
        bytes(row["record_key"]),
        bytes(row["digest"]),
        row["canonical_version"],
        row["meter_id"],
        row["interval_start"],
        row["seq"],
        SubmissionState(row["state"]),
        row["reason"],
    )


def _row(conn: sqlite3.Connection, run_id: str, key: bytes) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM submissions WHERE run_id = ? AND record_key = ?",
        (run_id, bytes(key)),
    ).fetchone()


def get_submission(
    conn: sqlite3.Connection, run_id: str, key: bytes
) -> Submission | None:
    row = _row(conn, run_id, key)
    return None if row is None else _submission(row)


def list_submissions(
    conn: sqlite3.Connection,
    run_id: str,
    states: set[SubmissionState] | None = None,
) -> list[Submission]:
    rows = conn.execute(
        "SELECT * FROM submissions WHERE run_id = ? ORDER BY submission_id", (run_id,)
    ).fetchall()
    found = [_submission(row) for row in rows]
    return [s for s in found if states is None or s.state in states]


def attempts(conn: sqlite3.Connection, run_id: str, key: bytes) -> list[Attempt]:
    rows = conn.execute(
        "SELECT a.* FROM submission_attempts a JOIN submissions s "
        "ON a.submission_id = s.submission_id "
        "WHERE s.run_id = ? AND s.record_key = ? ORDER BY a.attempt_id",
        (run_id, bytes(key)),
    ).fetchall()
    return [
        Attempt(
            row["tx_hash"],
            row["sender"],
            row["nonce"],
            bytes(row["raw_tx"]),
            row["outcome"],
            row["receipt_status"],
            row["block_number"],
            row["block_hash"],
            row["gas_used"],
            row["reason"],
        )
        for row in rows
    ]


class _Transaction:
    """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, kind, error, trace) -> None:
        self.conn.execute("ROLLBACK" if kind else "COMMIT")


def prepare_submission(
    conn: sqlite3.Connection,
    run_id: str,
    reading: Reading,
    key: bytes,
    digest: bytes,
    canonical_version: str,
) -> Submission:
    """Atomically store the reading (if new) and a PREPARED intent.

    An identical resume returns the existing intent unchanged. A different
    stored reading or intent raises ConflictError and changes nothing.
    """
    with _Transaction(conn):
        existing = get_reading(conn, reading.meter_id, reading.interval_start)
        if existing is not None and existing != reading:
            raise ConflictError(f"conflicting stored reading for {bytes(key).hex()}")
        if existing is None:
            insert_reading(conn, reading)
        intent = get_submission(conn, run_id, key)
        if intent is not None:
            expected = (
                bytes(digest),
                canonical_version,
                reading.meter_id,
                reading.interval_start,
                reading.seq,
            )
            stored = (
                intent.digest,
                intent.canonical_version,
                intent.meter_id,
                intent.interval_start,
                intent.seq,
            )
            if stored != expected:
                raise ConflictError(
                    f"conflicting journal intent for {bytes(key).hex()}"
                )
            return intent
        conn.execute(
            "INSERT INTO submissions (run_id, record_key, digest, canonical_version, "
            "meter_id, interval_start, seq, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                bytes(key),
                bytes(digest),
                canonical_version,
                reading.meter_id,
                reading.interval_start,
                reading.seq,
                SubmissionState.PREPARED.value,
            ),
        )
        created = get_submission(conn, run_id, key)
    assert created is not None
    return created


def _transition(
    conn: sqlite3.Connection,
    run_id: str,
    key: bytes,
    target: SubmissionState,
    reason: str | None,
) -> sqlite3.Row:
    row = _row(conn, run_id, key)
    if row is None:
        raise JournalError(f"no journal intent for {bytes(key).hex()} in run {run_id}")
    current = SubmissionState(row["state"])
    if target not in TRANSITIONS[current]:
        raise JournalError(f"invalid journal transition {current} -> {target}")
    conn.execute(
        f"UPDATE submissions SET state = ?, reason = ?, updated_at = {_NOW} "
        "WHERE submission_id = ?",
        (target.value, _bounded(reason), row["submission_id"]),
    )
    return row


def record_attempt(
    conn: sqlite3.Connection,
    run_id: str,
    key: bytes,
    *,
    tx_hash: str,
    sender: str,
    nonce: int,
    raw_tx: bytes,
) -> None:
    """Persist a signed transaction's identity before broadcast (-> SUBMITTED).

    Re-recording the same hash (an identical rebroadcast) adds no new attempt.
    """
    with _Transaction(conn):
        row = _transition(
            conn, run_id, key, SubmissionState.SUBMITTED, f"submitted {tx_hash}"
        )
        known = conn.execute(
            "SELECT submission_id FROM submission_attempts WHERE tx_hash = ?",
            (tx_hash,),
        ).fetchone()
        if known is not None:
            if known[0] != row["submission_id"]:
                raise JournalError(f"{tx_hash} belongs to another submission")
            return
        conn.execute(
            "INSERT INTO submission_attempts "
            "(submission_id, tx_hash, sender, nonce, raw_tx) VALUES (?, ?, ?, ?, ?)",
            (row["submission_id"], tx_hash, sender, nonce, bytes(raw_tx)),
        )


def record_outcome(
    conn: sqlite3.Connection,
    run_id: str,
    key: bytes,
    state: SubmissionState,
    *,
    reason: str | None = None,
    tx_hash: str | None = None,
    outcome: str | None = None,
    receipt_status: int | None = None,
    block_number: int | None = None,
    block_hash: str | None = None,
    gas_used: int | None = None,
) -> None:
    """Move the intent to `state` and, when tx_hash is given, store its evidence."""
    with _Transaction(conn):
        row = _transition(conn, run_id, key, state, reason)
        if tx_hash is None:
            return
        updated = conn.execute(
            "UPDATE submission_attempts SET outcome = ?, receipt_status = ?, "
            f"block_number = ?, block_hash = ?, gas_used = ?, reason = ?, updated_at = {_NOW} "
            "WHERE tx_hash = ? AND submission_id = ?",
            (
                outcome,
                receipt_status,
                block_number,
                block_hash,
                gas_used,
                _bounded(reason),
                tx_hash,
                row["submission_id"],
            ),
        )
        if updated.rowcount != 1:
            raise JournalError(f"{tx_hash} is not an attempt of this submission")
