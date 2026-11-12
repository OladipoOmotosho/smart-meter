"""Task 7.2: run manifests, expected records and writer ownership.

Requirements: R2.5-R2.6, R5.2, R5.6, R6.4, R9.2.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import deployment_context
from smart_meter import runs
from smart_meter.config import run_paths
from smart_meter.fingerprint import KEY_DOMAIN, READING_DOMAIN, digest, record_key
from smart_meter.models import Reading

FIXTURES = Path(__file__).parent / "fixtures"
THREE_HOURS = FIXTURES / "rounding_boundaries.csv"
PIPELINE = Path(__file__).resolve().parents[1]


_deployment = deployment_context


@pytest.fixture
def source(tmp_path):
    copy = tmp_path / "source.csv"
    shutil.copyfile(THREE_HOURS, copy)
    return copy


@pytest.fixture
def paths(tmp_path):
    return run_paths("run-a", base=tmp_path / "results", create=True)


def _config(source, **changes):
    return replace(runs.RunConfig(source_path=source, meter_id="SYN-1"), **changes)


def _snapshot(paths):
    return {p.name: p.read_bytes() for p in paths.root.iterdir() if p.is_file()}


# --- New runs -----------------------------------------------------------------


def test_new_run_persists_manifest_and_expected_records(paths, source):
    prepared = runs.open_run(paths, _config(source), _deployment())
    assert not prepared.resumed and len(prepared.expected) == 3
    manifest = json.loads(paths.manifest.read_text())
    assert manifest["format"] == runs.MANIFEST_FORMAT
    assert manifest["run_id"] == "run-a"
    assert (
        manifest["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert manifest["conversion"] == runs.CONVERSION
    selection = manifest["selection"]
    assert (selection["meter_id"], selection["limit"]) == ("SYN-1", None)
    assert selection["emitted_intervals"] == 3 and selection["source_rows"] == 180
    assert selection["selected_start"] == prepared.readings[0].interval_start
    assert manifest["formats"] == {"reading": READING_DOMAIN, "key": KEY_DOMAIN}
    assert manifest["deployment"] == _deployment().to_json()
    expected_bytes = paths.expected.read_bytes()
    assert manifest["expected_records"] == {
        "file": "expected_records.json",
        "sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "count": 3,
    }
    for record, reading in zip(prepared.expected, prepared.readings, strict=True):
        assert record.record_key == record_key(reading.meter_id, reading.interval_start)
        assert record.digest == digest(reading)
        assert record.seq == reading.seq
    assert runs.load_expected(paths) == prepared.expected
    names = set()

    def collect(node):
        if isinstance(node, dict):
            names.update(node)
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(manifest)
    collect(json.loads(expected_bytes))
    assert not [
        n for n in names if "private" in n or (n.endswith("_key") and n != "record_key")
    ]


def test_limit_bounds_selection_and_is_recorded(paths, source):
    prepared = runs.open_run(paths, _config(source, limit=2), _deployment())
    assert [r.seq for r in prepared.expected] == [0, 1]
    selection = json.loads(paths.manifest.read_text())["selection"]
    assert (selection["limit"], selection["emitted_intervals"]) == (2, 2)
    assert selection["source_rows"] == 120  # stopped after the second hour


def test_existing_run_is_never_reprepared(paths, source):
    runs.open_run(paths, _config(source), _deployment())
    before = _snapshot(paths)
    with pytest.raises(runs.RunError, match="already prepared"):
        runs.open_run(paths, _config(source, limit=1), _deployment())
    assert _snapshot(paths) == before


def test_unsupported_interval_is_rejected(paths, source):
    with pytest.raises(runs.IncompatibleRun, match="60-minute"):
        runs.open_run(paths, _config(source, interval_minutes=30), _deployment())
    assert not paths.manifest.exists()


# --- Resume -------------------------------------------------------------------


def test_matching_resume_is_accepted_unchanged(paths, source):
    first = runs.open_run(paths, _config(source), _deployment())
    before = _snapshot(paths)
    again = runs.open_run(paths, _config(source), _deployment(), resume=True)
    assert again.resumed and again.expected == first.expected
    assert again.readings == first.readings
    assert _snapshot(paths) == before


def _edit_source(source):
    text = source.read_text().replace(",1,0,0,0,60,0", ",2,0,0,0,60,0", 1)
    source.write_text(text)


def _edit_expected(paths):
    document = json.loads(paths.expected.read_text())
    document["records"][0]["digest"] = "0x" + "00" * 32
    paths.expected.write_text(json.dumps(document))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p, s: {"config": _config(s, limit=2)}, "expected records|selection"),
        (lambda p, s: {"config": _config(s, meter_id="OTHER")}, "expected records"),
        (lambda p, s: {"deployment": _deployment(chain_id=1)}, "deployment"),
        (lambda p, s: _edit_source(s) or {}, "expected records|source"),
        (lambda p, s: _edit_expected(p) or {}, "changed since"),
        (lambda p, s: p.manifest.unlink() or {}, "no manifest"),
    ],
    ids=[
        "other-limit",
        "other-meter",
        "other-deployment",
        "source-edited",
        "expected-edited",
        "manifest-missing",
    ],
)
def test_incompatible_resume_is_refused_and_changes_nothing(
    paths, source, change, message
):
    runs.open_run(paths, _config(source), _deployment())
    overrides = change(paths, source)
    before = _snapshot(paths)
    with pytest.raises(runs.IncompatibleRun, match=message):
        runs.open_run(
            paths,
            overrides.get("config", _config(source)),
            overrides.get("deployment", _deployment()),
            resume=True,
        )
    assert _snapshot(paths) == before


# --- Interrupted preparation --------------------------------------------------


def test_manifest_write_failure_stops_and_identical_retry_completes(
    paths, source, monkeypatch
):
    real = runs._create_only

    def fail_manifest(path, content):
        if path == paths.manifest:
            raise OSError("disk full")
        real(path, content)

    monkeypatch.setattr(runs, "_create_only", fail_manifest)
    with pytest.raises(OSError, match="disk full"):
        runs.open_run(paths, _config(source), _deployment())
    assert paths.expected.exists() and not paths.manifest.exists()
    monkeypatch.undo()

    with pytest.raises(runs.IncompatibleRun, match="partially prepared"):
        runs.open_run(paths, _config(source, limit=1), _deployment())
    assert not paths.manifest.exists()
    prepared = runs.open_run(paths, _config(source), _deployment())
    assert paths.manifest.exists() and len(prepared.expected) == 3
    assert not [p for p in paths.root.iterdir() if p.name.endswith(".tmp")]


# --- Writer ownership ---------------------------------------------------------


def test_second_writer_in_process_is_rejected_until_release(paths):
    with runs.writer_lock(paths):
        with pytest.raises(runs.WriterBusy, match="another writer"):
            with runs.writer_lock(paths):
                pytest.fail("second writer acquired the lock")
    with runs.writer_lock(paths):
        pass


HOLDER = """
import sys, time
from pathlib import Path
from smart_meter import runs
from smart_meter.config import run_paths
paths = run_paths("run-a", base=Path(sys.argv[1]))
with runs.writer_lock(paths):
    Path(sys.argv[2]).write_text("held")
    time.sleep(120)
"""


def test_lock_blocks_another_process_and_is_released_when_it_crashes(paths, tmp_path):
    ready = tmp_path / "held"
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(paths.root.parent), str(ready)],
        cwd=PIPELINE,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(PIPELINE)},
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists():
            assert holder.poll() is None, "lock holder exited early"
            assert time.monotonic() < deadline, "lock holder never acquired"
            time.sleep(0.05)
        with pytest.raises(runs.WriterBusy):
            with runs.writer_lock(paths):
                pass
    finally:
        holder.kill()  # simulate a crash: no cleanup code runs
        holder.wait(timeout=10)
    assert paths.lock.exists()  # a stale file remains but does not block
    with runs.writer_lock(paths):
        pass


def test_readings_from_prepared_run_match_loader(paths, source):
    prepared = runs.open_run(paths, _config(source), _deployment())
    assert all(isinstance(r, Reading) for r in prepared.readings)
    assert [r.unit for r in prepared.readings] == ["Wh"] * 3


# --- Review B04: error paths of expected-record loading -----------------------


def _rewrite_expected(paths, document):
    content = json.dumps(document).encode()
    paths.expected.write_bytes(content)
    manifest = json.loads(paths.manifest.read_text())
    manifest["expected_records"]["sha256"] = hashlib.sha256(content).hexdigest()
    paths.manifest.write_text(json.dumps(manifest))


def test_expected_records_with_wrong_format_are_unreadable(paths, source):
    runs.open_run(paths, _config(source), _deployment())
    document = json.loads(paths.expected.read_text())
    document["format"] = "something-else/v0"
    _rewrite_expected(paths, document)
    with pytest.raises(runs.IncompatibleRun, match="unreadable"):
        runs.load_expected(paths)


def test_expected_records_with_duplicate_keys_are_refused(paths, source):
    runs.open_run(paths, _config(source), _deployment())
    document = json.loads(paths.expected.read_text())
    document["records"][1]["record_key"] = document["records"][0]["record_key"]
    _rewrite_expected(paths, document)
    with pytest.raises(runs.IncompatibleRun, match="duplicate or malformed"):
        runs.load_expected(paths)


def test_load_expected_detects_change_and_missing_files(paths, source):
    runs.open_run(paths, _config(source), _deployment())
    paths.expected.write_bytes(paths.expected.read_bytes() + b" ")
    with pytest.raises(runs.IncompatibleRun, match="changed since"):
        runs.load_expected(paths)
    paths.expected.unlink()
    with pytest.raises(runs.IncompatibleRun, match="missing"):
        runs.load_expected(paths)
