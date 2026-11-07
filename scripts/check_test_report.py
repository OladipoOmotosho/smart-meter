"""Reject absent, skipped or expected-fail required tests in saved reports."""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REQUIRED_CHAIN = {
    "test_positive_control_clean_record_verifies",
    "test_A1_post_commit_tampering_is_detected",
    "test_A2_unauthorized_submission_is_rejected",
    "test_A3_existing_fingerprint_cannot_be_replaced",
    "test_A4_boundary_change_before_commit_is_not_detected",
}
REQUIRED_SCENARIO_PREFIXES = {
    scenario: f"test_{scenario}_" for scenario in ("S5", "S6", "S7", "S8", "S9", "S10")
}
REQUIRED_CONTRACT = {
    "testFuzz_FirstCommitRemainsFixed",
    "test_AggregatorCanCommit",
    "test_GetCommitmentReturnsStoredValues",
    "test_UnknownKeyIsEmpty",
    "test_RevertWhen_UnauthorizedCommit",
    "test_RevertWhen_KeyAlreadyCommitted",
    "test_RevertWhen_ZeroDigest",
    "test_EmitsCommittedEvent",
}


def check_junit(path: Path, suite: str) -> list[str]:
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    problems = [] if cases else ["no tests collected"]
    names = {case.attrib.get("name", "") for case in cases}
    required = REQUIRED_CHAIN if suite == "chain" else set()
    for name in sorted(required - names):
        problems.append(f"required case absent: {name}")
    if suite == "chain":
        for scenario, prefix in REQUIRED_SCENARIO_PREFIXES.items():
            if not any(name.startswith(prefix) for name in names):
                problems.append(f"required scenario absent: {scenario} ({prefix}*)")
    for case in cases:
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            problems.append(
                f"required case did not pass: {case.attrib.get('name', '?')}"
            )
    if suite == "unit":
        for module in ("test_config", "test_fingerprint"):
            if not any(module in case.attrib.get("classname", "") for case in cases):
                problems.append(f"required module absent: {module}")
    print(f"{suite}: {len(cases)} collected; {len(problems)} report problems")
    return problems


def check_contracts(path: Path) -> list[str]:
    output = path.read_text()
    matches = re.findall(
        r"\[(PASS|FAIL|SKIP)(?::[^\]]+)?\]\s+(test(?:_|Fuzz|Invariant)\w+)\(",
        output,
    )
    names = {name for _, name in matches}
    problems = [] if matches else ["no contract tests reported"]
    for name in sorted(REQUIRED_CONTRACT - names):
        problems.append(f"required case absent: {name}")
    for status, name in matches:
        if status != "PASS":
            problems.append(f"required case did not pass: {name} ({status})")
    print(f"contracts: {len(matches)} reported; {len(problems)} report problems")
    return problems


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"unit", "chain", "contracts"}:
        print(
            "usage: check_test_report.py {unit|chain|contracts} REPORT", file=sys.stderr
        )
        return 2
    suite, path = sys.argv[1], Path(sys.argv[2])
    try:
        problems = (
            check_contracts(path) if suite == "contracts" else check_junit(path, suite)
        )
    except (OSError, ET.ParseError) as error:
        print(f"cannot read test report: {error}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
