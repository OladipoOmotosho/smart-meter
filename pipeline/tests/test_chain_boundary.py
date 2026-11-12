"""Task 6.4 gate additions: event fields via the ABI and teardown after failure."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from smart_meter import chain
from smart_meter.fingerprint import digest, record_key
from smart_meter.models import Reading
from web3 import Web3

READING = Reading("EVENT-METER", "2022-01-01T00:00:00Z", 60)
TESTS = Path(__file__).resolve().parent


@pytest.mark.chain
def test_committed_event_fields_match_abi_and_state(deployment):
    w3, registry = deployment.w3, deployment.registry
    key = record_key(READING.meter_id, READING.interval_start)
    value = digest(READING)
    result = chain.send_tx(
        w3, registry.functions.commit(key, value), deployment.aggregator_key
    )
    assert result.state is chain.TxState.SUCCEEDED
    receipt = w3.eth.get_transaction_receipt(result.tx_hash)
    assert len(receipt["logs"]) == 1
    log = receipt["logs"][0]
    assert log["address"] == registry.address
    assert bytes(log["topics"][0]) == bytes(
        Web3.keccak(text="Committed(bytes32,bytes32,address,uint64)")
    )
    (event,) = registry.events.Committed().process_receipt(receipt)
    block = w3.eth.get_block(receipt["blockNumber"])
    assert event["args"]["recordKey"] == key
    assert event["args"]["digest"] == value
    assert event["args"]["submitter"] == deployment.aggregator
    assert event["args"]["committedAt"] == block["timestamp"]
    stored = registry.functions.getCommitment(key).call()
    assert tuple(stored) == (value, block["timestamp"], deployment.aggregator)


FAILING_TEST = """
import json, os

def test_deliberate_failure(anvil_node, deployment):
    with open(os.environ["PROBE_OUT"], "w") as handle:
        json.dump({"pid": anvil_node.process.pid, "url": anvil_node.rpc_url}, handle)
    assert False, "deliberate failure inside a chain fixture"
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.chain
def test_owned_node_is_stopped_after_a_failing_test(tmp_path):
    (tmp_path / "test_failing.py").write_text(FAILING_TEST)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    probe = tmp_path / "probe.json"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTHONPATH": os.pathsep.join([str(TESTS.parent), str(TESTS)]),
        "PROBE_OUT": str(probe),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
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
            str(tmp_path / "test_failing.py"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = run.stdout + run.stderr
    assert run.returncode == 1, output
    assert "1 failed" in output and "deliberate failure" in output
    started = json.loads(probe.read_text())
    assert not _alive(started["pid"])
    port = int(started["url"].rsplit(":", 1)[1])
    with socket.socket() as client:
        client.settimeout(0.2)
        assert client.connect_ex(("127.0.0.1", port)) != 0
