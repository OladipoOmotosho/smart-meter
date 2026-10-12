"""AMPds2 loader. [YOU WRITE THIS: Step 5]

Turn the raw AMPds2 whole-house file into Reading objects.

Before writing code, open the CSV and write down:
  - the timestamp column and its format (it is a Unix timestamp)
  - which column is power (watts) and which, if any, is an energy counter
  - the sampling interval

Watch out: power (W) is not energy (Wh). If you only have power samples, the
energy for an interval is power x time (1-minute samples: sum of W / 60 = Wh).
Do not relabel a power value as kWh. State the conversion in the report.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .models import Reading


def load_readings(path: Path, meter_id: str = "AMPDS2-WHE",
                  interval_minutes: int = 60, limit: int | None = None) -> Iterator[Reading]:
    """Yield one Reading per interval, oldest first, with seq = 0, 1, 2, ...

    interval_start must be ISO 8601 UTC, e.g. "2012-04-01T00:00:00Z".
    value_wh must be an int (energy used in that interval).
    limit caps how many readings are produced (useful for quick demos).
    """
    raise NotImplementedError("Step 5 in docs/BUILD_GUIDE.md")
