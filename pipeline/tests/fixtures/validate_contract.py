"""Independently validate Task 1 fixture definitions and source evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = FIXTURE_DIR.parents[2]
SOURCE_HEADER = [
    "unix_ts",
    "V",
    "I",
    "f",
    "DPF",
    "APF",
    "P",
    "Pt",
    "Q",
    "Qt",
    "S",
    "St",
]
SOURCE_HASHES = {
    "Electricity_WHE.csv": (
        "b33fb7f1e3acf21d8dfe8876102965ec8872a5ce9142a8a400ed29f012a19964"
    ),
    "Electricity_P.csv": (
        "c5564ba459b74b3df4ca6379769f953526ea3e00cc214f6d8bb914dd8fc11fad"
    ),
}


def round_half_up(value: Fraction) -> int:
    """Round a nonnegative fraction to an integer, with ties rounding up."""
    shifted = value + Fraction(1, 2)
    return shifted.numerator // shifted.denominator


def read_rows(name: str) -> tuple[list[str] | None, list[dict[str, str]]]:
    """Read a fixture without calling production loader code."""
    with (FIXTURE_DIR / name).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def numeric_timestamp(raw_timestamp: str) -> int:
    """Parse the fixture's optional documented imputation prefix."""
    return int(raw_timestamp.removeprefix("+"))


def validate_expected_case(case: dict[str, object]) -> None:
    """Validate a successful fixture against literal independent results."""
    name = str(case["file"])
    header, rows = read_rows(name)
    assert header == SOURCE_HEADER, name

    timestamps = [numeric_timestamp(row["unix_ts"]) for row in rows]
    assert all(
        current - previous == 60
        for previous, current in zip(timestamps, timestamps[1:])
    ), name

    hours: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row, timestamp in zip(rows, timestamps):
        hours[timestamp - timestamp % 3600].append(row)
    complete_hours = [
        (hour, hour_rows)
        for hour, hour_rows in sorted(hours.items())
        if len(hour_rows) == 60
    ]

    expected = case["expected"]
    assert isinstance(expected, list)
    assert len(complete_hours) == len(expected), name
    for (hour, hour_rows), interval in zip(complete_hours, expected):
        assert isinstance(interval, dict)
        interval_start = datetime.fromtimestamp(hour, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        assert interval_start == interval["interval_start"], name
        energy_wh = sum(
            (Fraction(row["P"]) for row in hour_rows), start=Fraction()
        ) / 60
        assert energy_wh == Fraction(str(interval["exact_wh"])), name
        assert round_half_up(energy_wh) == interval["rounded_wh"], name
        if "sample_count" in interval:
            assert len(hour_rows) == interval["sample_count"], name
        if "imputed_count" in interval:
            imputed_count = sum(
                row["unix_ts"].startswith("+") for row in hour_rows
            )
            assert imputed_count == interval["imputed_count"], name

    if "excluded_boundary_rows" in case:
        retained_rows = sum(len(hour_rows) for _, hour_rows in complete_hours)
        assert len(rows) - retained_rows == case["excluded_boundary_rows"], name


def validate_rejection_case(case: dict[str, object]) -> None:
    """Check that each rejection fixture contains its one intended defect."""
    name = str(case["file"])
    header, rows = read_rows(name)
    if name == "wrong_schema.csv":
        assert header == ["timestamp", "power"]
    else:
        assert header == SOURCE_HEADER, name

    if name == "duplicate_timestamp.csv":
        timestamps = [numeric_timestamp(row["unix_ts"]) for row in rows]
        assert len(timestamps) == 61 and timestamps.count(1640996400) == 2
    elif name == "gap_hour.csv":
        timestamps = [numeric_timestamp(row["unix_ts"]) for row in rows]
        assert len(timestamps) == 179 and 1640997000 not in timestamps
        counts: dict[int, int] = defaultdict(int)
        for timestamp in timestamps:
            counts[timestamp - timestamp % 3600] += 1
        assert list(counts.values()) == [60, 59, 60]
        assert [
            current - previous
            for previous, current in zip(timestamps, timestamps[1:])
            if current - previous != 60
        ] == [120]
    elif name == "out_of_order.csv":
        timestamps = [numeric_timestamp(row["unix_ts"]) for row in rows]
        reversals = [
            (previous, current)
            for previous, current in zip(timestamps, timestamps[1:])
            if current < previous
        ]
        assert reversals == [(1640996460, 1640996400)]
    elif name == "negative_power.csv":
        assert [
            (numeric_timestamp(row["unix_ts"]), row["P"])
            for row in rows
            if Fraction(row["P"]) < 0
        ] == [(1640995920, "-1")]
    elif name == "non_finite_power.csv":
        assert [
            (numeric_timestamp(row["unix_ts"]), row["P"])
            for row in rows
            if row["P"] == "NaN"
        ] == [(1640995680, "NaN")]
    elif name == "missing_power.csv":
        assert [
            (numeric_timestamp(row["unix_ts"]), row["P"])
            for row in rows
            if row["P"] == ""
        ] == [(1640995740, "")]
    elif name == "invalid_timestamp.csv":
        assert rows[7]["unix_ts"] == "not-a-timestamp"
    elif name == "empty.csv":
        assert rows == []


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for a local source file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_sources() -> None:
    """Verify source hashes and the selected 24-hour window."""
    raw_dir = REPOSITORY_ROOT / "data" / "raw"
    for name, expected_hash in SOURCE_HASHES.items():
        assert sha256(raw_dir / name) == expected_hash, name

    selected_rows: list[dict[str, str]] = []
    with (raw_dir / "Electricity_WHE.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == SOURCE_HEADER
        for row in reader:
            timestamp = numeric_timestamp(row["unix_ts"])
            if timestamp >= 1333350000:
                break
            if timestamp >= 1333263600:
                selected_rows.append(row)

    assert len(selected_rows) == 1440
    timestamps = [numeric_timestamp(row["unix_ts"]) for row in selected_rows]
    assert timestamps == list(range(1333263600, 1333350000, 60))
    assert all(not row["unix_ts"].startswith("+") for row in selected_rows)
    assert all(Fraction(row["P"]) >= 0 for row in selected_rows)
    first_hour_wh = sum(
        (Fraction(row["P"]) for row in selected_rows[:60]), start=Fraction()
    ) / 60
    full_window_wh = sum(
        (Fraction(row["P"]) for row in selected_rows), start=Fraction()
    ) / 60
    assert first_hour_wh == Fraction(96515, 60)
    assert round_half_up(first_hour_wh) == 1609
    assert full_window_wh == Fraction(383527, 10)


def main() -> None:
    """Run the independent Task 1 contract validation."""
    manifest = json.loads((FIXTURE_DIR / "cases.json").read_text(encoding="utf-8"))
    assert manifest["source_schema"] == SOURCE_HEADER
    cases = manifest["cases"]
    csv_files = list(FIXTURE_DIR.glob("*.csv"))
    assert len(cases) == 14
    assert len(csv_files) == 14

    for case in cases:
        if "expected" in case:
            validate_expected_case(case)
        else:
            validate_rejection_case(case)
    validate_sources()
    print("PASS: 14 fixture cases, selected window, and 2 source checksums")


if __name__ == "__main__":
    main()
