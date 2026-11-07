"""Local behavioral tests for ingestion, SQLite persistence and audit outcomes."""

from dataclasses import replace

import pytest
from smart_meter import chain, db
from smart_meter.aggregator import ingest
from smart_meter.fingerprint import digest, record_key
from smart_meter.models import Reading, Verdict
from smart_meter.verifier import verify

READING = Reading("M1", "2022-01-01T00:00:00Z", 60)


class ReadCall:
    def __init__(self, registry, key):
        self.registry, self.key = registry, key

    def call(self):
        if self.registry.error:
            raise OSError("RPC unavailable")
        return (self.registry.entries.get(self.key, bytes(32)), 1, "writer")


class Functions:
    def __init__(self, registry):
        self.registry = registry

    def getCommitment(self, key):
        return ReadCall(self.registry, key)

    def commit(self, key, value):
        return key, value


class Registry:
    def __init__(self):
        self.entries = {}
        self.error = False
        self.functions = Functions(self)


@pytest.fixture
def local(tmp_path):
    conn = db.connect(tmp_path / "readings.sqlite")
    registry = Registry()
    try:
        yield conn, registry, tmp_path
    finally:
        conn.close()


def _send_success(monkeypatch, registry):
    def send(_w3, call, _key):
        key, value = call
        registry.entries[key] = value
        return chain.TxResult("0x1234", 120000, 0.01, 1)

    monkeypatch.setattr(chain, "send_tx", send)


def _ingest(local, reading=READING):
    conn, registry, temp = local
    return ingest([reading], conn, None, registry, "throwaway", temp / "results.csv")


def test_new_commit_and_identical_resume_use_one_anchor(local, monkeypatch):
    conn, registry, temp = local
    _send_success(monkeypatch, registry)
    first = _ingest(local)
    second = _ingest(local)
    assert (first.attempted, first.newly_confirmed, first.reconciled) == (1, 1, 0)
    assert (second.attempted, second.newly_confirmed, second.reconciled) == (1, 0, 1)
    assert db.get_reading(conn, READING.meter_id, READING.interval_start) == READING
    assert db.all_keys(conn) == [(READING.meter_id, READING.interval_start)]
    assert len((temp / "results.csv").read_text().splitlines()) == 2


def test_local_conflict_stops_before_chain_write(local, monkeypatch):
    db.insert_reading(local[0], replace(READING, value_wh=61))
    monkeypatch.setattr(chain, "send_tx", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(ValueError, match="conflicting stored"):
        _ingest(local)


def test_chain_conflict_stops_before_chain_write(local, monkeypatch):
    local[1].entries[record_key(READING.meter_id, READING.interval_start)] = (
        bytes.fromhex("11" * 32)
    )
    monkeypatch.setattr(chain, "send_tx", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(ValueError, match="conflicting registry"):
        _ingest(local)


@pytest.mark.parametrize(
    "reading",
    [
        replace(READING, unit="kWh"),
        replace(READING, interval_start="2022-01-01T00:01:00Z"),
    ],
)
def test_ingestion_rejects_wrong_unit_or_interval(local, reading):
    with pytest.raises(ValueError, match=r"hourly UTC Wh|canonical hourly UTC"):
        _ingest(local, reading)


@pytest.mark.parametrize(
    "reading",
    [
        replace(READING, meter_id=""),
        replace(READING, interval_start="garbage:00:00Z"),
        replace(READING, interval_start="2022-02-30T00:00:00Z"),
    ],
)
def test_ingestion_rejects_invalid_identity_before_side_effects(
    local, monkeypatch, reading
):
    monkeypatch.setattr(chain, "send_tx", lambda *_: pytest.fail("unexpected write"))

    with pytest.raises(ValueError, match=r"valid meter ID|canonical hourly UTC"):
        _ingest(local, reading)

    assert db.all_keys(local[0]) == []
    assert local[1].entries == {}


def test_status_zero_never_confirms(local, monkeypatch):
    monkeypatch.setattr(
        chain, "send_tx", lambda *_: chain.TxResult("0xdead", 120000, 0.01, 0)
    )
    with pytest.raises(ValueError, match="transaction reverted"):
        _ingest(local)


def test_mismatching_confirmation_never_confirms(local, monkeypatch):
    def wrong(_w3, call, _key):
        local[1].entries[call[0]] = bytes.fromhex("22" * 32)
        return chain.TxResult("0x1234", 120000, 0.01, 1)

    monkeypatch.setattr(chain, "send_tx", wrong)
    with pytest.raises(ValueError, match="confirmation mismatch"):
        _ingest(local)


def test_matching_and_tampered_audit_are_distinct(local, monkeypatch):
    _send_success(monkeypatch, local[1])
    _ingest(local)
    result = verify(
        local[0],
        local[1],
        READING.meter_id,
        READING.interval_start,
        local[2] / "audit.csv",
    )
    assert result.outcome == Verdict.VERIFIED
    assert result.observed_digest == digest(READING).hex()
    local[0].execute("UPDATE readings SET value_wh=61")
    local[0].commit()
    assert (
        verify(local[0], local[1], READING.meter_id, READING.interval_start).outcome
        == Verdict.TAMPERED
    )


def test_missing_combinations(local):
    conn, registry, _ = local
    assert (
        verify(conn, registry, READING.meter_id, READING.interval_start).outcome
        == Verdict.MISSING_BOTH
    )
    db.insert_reading(conn, READING)
    assert (
        verify(conn, registry, READING.meter_id, READING.interval_start).outcome
        == Verdict.MISSING_COMMITMENT
    )
    conn.execute("DELETE FROM readings")
    conn.commit()
    registry.entries[record_key(READING.meter_id, READING.interval_start)] = digest(
        READING
    )
    assert (
        verify(conn, registry, READING.meter_id, READING.interval_start).outcome
        == Verdict.MISSING_RECORD
    )


def test_corrupt_record_and_unavailable_registry_are_errors(local):
    conn, registry, _ = local
    db.insert_reading(conn, READING)
    conn.execute("UPDATE readings SET value_wh='invalid'")
    conn.commit()
    assert (
        verify(conn, registry, READING.meter_id, READING.interval_start).outcome
        == Verdict.ERROR
    )
    conn.execute("UPDATE readings SET value_wh=60")
    conn.commit()
    registry.error = True
    assert (
        verify(conn, registry, READING.meter_id, READING.interval_start).outcome
        == Verdict.ERROR
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [("value_wh", 60.9), ("seq", 0.5)],
)
def test_fractional_stored_integer_is_an_audit_error(local, monkeypatch, column, value):
    _send_success(monkeypatch, local[1])
    _ingest(local)
    local[0].execute(f"UPDATE readings SET {column} = ?", (value,))
    local[0].commit()

    result = verify(local[0], local[1], READING.meter_id, READING.interval_start)

    assert result.outcome == Verdict.ERROR
    assert "record read" in result.reason


@pytest.mark.parametrize("entry", [(), ("bad", 1, "writer"), (b"short", 1, "writer")])
def test_malformed_registry_response_is_error(local, entry):
    class BadCall:
        def call(self):
            return entry

    local[1].functions.getCommitment = lambda _key: BadCall()
    assert (
        verify(local[0], local[1], READING.meter_id, READING.interval_start).outcome
        == Verdict.ERROR
    )


def test_closed_database_is_error(local):
    local[0].close()
    assert (
        verify(local[0], local[1], READING.meter_id, READING.interval_start).outcome
        == Verdict.ERROR
    )
