"""Settings loaded from the repo-root .env file. [provided]"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = REPO_ROOT / "contracts" / "out" / "MeterCommitmentRegistry.sol" / "MeterCommitmentRegistry.json"

load_dotenv(REPO_ROOT / ".env")


def _path(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


@dataclass(frozen=True)
class Settings:
    rpc_url: str
    contract_address: str
    aggregator_key: str
    attacker_key: str
    dataset_path: Path
    db_path: Path
    results_path: Path
    artifact_path: Path = ARTIFACT_PATH


def load_settings() -> Settings:
    return Settings(
        rpc_url=os.getenv("RPC_URL", "http://127.0.0.1:8545"),
        contract_address=os.getenv("CONTRACT_ADDRESS", ""),
        aggregator_key=os.getenv("AGGREGATOR_PRIVATE_KEY", ""),
        attacker_key=os.getenv("ATTACKER_PRIVATE_KEY", ""),
        dataset_path=_path("DATASET_PATH", "data/ampds2_whe.csv"),
        db_path=_path("DB_PATH", "data/utility.db"),
        results_path=_path("RESULTS_PATH", "results/results.csv"),
    )
