"""Acceptance tests for fingerprint.py (Step 1). Do not edit these to make them pass."""

from dataclasses import replace

from smart_meter.fingerprint import canonical_bytes, digest, record_key
from smart_meter.models import Reading

BASE = Reading(meter_id="AMPDS2-WHE", interval_start="2012-04-01T00:00:00Z", value_wh=5200, unit="Wh", seq=0)


def test_digest_is_32_bytes():
    assert isinstance(digest(BASE), bytes) and len(digest(BASE)) == 32


def test_record_key_is_32_bytes():
    k = record_key(BASE.meter_id, BASE.interval_start)
    assert isinstance(k, bytes) and len(k) == 32


def test_same_reading_same_digest():
    assert digest(BASE) == digest(replace(BASE))


def test_tampered_value_changes_digest():
    # The 5.2 kWh -> 25.2 kWh example from the presentation
    assert digest(BASE) != digest(replace(BASE, value_wh=25200))


def test_every_field_is_covered_by_the_digest():
    variants = [
        replace(BASE, meter_id="AMPDS2-OTHER"),
        replace(BASE, interval_start="2012-04-01T01:00:00Z"),
        replace(BASE, value_wh=5201),
        replace(BASE, unit="kWh"),
        replace(BASE, seq=1),
    ]
    digests = {digest(v) for v in variants} | {digest(BASE)}
    assert len(digests) == len(variants) + 1


def test_record_key_ignores_value():
    # The key names the slot; editing the value must not move the reading to a new slot
    assert record_key(BASE.meter_id, BASE.interval_start) == record_key(
        replace(BASE, value_wh=25200).meter_id, replace(BASE, value_wh=25200).interval_start
    )


def test_record_key_differs_by_meter_and_interval():
    k = record_key(BASE.meter_id, BASE.interval_start)
    assert k != record_key("AMPDS2-OTHER", BASE.interval_start)
    assert k != record_key(BASE.meter_id, "2012-04-01T01:00:00Z")


def test_canonical_bytes_are_unambiguous():
    # Naive concatenation turns (value_wh=12, seq=3) and (value_wh=1, seq=23) into the same "123"
    a = replace(BASE, value_wh=12, seq=3)
    b = replace(BASE, value_wh=1, seq=23)
    assert canonical_bytes(a) != canonical_bytes(b)
    assert digest(a) != digest(b)


def test_record_key_is_unambiguous():
    # ("AB", "C...") and ("A", "BC...") must not collide either
    assert record_key("AB", "C2012-04-01T00:00:00Z") != record_key("A", "BC2012-04-01T00:00:00Z")
