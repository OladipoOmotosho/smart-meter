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
   the chain: `VERIFIED`, `TAMPERED` or `MISSING`.

Limits, stated up front: the design detects changes made after a fingerprint is
committed. It cannot detect a reading that was already false when committed,
and it is built for retrospective audits, not real-time grid control.

Diagrams (Mermaid sources) are in `docs/diagrams/`.

## Layout

```
contracts/                Foundry project
  src/                    MeterCommitmentRegistry.sol
  test/                   Solidity tests
  script/                 Deploy.s.sol
pipeline/                 Python package and tests
  smart_meter/            config, models, db, chain, results, fingerprint,
                          dataset, aggregator, verifier, demo
  tests/                  fingerprint tests, attack tests
docs/                     diagrams
data/                     dataset and generated database (not committed)
```

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

The project is still being implemented. `make check` includes the required integration target. `make test-integration` owns a temporary local Anvil process, builds the contract, deploys a fresh registry per scenario, runs the chain-marked tests, and tears down its node. The checks now exercise the implemented loader, registry, basic ingestion and audit paths; a passing check does not complete the remaining manifest, journal, deployment-context, evaluation and safe demo tasks in the private project spec.

Test reports are written to `.test-results/` (or `REPORT_DIR`). The report checks reject empty, skipped and expected-fail required cases, and the CI workflow requires separate Python, contract and integration jobs. Python runtime settings never load `.env` implicitly. New run files belong in `results/<run_id>/`; write settings require a dataset and throwaway aggregator key, while audit settings require no signing key. The safe run and audit CLI commands are still pending Task 9.1.

For a manual local chain, `make chain` starts Anvil in the foreground on `127.0.0.1:8545`. `make deploy` uses the explicitly provided local `.env` and broadcasts to that node; use only throwaway Anvil accounts. The deployment script does not yet record the full deployment context required by the spec. `make demo` deliberately fails until Task 9.1 replaces the scaffold's database deletion. There is no routine reset command.

## Dataset

Makonin, Ellert, Bajic and Popowich, "Electricity, water, and natural gas
consumption of a residential house in Canada from 2012 to 2014," Scientific
Data 3, 160037 (2016). doi:10.1038/sdata.2016.37
