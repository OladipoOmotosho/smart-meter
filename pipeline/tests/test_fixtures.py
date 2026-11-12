"""Task 6.3: owned Anvil fixtures and a keyless audit client (R6.5, R9.3, R9.5)."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from smart_meter import db
from smart_meter.aggregator import ingest_in_context
from smart_meter.config import ARTIFACT_PATH
from smart_meter.fingerprint import record_key
from smart_meter.models import Reading, Verdict
from smart_meter.verifier import verify_in_context

READING = Reading("FIXTURE-METER", "2022-01-01T00:00:00Z", 60)
# Public addresses of the development mnemonic's first three accounts.
DEV_ADDRESSES = [
    "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
]


@pytest.mark.chain
def test_node_is_owned_loopback_with_throwaway_accounts(anvil_node, chain_w3):
    assert anvil_node.process.poll() is None
    assert anvil_node.rpc_url.startswith("http://127.0.0.1:")
    assert not anvil_node.rpc_url.endswith(":8545")  # never the developer default
    assert str(anvil_node.rpc_url.rsplit(":", 1)[1]) in anvil_node.process.args
    assert chain_w3.eth.chain_id == 31337
    accounts = [anvil_node.admin, anvil_node.aggregator, anvil_node.attacker]
    assert [a.address for a in accounts] == DEV_ADDRESSES


ISOLATION_PAIR = """
import json, os

def test_a_changes_chain(deployment):
    with open(os.environ["PROBE_OUT"], "w") as handle:
        json.dump({"registry": deployment.registry.address,
                   "height": deployment.w3.eth.block_number}, handle)

def test_b_sees_reverted_chain(chain_w3):
    with open(os.environ["PROBE_OUT"]) as handle:
        seen = json.load(handle)
    assert chain_w3.eth.get_code(seen["registry"]) == b""
    assert chain_w3.eth.block_number < seen["height"]
"""


@pytest.mark.chain
def test_each_chain_test_starts_from_a_reverted_snapshot(tmp_path):
    """Self-contained: an inner session runs both tests in a fixed order."""
    (tmp_path / "test_pair.py").write_text(ISOLATION_PAIR)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    tests_dir = Path(__file__).resolve().parent
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "conftest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--basetemp",
            str(tmp_path / "inner"),
            str(tmp_path / "test_pair.py"),
        ],
        cwd=tmp_path,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "PYTHONPATH": os.pathsep.join([str(tests_dir.parent), str(tests_dir)]),
            "PROBE_OUT": str(tmp_path / "probe.json"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = run.stdout + run.stderr
    assert run.returncode == 0, output
    assert "2 passed" in output


@pytest.mark.chain
def test_keyless_audit_sends_nothing_and_changes_nothing(deployment, reader, tmp_path):
    conn = db.connect(tmp_path / "readings.sqlite")
    try:
        ingest_in_context(
            [READING],
            conn,
            deployment.w3,
            deployment.context,
            ARTIFACT_PATH,
            deployment.aggregator_key,
            tmp_path / "ingest.csv",
        )
        key = record_key(READING.meter_id, READING.interval_start)
        before_rows = list(conn.iterdump())
        before_entry = deployment.registry.functions.getCommitment(key).call()
        before_height = reader.eth.block_number
        before_nonces = [reader.eth.get_transaction_count(a) for a in DEV_ADDRESSES]

        assert reader.eth.default_account is None or not reader.eth.default_account
        results = verify_in_context(
            conn,
            reader,
            deployment.context,
            ARTIFACT_PATH,
            [(READING.meter_id, READING.interval_start)],
            tmp_path / "audit.csv",
        )

        assert [r.outcome for r in results] == [Verdict.VERIFIED]
        assert list(conn.iterdump()) == before_rows
        assert deployment.registry.functions.getCommitment(key).call() == before_entry
        assert reader.eth.block_number == before_height
        assert [
            reader.eth.get_transaction_count(a) for a in DEV_ADDRESSES
        ] == before_nonces
    finally:
        conn.close()
    assert "VERIFIED" in (tmp_path / "audit.csv").read_text()


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_integration.py"
    spec = importlib.util.spec_from_file_location("run_integration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_passes_no_rpc_url_or_keys(monkeypatch, tmp_path):
    for name in (
        "RPC_URL",
        "AGGREGATOR_PRIVATE_KEY",
        "ADMIN_PRIVATE_KEY",
        "ATTACKER_PRIVATE_KEY",
        "CONTRACT_ADDRESS",
    ):
        monkeypatch.setenv(name, "personal-value")
    runner = _load_runner()
    seen = []

    def fake_run(args, cwd, env, check, **kwargs):
        seen.append(env)
        return subprocess.CompletedProcess(args, 0, "1 passed\n", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner.main(tmp_path / "report.xml") == 0
    assert len(seen) == 2  # forge build, then pytest
    for env in seen:
        assert set(env) == {
            "PATH",
            "HOME",
            "PYTHONDONTWRITEBYTECODE",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        }
        assert "personal-value" not in env.values()
