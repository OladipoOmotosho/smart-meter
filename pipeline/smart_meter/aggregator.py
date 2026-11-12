"""Store a reading, commit its digest, and verify confirmation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from web3 import Web3
from web3.contract import Contract

from . import chain, db, results
from .fingerprint import digest, record_key
from .models import Reading


@dataclass(frozen=True)
class IngestSummary:
    attempted: int
    newly_confirmed: int
    reconciled: int


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


def ingest(
    readings: Iterable[Reading],
    conn: sqlite3.Connection,
    w3: Web3,
    contract: Contract,
    aggregator_key: str,
    results_path: Path,
) -> IngestSummary:
    """Commit in order; an identical existing anchor is reconciled without a write."""
    attempted = newly_confirmed = reconciled = 0
    for reading in readings:
        attempted += 1
        _validate_reading(reading)
        key = record_key(reading.meter_id, reading.interval_start)
        expected = digest(reading)
        existing = db.get_reading(conn, reading.meter_id, reading.interval_start)
        if existing is not None and existing != reading:
            raise ValueError(f"conflicting stored reading for {key.hex()}")
        if existing is None:
            db.insert_reading(conn, reading)
        stored = contract.functions.getCommitment(key).call()
        if stored[0] != bytes(32):
            if stored[0] != expected:
                raise ValueError(f"conflicting registry digest for {key.hex()}")
            reconciled += 1
            continue
        tx = chain.send_tx(w3, contract.functions.commit(key, expected), aggregator_key)
        if tx.state is chain.TxState.UNCERTAIN:
            raise chain.SubmissionUncertain(tx)
        if tx.state is not chain.TxState.SUCCEEDED:
            raise chain.TransactionReverted(tx)
        confirmed = contract.functions.getCommitment(key).call()
        if confirmed[0] != expected:
            raise ValueError(f"registry confirmation mismatch for {key.hex()}")
        newly_confirmed += 1
        results.log(
            results_path,
            "commit",
            reading.meter_id,
            reading.interval_start,
            gas_used=tx.gas_used,
            seconds=tx.seconds,
            note=tx.tx_hash,
        )
    return IngestSummary(attempted, newly_confirmed, reconciled)


def ingest_in_context(
    readings: Iterable[Reading],
    conn: sqlite3.Connection,
    w3: Web3,
    context: chain.DeploymentContext,
    artifact_path: Path,
    aggregator_key: str,
    results_path: Path,
) -> IngestSummary:
    """Validate deployment, code and signer role before any storage or chain effect."""
    signer = w3.eth.account.from_key(aggregator_key).address
    contract = chain.validate_deployment(w3, context, artifact_path, writer=signer)
    return ingest(readings, conn, w3, contract, aggregator_key, results_path)
