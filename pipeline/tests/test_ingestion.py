"""Task 7.3: journaled ingestion and reconciliation (R5.1-R5.6).

Fast cases use a real temporary SQLite journal with a fake registry and fake
chain calls for precise faults. Chain cases run prepared runs end to end on the
owned Anvil.
"""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import Registry, deployment_context
from smart_meter import aggregator, chain, db, runs
from smart_meter.config import ARTIFACT_PATH, run_paths
from smart_meter.fingerprint import KEY_DOMAIN, digest, record_key
from smart_meter.models import Reading, SubmissionState

R1 = Reading("ING-1", "2022-01-01T00:00:00Z", 60, "Wh", 0)
R2 = Reading("ING-1", "2022-01-01T01:00:00Z", 61, "Wh", 1)
RUN = "default"
SENDER = "0x" + "11" * 20
FIXTURES = Path(__file__).parent / "fixtures"


def _key(r):
    return record_key(r.meter_id, r.interval_start)


def _hash(n):
    return "0x" + f"{n:064x}"


class FakeChain:
    """Scriptable prepare/broadcast/lookup with call records."""

    def __init__(self, registry):
        self.registry = registry
        self.prepared, self.broadcasts, self.lookups = [], [], []
        self.preflight_error = None
        self.broadcast_error = None
        self.outcome = "SUCCEEDED"
        self.lookup_result = None

    def prepare_tx(self, _w3, call, _key, **_):
        if self.preflight_error is not None:
            raise self.preflight_error
        n = len(self.prepared) + 1
        self.prepared.append(call)
        return chain.PreparedTx(_hash(n), SENDER, n, b"signed-%d" % n)

    def broadcast(self, _w3, prepared, **_):
        journaled = self.conn.execute(
            "SELECT 1 FROM submission_attempts WHERE tx_hash = ?", (prepared.tx_hash,)
        ).fetchone()
        assert journaled, "transaction broadcast before its identity was journaled"
        self.broadcasts.append(prepared.tx_hash)
        if self.broadcast_error is not None:
            raise self.broadcast_error(prepared, "nonce too low")
        key, value = self._call_for(prepared)
        state = chain.TxState(self.outcome)
        if state is chain.TxState.SUCCEEDED:
            self.registry.entries[key] = value
        status = {"SUCCEEDED": 1, "REVERTED": 0}.get(self.outcome)
        return chain.TxResult(
            prepared.tx_hash,
            SENDER,
            prepared.nonce,
            state,
            "fake",
            status=status,
            gas_used=48000 if status is not None else None,
            block_number=9 if status is not None else None,
            block_hash="0x" + "ab" * 32 if status is not None else None,
            seconds=0.01 if status is not None else None,
        )

    def _call_for(self, prepared):
        index = int(prepared.tx_hash, 16) - 1
        return self.prepared[index] if index < len(self.prepared) else self.resend_call

    def lookup(self, _w3, tx_hash, sender, nonce):
        self.lookups.append(tx_hash)
        return self.lookup_result(tx_hash, sender, nonce)

    def install(self, monkeypatch):
        monkeypatch.setattr(chain, "prepare_tx", self.prepare_tx)
        monkeypatch.setattr(chain, "broadcast", self.broadcast)
        monkeypatch.setattr(chain, "lookup", self.lookup)


@pytest.fixture
def world(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "readings.sqlite")
    registry = Registry()
    fake = FakeChain(registry)
    fake.conn = conn
    fake.install(monkeypatch)
    try:
        yield conn, registry, fake, tmp_path
    finally:
        conn.close()


def _ingest(world, readings=(R1,), **kwargs):
    conn, registry, _, tmp = world
    return aggregator.ingest(
        list(readings), conn, None, registry, "throwaway", tmp / "results.csv", **kwargs
    )


def _state(world, reading=R1):
    return db.get_submission(world[0], RUN, _key(reading)).state


def _events(world):
    path = world[3] / "results.csv"
    if not path.exists():
        return []
    return [line.split(",")[1] for line in path.read_text().splitlines()[1:]]


# --- First pass ---------------------------------------------------------------


def test_existing_matching_commitment_is_reconciled_without_a_write(world):
    world[1].entries[_key(R1)] = digest(R1)
    summary = _ingest(world)
    assert (summary.newly_confirmed, summary.reconciled) == (0, 1)
    assert world[2].prepared == [] and world[2].broadcasts == []
    assert _state(world) is SubmissionState.CONFIRMED
    assert _events(world) == ["reconcile"]


def test_new_and_reconciled_records_are_logged_distinctly(world):
    world[1].entries[_key(R2)] = digest(R2)
    summary = _ingest(world, (R1, R2))
    assert (summary.attempted, summary.newly_confirmed, summary.reconciled) == (2, 1, 1)
    assert summary.complete
    assert _events(world) == ["commit", "reconcile"]


def test_preflight_revert_is_failed_and_run_continues(world):
    world[2].preflight_error = chain.PreflightError("revert", "denied", SENDER, "0x12")
    summary = _ingest(world, (R1, R2))
    assert (summary.attempted, summary.failed, summary.newly_confirmed) == (2, 2, 0)
    assert _state(world, R1) is SubmissionState.FAILED
    assert world[2].broadcasts == []


def test_preflight_outage_raises_and_leaves_intent_prepared(world):
    world[2].preflight_error = chain.PreflightError("unavailable", "down", SENDER)
    with pytest.raises(chain.PreflightError):
        _ingest(world)
    assert _state(world) is SubmissionState.PREPARED
    assert db.attempts(world[0], RUN, _key(R1)) == []
    world[2].preflight_error = None
    assert _ingest(world).newly_confirmed == 1


def test_broadcast_rejection_is_failed_with_attempt_evidence(world):
    world[2].broadcast_error = chain.BroadcastRejected
    summary = _ingest(world)
    assert summary.failed == 1
    (attempt,) = db.attempts(world[0], RUN, _key(R1))
    assert (attempt.outcome, attempt.reason) == ("REJECTED", "nonce too low")


def test_uncertain_outcome_stops_further_submissions(world):
    world[2].outcome = "UNCERTAIN"
    summary = _ingest(world, (R1, R2))
    assert (summary.attempted, summary.uncertain) == (1, 1)
    assert db.get_submission(world[0], RUN, _key(R2)) is None
    assert len(world[2].prepared) == 1


# --- Resume and reconciliation --------------------------------------------------


def _leave_uncertain(world):
    world[2].outcome = "UNCERTAIN"
    _ingest(world, (R1, R2))
    world[2].outcome = "SUCCEEDED"
    return db.attempts(world[0], RUN, _key(R1))[0]


def _lookup(state, reason="fake"):
    return lambda tx, sender, nonce: chain.TxResult(
        tx, sender, nonce, chain.TxState(state), reason
    )


def test_resume_reconciles_mined_transaction_without_resending(world):
    attempt = _leave_uncertain(world)
    world[1].entries[_key(R1)] = digest(R1)  # the lost transaction was mined
    world[2].lookup_result = _lookup("SUCCEEDED", "mined with status 1")
    summary = _ingest(world, (R1, R2))
    assert world[2].lookups == [attempt.tx_hash]
    assert _state(world, R1) is SubmissionState.CONFIRMED
    # Each record lands in exactly one outcome count: R1 reconciled, R2 new.
    assert (summary.attempted, summary.reconciled, summary.newly_confirmed) == (2, 1, 1)
    assert len(world[2].prepared) == 2  # R1 once originally, R2 now
    assert world[2].broadcasts.count(attempt.tx_hash) == 1


def test_resume_rebroadcasts_identical_transaction_unknown_to_node(world):
    conn = world[0]
    db.prepare_submission(conn, RUN, R1, _key(R1), digest(R1), KEY_DOMAIN)
    db.record_attempt(
        conn, RUN, _key(R1), tx_hash=_hash(1), sender=SENDER, nonce=1, raw_tx=b"raw"
    )  # crash after journaling, before broadcast
    world[2].resend_call = (_key(R1), digest(R1))
    world[2].lookup_result = _lookup("UNCERTAIN", chain.UNKNOWN)
    summary = _ingest(world)
    assert world[2].prepared == []  # nothing newly signed
    assert world[2].broadcasts == [_hash(1)]
    assert summary.newly_confirmed == 1
    assert _state(world) is SubmissionState.CONFIRMED
    assert len(db.attempts(conn, RUN, _key(R1))) == 1


def test_resume_marks_reverted_in_flight_as_failed(world):
    _leave_uncertain(world)
    world[2].lookup_result = _lookup("REVERTED", "mined with status 0")
    summary = _ingest(world, (R1,))
    assert _state(world) is SubmissionState.FAILED
    assert (summary.attempted, summary.failed) == (1, 1)  # counted once


def test_uncertain_intent_unknown_to_node_is_rebroadcast_identically(world):
    attempt = _leave_uncertain(world)
    world[2].resend_call = (_key(R1), digest(R1))
    world[2].lookup_result = _lookup("UNCERTAIN", chain.UNKNOWN)
    prepared_before = len(world[2].prepared)
    summary = _ingest(world, (R1,))
    assert world[2].broadcasts[-1] == attempt.tx_hash
    assert len(world[2].prepared) == prepared_before  # not re-signed
    assert summary.newly_confirmed == 1 and summary.uncertain == 0
    assert len(db.attempts(world[0], RUN, _key(R1))) == 1
    assert _state(world) is SubmissionState.CONFIRMED


def test_rebroadcast_still_uncertain_blocks_new_submissions(world):
    _leave_uncertain(world)
    world[2].resend_call = (_key(R1), digest(R1))
    world[2].lookup_result = _lookup("UNCERTAIN", chain.PENDING)
    world[2].outcome = "UNCERTAIN"
    summary = _ingest(world, (R1, R2))
    assert (summary.attempted, summary.uncertain) == (0, 1)
    assert _state(world) is SubmissionState.UNCERTAIN
    assert db.get_submission(world[0], RUN, _key(R2)) is None


def test_preflight_revert_on_explicit_retry_keeps_failed_state(world):
    world[2].outcome = "REVERTED"
    _ingest(world)
    world[2].preflight_error = chain.PreflightError("revert", "denied", SENDER, "0x12")
    summary = _ingest(world, retry_failed=True)
    assert (summary.failed, summary.newly_confirmed) == (1, 0)
    assert _state(world) is SubmissionState.FAILED
    assert len(db.attempts(world[0], RUN, _key(R1))) == 1


def test_unresolvable_in_flight_blocks_new_submissions(world):
    _leave_uncertain(world)
    world[2].lookup_result = _lookup("UNCERTAIN", "lookup failed: down")
    before = len(world[2].prepared)
    summary = _ingest(world, (R1, R2))
    assert (summary.attempted, summary.uncertain) == (0, 1)
    assert len(world[2].prepared) == before
    assert db.get_submission(world[0], RUN, _key(R2)) is None


def test_in_flight_with_conflicting_registry_digest_stops(world):
    _leave_uncertain(world)
    world[1].entries[_key(R1)] = bytes.fromhex("33" * 32)
    world[2].lookup_result = _lookup("UNCERTAIN", chain.PENDING)
    with pytest.raises(db.ConflictError, match="conflicting registry"):
        _ingest(world)
    assert _state(world) is SubmissionState.FAILED


def test_failed_is_not_retried_unless_requested_and_keeps_evidence(world):
    world[2].outcome = "REVERTED"
    _ingest(world)
    again = _ingest(world)
    assert again.failed == 1 and len(world[2].prepared) == 1
    world[2].outcome = "SUCCEEDED"
    retried = _ingest(world, retry_failed=True)
    assert retried.newly_confirmed == 1
    first, second = db.attempts(world[0], RUN, _key(R1))
    assert (first.outcome, first.receipt_status) == ("REVERTED", 0)
    assert (second.outcome, second.receipt_status) == ("SUCCEEDED", 1)


def test_retry_of_failed_record_reconciles_matching_commitment(world):
    """Review B01: a FAILED intent whose digest is now on chain is reconciled."""
    world[2].outcome = "REVERTED"
    _ingest(world)
    world[1].entries[_key(R1)] = digest(R1)
    summary = _ingest(world, retry_failed=True)
    assert (summary.reconciled, summary.newly_confirmed, summary.failed) == (1, 0, 0)
    assert _state(world) is SubmissionState.CONFIRMED
    assert len(world[2].prepared) == 1  # nothing re-signed
    assert _events(world)[-1] == "reconcile"


def test_retry_of_failed_record_with_different_digest_is_a_conflict(world):
    """Review B01: an occupied key with another digest raises ConflictError."""
    world[2].outcome = "REVERTED"
    _ingest(world)
    world[1].entries[_key(R1)] = bytes.fromhex("33" * 32)
    with pytest.raises(db.ConflictError, match="conflicting registry"):
        _ingest(world, retry_failed=True)
    assert _state(world) is SubmissionState.FAILED
    assert len(world[2].prepared) == 1


def test_mined_receipt_without_commitment_names_the_discrepancy(world):
    """Review B02: success receipt but empty registry is not 'mined with status 1'."""
    conn = world[0]
    db.prepare_submission(conn, RUN, R1, _key(R1), digest(R1), KEY_DOMAIN)
    db.record_attempt(
        conn, RUN, _key(R1), tx_hash=_hash(1), sender=SENDER, nonce=1, raw_tx=b"raw"
    )
    world[2].lookup_result = _lookup("SUCCEEDED", "mined with status 1")
    summary = _ingest(world)
    assert summary.uncertain == 1
    sub = db.get_submission(conn, RUN, _key(R1))
    assert sub.state is SubmissionState.UNCERTAIN
    assert "registry" in sub.reason and "deployment" in sub.reason
    assert sub.reason != "mined with status 1"


def test_submit_refuses_an_unreconciled_in_flight_intent(world):
    """Review B03: the guard is explicit, not deleted for coverage."""
    conn, registry, _, tmp = world
    db.prepare_submission(conn, RUN, R1, _key(R1), digest(R1), KEY_DOMAIN)
    db.record_attempt(
        conn, RUN, _key(R1), tx_hash=_hash(1), sender=SENDER, nonce=1, raw_tx=b"raw"
    )
    run = aggregator._Run(conn, None, registry, "k", tmp / "r.csv", RUN, 1.0)
    with pytest.raises(db.JournalError, match="must be reconciled"):
        run.submit(R1, retry_failed=False)  # reconcile() deliberately skipped
    assert world[2].prepared == [] and world[2].broadcasts == []


def test_malformed_signing_key_stops_the_run_without_counting_records(world):
    """Review B07: a configuration error is operational, not a per-record failure."""
    world[2].preflight_error = chain.PreflightError(
        "configuration", "signing key is malformed", ""
    )
    with pytest.raises(chain.PreflightError) as caught:
        _ingest(world, (R1, R2))
    assert caught.value.kind == "configuration"
    assert _state(world, R1) is SubmissionState.PREPARED
    assert db.get_submission(world[0], RUN, _key(R2)) is None


def test_log_failure_after_success_surfaces_and_resume_does_not_resend(
    world, monkeypatch
):
    real_log = aggregator.results.log

    def broken(*_args, **_kwargs):
        raise OSError("results disk full")

    monkeypatch.setattr(aggregator.results, "log", broken)
    with pytest.raises(aggregator.ResultsWriteError, match="recorded in the journal"):
        _ingest(world)
    assert _state(world) is SubmissionState.CONFIRMED
    monkeypatch.setattr(aggregator.results, "log", real_log)
    summary = _ingest(world)
    assert (summary.newly_confirmed, summary.reconciled) == (0, 1)
    assert len(world[2].prepared) == 1 and len(world[2].broadcasts) == 1


def test_confirmed_journal_with_different_registry_is_a_conflict(world):
    _ingest(world)
    world[1].entries[_key(R1)] = bytes.fromhex("44" * 32)
    with pytest.raises(db.ConflictError, match="registry differs"):
        _ingest(world)


# --- Prepared runs on the owned Anvil -------------------------------------------


@pytest.fixture
def prepared(deployment, tmp_path):
    source = tmp_path / "source.csv"
    shutil.copyfile(FIXTURES / "rounding_boundaries.csv", source)
    paths = run_paths("run-chain", base=tmp_path / "results", create=True)
    config = runs.RunConfig(source_path=source, meter_id="CHAIN-1")
    return runs.open_run(paths, config, deployment.context), config


def _nonce(deployment):
    return deployment.w3.eth.get_transaction_count(deployment.aggregator)


@pytest.mark.chain
def test_prepared_run_commits_then_resume_sends_nothing(deployment, prepared):
    run, config = prepared
    summary = aggregator.ingest_run(
        run, deployment.w3, ARTIFACT_PATH, deployment.aggregator_key
    )
    assert (summary.attempted, summary.newly_confirmed, summary.reconciled) == (3, 3, 0)
    for record in run.expected:
        stored = deployment.registry.functions.getCommitment(record.record_key).call()
        assert bytes(stored[0]) == record.digest
    nonce = _nonce(deployment)
    resumed = runs.open_run(run.paths, config, deployment.context, resume=True)
    again = aggregator.ingest_run(
        resumed, deployment.w3, ARTIFACT_PATH, deployment.aggregator_key
    )
    assert (again.newly_confirmed, again.reconciled) == (0, 3)
    assert _nonce(deployment) == nonce


@pytest.mark.chain
def test_lost_receipt_is_reconciled_after_mining_without_a_second_send(
    deployment, prepared
):
    run, config = prepared
    w3 = deployment.w3
    w3.provider.make_request("evm_setAutomine", [False])
    try:
        first = aggregator.ingest_run(
            run, w3, ARTIFACT_PATH, deployment.aggregator_key, timeout=0.5
        )
        assert (first.attempted, first.uncertain, first.newly_confirmed) == (1, 1, 0)
        w3.provider.make_request("evm_mine", [])
    finally:
        w3.provider.make_request("evm_setAutomine", [True])
    nonce = _nonce(deployment)
    resumed = runs.open_run(run.paths, config, deployment.context, resume=True)
    summary = aggregator.ingest_run(
        resumed, w3, ARTIFACT_PATH, deployment.aggregator_key
    )
    assert summary.complete and summary.newly_confirmed == 2
    assert _nonce(deployment) == nonce + 2  # only the two remaining records
    conn = db.connect(run.paths.db)
    try:
        states = [s.state for s in db.list_submissions(conn, "run-chain")]
        first_attempts = db.attempts(conn, "run-chain", run.expected[0].record_key)
    finally:
        conn.close()
    assert states == [SubmissionState.CONFIRMED] * 3
    assert len(first_attempts) == 1 and first_attempts[0].receipt_status == 1


@pytest.mark.chain
def test_concurrent_writer_is_rejected_before_any_effect(deployment, prepared):
    run, _ = prepared
    nonce = _nonce(deployment)
    with runs.writer_lock(run.paths):
        with pytest.raises(runs.WriterBusy):
            aggregator.ingest_run(
                run, deployment.w3, ARTIFACT_PATH, deployment.aggregator_key
            )
    assert _nonce(deployment) == nonce
    assert not run.paths.db.exists()


@pytest.mark.chain
def test_revoked_writer_is_rejected_before_any_effect(deployment, prepared):
    run, _ = prepared
    registry = deployment.registry
    role = registry.functions.AGGREGATOR_ROLE().call()
    revoked = chain.send_tx(
        deployment.w3,
        registry.functions.revokeRole(role, deployment.aggregator),
        "0x" + bytes(deployment.node.admin.key).hex(),
    )
    assert revoked.state is chain.TxState.SUCCEEDED
    with pytest.raises(chain.DeploymentContextError, match="AGGREGATOR_ROLE"):
        aggregator.ingest_run(
            run, deployment.w3, ARTIFACT_PATH, deployment.aggregator_key
        )
    assert not run.paths.db.exists()


def test_run_whose_readings_differ_from_expected_is_refused(tmp_path):
    source = tmp_path / "source.csv"
    shutil.copyfile(FIXTURES / "rounding_boundaries.csv", source)
    paths = run_paths("run-x", base=tmp_path / "results", create=True)
    run = runs.open_run(
        paths, runs.RunConfig(source_path=source, meter_id="X"), deployment_context()
    )
    tampered = replace(
        run, readings=(*run.readings[:-1], replace(run.readings[-1], value_wh=999))
    )
    with pytest.raises(runs.IncompatibleRun, match="expected records"):
        aggregator.ingest_run(tampered, None, ARTIFACT_PATH, "unused")
    assert not paths.db.exists()
