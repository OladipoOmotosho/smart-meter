"""Task 7.1: schema versions, migrations and the submission journal (R5.1-R5.2).

Every case uses a real temporary SQLite file and reopens it where persistence
matters; `:memory:` would not prove durability.
"""

import sqlite3

import pytest
from smart_meter import db
from smart_meter.fingerprint import KEY_DOMAIN, digest, record_key
from smart_meter.models import Reading, SubmissionState

pytestmark = pytest.mark.sqlite

READING = Reading("J-METER", "2022-01-01T00:00:00Z", 60, "Wh", 3)
KEY = record_key(READING.meter_id, READING.interval_start)
DIGEST = digest(READING)
VERSION = KEY_DOMAIN
RUN = "run-1"
TX = "0x" + "ab" * 32
SENDER = "0x" + "11" * 20
LEGACY_SCHEMA = """
CREATE TABLE readings (
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


@pytest.fixture
def path(tmp_path):
    return tmp_path / "readings.sqlite"


def _open(path):
    return db.connect(path)


def _prepare(conn, reading=READING, key=KEY, value=DIGEST, run=RUN):
    return db.prepare_submission(conn, run, reading, key, value, VERSION)


def _tables(conn):
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    }


# --- Migrations ---------------------------------------------------------------


def test_new_database_is_created_at_current_version_and_reopens(path):
    conn = _open(path)
    assert db.schema_version(conn) == db.SCHEMA_VERSION == 1
    assert _tables(conn) == {"readings", "submissions", "submission_attempts"}
    conn.close()
    conn = _open(path)  # reopening does not re-run or fail
    assert db.schema_version(conn) == 1
    conn.close()


def test_legacy_readings_database_is_migrated_without_changing_rows(path):
    legacy = sqlite3.connect(path)
    legacy.executescript(LEGACY_SCHEMA)
    legacy.execute(
        "INSERT INTO readings (meter_id, interval_start, value_wh, unit, seq, stored_at)"
        " VALUES ('O''Brien', '2022-01-01T00:00:00Z', 7, 'Wh', 0, 'then')"
    )
    legacy.commit()
    before = list(legacy.execute("SELECT * FROM readings"))
    legacy.close()

    conn = _open(path)
    assert db.schema_version(conn) == 1
    assert [tuple(row) for row in conn.execute("SELECT * FROM readings")] == before
    assert db.get_reading(conn, "O'Brien", "2022-01-01T00:00:00Z").value_wh == 7
    conn.close()


@pytest.mark.parametrize(
    "setup",
    [
        "PRAGMA user_version = 99",
        "CREATE TABLE readings (meter_id TEXT, value REAL)",
        "CREATE TABLE something_else (x)",
    ],
    ids=["newer-version", "unexpected-columns", "unexpected-table"],
)
def test_unrecognized_schema_is_refused_and_file_untouched(path, setup):
    raw = sqlite3.connect(path)
    raw.execute(setup)
    raw.commit()
    raw.close()
    before = path.read_bytes()
    with pytest.raises(db.SchemaError):
        _open(path)
    assert path.read_bytes() == before


def test_failed_migration_rolls_back_completely(path, monkeypatch):
    _open(path).close()
    broken = (2, ("CREATE TABLE partial (x)", "THIS IS NOT SQL"))
    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, broken])
    monkeypatch.setattr(db, "SCHEMA_VERSION", 2)
    with pytest.raises(db.SchemaError, match="version 2"):
        _open(path)
    monkeypatch.undo()
    conn = _open(path)
    assert db.schema_version(conn) == 1
    assert "partial" not in _tables(conn)
    conn.close()


# --- Prepared intents ---------------------------------------------------------


def test_prepared_intent_and_reading_round_trip_exactly_after_reopen(path):
    conn = _open(path)
    created = _prepare(conn)
    conn.close()
    conn = _open(path)
    stored = db.get_submission(conn, RUN, KEY)
    assert stored == created
    assert stored.state is SubmissionState.PREPARED
    assert type(stored.record_key) is bytes and stored.record_key == KEY
    assert type(stored.digest) is bytes and stored.digest == DIGEST
    assert (stored.meter_id, stored.interval_start, stored.seq) == (
        READING.meter_id,
        READING.interval_start,
        READING.seq,
    )
    assert db.get_reading(conn, READING.meter_id, READING.interval_start) == READING
    conn.close()


def test_identical_prepare_is_idempotent(path):
    conn = _open(path)
    first = _prepare(conn)
    assert _prepare(conn) == first
    assert len(db.list_submissions(conn, RUN)) == 1
    assert db.all_keys(conn) == [(READING.meter_id, READING.interval_start)]
    conn.close()


@pytest.mark.parametrize(
    ("reading", "value", "message"),
    [
        (
            Reading(READING.meter_id, READING.interval_start, 61, "Wh", 3),
            None,
            "reading",
        ),
        (READING, bytes(32), "intent"),
        (
            Reading(READING.meter_id, READING.interval_start, 60, "Wh", 4),
            None,
            "reading",
        ),
    ],
    ids=["changed-value", "changed-digest", "changed-seq"],
)
def test_conflicting_prepare_changes_nothing(path, reading, value, message):
    conn = _open(path)
    _prepare(conn)
    before = list(conn.iterdump())
    with pytest.raises(db.ConflictError, match=message):
        _prepare(conn, reading=reading, value=value or digest(reading))
    assert list(conn.iterdump()) == before
    conn.close()


def test_failed_intent_insert_does_not_leave_the_reading(path):
    conn = _open(path)
    with pytest.raises(sqlite3.IntegrityError):
        _prepare(conn, key=b"short")  # violates the 32-byte key check
    assert db.get_reading(conn, READING.meter_id, READING.interval_start) is None
    assert db.list_submissions(conn, RUN) == []
    conn.close()


def test_runs_are_journaled_separately(path):
    conn = _open(path)
    _prepare(conn, run="run-a")
    _prepare(conn, run="run-b")
    assert [s.run_id for s in db.list_submissions(conn, "run-a")] == ["run-a"]
    assert [s.run_id for s in db.list_submissions(conn, "run-b")] == ["run-b"]
    conn.close()


def test_hostile_text_is_parameterized(path):
    hostile = Reading("x'); DROP TABLE readings; --", "2022-01-01T00:00:00Z", 1)
    conn = _open(path)
    db.prepare_submission(
        conn,
        RUN,
        hostile,
        record_key(hostile.meter_id, hostile.interval_start),
        digest(hostile),
        VERSION,
    )
    assert db.get_reading(conn, hostile.meter_id, hostile.interval_start) == hostile
    assert "readings" in _tables(conn)
    conn.close()


# --- Attempts and transitions -------------------------------------------------


def _attempt(conn, tx=TX, nonce=5):
    db.record_attempt(
        conn, RUN, KEY, tx_hash=tx, sender=SENDER, nonce=nonce, raw_tx=b"\x02signed"
    )


def test_submitted_attempt_survives_reopen_before_any_outcome(path):
    conn = _open(path)
    _prepare(conn)
    _attempt(conn)
    conn.close()
    conn = _open(path)
    assert db.get_submission(conn, RUN, KEY).state is SubmissionState.SUBMITTED
    (attempt,) = db.attempts(conn, RUN, KEY)
    assert (attempt.tx_hash, attempt.sender, attempt.nonce) == (TX, SENDER, 5)
    assert attempt.raw_tx == b"\x02signed" and attempt.outcome is None
    conn.close()


def test_confirmed_outcome_stores_receipt_evidence(path):
    conn = _open(path)
    _prepare(conn)
    _attempt(conn)
    db.record_outcome(
        conn,
        RUN,
        KEY,
        SubmissionState.CONFIRMED,
        tx_hash=TX,
        outcome="SUCCEEDED",
        receipt_status=1,
        block_number=12,
        block_hash="0x" + "cd" * 32,
        gas_used=48000,
        reason="mined with status 1",
    )
    conn.close()
    conn = _open(path)
    (attempt,) = db.attempts(conn, RUN, KEY)
    assert (attempt.receipt_status, attempt.block_number, attempt.gas_used) == (
        1,
        12,
        48000,
    )
    assert db.get_submission(conn, RUN, KEY).state is SubmissionState.CONFIRMED
    conn.close()


def test_retry_after_failure_keeps_first_attempts_evidence(path):
    conn = _open(path)
    _prepare(conn)
    _attempt(conn)
    db.record_outcome(
        conn,
        RUN,
        KEY,
        SubmissionState.FAILED,
        tx_hash=TX,
        outcome="REVERTED",
        receipt_status=0,
        block_number=7,
        block_hash="0x" + "ee" * 32,
        gas_used=30000,
        reason="mined with status 0",
    )
    retry = "0x" + "cd" * 32
    _attempt(conn, tx=retry, nonce=6)
    first, second = db.attempts(conn, RUN, KEY)
    assert (first.tx_hash, first.receipt_status, first.outcome) == (TX, 0, "REVERTED")
    assert (second.tx_hash, second.outcome) == (retry, None)
    assert db.get_submission(conn, RUN, KEY).state is SubmissionState.SUBMITTED
    conn.close()


def test_resubmission_records_a_reason_and_failed_can_be_confirmed(path):
    conn = _open(path)
    _prepare(conn)
    _attempt(conn)
    db.record_outcome(conn, RUN, KEY, SubmissionState.FAILED, reason="status 0")
    _attempt(conn, tx="0x" + "cd" * 32, nonce=6)
    assert db.get_submission(conn, RUN, KEY).reason == "submitted 0x" + "cd" * 32
    db.record_outcome(conn, RUN, KEY, SubmissionState.FAILED, reason="status 0")
    db.record_outcome(conn, RUN, KEY, SubmissionState.CONFIRMED, reason="reconciled")
    assert db.get_submission(conn, RUN, KEY).state is SubmissionState.CONFIRMED
    conn.close()


def test_identical_rebroadcast_does_not_duplicate_the_attempt(path):
    conn = _open(path)
    _prepare(conn)
    _attempt(conn)
    db.record_outcome(conn, RUN, KEY, SubmissionState.UNCERTAIN, reason="timeout")
    _attempt(conn)  # same signed transaction again
    assert len(db.attempts(conn, RUN, KEY)) == 1
    conn.close()


@pytest.mark.parametrize(
    ("steps", "target"),
    [
        ([], SubmissionState.UNCERTAIN),  # PREPARED -> UNCERTAIN
        (["submit", "confirm"], SubmissionState.SUBMITTED),  # CONFIRMED is terminal
        (["submit", "confirm"], SubmissionState.FAILED),
        (["submit"], SubmissionState.PREPARED),
    ],
    ids=[
        "prepared-uncertain",
        "confirmed-resubmit",
        "confirmed-failed",
        "back-to-prepared",
    ],
)
def test_invalid_transitions_are_rejected_and_change_nothing(path, steps, target):
    conn = _open(path)
    _prepare(conn)
    if "submit" in steps:
        _attempt(conn)
    if "confirm" in steps:
        db.record_outcome(conn, RUN, KEY, SubmissionState.CONFIRMED)
    before = list(conn.iterdump())
    with pytest.raises(db.JournalError, match="invalid journal transition"):
        if target is SubmissionState.SUBMITTED:
            _attempt(conn, tx="0x" + "99" * 32)
        else:
            db.record_outcome(conn, RUN, KEY, target)
    assert list(conn.iterdump()) == before
    conn.close()


def test_outcome_for_unknown_attempt_rolls_back_state_change(path):
    conn = _open(path)
    _prepare(conn)
    _attempt(conn)
    with pytest.raises(db.JournalError, match="not an attempt"):
        db.record_outcome(
            conn, RUN, KEY, SubmissionState.CONFIRMED, tx_hash="0x" + "00" * 32
        )
    assert db.get_submission(conn, RUN, KEY).state is SubmissionState.SUBMITTED
    conn.close()


def test_missing_intent_and_long_reason_are_handled(path):
    conn = _open(path)
    with pytest.raises(db.JournalError, match="no journal intent"):
        _attempt(conn)
    _prepare(conn)
    db.record_outcome(conn, RUN, KEY, SubmissionState.FAILED, reason="x" * 2000)
    assert len(db.get_submission(conn, RUN, KEY).reason) == db.MAX_REASON
    conn.close()


def test_journal_schema_has_no_private_key_column(path):
    conn = _open(path)
    for table in ("submissions", "submission_attempts"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert not any(
            "private" in c or (c.endswith("_key") and c != "record_key")
            for c in columns
        )
    conn.close()


# --- Review B04: remaining journal guards -------------------------------------


def test_non_text_stored_identity_field_is_an_error(path):
    conn = _open(path)
    _prepare(conn)
    conn.execute("UPDATE readings SET unit = x'5768'")  # BLOB keeps its type
    with pytest.raises(TypeError, match="unit must be text"):
        db.get_reading(conn, READING.meter_id, READING.interval_start)
    conn.close()


def test_transaction_hash_cannot_move_to_another_submission(path):
    conn = _open(path)
    _prepare(conn)
    _attempt(conn)
    other = Reading("J-OTHER", "2022-01-01T00:00:00Z", 1)
    other_key = record_key(other.meter_id, other.interval_start)
    db.prepare_submission(conn, RUN, other, other_key, digest(other), VERSION)
    before = list(conn.iterdump())
    with pytest.raises(db.JournalError, match="belongs to another submission"):
        db.record_attempt(
            conn, RUN, other_key, tx_hash=TX, sender=SENDER, nonce=9, raw_tx=b"x"
        )
    assert list(conn.iterdump()) == before
    conn.close()


def test_in_memory_database_is_supported_for_quick_checks():
    conn = db.connect(":memory:")
    assert db.schema_version(conn) == db.SCHEMA_VERSION
    conn.close()
