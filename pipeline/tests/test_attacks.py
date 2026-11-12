"""Required security scenarios against a fresh registry on the runner's Anvil."""

import json
import os
from dataclasses import replace

import pytest
from eth_abi import encode
from smart_meter import chain, db
from smart_meter.aggregator import ingest
from smart_meter.config import ARTIFACT_PATH, run_paths
from smart_meter.fingerprint import digest, record_key
from smart_meter.models import Reading, Verdict
from smart_meter.verifier import verify
from web3 import Web3

pytestmark = pytest.mark.chain
READING = Reading("TEST-METER", "2022-01-01T00:00:00Z", 60)


@pytest.fixture
def world(tmp_path):
    w3 = chain.connect(os.environ["RPC_URL"])
    admin = w3.eth.accounts[0]
    aggregator = w3.eth.accounts[1]
    attacker = w3.eth.accounts[2]
    artifact = json.loads(ARTIFACT_PATH.read_text())
    factory = w3.eth.contract(
        abi=artifact["abi"], bytecode=artifact["bytecode"]["object"]
    )
    receipt = w3.eth.wait_for_transaction_receipt(
        factory.constructor(admin).transact({"from": admin})
    )
    registry = w3.eth.contract(address=receipt.contractAddress, abi=artifact["abi"])
    w3.eth.wait_for_transaction_receipt(
        registry.functions.grantRole(
            registry.functions.AGGREGATOR_ROLE().call(), aggregator
        ).transact({"from": admin})
    )
    conn = db.connect(tmp_path / "readings.sqlite")
    try:
        yield w3, registry, conn, tmp_path, admin, aggregator, attacker
    finally:
        conn.close()


def _commit(world, reading=READING):
    w3, registry, conn, temp, _, _, _ = world
    return ingest(
        [reading],
        conn,
        w3,
        registry,
        os.environ["AGGREGATOR_PRIVATE_KEY"],
        temp / "results.csv",
    )


def _entry(world, reading=READING):
    return (
        world[1]
        .functions.getCommitment(record_key(reading.meter_id, reading.interval_start))
        .call()
    )


def _error_data(signature, types, values):
    return "0x" + (Web3.keccak(text=signature)[:4] + encode(types, values)).hex()


def test_positive_control_clean_record_verifies(world):
    summary = _commit(world)
    assert (summary.attempted, summary.newly_confirmed, summary.reconciled) == (1, 1, 0)
    assert _entry(world)[0] == digest(READING)
    assert (
        verify(world[2], world[1], READING.meter_id, READING.interval_start).outcome
        == Verdict.VERIFIED
    )


def test_A1_post_commit_tampering_is_detected(world):
    _commit(world)
    before = _entry(world)
    world[2].execute("UPDATE readings SET value_wh = 25200")
    world[2].commit()
    result = verify(world[2], world[1], READING.meter_id, READING.interval_start)
    assert result.outcome == Verdict.TAMPERED
    assert _entry(world) == before


def test_A2_unauthorized_submission_is_rejected(world):
    w3, registry, _, _, _, _, _ = world
    key = record_key(READING.meter_id, READING.interval_start)
    expected = _error_data(
        "AccessControlUnauthorizedAccount(address,bytes32)",
        ["address", "bytes32"],
        [world[6], registry.functions.AGGREGATOR_ROLE().call()],
    )
    with pytest.raises(chain.PreflightError) as caught:
        chain.send_tx(
            w3,
            registry.functions.commit(key, digest(READING)),
            os.environ["ATTACKER_PRIVATE_KEY"],
        )
    assert caught.value.kind == "revert"
    assert caught.value.data == expected
    assert not registry.functions.isCommitted(key).call()


def test_A3_existing_fingerprint_cannot_be_replaced(world):
    _commit(world)
    before = _entry(world)
    w3, registry, _, _, _, _, _ = world
    key = record_key(READING.meter_id, READING.interval_start)
    expected = _error_data("AlreadyCommitted(bytes32)", ["bytes32"], [key])
    with pytest.raises(chain.PreflightError) as caught:
        chain.send_tx(
            w3,
            registry.functions.commit(key, digest(replace(READING, value_wh=25200))),
            os.environ["AGGREGATOR_PRIVATE_KEY"],
        )
    assert caught.value.kind == "revert"
    assert caught.value.data == expected
    assert _entry(world) == before


def test_A4_boundary_change_before_commit_is_not_detected(world):
    changed = replace(READING, value_wh=25200)
    _commit(world, changed)
    assert (
        verify(world[2], world[1], changed.meter_id, changed.interval_start).outcome
        == Verdict.VERIFIED
    )


def test_S5_deleted_record_remains_auditable(world):
    _commit(world)
    world[2].execute("DELETE FROM readings")
    world[2].commit()
    assert (
        verify(world[2], world[1], READING.meter_id, READING.interval_start).outcome
        == Verdict.MISSING_RECORD
    )


def test_S6_absent_commitment_and_both_absent_are_distinct(world):
    db.insert_reading(world[2], READING)
    assert (
        verify(world[2], world[1], READING.meter_id, READING.interval_start).outcome
        == Verdict.MISSING_COMMITMENT
    )
    assert (
        verify(world[2], world[1], "UNKNOWN", READING.interval_start).outcome
        == Verdict.MISSING_BOTH
    )


def test_S7_revoked_role_cannot_submit(world):
    _commit(world)
    w3, registry, _, _, admin, aggregator, _ = world
    role = registry.functions.AGGREGATOR_ROLE().call()
    w3.eth.wait_for_transaction_receipt(
        registry.functions.revokeRole(role, aggregator).transact({"from": admin})
    )
    expected = _error_data(
        "AccessControlUnauthorizedAccount(address,bytes32)",
        ["address", "bytes32"],
        [aggregator, role],
    )
    with pytest.raises(chain.PreflightError) as caught:
        chain.send_tx(
            w3,
            registry.functions.commit(
                record_key("LATER", READING.interval_start), digest(READING)
            ),
            os.environ["AGGREGATOR_PRIVATE_KEY"],
        )
    assert caught.value.kind == "revert"
    assert caught.value.data == expected
    assert _entry(world)[0] == digest(READING)


def test_S8_corrupt_record_is_error(world):
    _commit(world)
    world[2].execute("UPDATE readings SET value_wh = 'corrupt'")
    world[2].commit()
    result = verify(world[2], world[1], READING.meter_id, READING.interval_start)
    assert result.outcome == Verdict.ERROR
    assert "record read" in result.reason


def test_S9_reverted_receipt_is_not_a_commit(world):
    w3, registry, _, _, _, _, attacker = world
    key = record_key("REVERTED", READING.interval_start)
    receipt = w3.eth.wait_for_transaction_receipt(
        registry.functions.commit(key, digest(READING)).transact(
            {"from": attacker, "gas": 200000}
        )
    )
    assert receipt.status == 0
    assert not registry.functions.isCommitted(key).call()


def test_S10_new_runs_are_separate_and_resume_reconciles(world):
    first = run_paths("first", base=world[3], create=True)
    second = run_paths("second", base=world[3], create=True)
    assert first.db != second.db
    original = _commit(world)
    again = _commit(world)
    assert (original.newly_confirmed, again.reconciled, again.newly_confirmed) == (
        1,
        1,
        0,
    )
