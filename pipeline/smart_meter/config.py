"""Explicit runtime settings and isolated paths for local runs."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPO_ROOT
    / "contracts"
    / "out"
    / "MeterCommitmentRegistry.sol"
    / "MeterCommitmentRegistry.json"
)
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class ConfigurationError(ValueError):
    """A required setting or safe run path is missing or invalid."""


def _path(value: str, root: Path = REPO_ROOT) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


@dataclass(frozen=True)
class RunPaths:
    root: Path
    db: Path
    results: Path
    manifest: Path


def run_paths(
    run_id: str, *, base: Path = REPO_ROOT / "results", create: bool = False
) -> RunPaths:
    """Return paths for one run; exclusive creation refuses collisions."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ConfigurationError(
            "run ID must be 1-64 letters, digits, underscores or hyphens"
        )
    root = base / run_id
    if create:
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise ConfigurationError(f"run directory already exists: {root}") from error
    return RunPaths(
        root, root / "readings.sqlite", root / "results.csv", root / "manifest.json"
    )


@dataclass(frozen=True)
class Settings:
    rpc_url: str = field(repr=False)
    contract_address: str
    dataset_path: Path | None
    run: RunPaths
    aggregator_key: str | None = field(default=None, repr=False)
    artifact_path: Path = ARTIFACT_PATH

    def diagnostics(self) -> dict[str, str]:
        """Safe fields only; never include private keys or a full environment dump."""
        endpoint = urlsplit(self.rpc_url)
        host = endpoint.hostname or ""
        port = f":{endpoint.port}" if endpoint.port else ""
        return {
            "rpc_endpoint": f"{endpoint.scheme}://{host}{port}",
            "contract_address": self.contract_address,
            "dataset_path": str(self.dataset_path) if self.dataset_path else "",
            "run_directory": str(self.run.root),
            "artifact_path": str(self.artifact_path),
            "mode": "write" if self.aggregator_key else "audit",
        }


def load_settings(
    *,
    run_id: str,
    mode: str,
    values: Mapping[str, str] | None = None,
    base: Path = REPO_ROOT / "results",
    create_run: bool = False,
) -> Settings:
    """Read supplied values or process environment, never a personal .env file."""
    if mode not in {"write", "audit"}:
        raise ConfigurationError("mode must be 'write' or 'audit'")
    source = os.environ if values is None else values
    required = ["RPC_URL", "CONTRACT_ADDRESS"]
    if mode == "write":
        required += ["DATASET_PATH", "AGGREGATOR_PRIVATE_KEY"]
    missing = [name for name in required if not source.get(name, "").strip()]
    if missing:
        raise ConfigurationError(
            f"missing required configuration: {', '.join(missing)}"
        )
    run = run_paths(run_id, base=base, create=create_run)
    return Settings(
        rpc_url=source["RPC_URL"],
        contract_address=source["CONTRACT_ADDRESS"],
        dataset_path=_path(source["DATASET_PATH"]) if mode == "write" else None,
        run=run,
        aggregator_key=source["AGGREGATOR_PRIVATE_KEY"] if mode == "write" else None,
        artifact_path=_path(source["ARTIFACT_PATH"])
        if source.get("ARTIFACT_PATH")
        else ARTIFACT_PATH,
    )
