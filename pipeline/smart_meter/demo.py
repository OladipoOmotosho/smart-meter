"""Safe local demonstration CLI. Exit 0 clean, 2 findings, 1 incomplete/error."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from web3 import Web3
from web3.exceptions import Web3Exception

from . import aggregator, chain, local_chain, runs, verifier
from .config import ARTIFACT_PATH, REPO_ROOT, run_paths
from .models import Verdict


def paths_for(directory: Path, *, create: bool = False):
    directory = directory.resolve()
    return run_paths(directory.name, base=directory.parent, create=create)


def new_run(directory: Path, source: Path, w3: Web3, limit: int = 24):
    paths = paths_for(directory, create=True)
    config = runs.RunConfig(source.resolve(), limit=limit)
    # Validate the source before deploying anything.
    runs._load(config)
    context = local_chain.deploy(w3)
    run = runs.open_run(paths, config, context)
    summary = aggregator.ingest_run(
        run, w3, ARTIFACT_PATH, local_chain.accounts()[1].key.hex()
    )
    return run, summary


def resume_run(directory: Path, w3: Web3):
    paths = paths_for(directory)
    manifest = json.loads(paths.manifest.read_text())
    context = chain.DeploymentContext.from_json(manifest["deployment"])
    selection = manifest["selection"]
    config = runs.RunConfig(
        Path(manifest["source"]["path"]), selection["meter_id"], selection["limit"]
    )
    run = runs.open_run(paths, config, context, resume=True)
    return aggregator.ingest_run(
        run, w3, ARTIFACT_PATH, local_chain.accounts()[1].key.hex()
    )


def audit_exit(rows) -> int:
    if not rows or any(row.outcome == Verdict.ERROR for row in rows):
        return 1
    return 2 if any(row.outcome != Verdict.VERIFIED for row in rows) else 0


def _audit(directory: Path, w3: Web3) -> int:
    paths = paths_for(directory)
    rows = verifier.audit_run(paths, w3, ARTIFACT_PATH, paths.root / "audit.csv")
    print(
        json.dumps(
            {
                "run_id": paths.root.name,
                "counts": {v.value: sum(r.outcome == v for r in rows) for v in Verdict},
            }
        )
    )
    return audit_exit(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("demo", "new", "resume", "audit", "scenarios")
    )
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument(
        "--source",
        type=Path,
        default=REPO_ROOT / "pipeline/tests/fixtures/two_hours.csv",
    )
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--rpc")
    args = parser.parse_args(argv)
    directory = args.run_dir or REPO_ROOT / "results" / (
        "demo-" + uuid.uuid4().hex[:12]
    )
    try:
        if args.command in {"resume", "audit"} and args.run_dir is None:
            raise ValueError("--run-dir is required for resume/audit")
        if args.command == "scenarios":
            from .scenarios import run_scenarios

            with local_chain.owned_node() as w3:
                return run_scenarios(directory, w3)
        if args.command == "demo":
            with local_chain.owned_node() as w3:
                run, summary = new_run(directory, args.source, w3, args.limit)
                print(json.dumps(asdict(summary)))
                if not summary.complete:
                    return 1
                resumed = resume_run(directory, w3)
                if not resumed.complete or resumed.newly_confirmed != 0:
                    return 1
                return _audit(run.paths.root, w3)
        if not args.rpc:
            raise ValueError("--rpc is required; start a local node with make chain")
        if args.command == "audit":
            w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 5}))
            return _audit(directory, w3)
        w3 = local_chain.local_client(args.rpc)
        if args.command == "new":
            _, summary = new_run(directory, args.source, w3, args.limit)
        else:
            summary = resume_run(directory, w3)
        print(json.dumps(asdict(summary)))
        return 0 if summary.complete else 1
    except (
        OSError,
        ValueError,
        RuntimeError,
        sqlite3.Error,
        Web3Exception,
        chain.SubmissionError,
        chain.SubmissionUncertain,
        KeyError,
        TypeError,
    ) as error:
        print(f"operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
