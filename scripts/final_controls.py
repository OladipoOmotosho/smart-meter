"""Five required deliberate defects, applied only in a disposable source copy."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONTROLS = [
    (
        "omit value",
        "pipeline/smart_meter/fingerprint.py",
        '_nonnegative_integer(r.value_wh, "value_wh"),',
        "0,",
        "python",
        "tests/test_fingerprint_contract.py::test_literal_versioned_bytes_and_hashes",
    ),
    (
        "bypass writer role",
        "contracts/src/MeterCommitmentRegistry.sol",
        "external onlyRole(AGGREGATOR_ROLE)",
        "external",
        "forge",
        "test_RevertWhen_UnauthorizedCommit",
    ),
    (
        "permit overwrite",
        "contracts/src/MeterCommitmentRegistry.sol",
        "if (commitments[recordKey].digest != bytes32(0)) revert AlreadyCommitted(recordKey);",
        "// duplicate guard deliberately removed",
        "forge",
        "test_RevertWhen_KeyAlreadyCommitted",
    ),
    (
        "accept status zero",
        "pipeline/smart_meter/chain.py",
        "TxState.SUCCEEDED if status == 1 else TxState.REVERTED,",
        "TxState.SUCCEEDED,",
        "python",
        "tests/test_transactions.py::test_mined_status_zero_is_reverted_with_evidence",
    ),
    (
        "audit surviving rows only",
        "pipeline/smart_meter/verifier.py",
        "for item in expected:\n",
        "for item in expected:\n            if conn is not None and db.get_reading(conn, item.meter_id, item.interval_start) is None:\n                continue\n",
        "python",
        "tests/test_audit_run.py::test_manifest_outcomes_and_read_only[delete-MISSING_RECORD]",
    ),
]


def execute(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=False)
    results = []
    with tempfile.TemporaryDirectory(prefix="smart-meter-controls-") as directory:
        target = Path(directory) / "repo"
        shutil.copytree(
            ROOT,
            target,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "__pycache__",
                "data",
                "results",
                ".test-results",
                "spec",
                ".agent",
                "out",
                "cache",
                "broadcast",
                "node_modules",
                ".coverage",
            ),
        )
        for name, relative, old, new, kind, test in CONTROLS:
            path = target / relative
            original = path.read_bytes()
            text = original.decode()
            if text.count(old) != 1:
                raise RuntimeError(f"STALE control: {name}")
            command = (
                ["forge", "test", "--match-test", "^" + test + r"\("]
                if kind == "forge"
                else [
                    sys.executable,
                    "-m",
                    "pytest",
                    test,
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ]
            )
            cwd = target / ("contracts" if kind == "forge" else "pipeline")
            baseline = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            if baseline.returncode or (
                kind == "forge" and "[PASS] " + test + "(" not in baseline.stdout
            ):
                raise RuntimeError(
                    f"baseline failed for {name}: {baseline.stdout}{baseline.stderr}"
                )
            try:
                path.write_text(text.replace(old, new))
                broken = subprocess.run(
                    command, cwd=cwd, capture_output=True, text=True
                )
                log = broken.stdout + broken.stderr
                caught = broken.returncode != 0 and (
                    "[FAIL" in log if kind == "forge" else "FAILED " + test in log
                )
                (output / (name.replace(" ", "-") + ".txt")).write_text(log)
                results.append({"control": name, "test": test, "caught": caught})
            finally:
                path.write_bytes(original)
            if path.read_bytes() != original:
                raise RuntimeError("source restoration failed")
            restored = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            if restored.returncode or (
                kind == "forge" and "[PASS] " + test + "(" not in restored.stdout
            ):
                raise RuntimeError(f"restored test failed: {name}")
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    return 0 if all(r["caught"] for r in results) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: final_controls.py OUTPUT_DIRECTORY")
    raise SystemExit(execute(Path(sys.argv[1]).resolve()))
