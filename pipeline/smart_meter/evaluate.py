"""Descriptive accounting of recorded evidence; no production performance claims."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

AUDIT_OUTCOMES = {
    "VERIFIED",
    "TAMPERED",
    "MISSING_RECORD",
    "MISSING_COMMITMENT",
    "MISSING_BOTH",
}


def distribution(values: list[float]) -> dict:
    """Nearest-rank p95; unavailable statistics are JSON null (N/A)."""
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("measurements must be finite and nonnegative")
    ordered = sorted(values)
    return {
        "n": len(values),
        "median": statistics.median(ordered) if ordered else None,
        "p95": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
    }


def rate(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def summarize(rows: list[dict]) -> dict:
    known = AUDIT_OUTCOMES | {
        "ERROR",
        "UNCERTAIN",
        "REVERTED",
        "REJECTED",
        "REPLACED",
        "ACCEPTED",
        "RECONCILED",
    }
    for number, row in enumerate(rows, 1):
        verdict = row.get("verdict", "")
        if verdict not in known | {"", None} or (
            row.get("event") in {"scenario", "verify", "submission"} and not verdict
        ):
            raise ValueError(f"invalid verdict in evidence row {number}: {verdict!r}")
    scenarios = [r for r in rows if r.get("event") == "scenario"]
    eligible = [
        r
        for r in scenarios
        if r.get("scenario_id") in {"A1", "S5"} and r.get("verdict") in AUDIT_OUTCOMES
    ]
    clean = [
        r
        for r in scenarios
        if r.get("scenario_id") == "S0" and r.get("verdict") in AUDIT_OUTCOMES
    ]
    rejected = [
        r
        for r in scenarios
        if r.get("scenario_id") in {"A2", "A3", "S7"}
        and r.get("verdict") in {"REJECTED", "ACCEPTED"}
    ]
    commits = [
        r for r in rows if r.get("event") == "commit" and str(r.get("status")) == "1"
    ]
    audits = [
        r
        for r in rows
        if r.get("event") == "verify" and r.get("verdict") in AUDIT_OUTCOMES
    ]

    def measured(items, field):
        return [float(r[field]) for r in items if r.get(field) not in (None, "")]

    return {
        # Log rows, not readings: a commit and its audit are two rows.
        "rows": len(rows),
        "events": dict(sorted(Counter(r.get("event", "") for r in rows).items())),
        "outcomes": dict(
            sorted(Counter(r["verdict"] for r in rows if r.get("verdict")).items())
        ),
        "detection": rate(
            sum(
                r["verdict"]
                == {"A1": "TAMPERED", "S5": "MISSING_RECORD"}[r["scenario_id"]]
                for r in eligible
            ),
            len(eligible),
        ),
        "false_alarms": rate(
            sum(r["verdict"] != "VERIFIED" for r in clean), len(clean)
        ),
        "rejections": rate(
            sum(r["verdict"] == "REJECTED" for r in rejected), len(rejected)
        ),
        "errors": sum(r.get("verdict") == "ERROR" for r in rows),
        "uncertain": sum(r.get("verdict") == "UNCERTAIN" for r in rows),
        "failed": sum(
            r.get("verdict") in {"REVERTED", "REJECTED", "REPLACED"} for r in rows
        ),
        "precommit_limit_cases": sum(r.get("scenario_id") == "A4" for r in scenarios),
        "excluded_from_detection": len(scenarios) - len(eligible),
        "commit_seconds": distribution(measured(commits, "seconds")),
        "audit_seconds": distribution(measured(audits, "seconds")),
        "commit_gas": distribution(measured(commits, "gas_used")),
        "timing_exclusions": {
            "commit": len(commits) - len(measured(commits, "seconds")),
            "audit": len(audits) - len(measured(audits, "seconds")),
        },
        "conditions": "serial local Anvil; receipt observation, not public-chain finality; p95 nearest rank",
    }


def projection(
    meters: int, interval_minutes: int, gas_per_commit: float | None
) -> dict:
    if (
        type(meters) is not int
        or meters < 1
        or type(interval_minutes) is not int
        or interval_minutes < 1
    ):
        raise ValueError("meters and interval minutes must be positive integers")
    if gas_per_commit is not None and (
        not math.isfinite(gas_per_commit) or gas_per_commit < 0
    ):
        raise ValueError("gas must be finite and nonnegative")
    count = meters * 1440 / interval_minutes
    return {
        "label": "hypothetical one-record-per-transaction projection, not measured throughput",
        "meters": meters,
        "interval_minutes": interval_minutes,
        "transactions_per_day": count,
        "gas_per_day": count * gas_per_commit if gas_per_commit is not None else None,
    }


def read_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"event", "verdict"} <= set(
                reader.fieldnames
            ):
                raise ValueError(f"not a results CSV: {path}")
            for number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"malformed CSV row {number} in {path}")
                rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(summarize(read_rows(args.files)), indent=2, allow_nan=False))
    except (OSError, ValueError) as error:
        parser.exit(1, f"evaluation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
