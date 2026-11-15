"""Read-only comparison of a stored reading with its registry commitment."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from web3 import Web3
from web3.contract import Contract
from web3.exceptions import Web3Exception

from . import chain, db, results, runs
from .config import RunPaths
from .fingerprint import KEY_DOMAIN, READING_DOMAIN, digest, record_key
from .models import AuditResult, Verdict


def verify(
    conn: sqlite3.Connection,
    contract: Contract,
    meter_id: str,
    interval_start: str,
    results_path: Path | None = None,
    *,
    block_identifier: str | None = None,
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
            call = contract.functions.getCommitment(key)
            entry = (
                call.call()
                if block_identifier is None
                else call.call(block_identifier=block_identifier)
            )
            if (
                len(entry) != 3
                or not isinstance(entry[0], bytes)
                or len(entry[0]) != 32
                or type(entry[1]) is not int
                or not 0 <= entry[1] < 2**64
                or not Web3.is_address(entry[2])
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
    result = AuditResult(
        outcome,
        reason,
        key.hex(),
        observed,
        committed,
        elapsed,
        meter_id=meter_id,
        interval_start=interval_start,
    )
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


def verify_in_context(
    conn: sqlite3.Connection,
    w3: Web3,
    context: chain.DeploymentContext,
    artifact_path: Path,
    identities: Iterable[tuple[str, str]],
    results_path: Path | None = None,
) -> list[AuditResult]:
    """Validate the recorded deployment once, then audit each identity.

    An invalid or unreachable deployment yields ERROR for every identity; it is
    never reported as a missing commitment or a verified reading (R6.3).
    """
    identities = list(identities)
    start = time.perf_counter()
    try:
        contract = chain.validate_deployment(w3, context, artifact_path)
    except chain.DeploymentContextError as error:
        reason = f"deployment context invalid: {error}"
        elapsed = time.perf_counter() - start
        failures = []
        for meter_id, interval_start in identities:
            key = record_key(meter_id, interval_start).hex()
            failures.append(
                AuditResult(Verdict.ERROR, reason, key, None, None, elapsed)
            )
            if results_path is not None:
                results.log(
                    results_path,
                    "verify",
                    meter_id,
                    interval_start,
                    verdict=Verdict.ERROR.value,
                    seconds=elapsed,
                    note=reason,
                )
        return failures
    return [
        verify(conn, contract, meter_id, interval_start, results_path)
        for meter_id, interval_start in identities
    ]


class AuditError(RuntimeError):
    """The run cannot be audited; its context is invalid or unavailable."""


def audit_run(
    paths: RunPaths, w3: Web3, artifact_path: Path, output: Path | None = None
) -> list[AuditResult]:
    """Audit every manifest identity using a read-only SQLite snapshot and fixed block.

    A broken manifest/deployment aborts with AuditError. Per-record failures are
    ERROR results. No database is created or migrated, and no transaction is sent.
    """
    start = time.perf_counter()
    try:
        manifest = json.loads(paths.manifest.read_text())
        if (
            manifest["format"] != runs.MANIFEST_FORMAT
            or manifest["run_id"] != paths.root.name
            or manifest["formats"] != {"reading": READING_DOMAIN, "key": KEY_DOMAIN}
        ):
            raise ValueError("manifest format or run identity differs")
        expected = runs.load_expected(paths)
        if not expected or manifest["expected_records"]["count"] != len(expected):
            raise ValueError("manifest expected count differs or is empty")
        context = chain.DeploymentContext.from_json(manifest["deployment"])
        contract = chain.validate_deployment(w3, context, artifact_path)
        block = w3.eth.get_block("latest")
        block_hash = "0x" + bytes(block["hash"]).hex()
        if len(block_hash) != 66:
            raise ValueError("invalid audit block hash")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        runs.RunError,
        Web3Exception,
    ) as error:
        raise AuditError(f"audit context invalid: {error}") from error
    context_seconds = time.perf_counter() - start
    output_rows = []
    conn = None
    database_start = time.perf_counter()
    try:
        conn = sqlite3.connect(paths.db.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
    except sqlite3.Error as error:
        database_error = str(error)
    else:
        database_error = None
    database_seconds = time.perf_counter() - database_start
    try:
        for item in expected:
            if database_error is not None:
                result = AuditResult(
                    Verdict.ERROR,
                    f"database read failed: {database_error}",
                    item.record_key.hex(),
                    None,
                    None,
                    database_seconds,
                )
            else:
                result = verify(
                    conn,
                    contract,
                    item.meter_id,
                    item.interval_start,
                    block_identifier=block_hash,
                )
            result = replace(
                result,
                run_id=paths.root.name,
                meter_id=item.meter_id,
                interval_start=item.interval_start,
                expected_digest=item.digest.hex(),
                registry_address=context.registry_address,
                chain_id=context.chain_id,
                block_hash=block_hash,
                context_seconds=context_seconds,
            )
            output_rows.append(result)
            if output is not None:
                results.log(
                    output,
                    "verify",
                    result.meter_id,
                    result.interval_start,
                    verdict=result.outcome.value,
                    seconds=result.seconds,
                    note=result.reason,
                    run_id=result.run_id,
                    record_key=result.record_key,
                    expected_digest=result.expected_digest,
                    observed_digest=result.observed_digest,
                    committed_digest=result.committed_digest,
                    registry_address=result.registry_address,
                    chain_id=result.chain_id,
                    block_hash=result.block_hash,
                    context_seconds=result.context_seconds,
                    stage="audit",
                )
    finally:
        if conn is not None:
            conn.close()
    return output_rows
