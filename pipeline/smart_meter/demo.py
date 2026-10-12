"""End-to-end demo: dataset -> database -> blockchain -> audit. [provided glue]

Runs once Steps 1 to 7 are done:  make demo
"""

from __future__ import annotations

from collections import Counter

from . import chain, db
from .aggregator import ingest
from .config import load_settings
from .dataset import load_readings
from .verifier import verify

DEMO_READINGS = 24  # one day of hourly readings


def main() -> None:
    s = load_settings()
    w3 = chain.connect(s.rpc_url)
    contract = chain.load_contract(w3, s.contract_address, s.artifact_path)

    if s.db_path.exists():
        s.db_path.unlink()  # fresh database each run; the chain keeps its history until Anvil restarts
    conn = db.connect(s.db_path)

    readings = list(load_readings(s.dataset_path, limit=DEMO_READINGS))
    committed = ingest(readings, conn, w3, contract, s.aggregator_key, s.results_path)
    print(f"Committed {committed} readings")

    verdicts = Counter(verify(conn, contract, m, t, s.results_path) for m, t in db.all_keys(conn))
    print("Audit:", dict(verdicts))


if __name__ == "__main__":
    main()
