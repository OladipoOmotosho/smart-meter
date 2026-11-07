"""Enforce design §10 branch coverage for critical Python modules."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from coverage import Coverage

CRITICAL = ("dataset.py", "fingerprint.py", "aggregator.py", "verifier.py")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_branch_coverage.py COVERAGE_DATA", file=sys.stderr)
        return 2
    cov = Coverage(data_file=sys.argv[1])
    cov.load()
    with tempfile.TemporaryDirectory() as temporary:
        report = Path(temporary) / "coverage.json"
        cov.json_report(outfile=str(report))
        data = json.loads(report.read_text())
        files = data["files"]
    problems = []
    overall = data["totals"]
    if (
        not overall["num_statements"]
        or overall["covered_lines"] / overall["num_statements"] < 0.85
    ):
        problems.append(
            f"overall line coverage: {overall['covered_lines']}/{overall['num_statements']}; requires at least 85%"
        )
    for module in CRITICAL:
        matches = [
            entry["summary"]
            for name, entry in files.items()
            if name.endswith("/" + module)
        ]
        if len(matches) != 1:
            problems.append(f"{module}: missing or ambiguous coverage data")
            continue
        covered = matches[0]["covered_branches"]
        total = matches[0]["num_branches"]
        if not total or covered / total < 0.90:
            problems.append(
                f"{module}: {covered}/{total} branches; requires at least 90%"
            )
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
