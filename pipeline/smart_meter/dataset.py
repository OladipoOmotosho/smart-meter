"""Stream AMPds2 whole-house minute power into complete UTC-hour readings."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from .models import Reading

REQUIRED_COLUMNS = {"unix_ts", "P"}
UNIX_SECONDS = re.compile(r"\+?[0-9]+\Z")


def _sample(row: dict[str, str], line: int) -> tuple[int, Decimal]:
    raw_ts = row["unix_ts"].strip()
    if not UNIX_SECONDS.fullmatch(raw_ts):
        raise ValueError(f"invalid unix_ts at source row {line}")
    timestamp = int(raw_ts.lstrip("+"))
    if timestamp % 60:
        raise ValueError(f"unaligned unix_ts at source row {line}")
    raw_power = row["P"].strip()
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
    return timestamp, power


def _reading(meter_id: str, hour: int, powers: list[Decimal], seq: int) -> Reading:
    value = (sum(powers) / Decimal(60)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    start = datetime.fromtimestamp(hour, UTC).strftime("%Y-%m-%dT%H:00:00Z")
    return Reading(meter_id, start, int(value), "Wh", seq)


def load_readings(
    path: Path,
    meter_id: str = "AMPDS2-WHE",
    interval_minutes: int = 60,
    limit: int | None = None,
) -> Iterator[Reading]:
    """Yield complete one-hour readings; reject malformed or internally gapped input."""
    if interval_minutes != 60:
        raise ValueError("only 60-minute intervals are supported")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("limit must be a positive integer")
    if not isinstance(meter_id, str) or not meter_id:
        raise ValueError("meter_id must be a nonempty string")
    with Path(path).open(newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(
            reader.fieldnames
        ):
            raise ValueError("expected AMPds2 WHE columns unix_ts and P")
        first_hour: int | None = None
        hour: int | None = None
        powers: list[Decimal] = []
        previous: int | None = None
        emitted = 0
        saw_row = False
        for line, row in enumerate(reader, start=2):
            saw_row = True
            timestamp, power = _sample(row, line)
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
                first_hour = hour
            elif current_hour != hour:
                if len(powers) == 60:
                    yield _reading(meter_id, hour, powers, emitted)
                    emitted += 1
                    if limit is not None and emitted >= limit:
                        return
                elif hour != first_hour:
                    raise ValueError(
                        f"incomplete internal hour before source row {line}"
                    )
                hour = current_hour
                powers = []
            powers.append(power)
        if not saw_row:
            raise ValueError("source contains no readings")
        if hour is not None and len(powers) == 60:
            yield _reading(meter_id, hour, powers, emitted)
