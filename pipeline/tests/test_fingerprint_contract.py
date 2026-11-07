"""R3.1-R3.4, P1-P3: versioned bytes, typed fields and independent oracles."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from smart_meter.fingerprint import canonical_bytes, digest, record_key
from smart_meter.models import Reading

VECTOR_PATH = Path(__file__).parent / "fixtures" / "fingerprint_vectors.json"
VECTOR = json.loads(VECTOR_PATH.read_text())
BASE = Reading(**VECTOR["reading"])
TEXT = st.text(max_size=24)
READINGS = st.builds(
    Reading,
    meter_id=TEXT,
    interval_start=TEXT,
    value_wh=st.integers(min_value=0, max_value=10**18),
    unit=TEXT,
    seq=st.integers(min_value=0, max_value=10**9),
)


def test_literal_versioned_bytes_and_hashes():
    assert canonical_bytes(BASE) == VECTOR["canonical_ascii"].encode("ascii")
    assert digest(BASE).hex() == VECTOR["digest_hex"]
    assert record_key(BASE.meter_id, BASE.interval_start).hex() == VECTOR["key_hex"]


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"meter_id": 1}, TypeError),
        ({"interval_start": None}, TypeError),
        ({"unit": b"Wh"}, TypeError),
        ({"value_wh": True}, TypeError),
        ({"value_wh": 1.0}, TypeError),
        ({"seq": False}, TypeError),
        ({"seq": 0.5}, TypeError),
        ({"value_wh": -1}, ValueError),
        ({"seq": -1}, ValueError),
    ],
)
def test_invalid_stored_types_cannot_be_fingerprinted(change, error):
    with pytest.raises(error):
        canonical_bytes(replace(BASE, **change))


def test_identity_rejects_nontext_without_enforcing_timestamp_syntax():
    with pytest.raises(TypeError):
        record_key(123, BASE.interval_start)
    with pytest.raises(TypeError):
        record_key(BASE.meter_id, None)
    assert len(record_key("meter", "not-a-timestamp")) == 32


def test_special_characters_have_exact_json_escaping():
    reading = replace(BASE, meter_id='A,"\\\n雪')
    encoded = canonical_bytes(reading)
    assert encoded.isascii()
    assert json.loads(encoded) == [
        "smart-meter/reading/v1",
        reading.meter_id,
        reading.interval_start,
        reading.value_wh,
        reading.unit,
        reading.seq,
    ]
    assert b"\\u96ea" in encoded


def test_fresh_process_produces_same_fixed_digest():
    code = (
        "from smart_meter.fingerprint import digest;"
        "from smart_meter.models import Reading;"
        "print(digest(Reading('AMPDS2-WHE','2012-04-01T00:00:00Z',5200,'Wh',0)).hex())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == VECTOR["digest_hex"]


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(READINGS)
def test_p1_repeated_encoding_is_deterministic(reading):
    first = canonical_bytes(reading)
    assert first == canonical_bytes(replace(reading))
    assert digest(reading) == digest(replace(reading))


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(READINGS)
def test_p2_content_changes_preserve_identity_key(reading):
    changed = replace(reading, value_wh=reading.value_wh + 1)
    assert record_key(reading.meter_id, reading.interval_start) == record_key(
        changed.meter_id, changed.interval_start
    )
    assert canonical_bytes(reading) != canonical_bytes(changed)
    assert digest(reading) != digest(changed)


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(TEXT, st.text(min_size=1, max_size=12), TEXT)
def test_p3_field_boundaries_remain_unambiguous(prefix, middle, suffix):
    first = record_key(prefix + middle, suffix)
    second = record_key(prefix, middle + suffix)
    assert first != second
    reading = Reading(prefix, suffix, 0)
    assert json.loads(canonical_bytes(reading)) == [
        "smart-meter/reading/v1",
        prefix,
        suffix,
        0,
        "Wh",
        0,
    ]
