"""Independent local security scenarios with exact outcomes and public evidence."""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from web3 import Web3

from . import aggregator, chain, db, local_chain, results, runs, verifier
from .config import ARTIFACT_PATH, REPO_ROOT
from .demo import paths_for, resume_run
from .fingerprint import digest, record_key

EXPECTED = {
    "S0": "VERIFIED",
    "A1": "TAMPERED",
    "A2": "REJECTED",
    "A3": "REJECTED",
    "A4": "VERIFIED",
    "S5": "MISSING_RECORD",
    "S6": "MISSING_COMMITMENT",
    "S6b": "MISSING_BOTH",
    "S7": "REJECTED",
    "S8": "ERROR",
    "S9": "REVERTED",
    "S10": "RECONCILED",
}


def run_scenarios(directory: Path, w3: Web3) -> int:
    """Create-only scenario directory; every case deploys a separate registry."""
    directory.mkdir(parents=True, exist_ok=False)
    admin, writer, attacker = local_chain.accounts()
    all_passed = True
    for scenario, expected in EXPECTED.items():
        source = REPO_ROOT / "pipeline/tests/fixtures/two_hours.csv"
        if scenario == "A4":
            with source.open(newline="") as handle:
                reader = csv.DictReader(handle)
                fields, rows = reader.fieldnames, list(reader)
            for row in rows:
                row["P"] = "999"
            source = directory / "altered-before-commit.csv"
            with source.open("w", newline="") as handle:
                out = csv.DictWriter(handle, fieldnames=fields)
                out.writeheader()
                out.writerows(rows)
        paths = paths_for(directory / scenario, create=True)
        context = local_chain.deploy(w3)
        run = runs.open_run(paths, runs.RunConfig(source, limit=2), context)
        contract = chain.validate_deployment(w3, context, ARTIFACT_PATH)
        conn = db.connect(paths.db)
        gas = seconds = status = tx_hash = None
        try:
            if scenario not in {"A2", "S6", "S6b"}:
                summary = aggregator.ingest_run(
                    run, w3, ARTIFACT_PATH, writer.key.hex()
                )
                if not summary.complete:
                    raise RuntimeError(f"{scenario}: initial ingestion incomplete")
            reading = run.readings[0]
            key = record_key(reading.meter_id, reading.interval_start)
            before = contract.functions.getCommitment(key).call()
            note = ""
            if scenario in {"A2", "A3", "S7"}:
                signing_key = (
                    attacker.key.hex() if scenario == "A2" else writer.key.hex()
                )
                attempt_key = key
                role = contract.functions.AGGREGATOR_ROLE().call()
                if scenario == "S7":
                    chain.send_tx(
                        w3,
                        contract.functions.revokeRole(role, writer.address),
                        admin.key.hex(),
                    )
                    attempt_key = record_key("later", reading.interval_start)
                if scenario == "A3":
                    signature, types, values = (
                        "AlreadyCommitted(bytes32)",
                        ["bytes32"],
                        [key],
                    )
                else:
                    signature, types, values = (
                        "AccessControlUnauthorizedAccount(address,bytes32)",
                        ["address", "bytes32"],
                        [
                            attacker.address if scenario == "A2" else writer.address,
                            role,
                        ],
                    )
                want_error = (
                    "0x"
                    + (
                        Web3.keccak(text=signature)[:4] + w3.codec.encode(types, values)
                    ).hex()
                )
                try:
                    chain.send_tx(
                        w3,
                        contract.functions.commit(
                            attempt_key, digest(replace(reading, value_wh=777))
                        ),
                        signing_key,
                    )
                    actual = "ACCEPTED"
                except chain.PreflightError as error:
                    actual = (
                        "REJECTED"
                        if error.kind == "revert" and error.data == want_error
                        else "ERROR"
                    )
                    note = str(error)
            elif scenario == "S9":
                tx = contract.functions.commit(
                    record_key("reverted", reading.interval_start), digest(reading)
                ).transact({"from": attacker.address, "gas": 200000})
                receipt = w3.eth.wait_for_transaction_receipt(tx, timeout=15)
                status, gas, tx_hash = (
                    receipt["status"],
                    receipt["gasUsed"],
                    "0x" + bytes(tx).hex(),
                )
                actual = "REVERTED" if status == 0 else "ACCEPTED"
            elif scenario == "S10":
                summary = resume_run(paths.root, w3)
                actual = (
                    "RECONCILED"
                    if summary.reconciled == 2 and summary.newly_confirmed == 0
                    else "ERROR"
                )
            else:
                if scenario == "A1":
                    conn.execute("UPDATE readings SET value_wh=value_wh+1")
                elif scenario == "S5":
                    conn.execute("DELETE FROM readings")
                elif scenario == "S6":
                    for item in run.readings:
                        db.insert_reading(conn, item)
                elif scenario == "S8":
                    conn.execute("UPDATE readings SET value_wh='corrupt'")
                conn.commit()
                audited = verifier.audit_run(
                    paths, w3, ARTIFACT_PATH, paths.root / "audit.csv"
                )
                outcomes = {item.outcome.value for item in audited}
                actual = next(iter(outcomes)) if len(outcomes) == 1 else "ERROR"
                seconds = sum(item.seconds for item in audited)
                note = (
                    "expected pre-commit limitation; excluded from detection rate"
                    if scenario == "A4"
                    else audited[0].reason
                )
            unchanged = contract.functions.getCommitment(key).call() == before
            passed = actual == expected and unchanged
            all_passed &= passed
            results.log(
                directory / "scenarios.csv",
                "scenario",
                reading.meter_id,
                reading.interval_start,
                verdict=actual,
                gas_used=gas,
                seconds=seconds,
                note=note,
                run_id=scenario,
                scenario_id=scenario,
                record_key=key.hex(),
                registry_address=context.registry_address,
                chain_id=context.chain_id,
                expected_outcome=expected,
                passed=passed,
                tx_hash=tx_hash,
                status=status,
                stage="scenario",
            )
        finally:
            conn.close()
    return 0 if all_passed else 1
