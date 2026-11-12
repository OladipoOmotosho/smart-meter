"""Stream AMPds2 whole-house minute power into complete UTC-hour readings."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

from .models import Reading

WHE_HEADER = "unix_ts,V,I,f,DPF,APF,P,Pt,Q,Qt,S,St".split(",")
UNIX_SECONDS = re.compile(r"\+?[0-9]+\Z")


@dataclass
class LoadMetadata:
    source_rows: int = 0
    emitted_intervals: int = 0
    imputed_samples: int = 0
    excluded_boundary_rows: int = 0
    excluded_boundary_hours: int = 0
    selected_start: str | None = None
    selected_end: str | None = None


def _sample(row: dict[str, str | None], line: int) -> tuple[int, Fraction, bool]:
    raw_ts = (row["unix_ts"] or "").strip()
    if not UNIX_SECONDS.fullmatch(raw_ts):
        raise ValueError(f"invalid unix_ts at source row {line}")
    imputed = raw_ts.startswith("+")
    timestamp = int(raw_ts.lstrip("+"))
    if timestamp % 60:
        raise ValueError(f"unaligned unix_ts at source row {line}")
    raw_power = (row["P"] or "").strip()
    if not raw_power:
        raise ValueError(f"missing P at source row {line}")
    try:
        power = Decimal(raw_power)
    except InvalidOperation as error:
        raise ValueError(f"invalid P at source row {line}") from error
    if not power.is_finite():
        raise ValueError(f"non-finite P at source row {line}")
    if power < 0:
        raise ValueError(f"unsupported negative P at source row {line}")
    return timestamp, Fraction(power), imputed


def _reading(meter_id: str, hour: int, powers: list[Fraction], seq: int) -> Reading:
    exact_wh = sum(powers, start=Fraction()) / 60
    value = (2 * exact_wh.numerator + exact_wh.denominator) // (
        2 * exact_wh.denominator
    )
    start = datetime.fromtimestamp(hour, UTC).strftime("%Y-%m-%dT%H:00:00Z")
    return Reading(meter_id, start, value, "Wh", seq)


def load_readings(
    path: Path,
    meter_id: str = "AMPDS2-WHE",
    interval_minutes: int = 60,
    limit: int | None = None,
    metadata: LoadMetadata | None = None,
) -> Iterator[Reading]:
    """Yield complete one-hour readings; reject malformed or internally gapped input."""
    if interval_minutes != 60:
        raise ValueError("only 60-minute intervals are supported")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("limit must be a positive integer")
    if not isinstance(meter_id, str) or not meter_id:
        raise ValueError("meter_id must be a nonempty string")
    details = metadata if metadata is not None else LoadMetadata()
    with Path(path).open(newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != WHE_HEADER:
            raise ValueError("expected the AMPds2 WHE header at source row 1")
        hour: int | None = None
        powers: list[Fraction] = []
        imputed_in_hour = 0
        previous: int | None = None
        emitted = 0
        saw_row = False
        for line, row in enumerate(reader, start=2):
            saw_row = True
            timestamp, power, imputed = _sample(row, line)
            details.source_rows += 1
            if previous is not None:
                if timestamp <= previous:
                    raise ValueError(
                        f"duplicate or reversed timestamp at source row {line}"
                    )
                if timestamp - previous != 60:
                    raise ValueError(f"missing minute before source row {line}")
            previous = timestamp
            current_hour = timestamp - timestamp % 3600
            if hour is None:
                hour = current_hour
            elif current_hour != hour:
                if emitted:
                    raise ValueError(
                        f"incomplete internal hour before source row {line}"
                    )
                details.excluded_boundary_rows += len(powers)
                details.excluded_boundary_hours += 1
                hour = current_hour
                powers = []
                imputed_in_hour = 0
            powers.append(power)
            imputed_in_hour += int(imputed)
            if len(powers) == 60:
                reading = _reading(meter_id, hour, powers, emitted)
                details.emitted_intervals += 1
                details.imputed_samples += imputed_in_hour
                if details.selected_start is None:
                    details.selected_start = reading.interval_start
                details.selected_end = (
                    datetime.fromtimestamp(hour, UTC) + timedelta(hours=1)
                ).strftime("%Y-%m-%dT%H:00:00Z")
                yield reading
                emitted += 1
                hour = None
                powers = []
                imputed_in_hour = 0
                if limit is not None and emitted >= limit:
                    return
        if not saw_row:
            raise ValueError("source contains no readings")
        if powers:
            details.excluded_boundary_rows += len(powers)
            details.excluded_boundary_hours += 1
        if not emitted:
            raise ValueError("source contains no complete hourly intervals")
