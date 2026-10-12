"""Trusted aggregator: store, fingerprint, commit. [YOU WRITE THIS: Step 6]

For each reading, in this order:
  1. insert it into the database (db.insert_reading)
  2. compute its record key and digest (fingerprint module)
  3. commit both to the contract, signed by the aggregator key (chain.send_tx)
  4. log the gas used and the time taken (results.log, event="commit")

Think about: what should happen if step 3 fails after step 1 succeeded?
Note your answer in the report; the simple choice is fine for a prototype.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from web3 import Web3
from web3.contract import Contract

from .models import Reading


def ingest(readings: Iterable[Reading], conn: sqlite3.Connection, w3: Web3,
           contract: Contract, aggregator_key: str, results_path: Path) -> int:
    """Store and commit every reading. Return how many were committed."""
    raise NotImplementedError("Step 6 in docs/BUILD_GUIDE.md")
