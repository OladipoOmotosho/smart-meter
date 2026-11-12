"""Journaled ingestion and reconciliation (Task 7.3, R5.1-R5.6).

Each intended commitment is written to the SQLite journal before any network
effect and its signed transaction identity before broadcast. A run first
reconciles in-flight intents, then submits serially. A new commitment counts as
confirmed only after a success receipt and an exactly matching registry entry.
SQLite and the chain are never treated as one atomic transaction.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from web3 import Web3
from web3.contract import Contract

from . import chain, db, results, runs
from .fingerprint import KEY_DOMAIN, digest, record_key
from .models import Reading, SubmissionState

DEFAULT_RUN_ID = "default"
IN_FLIGHT = {SubmissionState.SUBMITTED, SubmissionState.UNCERTAIN}


@dataclass(frozen=True)
class IngestSummary:
    attempted: int
    newly_confirmed: int
    reconciled: int
    failed: int = 0
    uncertain: int = 0

    @property
    def complete(self) -> bool:
        return self.failed == 0 and self.uncertain == 0


class ResultsWriteError(RuntimeError):
    """A confirmed write could not be logged; the journal already records it."""


def _validate_reading(reading: Reading) -> None:
    if not isinstance(reading.meter_id, str) or not reading.meter_id.strip():
        raise ValueError("ingestion requires a valid meter ID")
    try:
        parsed = datetime.strptime(reading.interval_start, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as error:
        raise ValueError(
            "ingestion requires a canonical hourly UTC timestamp"
        ) from error
    if (
        parsed.minute != 0
        or parsed.second != 0
        or parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != reading.interval_start
    ):
        raise ValueError("ingestion requires a canonical hourly UTC timestamp")
    if reading.unit != "Wh":
        raise ValueError("ingestion requires an hourly UTC Wh reading")


def _registry_digest(contract: Contract, key: bytes) -> bytes | None:
    entry = contract.functions.getCommitment(key).call()
    stored = bytes(entry[0])
    return None if stored == bytes(32) else stored


@dataclass
class _Counts:
    attempted: int = 0
    newly_confirmed: int = 0
    reconciled: int = 0
    failed: int = 0
    uncertain: int = 0

    def summary(self) -> IngestSummary:
        return IngestSummary(
            self.attempted,
            self.newly_confirmed,
            self.reconciled,
            self.failed,
            self.uncertain,
        )


class _Run:
    """One serial ingestion pass over a journal."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        w3: Web3,
        contract: Contract,
        aggregator_key: str,
        results_path: Path,
        run_id: str,
        timeout: float,
    ):
        self.conn, self.w3, self.contract = conn, w3, contract
        self.signing_key = aggregator_key
        self.results_path, self.run_id = results_path, run_id
        self.timeout = timeout
        self.counts = _Counts()
        self.settled: set[bytes] = set()  # keys already counted in this pass

    # --- journal helpers ---

    def _outcome(self, sub: db.Submission, state: SubmissionState, **fields) -> None:
        db.record_outcome(self.conn, self.run_id, sub.record_key, state, **fields)

    def _log(self, sub: db.Submission, event: str, **fields) -> None:
        try:
            results.log(
                self.results_path, event, sub.meter_id, sub.interval_start, **fields
            )
        except OSError as error:
            raise ResultsWriteError(
                f"{event} for {sub.record_key.hex()} is recorded in the journal "
                f"but the results log failed: {error}"
            ) from error

    def _evidence(self, result: chain.TxResult) -> dict:
        return {
            "tx_hash": result.tx_hash,
            "outcome": result.state.value,
            "receipt_status": result.status,
            "block_number": result.block_number,
            "block_hash": result.block_hash,
            "gas_used": result.gas_used,
            "reason": result.reason,
        }

    def _conflict(self, sub: db.Submission, reason: str) -> None:
        if sub.state is not SubmissionState.FAILED:
            self._outcome(sub, SubmissionState.FAILED, reason=reason)
        raise db.ConflictError(f"{reason} for {sub.record_key.hex()}")

    def _reconciled(self, sub: db.Submission, reason: str, **evidence) -> None:
        self._outcome(sub, SubmissionState.CONFIRMED, reason=reason, **evidence)
        self.counts.reconciled += 1
        self._log(sub, "reconcile", note=reason)

    # --- settle a broadcast result ---

    def _settle(self, sub: db.Submission, result: chain.TxResult) -> bool:
        """Record a broadcast outcome; return False if the run must stop."""
        evidence = self._evidence(result)
        if result.state is chain.TxState.SUCCEEDED:
            if _registry_digest(self.contract, sub.record_key) != sub.digest:
                evidence["reason"] = "registry confirmation mismatch"
                self._outcome(sub, SubmissionState.FAILED, **evidence)
                raise db.ConflictError(
                    f"registry confirmation mismatch for {sub.record_key.hex()}"
                )
            self._outcome(sub, SubmissionState.CONFIRMED, **evidence)
            self.counts.newly_confirmed += 1
            self._log(
                sub,
                "commit",
                gas_used=result.gas_used,
                seconds=result.seconds,
                note=result.tx_hash,
            )
            return True
        if result.state is chain.TxState.UNCERTAIN:
            self._outcome(sub, SubmissionState.UNCERTAIN, **evidence)
            self.counts.uncertain += 1
            return False
        self._outcome(sub, SubmissionState.FAILED, **evidence)  # REVERTED, REPLACED
        self.counts.failed += 1
        return True

    def _broadcast(self, sub: db.Submission, prepared: chain.PreparedTx) -> bool:
        try:
            result = chain.broadcast(self.w3, prepared, timeout=self.timeout)
        except chain.BroadcastRejected as error:
            self._outcome(
                sub,
                SubmissionState.FAILED,
                tx_hash=prepared.tx_hash,
                outcome="REJECTED",
                reason=error.reason,
            )
            self.counts.failed += 1
            return True
        return self._settle(sub, result)

    # --- reconcile in-flight intents (R5.4) ---

    def reconcile(self) -> bool:
        """Resolve SUBMITTED/UNCERTAIN intents; return False if any stays uncertain."""
        clear = True
        for sub in db.list_submissions(self.conn, self.run_id, IN_FLIGHT):
            self.settled.add(sub.record_key)
            last = db.attempts(self.conn, self.run_id, sub.record_key)[-1]
            looked = chain.lookup(self.w3, last.tx_hash, last.sender, last.nonce)
            stored = _registry_digest(self.contract, sub.record_key)
            if stored == sub.digest:
                evidence = (
                    self._evidence(looked)
                    if looked.state is chain.TxState.SUCCEEDED
                    and looked.tx_hash == last.tx_hash
                    else {}
                )
                evidence.pop("reason", None)
                self._reconciled(
                    sub, "reconciled: matching commitment on chain", **evidence
                )
                continue
            if stored is not None:
                self._conflict(sub, "conflicting registry digest")
            if looked.state in {chain.TxState.REVERTED, chain.TxState.REPLACED}:
                self._outcome(sub, SubmissionState.FAILED, **self._evidence(looked))
                self.counts.failed += 1
                continue
            if looked.state is chain.TxState.SUCCEEDED:
                # The receipt says it succeeded, yet this registry holds nothing.
                reason = (
                    f"receipt for {last.tx_hash} reports success but the registry "
                    "has no commitment; check the deployment context"
                )
                self._outcome(sub, SubmissionState.UNCERTAIN, reason=reason)
                self.counts.uncertain += 1
                clear = False
                continue
            if looked.reason in {chain.UNKNOWN, chain.PENDING}:
                # Rebroadcast the identical signed transaction: same hash and nonce.
                if sub.state is SubmissionState.UNCERTAIN:
                    db.record_attempt(
                        self.conn,
                        self.run_id,
                        sub.record_key,
                        tx_hash=last.tx_hash,
                        sender=last.sender,
                        nonce=last.nonce,
                        raw_tx=last.raw_tx,
                    )
                prepared = chain.PreparedTx(
                    last.tx_hash, last.sender, last.nonce, last.raw_tx
                )
                if not self._broadcast(sub, prepared):
                    clear = False
                continue
            # The lookup itself failed or the result is otherwise unknown.
            self._outcome(sub, SubmissionState.UNCERTAIN, reason=looked.reason)
            self.counts.uncertain += 1
            clear = False
        return clear

    # --- new submissions ---

    def submit(self, reading: Reading, *, retry_failed: bool) -> bool:
        """Process one reading; return False if the run must stop."""
        self.counts.attempted += 1
        _validate_reading(reading)
        key = record_key(reading.meter_id, reading.interval_start)
        expected = digest(reading)
        sub = db.prepare_submission(
            self.conn, self.run_id, reading, key, expected, KEY_DOMAIN
        )
        if key in self.settled:
            return True  # its outcome was already counted during reconciliation
        if sub.state in IN_FLIGHT:
            # reconcile() settles or stops on every in-flight intent first, so
            # reaching this means the pass was driven out of order.
            raise db.JournalError(
                f"in-flight intent {key.hex()} must be reconciled before submission"
            )
        if sub.state is SubmissionState.CONFIRMED:
            if _registry_digest(self.contract, key) != expected:
                raise db.ConflictError(
                    f"journal says confirmed but registry differs for {key.hex()}"
                )
            self.counts.reconciled += 1
            return True
        if sub.state is SubmissionState.FAILED and not retry_failed:
            self.counts.failed += 1
            return True
        stored = _registry_digest(self.contract, key)
        if stored == expected:  # PREPARED, or FAILED under an explicit retry
            self._reconciled(sub, "reconciled: commitment already on chain")
            return True
        if stored is not None:
            self._conflict(sub, "conflicting registry digest")
        try:
            prepared = chain.prepare_tx(
                self.w3, self.contract.functions.commit(key, expected), self.signing_key
            )
        except chain.PreflightError as error:
            if error.kind in {"unavailable", "configuration"}:
                raise  # nothing sent; operational, not a per-record failure
            if sub.state is SubmissionState.PREPARED:
                self._outcome(sub, SubmissionState.FAILED, reason=str(error))
            self.counts.failed += 1
            return True
        db.record_attempt(
            self.conn,
            self.run_id,
            key,
            tx_hash=prepared.tx_hash,
            sender=prepared.sender,
            nonce=prepared.nonce,
            raw_tx=prepared.raw,
        )
        return self._broadcast(sub, prepared)


def ingest(
    readings: Iterable[Reading],
    conn: sqlite3.Connection,
    w3: Web3,
    contract: Contract,
    aggregator_key: str,
    results_path: Path,
    *,
    run_id: str = DEFAULT_RUN_ID,
    retry_failed: bool = False,
    timeout: float = chain.DEFAULT_RECEIPT_TIMEOUT,
) -> IngestSummary:
    """Reconcile in-flight intents, then submit each reading serially.

    Stops without further submissions when any outcome is uncertain. Raises
    ConflictError on a changed local reading or a different registry digest,
    PreflightError(kind='unavailable') when the node cannot be reached, and
    ResultsWriteError if logging fails after the journal records success.
    """
    run = _Run(conn, w3, contract, aggregator_key, results_path, run_id, timeout)
    if not run.reconcile():
        return run.counts.summary()
    for reading in readings:
        if not run.submit(reading, retry_failed=retry_failed):
            break
    return run.counts.summary()


def ingest_in_context(
    readings: Iterable[Reading],
    conn: sqlite3.Connection,
    w3: Web3,
    context: chain.DeploymentContext,
    artifact_path: Path,
    aggregator_key: str,
    results_path: Path,
    *,
    run_id: str = DEFAULT_RUN_ID,
) -> IngestSummary:
    """Validate deployment, code and signer role before any storage or chain effect."""
    signer = w3.eth.account.from_key(aggregator_key).address
    contract = chain.validate_deployment(w3, context, artifact_path, writer=signer)
    return ingest(
        readings, conn, w3, contract, aggregator_key, results_path, run_id=run_id
    )


def ingest_run(
    run: runs.PreparedRun,
    w3: Web3,
    artifact_path: Path,
    aggregator_key: str,
    *,
    retry_failed: bool = False,
    timeout: float = chain.DEFAULT_RECEIPT_TIMEOUT,
) -> IngestSummary:
    """Ingest a prepared run as its single writer, in its recorded deployment."""
    for record, reading in zip(run.expected, run.readings, strict=True):
        if (
            digest(reading) != record.digest
            or record_key(reading.meter_id, reading.interval_start) != record.record_key
        ):
            raise runs.IncompatibleRun("readings do not match the expected records")
    context = chain.DeploymentContext.from_json(run.manifest["deployment"])
    with runs.writer_lock(run.paths):
        signer = w3.eth.account.from_key(aggregator_key).address
        contract = chain.validate_deployment(w3, context, artifact_path, writer=signer)
        conn = db.connect(run.paths.db)
        try:
            return ingest(
                run.readings,
                conn,
                w3,
                contract,
                aggregator_key,
                run.paths.results,
                run_id=run.paths.root.name,
                retry_failed=retry_failed,
                timeout=timeout,
            )
        finally:
            conn.close()
