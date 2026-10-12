"""Auditor: recompute and compare. [YOU WRITE THIS: Step 7]

For one (meter_id, interval_start):
  1. read the reading from the database as it is NOW (db.get_reading)
  2. recompute its digest (fingerprint.digest)
  3. read the committed fingerprint (contract.functions.getCommitment(key).call())
  4. return VERIFIED, TAMPERED or MISSING (models.Verdict)
  5. log the verdict and the time taken (results.log, event="verify")

Decide and document: what verdict if the reading is gone from the database
but a commitment exists? (Deletion is also tampering.)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from web3.contract import Contract

from .models import Verdict


def verify(conn: sqlite3.Connection, contract: Contract, meter_id: str,
           interval_start: str, results_path: Path | None = None) -> Verdict:
    raise NotImplementedError("Step 7 in docs/BUILD_GUIDE.md")
