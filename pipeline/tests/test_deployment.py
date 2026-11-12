"""Task 6.1: deployment records and context validation (R4.6, R6.3, R9.4-R9.5)."""

import json
import socket
from dataclasses import replace

import pytest
from smart_meter import chain, db
from smart_meter.aggregator import ingest_in_context
from smart_meter.config import ARTIFACT_PATH
from smart_meter.fingerprint import KEY_DOMAIN, READING_DOMAIN, digest, record_key
from smart_meter.models import Reading, Verdict
from smart_meter.verifier import verify_in_context
from web3 import Web3

READING = Reading("CTX-METER", "2022-01-01T00:00:00Z", 60)
IDENTITY = (READING.meter_id, READING.interval_start)
THROWAWAY_KEY = "0x" + "11" * 32
ADDRESS_A = Web3.to_checksum_address("0x" + "aa" * 20)
ADDRESS_B = Web3.to_checksum_address("0x" + "bb" * 20)


def _context(**changes) -> chain.DeploymentContext:
    base = chain.DeploymentContext(
        chain_id=31337,
        registry_address=ADDRESS_A,
        deployment_tx_hash="0x" + "01" * 32,
        deployment_block_number=1,
        deployment_block_hash="0x" + "02" * 32,
        runtime_code_hash="0x" + "03" * 32,
        admin=ADDRESS_A,
        aggregator=ADDRESS_B,
        versions={
            "contract": "MeterCommitmentRegistry",
            "compiler": "0.8.24+commit.e11b9ed9",
            "node_client": "anvil/v1.9.0",
            "reading_format": READING_DOMAIN,
            "key_format": KEY_DOMAIN,
        },
    )
    return replace(base, **changes)


# --- Record format (fast) -----------------------------------------------------


def test_record_round_trips_and_has_only_public_fields(tmp_path):
    path = tmp_path / "deployment.json"
    chain.save_deployment(path, _context())
    assert chain.load_deployment(path) == _context()
    record = json.loads(path.read_text())
    assert set(record) == {
        "format",
        "chain_id",
        "registry_address",
        "deployment_tx_hash",
        "deployment_block_number",
        "deployment_block_hash",
        "runtime_code_hash",
        "admin",
        "aggregator",
        "versions",
    }
    assert not any("key" in name or "private" in name for name in record)


def test_existing_record_is_never_replaced(tmp_path):
    path = tmp_path / "deployment.json"
    chain.save_deployment(path, _context())
    with pytest.raises(chain.DeploymentContextError, match="already exists"):
        chain.save_deployment(path, _context(chain_id=1))
    assert chain.load_deployment(path).chain_id == 31337
    assert sorted(p.name for p in tmp_path.iterdir()) == ["deployment.json"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("chain_id", True, "chain_id"),
        ("chain_id", 0, "chain_id"),
        ("deployment_block_number", -1, "deployment_block_number"),
        ("registry_address", ADDRESS_A.lower(), "registry_address"),
        ("admin", "0x" + "00" * 20, "admin"),
        ("runtime_code_hash", "0x" + "03" * 31, "runtime_code_hash"),
        ("deployment_block_hash", "0x" + "AB" * 32, "deployment_block_hash"),
        ("deployment_tx_hash", "0x" + "zz" * 32, "deployment_tx_hash"),
        ("format", "smart-meter/deployment/v0", "format"),
    ],
)
def test_malformed_record_is_rejected(field, value, message):
    record = _context().to_json()
    record[field] = value
    with pytest.raises(chain.DeploymentContextError, match=message):
        chain.DeploymentContext.from_json(record)


@pytest.mark.parametrize("extra", ["aggregator_private_key", "admin_private_key"])
def test_record_with_unexpected_secret_field_is_rejected(extra):
    record = _context().to_json() | {extra: THROWAWAY_KEY}
    with pytest.raises(chain.DeploymentContextError, match="unexpected"):
        chain.DeploymentContext.from_json(record)


def test_missing_or_incomplete_record_is_actionable(tmp_path):
    with pytest.raises(chain.DeploymentContextError, match="not found"):
        chain.load_deployment(tmp_path / "absent.json")
    record = _context().to_json()
    del record["runtime_code_hash"]
    record["versions"] = {"contract": "MeterCommitmentRegistry"}
    with pytest.raises(chain.DeploymentContextError, match="missing"):
        chain.DeploymentContext.from_json(record)


# --- Unreachable RPC (fast) ---------------------------------------------------


def _closed_rpc() -> Web3:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return Web3(
        Web3.HTTPProvider(f"http://127.0.0.1:{port}", request_kwargs={"timeout": 2})
    )


def _artifact(tmp_path):
    """A faithful copy of the built artifact and its runtime-code hash."""
    return _real_artifact(tmp_path, lambda artifact: None)


def test_unreachable_rpc_is_audit_error_not_missing(tmp_path):
    artifact, code_hash = _artifact(tmp_path)
    conn = db.connect(tmp_path / "readings.sqlite")
    try:
        results = verify_in_context(
            conn,
            _closed_rpc(),
            _context(runtime_code_hash=code_hash),
            artifact,
            [IDENTITY],
        )
    finally:
        conn.close()
    assert [r.outcome for r in results] == [Verdict.ERROR]
    assert "chain ID failed" in results[0].reason
    assert results[0].record_key == record_key(*IDENTITY).hex()


def test_unreachable_rpc_stops_ingestion_before_storage(tmp_path):
    artifact, code_hash = _artifact(tmp_path)
    conn = db.connect(tmp_path / "readings.sqlite")
    try:
        with pytest.raises(chain.DeploymentContextError, match="chain ID failed"):
            ingest_in_context(
                [READING],
                conn,
                _closed_rpc(),
                _context(runtime_code_hash=code_hash),
                artifact,
                THROWAWAY_KEY,
                tmp_path / "results.csv",
            )
        assert db.get_reading(conn, *IDENTITY) is None
    finally:
        conn.close()
    assert not (tmp_path / "results.csv").exists()


def test_artifact_mismatch_fails_before_any_rpc(tmp_path):
    artifact, _ = _artifact(tmp_path)
    with pytest.raises(chain.DeploymentContextError, match="artifact does not match"):
        chain.validate_deployment(_closed_rpc(), _context(), artifact)
    with pytest.raises(chain.DeploymentContextError, match="not found"):
        chain.validate_deployment(_closed_rpc(), _context(), tmp_path / "absent.json")


def _real_artifact(tmp_path, mutate):
    artifact = json.loads(ARTIFACT_PATH.read_text())
    mutate(artifact)
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(artifact))
    runtime = artifact["deployedBytecode"]["object"]
    return path, "0x" + bytes(Web3.keccak(hexstr=runtime)).hex()


def _drop(name):
    return lambda a: a.update(abi=[e for e in a["abi"] if e.get("name") != name])


def _retype_event(a):
    for entry in a["abi"]:
        if entry.get("name") == "Committed":
            entry["inputs"][2]["indexed"] = False


def _retype_output(a):
    for entry in a["abi"]:
        if entry.get("name") == "isCommitted":
            entry["outputs"][0]["type"] = "uint256"


@pytest.mark.parametrize(
    "mutate",
    [
        _drop("getCommitment"),
        _drop("commit"),
        _drop("Committed"),
        _drop("hasRole"),
        lambda a: a.update(abi=[]),
        lambda a: a.pop("abi"),
        _retype_event,
        _retype_output,
    ],
    ids=[
        "no-getCommitment",
        "no-commit",
        "no-event",
        "no-hasRole",
        "empty-abi",
        "missing-abi",
        "event-indexing",
        "output-type",
    ],
)
def test_tampered_abi_is_rejected_before_any_rpc(tmp_path, mutate):
    artifact, code_hash = _real_artifact(tmp_path, mutate)
    context = _context(runtime_code_hash=code_hash)
    with pytest.raises(chain.DeploymentContextError, match=r"ABI|malformed"):
        chain.validate_deployment(_closed_rpc(), context, artifact)


def test_abi_that_code_does_not_implement_is_rejected(tmp_path):
    def foreign_runtime(a):
        a["deployedBytecode"]["object"] = "0x6000"

    artifact, code_hash = _real_artifact(tmp_path, foreign_runtime)
    with pytest.raises(chain.DeploymentContextError, match="not implemented"):
        chain.validate_deployment(
            _closed_rpc(), _context(runtime_code_hash=code_hash), artifact
        )


def _runtime(*parts: bytes):
    return lambda a: a["deployedBytecode"].update(object="0x" + b"".join(parts).hex())


SELECTORS = [
    bytes(Web3.keccak(text=sig)[:4])
    for sig in (
        "commit(bytes32,bytes32)",
        "getCommitment(bytes32)",
        "isCommitted(bytes32)",
        "AGGREGATOR_ROLE()",
        "hasRole(bytes32,address)",
    )
]
TOPIC = bytes(Web3.keccak(text="Committed(bytes32,bytes32,address,uint64)"))


def test_code_with_event_but_missing_selector_is_rejected(tmp_path):
    """Review B08 control: isolates the selector check from the event check."""
    artifact, code_hash = _real_artifact(tmp_path, _runtime(TOPIC, *SELECTORS[1:]))
    with pytest.raises(
        chain.DeploymentContextError, match=r"commit\(bytes32,bytes32\) is not"
    ):
        chain.validate_deployment(
            _closed_rpc(), _context(runtime_code_hash=code_hash), artifact
        )


def test_code_with_selectors_but_missing_event_is_rejected(tmp_path):
    artifact, code_hash = _real_artifact(tmp_path, _runtime(*SELECTORS))
    with pytest.raises(
        chain.DeploymentContextError, match=r"event .* is not implemented"
    ):
        chain.validate_deployment(
            _closed_rpc(), _context(runtime_code_hash=code_hash), artifact
        )


# --- Live deployments on the owned Anvil (tests/conftest.py) ------------------


def _rpc(w3, method, *params):
    response = w3.provider.make_request(method, list(params))
    assert "error" not in response, response
    return response["result"]


@pytest.fixture
def deployed(deployment):
    d = deployment
    return d.w3, d.registry, d.context, d.admin, d.aggregator, d.attacker, d


@pytest.mark.chain
def test_capture_records_live_deployment_identity(deployed):
    w3, registry, context, admin, aggregator, _, _ = deployed
    receipt = w3.eth.get_transaction_receipt(context.deployment_tx_hash)
    code = w3.eth.get_code(registry.address)
    assert context.chain_id == w3.eth.chain_id
    assert context.registry_address == registry.address
    assert context.deployment_block_number == receipt["blockNumber"]
    assert context.deployment_block_hash == "0x" + bytes(receipt["blockHash"]).hex()
    assert context.runtime_code_hash == "0x" + bytes(Web3.keccak(code)).hex()
    assert (context.admin, context.aggregator) == (admin, aggregator)
    assert context.versions["compiler"].startswith("0.8.24")
    assert context.versions["node_client"].lower().startswith("anvil")
    chain.validate_deployment(w3, context, ARTIFACT_PATH)
    chain.validate_deployment(w3, context, ARTIFACT_PATH, writer=aggregator)


@pytest.mark.chain
def test_capture_rejects_unprivileged_aggregator_and_non_creation(deployed):
    w3, _, context, admin, _, other, _ = deployed
    with pytest.raises(chain.DeploymentContextError, match="AGGREGATOR_ROLE"):
        chain.capture_deployment(
            w3, context.deployment_tx_hash, ARTIFACT_PATH, admin=admin, aggregator=other
        )
    with pytest.raises(chain.DeploymentContextError, match="DEFAULT_ADMIN_ROLE"):
        chain.capture_deployment(
            w3,
            context.deployment_tx_hash,
            ARTIFACT_PATH,
            admin=other,
            aggregator=context.aggregator,
        )
    transfer = w3.eth.send_transaction({"from": admin, "to": other, "value": 1})
    w3.eth.wait_for_transaction_receipt(transfer)
    with pytest.raises(chain.DeploymentContextError, match="did not create"):
        chain.capture_deployment(
            w3,
            "0x" + bytes(transfer).hex(),
            ARTIFACT_PATH,
            admin=admin,
            aggregator=other,
        )


@pytest.mark.chain
@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c, other: replace(c, chain_id=c.chain_id + 1), "chain ID"),
        (lambda c, other: replace(c, registry_address=other), "no contract code"),
        (
            lambda c, other: replace(c, deployment_tx_hash="0x" + "ee" * 32),
            "not found",
        ),
        (
            lambda c, other: replace(c, deployment_block_hash="0x" + "ee" * 32),
            "deployment block differs",
        ),
        (
            lambda c, other: replace(
                c, deployment_block_number=c.deployment_block_number + 1
            ),
            "deployment block differs",
        ),
    ],
    ids=["wrong-chain", "no-bytecode", "unknown-tx", "block-hash", "block-number"],
)
def test_wrong_context_is_rejected_for_audit(deployed, change, message):
    w3, _, context, _, _, other, _ = deployed
    with pytest.raises(chain.DeploymentContextError, match=message):
        chain.validate_deployment(w3, change(context, other), ARTIFACT_PATH)


@pytest.mark.chain
def test_other_registry_with_same_code_is_rejected(deployed, new_registry):
    w3, _, context, _, _, _, _ = deployed
    _, second = new_registry(w3)
    wrong = replace(context, registry_address=second.address)
    with pytest.raises(chain.DeploymentContextError, match="did not create"):
        chain.validate_deployment(w3, wrong, ARTIFACT_PATH)


@pytest.mark.chain
def test_replaced_runtime_code_is_rejected(deployed):
    w3, registry, context, _, _, _, _ = deployed
    _rpc(w3, "anvil_setCode", registry.address, "0x6000")
    with pytest.raises(chain.DeploymentContextError, match="runtime code"):
        chain.validate_deployment(w3, context, ARTIFACT_PATH)


@pytest.mark.chain
def test_chain_reset_and_identical_redeploy_is_rejected(
    chain_w3, anvil_node, new_registry
):
    w3 = chain_w3
    snapshot = _rpc(w3, "evm_snapshot")
    tx_hash, registry = new_registry(w3)
    context = chain.capture_deployment(
        w3,
        tx_hash,
        ARTIFACT_PATH,
        admin=anvil_node.admin.address,
        aggregator=anvil_node.aggregator.address,
    )
    assert _rpc(w3, "evm_revert", snapshot) is True
    with pytest.raises(chain.DeploymentContextError, match="no contract code"):
        chain.validate_deployment(w3, context, ARTIFACT_PATH)
    _rpc(w3, "evm_increaseTime", 3600)
    _, redeployed = new_registry(w3)
    assert redeployed.address == registry.address  # same sender nonce, same code
    with pytest.raises(chain.DeploymentContextError, match=r"block|not found"):
        chain.validate_deployment(w3, context, ARTIFACT_PATH)


@pytest.mark.chain
def test_writer_must_be_recorded_aggregator_with_current_role(deployed):
    w3, registry, context, admin, aggregator, other, _ = deployed
    with pytest.raises(chain.DeploymentContextError, match="not the recorded"):
        chain.validate_deployment(w3, context, ARTIFACT_PATH, writer=other)
    role = registry.functions.AGGREGATOR_ROLE().call()
    w3.eth.wait_for_transaction_receipt(
        registry.functions.revokeRole(role, aggregator).transact({"from": admin})
    )
    with pytest.raises(chain.DeploymentContextError, match="AGGREGATOR_ROLE"):
        chain.validate_deployment(w3, context, ARTIFACT_PATH, writer=aggregator)
    chain.validate_deployment(w3, context, ARTIFACT_PATH)  # audits remain possible


@pytest.mark.chain
def test_ingest_and_audit_in_valid_context(deployed, tmp_path):
    w3, registry, context, *_ = deployed
    conn = db.connect(tmp_path / "readings.sqlite")
    try:
        summary = ingest_in_context(
            [READING],
            conn,
            w3,
            context,
            ARTIFACT_PATH,
            deployed[6].aggregator_key,
            tmp_path / "results.csv",
        )
        assert summary.newly_confirmed == 1
        key = record_key(*IDENTITY)
        assert registry.functions.getCommitment(key).call()[0] == digest(READING)
        results = verify_in_context(conn, w3, context, ARTIFACT_PATH, [IDENTITY])
        assert [r.outcome for r in results] == [Verdict.VERIFIED]
    finally:
        conn.close()


@pytest.mark.chain
def test_wrong_signer_and_wrong_deployment_have_no_effects(deployed, tmp_path):
    w3, registry, context, _, _, other, _ = deployed
    conn = db.connect(tmp_path / "readings.sqlite")
    key = record_key(*IDENTITY)
    try:
        with pytest.raises(chain.DeploymentContextError, match="not the recorded"):
            ingest_in_context(
                [READING],
                conn,
                w3,
                context,
                ARTIFACT_PATH,
                deployed[6].attacker_key,
                tmp_path / "results.csv",
            )
        wrong = replace(context, registry_address=other)
        with pytest.raises(chain.DeploymentContextError, match="no contract code"):
            ingest_in_context(
                [READING],
                conn,
                w3,
                wrong,
                ARTIFACT_PATH,
                deployed[6].aggregator_key,
                tmp_path / "results.csv",
            )
        assert db.get_reading(conn, *IDENTITY) is None
        assert registry.functions.isCommitted(key).call() is False
        audited = verify_in_context(
            conn, w3, wrong, ARTIFACT_PATH, [IDENTITY], tmp_path / "audit.csv"
        )
    finally:
        conn.close()
    assert [r.outcome for r in audited] == [Verdict.ERROR]
    assert audited[0].reason.startswith("deployment context invalid")
    assert "ERROR" in (tmp_path / "audit.csv").read_text()
    assert not (tmp_path / "results.csv").exists()
