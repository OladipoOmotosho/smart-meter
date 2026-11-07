"""R6.5/R9.2/R9.5: runtime settings never import a personal environment file."""

from pathlib import Path

import pytest
from smart_meter.config import ConfigurationError, load_settings, run_paths


def test_write_requires_explicit_fields_and_ignores_environment_file(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text("AGGREGATOR_PRIVATE_KEY=personal-secret\n")
    monkeypatch.chdir(tmp_path)
    values = {
        "RPC_URL": "http://127.0.0.1:8545",
        "CONTRACT_ADDRESS": "0xabc",
        "DATASET_PATH": "fixture.csv",
    }
    with pytest.raises(ConfigurationError, match="AGGREGATOR_PRIVATE_KEY"):
        load_settings(run_id="one", mode="write", values=values, base=tmp_path)


def test_audit_needs_no_signing_key_or_dataset(tmp_path):
    settings = load_settings(
        run_id="audit-1",
        mode="audit",
        values={"RPC_URL": "http://127.0.0.1:8545", "CONTRACT_ADDRESS": "0xabc"},
        base=tmp_path,
    )
    assert settings.aggregator_key is None
    assert settings.dataset_path is None
    assert settings.run.db == tmp_path / "audit-1" / "readings.sqlite"


def test_new_run_paths_are_separate_and_collision_is_rejected(tmp_path):
    first = run_paths("first", base=tmp_path, create=True)
    second = run_paths("second", base=tmp_path, create=True)
    assert first.db != second.db
    assert first.results != second.results
    assert first.manifest != second.manifest
    with pytest.raises(ConfigurationError, match="already exists"):
        run_paths("first", base=tmp_path, create=True)
    for run_id in ("../escape", "bad/name", "", "."):
        with pytest.raises(ConfigurationError, match="run ID"):
            run_paths(run_id, base=tmp_path, create=True)


def test_diagnostics_exclude_private_key(tmp_path):
    secret = "do-not-print-this-key"
    url_secret = "another-secret"
    settings = load_settings(
        run_id="write-1",
        mode="write",
        values={
            "RPC_URL": f"http://user:{url_secret}@127.0.0.1:8545/token?key={url_secret}",
            "CONTRACT_ADDRESS": "0xabc",
            "DATASET_PATH": "fixture.csv",
            "AGGREGATOR_PRIVATE_KEY": secret,
        },
        base=tmp_path,
    )
    assert secret not in repr(settings.diagnostics())
    assert url_secret not in repr(settings.diagnostics())
    assert url_secret not in repr(settings)
    assert settings.dataset_path == Path(__file__).resolve().parents[2] / "fixture.csv"
