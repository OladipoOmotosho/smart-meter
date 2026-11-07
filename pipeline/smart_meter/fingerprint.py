"""Versioned, unambiguous bytes and SHA-256 fingerprints for readings."""

from __future__ import annotations

import hashlib
import json

from .models import Reading

READING_DOMAIN = "smart-meter/reading/v1"
KEY_DOMAIN = "smart-meter/key/v1"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer, not a boolean or float")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _encode(fields: list[str | int]) -> bytes:
    return json.dumps(
        fields, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_bytes(r: Reading) -> bytes:
    """Encode all five fields; physical units and timestamps are checked upstream."""
    if not isinstance(r, Reading):
        raise TypeError("reading must be a Reading")
    return _encode(
        [
            READING_DOMAIN,
            _text(r.meter_id, "meter_id"),
            _text(r.interval_start, "interval_start"),
            _nonnegative_integer(r.value_wh, "value_wh"),
            _text(r.unit, "unit"),
            _nonnegative_integer(r.seq, "seq"),
        ]
    )


def record_key(meter_id: str, interval_start: str) -> bytes:
    """Hash the identity only, independent of value, unit and sequence."""
    identity = _encode(
        [
            KEY_DOMAIN,
            _text(meter_id, "meter_id"),
            _text(interval_start, "interval_start"),
        ]
    )
    return hashlib.sha256(identity).digest()


def digest(r: Reading) -> bytes:
    """Hash the exact versioned reading bytes."""
    return hashlib.sha256(canonical_bytes(r)).digest()
