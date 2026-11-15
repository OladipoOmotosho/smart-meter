"""R8/P12: literal denominator, nearest-rank and exclusion oracles."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from smart_meter import evaluate


def scenario(name, actual):
    return {"event": "scenario", "scenario_id": name, "verdict": actual}


def test_known_counts_exclude_errors_and_precommit_limit():
    rows = [
        scenario("A1", "TAMPERED"),
        scenario("A1", "VERIFIED"),
        scenario("S5", "MISSING_RECORD"),
        scenario("A1", "ERROR"),
        scenario("A4", "VERIFIED"),
        scenario("S0", "VERIFIED"),
        scenario("S0", "TAMPERED"),
        scenario("S0", "ERROR"),
        scenario("A2", "REJECTED"),
        scenario("A3", "ACCEPTED"),
    ]
    got = evaluate.summarize(rows)
    assert got["detection"] == {"numerator": 2, "denominator": 3, "rate": 2 / 3}
    assert got["false_alarms"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert got["rejections"]["rate"] == 0.5
    assert got["errors"] == 2 and got["precommit_limit_cases"] == 1
    assert got["excluded_from_detection"] == 7


def test_empty_and_nearest_rank_small_samples():
    assert evaluate.distribution([]) == {"n": 0, "median": None, "p95": None}
    assert evaluate.distribution([7]) == {"n": 1, "median": 7, "p95": 7}
    assert evaluate.distribution(list(range(1, 21))) == {
        "n": 20,
        "median": 10.5,
        "p95": 19,
    }
    assert evaluate.summarize([])["detection"]["rate"] is None


def test_receipt_latency_excludes_resume_failed_and_unknown():
    rows = [
        {"event": "commit", "status": "1", "seconds": "0.2", "gas_used": "100"},
        {"event": "commit", "status": "1", "seconds": "", "gas_used": ""},
        {"event": "commit", "status": "0", "seconds": "99", "gas_used": "200"},
        {"event": "reconcile", "seconds": "99"},
        {"event": "verify", "verdict": "VERIFIED", "seconds": "0.1"},
        {"event": "verify", "verdict": "ERROR", "seconds": "99"},
    ]
    got = evaluate.summarize(rows)
    assert got["commit_seconds"] == {"n": 1, "median": 0.2, "p95": 0.2}
    assert got["commit_gas"]["median"] == 100
    assert got["audit_seconds"]["n"] == 1
    assert got["timing_exclusions"]["commit"] == 1


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_measurements_rejected(value):
    with pytest.raises(ValueError):
        evaluate.distribution([value])


def test_projection_is_labelled_and_not_a_loader_mode():
    assert evaluate.projection(1000, 60, 100)["transactions_per_day"] == 24000
    assert evaluate.projection(1000, 15, 100)["gas_per_day"] == 9600000
    assert evaluate.projection(1, 60, None)["gas_per_day"] is None
    with pytest.raises(ValueError):
        evaluate.projection(True, 60, 100)
    with pytest.raises(ValueError):
        evaluate.projection(1, 60, -1)


@settings(max_examples=200)
@given(
    st.lists(
        st.sampled_from(
            [
                ("A1", "TAMPERED"),
                ("A1", "ERROR"),
                ("A4", "VERIFIED"),
                ("S0", "VERIFIED"),
                ("S0", "TAMPERED"),
            ]
        ),
        max_size=40,
    )
)
def test_p12_accounting_is_deterministic_and_order_independent(items):
    rows = [scenario(*item) for item in items]
    assert evaluate.summarize(rows) == evaluate.summarize(list(reversed(rows)))
    assert evaluate.summarize(rows)["detection"]["denominator"] == items.count(
        ("A1", "TAMPERED")
    )


def test_csv_cli_and_invalid_schema(tmp_path, capsys):
    path = tmp_path / "results.csv"
    path.write_text("event,verdict\nscenario,ERROR\n")
    assert evaluate.main([str(path)]) == 0
    assert '"errors": 1' in capsys.readouterr().out
    path.write_text("wrong,fields\n")
    with pytest.raises(SystemExit) as caught:
        evaluate.main([str(path)])
    assert caught.value.code == 1


def test_row_counts_are_labelled_and_outcomes_exclude_rows_without_verdict():
    """Commit rows have no verdict; they must not appear as an empty outcome."""
    summary = evaluate.summarize(
        [
            {"event": "commit", "status": "1", "verdict": "", "seconds": "0.1"},
            {"event": "verify", "verdict": "VERIFIED", "seconds": "0.2"},
        ]
    )
    assert summary["rows"] == 2
    assert summary["events"] == {"commit": 1, "verify": 1}
    assert summary["outcomes"] == {"VERIFIED": 1}
    assert "records" not in summary


@pytest.mark.parametrize(
    "body", ["event,verdict\nscenario,ERROR,extra\n", "event,verdict\nscenario\n"]
)
def test_truncated_or_extra_csv_fields_fail(tmp_path, body):
    path = tmp_path / "broken.csv"
    path.write_text(body)
    with pytest.raises(ValueError, match="row"):
        evaluate.read_rows([path])


def test_unknown_verdict_cannot_silently_shrink_detection_denominator():
    with pytest.raises(ValueError, match="verdict"):
        evaluate.summarize([scenario("A1", "TAMPERED"), scenario("A1", "VERIFED")])
