"""Fingerprints for meter readings. [YOU WRITE THIS: Step 1]

Done when: `make test-pipeline` passes every test in tests/test_fingerprint.py.

Three functions:
  canonical_bytes(r)  -> the one exact byte form of a reading
  record_key(...)     -> 32 bytes that identify WHICH reading (the slot)
  digest(r)           -> 32 bytes that capture WHAT the reading says (the content)

Questions to answer before you type (write your answers in the report):
  1. Field order and separators: how do you make sure two different readings
     can never produce the same bytes? (See the "ambiguity" test.)
  2. Text encoding: which one, and why does it matter?
  3. Why must record_key ignore value_wh, while digest must include it?
  4. Should the bytes start with a format version (e.g. "v1")? What breaks
     later if you change the format without one?
"""

from __future__ import annotations

from .models import Reading


def canonical_bytes(r: Reading) -> bytes:
    """Serialize every field of r in a fixed, unambiguous format."""
    raise NotImplementedError("Step 1 in docs/BUILD_GUIDE.md")


def record_key(meter_id: str, interval_start: str) -> bytes:
    """SHA-256 of the identity fields only. Must return exactly 32 bytes."""
    raise NotImplementedError("Step 1 in docs/BUILD_GUIDE.md")


def digest(r: Reading) -> bytes:
    """SHA-256 of canonical_bytes(r). Must return exactly 32 bytes."""
    raise NotImplementedError("Step 1 in docs/BUILD_GUIDE.md")
