# smart-meter

A blockchain-based prototype for detecting changes to stored smart meter
readings using SHA-256 fingerprints and smart contracts.

## How it works

1. Household readings from the public AMPds2 dataset are replayed as meter readings.
2. Each reading is stored in a SQLite database that plays the utility's records.
3. A trusted aggregator computes a SHA-256 fingerprint of the reading.
4. The fingerprint is committed to a smart contract on a local Anvil chain.
   Only accounts with the aggregator role may commit, and a fingerprint can never be replaced.
5. An auditor recomputes the fingerprint from the database and compares it with
   the chain: `VERIFIED`, `TAMPERED`, `MISSING_RECORD`, `MISSING_COMMITMENT`,
   `MISSING_BOTH`, or `ERROR`.

Limits, stated up front: the design detects changes made after a fingerprint is
committed. It cannot detect a reading that was already false when committed,
and it is built for retrospective audits, not real-time grid control.

Diagrams (Mermaid sources) are in `docs/diagrams/`.

## Layout

```
contracts/                Foundry project
  src/                    MeterCommitmentRegistry.sol
  test/                   Solidity example, fuzz and stateful invariant tests
  script/                 Deploy.s.sol
pipeline/                 Python package and tests
  smart_meter/            dataset (loader), fingerprint, db (readings + journal),
                          chain (deployment context, transactions), runs
                          (manifests, writer lock), aggregator, verifier,
                          scenarios, evaluate, experiment, demo, local_chain
  tests/                  fast, SQLite, property and owned-Anvil chain tests
scripts/                  report guards, coverage gate, integration runner,
                          broken-control checks
docs/                     report, data dictionary, toolchain, diagrams,
                          curated evidence (docs/evidence/)
data/, results/           dataset and generated run directories (not committed)
```

## Storage, journal and run files

Each run lives in its own `results/<run_id>/` directory, holding:

- `readings.sqlite`: the database the insider attack edits. Schema version 1
  (`PRAGMA user_version`) has the `readings` table plus a submission journal:
  `submissions` (one intended commitment per run and record key) and
  `submission_attempts` (the signed transaction's hash, sender, nonce and raw
  payload, plus receipt evidence). Migrations are transactional; an unknown
  or newer schema is refused rather than reinterpreted.
- `manifest.json` and `expected_records.json`: the source checksum,
  conversion policy, selection, deployment context and expected record keys
  and digests. Both are written once and never replaced. Audits use the
  expected keys, so a deleted or re-keyed row is still reported.
- `writer.lock`: an OS lock that allows a single writer and is released if
  the process exits or crashes.
- `results.csv` and `audit.csv`: raw evidence rows.

A submission moves through `PREPARED -> SUBMITTED -> CONFIRMED`, or ends
`FAILED` (a definite rejection or revert) or `UNCERTAIN` (the outcome is
unknown, for example after a receipt timeout). The signed transaction is
journalled before broadcast. A resume first reconciles uncertain submissions
against the chain, rebroadcasting the identical signed transaction rather than
signing a new one. A record counts as confirmed only after a successful
receipt and a matching registry entry. SQLite and the chain are never treated
as one atomic transaction.

## Current setup and checks

Use Python 3.12 and [Foundry v1.9.0](https://github.com/foundry-rs/foundry/releases/tag/v1.9.0). The exact contract-library revisions and update method are in [the toolchain guide](docs/TOOLCHAIN.md). Install Foundry first; `make install` creates `.venv`, installs the exact Python lock and checks out the pinned Solidity libraries. It does not install the Foundry binaries themselves.

```bash
make help
make install
make lint
make build
make test-unit
make test-contracts
make coverage
```

`make check` requires lint, build, Python tests, contract tests, owned-Anvil integration and combined coverage. Reports reject empty/skipped required suites. Coverage includes both Python suites, requires 85% overall lines and 90% branches in each critical module, and runs in CI's integration job. See [toolchain](docs/TOOLCHAIN.md) and the [evaluation report](docs/REPORT.md).

## Run the demonstration

```bash
make build
make demo
# Or choose an output directory and source explicitly:
cd pipeline
../.venv/bin/python -m smart_meter.demo demo --run-dir ../results/example --source tests/fixtures/two_hours.csv
../.venv/bin/python -m smart_meter.demo scenarios --run-dir ../results/scenarios-example
```

The synthetic input has two complete hours yielding 60 and 120 Wh. `demo` creates a fresh registry, stores the run manifest and expected identities, ingests, resumes without another commit, and audits. It owns and stops a disposable local Anvil node; files remain, but that chain is unavailable after the command exits. Reproduce with a new run directory. Existing directories are refused, never deleted. Scenario directories each use a distinct registry; A4 correctly returns VERIFIED because its alteration preceded commitment.

For separate new/resume/audit commands, keep your local node alive (`make chain` in another terminal), then from `pipeline/`:

```bash
../.venv/bin/python -m smart_meter.demo new --rpc http://127.0.0.1:8545 --run-dir ../results/live --source tests/fixtures/two_hours.csv
../.venv/bin/python -m smart_meter.demo resume --rpc http://127.0.0.1:8545 --run-dir ../results/live
../.venv/bin/python -m smart_meter.demo audit --rpc http://127.0.0.1:8545 --run-dir ../results/live
```

Writes accept only loopback Anvil and use the public development mnemonic's throwaway accounts. Commands do not load `.env`. The audit needs no signing key. A reset/wrong chain produces an error. Resume checks the original source path, checksum, selection and deployment. The manual `make deploy` is a lower-level `.env`-driven developer command; the new CLI captures complete deployment context automatically.

Exit codes: **0** completed cleanly, **2** completed audit with findings, **1** operational failure or incomplete work. Scenarios return 0 only when every expected result matches, including the expected A4 limitation and S8 error.

## Presentation dashboard

```bash
make build        # once, so the live run can deploy the contract
make dashboard    # http://127.0.0.1:8765 (or: make dashboard PORT=9000)
```

The dashboard shows the curated evidence in `docs/evidence/` as one page: each
security scenario with its expected and actual outcome, detection, false-alarm
and rejection rates as numerator/denominator, the three real-data runs, timing
and gas charts, and provenance. Every number is read from the evidence files;
nothing is retyped or recomputed. A4 is labelled as the pre-commit limitation,
and timings are labelled as local Anvil measurements.

**Run all scenarios on a fresh chain** runs the same tested scenario suite live
on a disposable local chain the dashboard starts and stops, writing only to a new
`results/dashboard-<time>/` directory. It never edits the curated evidence.

The dashboard listens on loopback only, needs no internet connection and no
keys, and uses only the Python standard library. Use the **Light / dark** button
to match the projector.

## Evaluation and evidence

```bash
cd pipeline
../.venv/bin/python -m smart_meter.evaluate ../results/live/results.csv ../results/live/audit.csv
../.venv/bin/python -m smart_meter.experiment --output ../docs/evidence/my-evaluation
# From repository root:
.venv/bin/python scripts/final_controls.py /tmp/smart-meter-new-controls
```

The experiment requires the original local AMPds2 files with the checksums in [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md). It performs three independent 24-reading local runs and verifies both original checksums afterward. Full datasets and databases stay ignored. Curated public manifests, expected keys, CSV outcomes, versions and descriptive metrics are retained under `docs/evidence/`. JSON null means unavailable (N/A), not zero.

Read the [report](docs/REPORT.md) for measured results, timing boundaries and denominators. Fingerprint equality establishes consistency with a commitment, not physical truth or privacy. The operator controls Anvil and the manifest; this does not demonstrate independent governance. A separately protected conventional log could provide the independent reference under similar trust assumptions.

Verification findings and remaining acceptance items are recorded in the [audit summary](docs/AUDIT_SUMMARY.md).

## Dataset

Makonin, Ellert, Bajic and Popowich, "Electricity, water, and natural gas
consumption of a residential house in Canada from 2012 to 2014," Scientific
Data 3, 160037 (2016). doi:10.1038/sdata.2016.37
