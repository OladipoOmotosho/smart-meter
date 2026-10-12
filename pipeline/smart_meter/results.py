"""Append-only CSV log of everything the evaluation needs. [provided]"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["logged_at", "event", "meter_id", "interval_start", "verdict", "gas_used", "seconds", "note"]


def log(path: Path, event: str, meter_id: str = "", interval_start: str = "",
        verdict: str = "", gas_used: int | None = None, seconds: float | None = None, note: str = "") -> None:
    """event examples: "commit", "verify", "attack_A1", "attack_A2"."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({
            "logged_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event, "meter_id": meter_id, "interval_start": interval_start,
            "verdict": verdict, "gas_used": "" if gas_used is None else gas_used,
            "seconds": "" if seconds is None else f"{seconds:.6f}", "note": note,
        })
