"""R10.3/R10.5: reports cannot make absent or skipped required suites green."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_test_report.py"


def _check(suite, report):
    return subprocess.run(
        [sys.executable, str(SCRIPT), suite, str(report)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_empty_required_suite_fails(tmp_path):
    report = tmp_path / "empty.xml"
    report.write_text('<testsuite tests="0"/>')
    result = _check("chain", report)
    assert result.returncode == 1
    assert "no tests collected" in result.stderr
    assert "test_A1_post_commit_tampering_is_detected" in result.stderr


def test_skip_only_required_suite_fails(tmp_path):
    report = tmp_path / "skipped.xml"
    report.write_text(
        '<testsuite><testcase name="test_A1_post_commit_tampering_is_detected">'
        '<skipped message="not written"/></testcase></testsuite>'
    )
    result = _check("chain", report)
    assert result.returncode == 1
    assert "required case did not pass" in result.stderr


def test_contract_skip_and_absent_case_fail(tmp_path):
    report = tmp_path / "forge.txt"
    report.write_text("[SKIP: unfinished] test_AggregatorCanCommit() (gas: 0)\n")
    result = _check("contracts", report)
    assert result.returncode == 1
    assert "test_AggregatorCanCommit (SKIP)" in result.stderr
    assert "test_RevertWhen_ZeroDigest" in result.stderr


def test_skipped_fuzz_contract_case_fails(tmp_path):
    required = [
        "test_AggregatorCanCommit",
        "test_GetCommitmentReturnsStoredValues",
        "test_UnknownKeyIsEmpty",
        "test_RevertWhen_UnauthorizedCommit",
        "test_RevertWhen_KeyAlreadyCommitted",
        "test_RevertWhen_ZeroDigest",
        "test_EmitsCommittedEvent",
    ]
    report = tmp_path / "forge.txt"
    report.write_text(
        "\n".join(f"[PASS] {name}() (gas: 1)" for name in required)
        + "\n[SKIP: disabled] testFuzz_FirstCommitRemainsFixed(bytes32,bytes32,bytes32)\n"
    )

    result = _check("contracts", report)

    assert result.returncode == 1
    assert "testFuzz_FirstCommitRemainsFixed (SKIP)" in result.stderr
