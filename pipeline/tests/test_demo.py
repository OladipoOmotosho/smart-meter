"""R7-R9: real two-hour CLI workflows, exit codes and independent scenarios."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from smart_meter import demo, local_chain, scenarios
from smart_meter.models import Verdict

SOURCE = Path(__file__).parent / "fixtures/two_hours.csv"


@pytest.mark.parametrize(
    "outcomes,code",
    [
        ([Verdict.VERIFIED], 0),
        ([Verdict.TAMPERED], 2),
        ([Verdict.MISSING_RECORD], 2),
        ([Verdict.ERROR, Verdict.TAMPERED], 1),
        ([], 1),
    ],
)
def test_exit_prioritizes_operational_errors(outcomes, code):
    assert demo.audit_exit([SimpleNamespace(outcome=v) for v in outcomes]) == code


@pytest.mark.parametrize(
    "args", [["audit"], ["new"], ["resume"], ["audit", "--run-dir", "missing"]]
)
def test_missing_cli_prerequisites_fail(args):
    assert demo.main(args) == 1


def test_public_chain_is_refused():
    with pytest.raises(ValueError, match="loopback"):
        local_chain.local_client("https://example.com")


@pytest.mark.chain
@pytest.mark.e2e
def test_two_hour_new_resume_audit_and_findings(deployment, tmp_path):
    rpc = deployment.node.rpc_url
    first, second = tmp_path / "first", tmp_path / "second"
    for path in (first, second):
        assert (
            demo.main(
                ["new", "--run-dir", str(path), "--source", str(SOURCE), "--rpc", rpc]
            )
            == 0
        )
        assert demo.main(["audit", "--run-dir", str(path), "--rpc", rpc]) == 0
    manifests = [
        json.loads((path / "manifest.json").read_text()) for path in (first, second)
    ]
    assert (
        manifests[0]["deployment"]["registry_address"]
        != manifests[1]["deployment"]["registry_address"]
    )
    before = deployment.w3.eth.block_number
    assert demo.main(["resume", "--run-dir", str(first), "--rpc", rpc]) == 0
    assert deployment.w3.eth.block_number == before
    assert (
        demo.main(
            ["new", "--run-dir", str(first), "--source", str(SOURCE), "--rpc", rpc]
        )
        == 1
    )
    import sqlite3

    with sqlite3.connect(first / "readings.sqlite") as conn:
        conn.execute("DELETE FROM readings")
    assert demo.main(["audit", "--run-dir", str(first), "--rpc", rpc]) == 2
    assert (
        demo.main(["audit", "--run-dir", str(first), "--rpc", "http://127.0.0.1:1"])
        == 1
    )
    with (first / "audit.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4 and rows[-1]["verdict"] == "MISSING_RECORD"


@pytest.mark.chain
@pytest.mark.e2e
def test_scenario_runner_exports_all_expected_outcomes(deployment, tmp_path):
    root = tmp_path / "scenarios"
    assert scenarios.run_scenarios(root, deployment.w3) == 0
    with (root / "scenarios.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert {r["scenario_id"] for r in rows} == set(scenarios.EXPECTED)
    assert all(r["passed"] == "True" for r in rows)
    assert len({r["registry_address"] for r in rows}) == len(rows)
    assert next(r for r in rows if r["scenario_id"] == "A4")["verdict"] == "VERIFIED"
    assert next(r for r in rows if r["scenario_id"] == "S9")["status"] == "0"


@pytest.mark.chain
@pytest.mark.e2e
def test_disposable_demo_runs_twice_and_stops_owned_node(tmp_path):
    for name in ("one", "two"):
        assert (
            demo.main(
                ["demo", "--run-dir", str(tmp_path / name), "--source", str(SOURCE)]
            )
            == 0
        )
