"""Reproduce three bounded AMPds2 runs and retain public evidence (Task 10.2)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from . import evaluate, local_chain, runs, scenarios, verifier
from .config import ARTIFACT_PATH, REPO_ROOT
from .demo import new_run, resume_run

CHECKSUMS = {
    "Electricity_WHE.csv": "b33fb7f1e3acf21d8dfe8876102965ec8872a5ce9142a8a400ed29f012a19964",
    "Electricity_P.csv": "c5564ba459b74b3df4ca6379769f953526ea3e00cc214f6d8bb914dd8fc11fad",
}


def execute(output: Path) -> dict:
    """Fail on source mismatch; each run owns a new node, registry and database."""
    source_root = REPO_ROOT / "data/raw"
    before = {name: runs._sha256_file(source_root / name) for name in CHECKSUMS}
    if before != CHECKSUMS:
        raise ValueError("source checksums differ from the verified data dictionary")
    output.mkdir(parents=True, exist_ok=False)
    code = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
        ).strip()
    )
    provenance = {
        "code_revision": code,
        "dirty": dirty,
        "source_checksums_before": before,
        "foundry": subprocess.check_output(
            ["forge", "--version"], text=True
        ).splitlines()[0],
        "anvil": subprocess.check_output(
            ["anvil", "--version"], text=True
        ).splitlines()[0],
        "command": f"python -m smart_meter.experiment --output {output}",
        "selection": "one AMPds2 WHE channel; 24 hourly intervals, 2012-04-01T07:00:00Z to 2012-04-02T07:00:00Z",
        "code_sha256": {
            str(p.relative_to(REPO_ROOT)): runs._sha256_file(p)
            for p in sorted((REPO_ROOT / "pipeline/smart_meter").glob("*.py"))
        },
    }
    all_rows, per_run = [], []
    for index in range(1, 4):
        destination = output / f"run-{index}"
        working = REPO_ROOT / "results" / f"{output.name}-run-{index}"
        with local_chain.owned_node() as w3:
            run, summary = new_run(working, source_root / "Electricity_WHE.csv", w3, 24)
            if not summary.complete or summary.newly_confirmed != 24:
                raise RuntimeError(
                    "real-data ingestion did not confirm all 24 readings"
                )
            audit = run.paths.root / "audit.csv"
            rows = verifier.audit_run(run.paths, w3, ARTIFACT_PATH, audit)
            if len(rows) != 24 or any(r.outcome.value != "VERIFIED" for r in rows):
                raise RuntimeError("real-data clean audit failed")
            block_before = w3.eth.block_number
            resumed = resume_run(working, w3)
            if (
                resumed.reconciled != 24
                or resumed.newly_confirmed
                or w3.eth.block_number != block_before
            ):
                raise RuntimeError(
                    "resume introduced a new transaction or missed records"
                )
            destination.mkdir()
            for path in (
                run.paths.manifest,
                run.paths.expected,
                run.paths.results,
                audit,
            ):
                shutil.copyfile(path, destination / path.name)
            raw = evaluate.read_rows([run.paths.results, audit])
            all_rows.extend(raw)
            metrics = evaluate.summarize(raw)
            per_run.append(
                {
                    "run": index,
                    "ingestion": asdict(summary),
                    "resume": asdict(resumed),
                    "metrics": metrics,
                }
            )
    with local_chain.owned_node() as w3:
        scenario_root = REPO_ROOT / "results" / (output.name + "-scenarios")
        if scenarios.run_scenarios(scenario_root, w3) != 0:
            raise RuntimeError("security scenario mismatch")
        shutil.copyfile(scenario_root / "scenarios.csv", output / "scenarios.csv")
        all_rows.extend(evaluate.read_rows([output / "scenarios.csv"]))
    after = {name: runs._sha256_file(source_root / name) for name in CHECKSUMS}
    if before != after:
        raise RuntimeError("original source files changed during evaluation")
    pooled = evaluate.summarize(all_rows)
    report = {
        "provenance": {**provenance, "source_checksums_after": after},
        "runs": per_run,
        "pooled": pooled,
        "projection": evaluate.projection(1000, 60, pooled["commit_gas"]["median"]),
        "limitations": "Three descriptive local runs, not statistical proof or public-network performance. Anvil and manifest share an operator. A4 is outside post-commit detection.",
    }
    (output / "evaluation.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(execute(args.output.resolve())["pooled"], indent=2))


if __name__ == "__main__":
    main()
