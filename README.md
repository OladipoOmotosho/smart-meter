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

## Quick start

Requires Foundry and Python 3.11+.

```bash
make install          # contract libraries + Python environment
cp .env.example .env  # then fill it in from the Anvil account list
make chain            # in a separate terminal; leave running
make build
make test-contracts
make deploy           # copy the printed address into .env
make test-pipeline
make demo
```

## Dataset

Makonin, Ellert, Bajic and Popowich, "Electricity, water, and natural gas
consumption of a residential house in Canada from 2012 to 2014," Scientific
Data 3, 160037 (2016). doi:10.1038/sdata.2016.37
