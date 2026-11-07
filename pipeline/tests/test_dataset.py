"""R2/P4: the selected WHE adapter uses exact hourly energy conversion."""

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from smart_meter.dataset import load_readings

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["file"])
def test_documented_source_cases(case):
    path = FIXTURES / case["file"]
    if "reject" in case:
        with pytest.raises(ValueError):
            list(load_readings(path))
    else:
        readings = list(load_readings(path))
        assert [r.value_wh for r in readings] == [
            item["rounded_wh"] for item in case["expected"]
        ]
        assert [r.interval_start for r in readings] == [
            item["interval_start"] for item in case["expected"]
        ]
        assert [r.seq for r in readings] == list(range(len(readings)))


def test_limit_and_unsupported_interval():
    path = FIXTURES / "rounding_boundaries.csv"
    assert [r.value_wh for r in load_readings(path, limit=2)] == [0, 1]
    with pytest.raises(ValueError, match="60-minute"):
        list(load_readings(path, interval_minutes=15))
    with pytest.raises(ValueError, match="limit"):
        list(load_readings(path, limit=0))


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=1000), min_size=60, max_size=60))
def test_p4_wh_matches_integer_oracle(powers):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "hour.csv"
        rows = ["unix_ts,P"] + [
            f"{1640995200 + 60 * minute},{power}" for minute, power in enumerate(powers)
        ]
        path.write_text("\n".join(rows) + "\n")
        expected = (sum(powers) + 30) // 60
        assert [r.value_wh for r in load_readings(path)] == [expected]
