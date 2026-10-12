"""Shared types. [provided]

Design decision: energy is stored as an integer number of watt-hours
(value_wh), never as a float. 5.2 kWh is value_wh=5200. Floats have more than
one text form (5.2, 5.20, 5.199999...), and a fingerprint must be computed from
exactly one form, or the same reading would produce different digests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Reading:
    meter_id: str        # e.g. "AMPDS2-WHE"
    interval_start: str  # ISO 8601 UTC, e.g. "2012-04-01T00:00:00Z"
    value_wh: int        # energy used in the interval, in watt-hours
    unit: str = "Wh"
    seq: int = 0         # position of the reading in the replayed stream


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"    # stored reading matches its on-chain fingerprint
    TAMPERED = "TAMPERED"    # fingerprint exists but no longer matches
    MISSING = "MISSING"      # no fingerprint was ever committed for this key
