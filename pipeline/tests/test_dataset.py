"""R2/P4: the selected WHE adapter uses exact hourly energy conversion."""

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from smart_meter.dataset import LoadMetadata, load_readings

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


def test_limit_stops_before_invalid_trailing_data(tmp_path):
    source = (FIXTURES / "valid_60w_hour.csv").read_text()
    path = tmp_path / "bounded.csv"
    path.write_text(source + "not-a-timestamp,0,0,0,0,0,invalid,0,0,0,0,0\n")
    metadata = LoadMetadata()

    assert [
        reading.value_wh for reading in load_readings(path, limit=1, metadata=metadata)
    ] == [60]
    assert metadata.source_rows == 60


def test_metadata_preserves_imputation_and_counts_partial_edges():
    imputed = LoadMetadata()
    assert (
        len(list(load_readings(FIXTURES / "imputed_hour.csv", metadata=imputed))) == 1
    )
    assert imputed.imputed_samples == 1
    assert imputed.emitted_intervals == 1
    assert imputed.selected_start == "2022-01-01T00:00:00Z"
    assert imputed.selected_end == "2022-01-01T01:00:00Z"

    edges = LoadMetadata()
    assert len(list(load_readings(FIXTURES / "partial_edges.csv", metadata=edges))) == 1
    assert edges.excluded_boundary_rows == 60
    assert edges.excluded_boundary_hours == 2


def test_partial_only_source_fails_with_metadata(tmp_path):
    rows = ["unix_ts,P"] + [f"{1640995200 + minute * 60},60" for minute in range(30)]
    path = tmp_path / "partial.csv"
    path.write_text("\n".join(rows) + "\n")
    metadata = LoadMetadata()

    with pytest.raises(ValueError, match="no complete hourly intervals"):
        list(load_readings(path, metadata=metadata))

    assert metadata.excluded_boundary_rows == 30
    assert metadata.excluded_boundary_hours == 1


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
