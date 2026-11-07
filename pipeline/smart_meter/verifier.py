"""Read-only comparison of a stored reading with its registry commitment."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from web3.contract import Contract
from web3.exceptions import Web3Exception

from . import db, results
from .fingerprint import digest, record_key
from .models import AuditResult, Verdict


def verify(
    conn: sqlite3.Connection,
    contract: Contract,
    meter_id: str,
    interval_start: str,
    results_path: Path | None = None,
) -> AuditResult:
    """Return an explained outcome without signing or changing stored readings."""
    start = time.perf_counter()
    key = record_key(meter_id, interval_start)
    observed: str | None = None
    committed: str | None = None
    try:
        reading = db.get_reading(conn, meter_id, interval_start)
        if reading is not None:
            observed = digest(reading).hex()
    except (sqlite3.DatabaseError, TypeError, ValueError, OverflowError) as error:
        outcome, reason = Verdict.ERROR, f"record read/encoding failed: {error}"
    else:
        try:
            entry = contract.functions.getCommitment(key).call()
            if (
                len(entry) != 3
                or not isinstance(entry[0], bytes)
                or len(entry[0]) != 32
            ):
                raise ValueError("malformed registry commitment")
            committed = entry[0].hex() if entry[0] != bytes(32) else None
        except (Web3Exception, OSError, ValueError, TypeError) as error:
            outcome, reason = Verdict.ERROR, f"registry read failed: {error}"
        else:
            if reading is None and committed is None:
                outcome, reason = Verdict.MISSING_BOTH, "record and commitment absent"
            elif reading is None:
                outcome, reason = Verdict.MISSING_RECORD, "stored record absent"
            elif committed is None:
                outcome, reason = Verdict.MISSING_COMMITMENT, "commitment absent"
            elif observed == committed:
                outcome, reason = Verdict.VERIFIED, "fingerprints match"
            else:
                outcome, reason = Verdict.TAMPERED, "fingerprint mismatch"
    elapsed = time.perf_counter() - start
    result = AuditResult(outcome, reason, key.hex(), observed, committed, elapsed)
    if results_path is not None:
        results.log(
            results_path,
            "verify",
            meter_id,
            interval_start,
            verdict=outcome.value,
            seconds=elapsed,
            note=reason,
        )
    return result
