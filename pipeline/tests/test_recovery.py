"""Task 7.4 gate: persistence, crashes and retries (P7-P8, R5.1-R5.6, R7.6).

Crashes are simulated with a BaseException that no pipeline handler catches,
so only transaction rollbacks and the durable journal survive, as after a
process kill. Real temporary SQLite files are reopened between passes.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from helpers import Registry
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from smart_meter import aggregator, chain, db
from smart_meter.config import ARTIFACT_PATH
from smart_meter.fingerprint import KEY_DOMAIN, digest, record_key
from smart_meter.models import Reading, SubmissionState

RUN = "default"
SENDER = "0x" + "11" * 20


class Crash(BaseException):
    """Simulated process death: bypasses every `except Exception` handler."""


def _readings(count):
    return [
        Reading("REC-1", f"2022-01-01T{hour:02d}:00:00Z", 60 + hour, "Wh", hour)
        for hour in range(count)
    ]


class Node:
    """A fake chain with exactly-once registry writes and scripted faults."""

    def __init__(self, registry, conn):
        self.registry, self.conn = registry, conn
        self.signed: dict[str, tuple[bytes, bytes]] = {}
        self.writes: list[bytes] = []
        self.successes_this_pass = 0
        self.script: list[str] = []

    def _next(self):
        return self.script.pop(0) if self.script else "SUCCEEDED"

    def prepare_tx(self, _w3, call, _key, **_):
        action = self.script[0] if self.script else "SUCCEEDED"
        if action == "CRASH_BEFORE_SIGN":
            self.script.pop(0)
            raise Crash
        if action == "PREFLIGHT_REVERT":
            self.script.pop(0)
            raise chain.PreflightError("revert", "denied", SENDER, "0x12")
        if action == "UNAVAILABLE":
            self.script.pop(0)
            raise chain.PreflightError("unavailable", "down", SENDER)
        tx_hash = "0x" + f"{len(self.signed) + 1:064x}"
        self.signed[tx_hash] = call
        return chain.PreparedTx(
            tx_hash, SENDER, len(self.signed), b"raw" + tx_hash.encode()
        )

    def _mine(self, tx_hash):
        key, value = self.signed[tx_hash]
        assert key not in self.registry.entries, "second commitment for one key"
        self.registry.entries[key] = value
        self.writes.append(key)

    def broadcast(self, _w3, prepared, **_):
        journaled = self.conn.execute(
            "SELECT 1 FROM submission_attempts WHERE tx_hash = ?", (prepared.tx_hash,)
        ).fetchone()
        assert journaled, "broadcast before journaling"
        action = self._next()
        ident = (prepared.tx_hash, SENDER, prepared.nonce)
        if action == "CRASH_AFTER_BROADCAST":
            self._mine(prepared.tx_hash)
            raise Crash
        if action == "REJECTED":
            raise chain.BroadcastRejected(prepared, "nonce too low")
        if action == "UNCERTAIN":
            return chain.TxResult(*ident, chain.TxState.UNCERTAIN, "timeout")
        if action == "REVERTED":
            return chain.TxResult(
                *ident,
                chain.TxState.REVERTED,
                "status 0",
                status=0,
                gas_used=1,
                block_number=1,
                block_hash="0x" + "ee" * 32,
            )
        self._mine(prepared.tx_hash)
        self.successes_this_pass += 1
        return chain.TxResult(
            *ident,
            chain.TxState.SUCCEEDED,
            "status 1",
            status=1,
            gas_used=48000,
            block_number=2,
            block_hash="0x" + "ab" * 32,
            seconds=0.01,
        )

    def lookup(self, _w3, tx_hash, sender, nonce):
        key, value = self.signed[tx_hash]
        if self.registry.entries.get(key) == value:
            return chain.TxResult(
                tx_hash,
                sender,
                nonce,
                chain.TxState.SUCCEEDED,
                "mined",
                status=1,
                gas_used=48000,
                block_number=2,
                block_hash="0x" + "ab" * 32,
            )
        return chain.TxResult(
            tx_hash, sender, nonce, chain.TxState.UNCERTAIN, chain.UNKNOWN
        )

    def install(self, monkeypatch):
        monkeypatch.setattr(chain, "prepare_tx", self.prepare_tx)
        monkeypatch.setattr(chain, "broadcast", self.broadcast)
        monkeypatch.setattr(chain, "lookup", self.lookup)


def _pass(path, registry, node, readings, **kwargs):
    """One process lifetime: open the file, ingest, close (even on a crash)."""
    conn = db.connect(path)
    node.conn = conn
    node.successes_this_pass = 0
    try:
        return aggregator.ingest(
            readings,
            conn,
            None,
            registry,
            "throwaway",
            Path(path).with_suffix(".csv"),
            **kwargs,
        )
    finally:
        conn.close()


def _states(path):
    conn = db.connect(path)
    try:
        return {s.record_key: s for s in db.list_submissions(conn, RUN)}
    finally:
        conn.close()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / "journal.sqlite"
    registry = Registry()
    node = Node(registry, None)
    node.install(monkeypatch)
    return path, registry, node


# --- Named crash points -----------------------------------------------------------


def test_crash_before_signing_resumes_with_one_submission(setup):
    path, registry, node = setup
    readings = _readings(1)
    node.script = ["CRASH_BEFORE_SIGN"]
    with pytest.raises(Crash):
        _pass(path, registry, node, readings)
    (sub,) = _states(path).values()
    assert sub.state is SubmissionState.PREPARED and registry.entries == {}
    summary = _pass(path, registry, node, readings)
    assert (summary.newly_confirmed, summary.reconciled) == (1, 0)
    assert len(node.writes) == 1 and len(node.signed) == 1


def test_crash_after_broadcast_reconciles_without_a_second_send(setup):
    path, registry, node = setup
    readings = _readings(2)
    node.script = ["CRASH_AFTER_BROADCAST"]
    with pytest.raises(Crash):
        _pass(path, registry, node, readings)
    states = _states(path)
    first = record_key(readings[0].meter_id, readings[0].interval_start)
    assert states[first].state is SubmissionState.SUBMITTED  # outcome never recorded
    assert node.writes == [first]
    summary = _pass(path, registry, node, readings)
    assert (summary.reconciled, summary.newly_confirmed) == (1, 1)
    assert len(node.signed) == 2  # one per record; the first was never re-signed
    assert sorted(node.writes) == sorted(_states(path))  # each key written once
    assert all(s.state is SubmissionState.CONFIRMED for s in _states(path).values())


def test_journal_write_failure_after_success_reconciles_without_resend(
    setup, monkeypatch
):
    path, registry, node = setup
    readings = _readings(1)
    real = db.record_outcome

    def failing(conn, run_id, key, state, **kwargs):
        if state is SubmissionState.CONFIRMED:
            raise sqlite3.OperationalError("disk I/O error")
        return real(conn, run_id, key, state, **kwargs)

    monkeypatch.setattr(db, "record_outcome", failing)
    with pytest.raises(sqlite3.OperationalError):
        _pass(path, registry, node, readings)
    monkeypatch.setattr(db, "record_outcome", real)
    (sub,) = _states(path).values()
    assert sub.state is SubmissionState.SUBMITTED and len(node.writes) == 1
    summary = _pass(path, registry, node, readings)
    assert (summary.newly_confirmed, summary.reconciled) == (0, 1)
    assert len(node.signed) == 1 and len(node.writes) == 1


def test_original_reading_survives_crash_and_conflicting_resume(setup):
    path, registry, node = setup
    readings = _readings(1)
    node.script = ["CRASH_AFTER_BROADCAST"]
    with pytest.raises(Crash):
        _pass(path, registry, node, readings)
    changed = [Reading(**{**readings[0].__dict__, "value_wh": 999})]
    with pytest.raises(db.ConflictError):
        _pass(path, registry, node, changed)
    conn = db.connect(path)
    try:
        assert (
            db.get_reading(conn, readings[0].meter_id, readings[0].interval_start)
            == (readings[0])
        )
    finally:
        conn.close()
    assert len(node.writes) == 1


# --- P7: storage round-trip -----------------------------------------------------

TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=24
)


@settings(max_examples=200, deadline=None)
@given(
    meter=TEXT,
    value=st.integers(min_value=0, max_value=2**62),
    other=st.integers(min_value=0, max_value=2**62),
    seq=st.integers(min_value=0, max_value=2**31),
    unit=TEXT,
)
def test_p7_reading_round_trips_and_duplicate_cannot_replace(
    meter, value, other, seq, unit
):
    reading = Reading(meter, "2022-01-01T00:00:00Z", value, unit, seq)
    key = record_key(reading.meter_id, reading.interval_start)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "p7.sqlite"
        conn = db.connect(path)
        db.prepare_submission(conn, RUN, reading, key, digest(reading), KEY_DOMAIN)
        conn.close()
        conn = db.connect(path)
        try:
            stored = db.get_reading(conn, meter, reading.interval_start)
            assert stored == reading
            assert digest(stored) == digest(reading)
            if other != value:
                duplicate = Reading(meter, reading.interval_start, other, unit, seq)
                with pytest.raises(db.ConflictError):
                    db.prepare_submission(
                        conn, RUN, duplicate, key, digest(duplicate), KEY_DOMAIN
                    )
            assert db.get_reading(conn, meter, reading.interval_start) == reading
            assert len(db.all_keys(conn)) == 1
        finally:
            conn.close()


# --- P8: honest confirmation across faults and resumes ----------------------------

ACTIONS = st.sampled_from(
    [
        "SUCCEEDED",
        "REVERTED",
        "UNCERTAIN",
        "REJECTED",
        "PREFLIGHT_REVERT",
        "UNAVAILABLE",
        "CRASH_BEFORE_SIGN",
        "CRASH_AFTER_BROADCAST",
    ]
)


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    count=st.integers(min_value=1, max_value=4), script=st.lists(ACTIONS, max_size=8)
)
def test_p8_faults_never_confirm_and_resume_commits_each_key_once(
    monkeypatch, count, script
):
    readings = _readings(count)
    registry = Registry()
    node = Node(registry, None)
    node.install(monkeypatch)
    node.script = list(script)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "p8.sqlite"
        for _ in range(len(script) + count + 2):
            try:
                summary = _pass(path, registry, node, readings, retry_failed=True)
            except (Crash, chain.PreflightError):
                summary = None
            states = _states(path)
            # Every confirmed intent matches the registry; nothing else is there.
            confirmed = {
                k for k, s in states.items() if s.state is SubmissionState.CONFIRMED
            }
            assert confirmed <= set(registry.entries)
            for key in confirmed:
                assert registry.entries[key] == states[key].digest
            if summary is not None:
                assert summary.newly_confirmed == node.successes_this_pass
                assert (
                    summary.newly_confirmed
                    + summary.reconciled
                    + summary.failed
                    + summary.uncertain
                    <= count
                )
                if summary.complete and summary.attempted == count:
                    break
        final = _states(path)
        assert len(final) == count
        assert all(s.state is SubmissionState.CONFIRMED for s in final.values())
        assert sorted(node.writes) == sorted(final)  # exactly one write per key
        assert set(registry.entries) == set(final)


# --- Real chain: crash after a genuine broadcast -----------------------------------


@pytest.mark.chain
def test_real_crash_after_broadcast_reconciles_without_second_transaction(
    deployment, tmp_path, monkeypatch
):
    import shutil

    from smart_meter import runs
    from smart_meter.config import run_paths

    source = tmp_path / "source.csv"
    shutil.copyfile(
        Path(__file__).parent / "fixtures" / "rounding_boundaries.csv", source
    )
    paths = run_paths("crash-run", base=tmp_path / "results", create=True)
    config = runs.RunConfig(source_path=source, meter_id="CRASH-1", limit=2)
    run = runs.open_run(paths, config, deployment.context)
    real_broadcast = chain.broadcast

    def broadcast_then_die(w3, prepared, **kwargs):
        result = real_broadcast(w3, prepared, **kwargs)
        assert result.state is chain.TxState.SUCCEEDED
        raise Crash  # the process dies before recording the outcome

    monkeypatch.setattr(chain, "broadcast", broadcast_then_die)
    with pytest.raises(Crash):
        aggregator.ingest_run(
            run, deployment.w3, ARTIFACT_PATH, deployment.aggregator_key
        )
    monkeypatch.setattr(chain, "broadcast", real_broadcast)
    nonce = deployment.w3.eth.get_transaction_count(deployment.aggregator)

    resumed = runs.open_run(paths, config, deployment.context, resume=True)
    summary = aggregator.ingest_run(
        resumed, deployment.w3, ARTIFACT_PATH, deployment.aggregator_key
    )
    assert (summary.reconciled, summary.newly_confirmed) == (1, 1)
    assert deployment.w3.eth.get_transaction_count(deployment.aggregator) == nonce + 1
    conn = db.connect(paths.db)
    try:
        subs = db.list_submissions(conn, "crash-run")
        first = db.attempts(conn, "crash-run", run.expected[0].record_key)
    finally:
        conn.close()
    assert [s.state for s in subs] == [SubmissionState.CONFIRMED] * 2
    assert len(first) == 1 and first[0].receipt_status == 1
    for record in run.expected:
        stored = deployment.registry.functions.getCommitment(record.record_key).call()
        assert bytes(stored[0]) == record.digest
