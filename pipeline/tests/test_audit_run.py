"""R6.1-R6.6: complete manifest audits and read-only evidence."""

import json
from pathlib import Path

import pytest
from helpers import Registry, deployment_context
from smart_meter import db, runs, verifier
from smart_meter.config import run_paths
from smart_meter.fingerprint import digest, record_key


def test_manifest_identity_must_match_its_key(tmp_path):
    paths = run_paths("audit", base=tmp_path, create=True)
    source = Path(__file__).parent / "fixtures/rounding_boundaries.csv"
    runs.open_run(paths, runs.RunConfig(source), deployment_context())
    document = json.loads(paths.expected.read_bytes())
    document["records"][0]["meter_id"] = "wrong-meter"
    with pytest.raises(runs.IncompatibleRun, match="identity"):
        runs._parse_expected(json.dumps(document).encode())


def test_malformed_commitment_metadata_is_error(tmp_path):
    conn = db.connect(tmp_path / "readings.sqlite")
    registry = Registry()

    class Call:
        def call(self):
            return bytes(32), "not-a-time", None

    registry.functions.getCommitment = lambda key: Call()
    try:
        result = verifier.verify(conn, registry, "M1", "2022-01-01T00:00:00Z")
        assert result.outcome.value == "ERROR"
    finally:
        conn.close()


@pytest.fixture
def audit_setup(tmp_path, monkeypatch):
    from types import SimpleNamespace

    paths = run_paths("audit", base=tmp_path, create=True)
    source = Path(__file__).parent / "fixtures/rounding_boundaries.csv"
    run = runs.open_run(paths, runs.RunConfig(source), deployment_context())
    conn = db.connect(paths.db)
    registry = Registry()
    for reading in run.readings:
        db.insert_reading(conn, reading)
        registry.entries[record_key(reading.meter_id, reading.interval_start)] = digest(
            reading
        )
    monkeypatch.setattr(verifier.chain, "validate_deployment", lambda *a: registry)
    w3 = SimpleNamespace(
        eth=SimpleNamespace(get_block=lambda _: {"hash": bytes.fromhex("aa" * 32)})
    )
    yield paths, run, conn, registry, w3
    conn.close()


@pytest.mark.parametrize(
    "change,outcome",
    [
        ("none", "VERIFIED"),
        ("value_wh=42", "TAMPERED"),
        ("unit='kWh'", "TAMPERED"),
        ("seq=99", "TAMPERED"),
        ("meter_id='moved'", "MISSING_RECORD"),
        ("delete", "MISSING_RECORD"),
        ("anchors", "MISSING_COMMITMENT"),
        ("both", "MISSING_BOTH"),
        ("value_wh='bad'", "ERROR"),
        ("rpc", "ERROR"),
        ("database", "ERROR"),
    ],
)
def test_manifest_outcomes_and_read_only(audit_setup, change, outcome):
    paths, run, conn, registry, w3 = audit_setup
    if change in {"delete", "both"}:
        conn.execute("DELETE FROM readings")
    elif "=" in change:
        conn.execute("UPDATE readings SET " + change)
    elif change == "rpc":
        registry.error = True
    if change in {"anchors", "both"}:
        registry.entries.clear()
    conn.commit()
    conn.close()
    if change == "database":
        paths.db.unlink()
    before = paths.db.read_bytes() if paths.db.exists() else None
    anchors = dict(registry.entries)
    rows = verifier.audit_run(paths, w3, Path("unused"), paths.root / "audit.csv")
    assert len(rows) == 3
    assert {row.outcome.value for row in rows} == {outcome}
    assert [row.record_key for row in rows] == [
        r.record_key.hex() for r in run.expected
    ]
    assert all(
        row.run_id == "audit" and row.expected_digest and row.reason and row.block_hash
        for row in rows
    )
    assert (paths.db.read_bytes() if paths.db.exists() else None) == before
    assert registry.entries == anchors


@pytest.mark.parametrize(
    "change", ["missing", "format", "count", "deployment", "expected", "block"]
)
def test_bad_context_aborts_before_audit(audit_setup, change):
    paths, _, _, _, w3 = audit_setup
    manifest = json.loads(paths.manifest.read_text())
    if change == "missing":
        paths.manifest.unlink()
    elif change == "expected":
        paths.expected.write_text("broken")
    elif change == "block":
        w3.eth.get_block = lambda _: {"hash": b"short"}
    else:
        if change == "format":
            manifest["format"] = "future"
        elif change == "count":
            manifest["expected_records"]["count"] = 0
        else:
            manifest["deployment"] = {}
        paths.manifest.write_text(json.dumps(manifest))
    with pytest.raises(verifier.AuditError):
        verifier.audit_run(paths, w3, Path("unused"))


@pytest.mark.property
def test_generated_audit_table_and_read_only():
    import sqlite3

    from hypothesis import given, settings
    from hypothesis import strategies as st
    from smart_meter.models import Reading

    @settings(max_examples=200)
    @given(st.integers(0, 10**8), st.booleans(), st.booleans(), st.booleans())
    def check(value, stored, anchored, changed):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(db.READINGS_TABLE)
        reading = Reading("M", "2022-01-01T00:00:00Z", value)
        registry = Registry()
        if stored:
            db.insert_reading(conn, reading)
        if anchored:
            from dataclasses import replace

            registry.entries[record_key(reading.meter_id, reading.interval_start)] = (
                digest(replace(reading, value_wh=value + int(changed)))
            )
        before = list(conn.iterdump())
        result = verifier.verify(
            conn, registry, reading.meter_id, reading.interval_start
        )
        want = (
            ("TAMPERED" if changed else "VERIFIED")
            if stored and anchored
            else (
                "MISSING_COMMITMENT"
                if stored
                else "MISSING_RECORD"
                if anchored
                else "MISSING_BOTH"
            )
        )
        assert result.outcome.value == want
        assert list(conn.iterdump()) == before
        conn.close()

    check()


@pytest.mark.chain
def test_manifest_audit_on_real_chain_is_read_only(deployment, tmp_path, reader):
    from smart_meter.aggregator import ingest_run
    from smart_meter.config import ARTIFACT_PATH

    paths = run_paths("live", base=tmp_path, create=True)
    source = Path(__file__).parent / "fixtures/rounding_boundaries.csv"
    run = runs.open_run(paths, runs.RunConfig(source), deployment.context)
    assert ingest_run(
        run, deployment.w3, ARTIFACT_PATH, deployment.aggregator_key
    ).complete
    before = paths.db.read_bytes()
    block = reader.eth.block_number
    assert {
        r.outcome.value for r in verifier.audit_run(paths, reader, ARTIFACT_PATH)
    } == {"VERIFIED"}
    assert paths.db.read_bytes() == before and reader.eth.block_number == block
    conn = db.connect(paths.db)
    conn.execute("DELETE FROM readings")
    conn.commit()
    conn.close()
    rows = verifier.audit_run(paths, reader, ARTIFACT_PATH)
    assert len(rows) == 3 and {r.outcome.value for r in rows} == {"MISSING_RECORD"}


def test_results_schema_refuses_mixed_headers(tmp_path):
    from smart_meter import results

    path = tmp_path / "results.csv"
    path.write_text("old,header\n")
    with pytest.raises(ValueError, match="schema"):
        results.log(path, "verify")
    with pytest.raises(ValueError, match="unknown"):
        results.log(tmp_path / "new.csv", "verify", unsupported="x")


@pytest.mark.property
def test_generated_deletion_never_shrinks_audit(audit_setup):
    from hypothesis import given, settings
    from hypothesis import strategies as st

    paths, run, conn, _registry, w3 = audit_setup

    @settings(max_examples=200)
    @given(st.integers(0, 1000000), st.sets(st.integers(0, 2)))
    def check(offset, deleted):
        conn.execute("DELETE FROM readings")
        conn.commit()
        for index, reading in enumerate(run.readings):
            if index not in deleted:
                db.insert_reading(conn, reading)
        # Extra rows are explicitly outside manifest completeness.
        from dataclasses import replace

        db.insert_reading(conn, replace(run.readings[0], meter_id=f"extra-{offset}"))
        before = paths.db.read_bytes()
        rows = verifier.audit_run(paths, w3, Path("unused"))
        assert len(rows) == len(run.expected)
        assert [r.outcome.value for r in rows] == [
            "MISSING_RECORD" if i in deleted else "VERIFIED" for i in range(3)
        ]
        assert paths.db.read_bytes() == before

    check()


def test_malformed_manifest_reference_aborts_cleanly(audit_setup):
    paths, _, _, _, w3 = audit_setup
    manifest = json.loads(paths.manifest.read_text())
    manifest["expected_records"] = None
    paths.manifest.write_text(json.dumps(manifest))
    with pytest.raises(verifier.AuditError, match="context"):
        verifier.audit_run(paths, w3, Path("unused"))


def test_database_failure_duration_is_measured(audit_setup, monkeypatch):
    paths, _, conn, _, w3 = audit_setup
    conn.close()
    paths.db.unlink()
    monkeypatch.setattr(verifier.time, "perf_counter", iter(range(100)).__next__)
    rows = verifier.audit_run(paths, w3, Path("unused"))
    assert all(row.seconds > 0 for row in rows)
