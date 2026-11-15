"""R10.4: collection/tool errors do not establish a caught security defect."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "mutation_probe", Path(__file__).resolve().parents[2] / "scripts/broken_controls.py"
)
harness = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = harness
spec.loader.exec_module(harness)


@pytest.mark.parametrize(
    "code,output",
    [
        (1, "ERROR collecting test.py\n1 error"),
        (4, "test not found"),
        (5, "no tests ran"),
    ],
)
def test_invalid_baseline_stops_mutation_run(monkeypatch, code, output):
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], code, output, ""),
    )
    monkeypatch.setattr(
        harness,
        "run_control",
        lambda *a: pytest.fail("mutation ran without a passing baseline"),
    )
    assert harness.main([]) == 1


def test_collection_error_is_not_caught_control(monkeypatch, tmp_path):
    source = tmp_path / "code.py"
    source.write_text("original")
    control = harness.Control(
        "probe",
        "code.py",
        (("original", "broken"),),
        "tests/test_probe.py::test_control",
    )
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 1, "ERROR collecting test.py\n1 error", ""
        ),
    )
    assert harness.run_control(control) != "CAUGHT"
    assert source.read_text() == "original"
