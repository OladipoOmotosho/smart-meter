# Implementation plan: Smart-meter integrity auditing

Status: all implementation groups pending verification.  
Baseline: 2026-10-15.  
Companion documents: [Requirements](requirements.md) · [Design](design.md)

## How to use this plan

Work in order, with one task group in progress. Check a box only after the described work and its relevant checks pass. Existing scaffold files do not establish completion. Each group ends with a test/review gate; keep evidence under the group using the template below. If blocked, record the actual cause and the smallest next action.

These tasks implement the current prototype. They do not authorize a pivot, public deployment, spending, automatic commits or deletion of the specs. Use a task branch before committing; commit/push/merge only when the user asks. Keep the applicable engineering practices from `setup/`, adapted to this stack. Preserve the user's work and review actual repository changes before editing.

Required tests are never optional `*` tasks. A group may pass its focused checks while later groups remain unfinished; do not describe that as a passing whole-project suite. Remove placeholder skips as their tests are implemented. The full gate remains incomplete until all required cases execute.

## Current baseline and first action

- The three previous spec files contained a webstore template, not smart-meter requirements.
- The registry and four core pipeline modules are unfinished. Contract/attack tests contain explicit skips.
- Two AMPds2 files already exist in `data/raw/`. Start by documenting their meaning, not downloading them again.
- README setup commands reference a missing Makefile. Python requirements are not pinned; contract libraries and CI configuration are not present in the inspected checkout.
- The demo deletes a configured database and enumerates only surviving rows; both must change before repeatable security demonstrations.

**Next action: Task 1.1.** Confirm source metadata and build the data dictionary. No application implementation was completed by authoring these specs.

## 1. Establish the dataset contract

Dependencies: none. Goal: remove uncertainty about columns, units and preprocessing before interpreting real readings.

- [ ] **1.1 Inspect source documentation and record provenance.** Read the local dataset paper plus its referenced metadata/table as needed; document exact locations supporting `unix_ts`, `P`, W, UTC/Unix seconds, minute sampling and imputation markers. Record DOI, available version, checksum, usage terms and retrieval date if known in `docs/DATA_DICTIONARY.md`. Explicitly label unavailable metadata. Requirements: R1.1–R1.3, R1.5.
- [ ] **1.2 Confirm the bounded input selection.** Use existing `data/raw/Electricity_WHE.csv` for the first adapter. Record why the P-file's `UNIX_TS`/`WHE` layout differs. Select 24 complete hourly intervals for the eventual demo; record how incomplete edges, imputed samples and unsupported negatives are handled. Do not reinterpret `Pt` without evidence. Requirements: R1.3, R2.1–R2.6.
- [ ] **1.3 Prepare small synthetic fixture definitions.** Specify literal minute samples with independently calculated Wh results, rounding ties, duplicate/gap/invalid rows and imputation flags. Put eventual tracked fixtures under `pipeline/tests/fixtures/`, not ignored `data/`. Source CSVs remain unchanged. Requirements: R1.4, R2.2–R2.5, R10.2.
- [ ] **1.4 Gate — validate the data contract.** Review every chosen field against a source; inspect actual headers and selected timestamps; independently calculate at least one interval and both sides of a rounding tie. Compare before/after source checksums. Report unresolved interpretation as a blocker to real-data ingestion. This documentation gate precedes the executable tests in Task 4. Requirements: R1.1–R1.5, R2.3, R10.1.

## 2. Make setup and verification reproducible

Dependencies: 1. Goal: a clean checkout can install the intended tools and run explicit checks.

- [ ] **2.1 Pin the environment.** Select and record a supported Python version, Foundry release, compiler and exact OpenZeppelin/forge-std revisions. Lock Python dependencies including pytest, coverage, Hypothesis and lint tools; avoid unused packages. Record the installation method and update policy. Requirements: R9.1, R10.6.
- [ ] **2.2 Implement real command targets.** Add the Makefile targets defined in design §10. `make test-unit` excludes chain tests explicitly; `make test-integration` owns its local node. Separate ordinary demo commands from any explicit reset operation. Update the tracked README to use commands that exist. Requirements: R9.1–R9.4.
- [ ] **2.3 Isolate configuration and result paths.** Test settings must not import personal `.env` values. Make required fields explicit for write commands while allowing read-only audit configuration. Define per-run output directories and secret-free config diagnostics. Requirements: R6.5, R9.2, R9.5.
- [ ] **2.4 Establish the check harness.** Add pytest markers, result reporting, lint/format configuration and CI `python`, `contracts`, `integration` jobs. Add checks for empty suites, skipped/xfail required cases and absent scenario IDs; prevent required jobs from being silently omitted. The complete check may legitimately fail while stubs remain. Requirements: R10.2–R10.5.
- [ ] **2.5 Gate — verify setup honestly.** From a disposable clean checkout/environment, install pinned dependencies, run command discovery, lint/build checks and test collection. Record the baseline failures/skips caused by unfinished code; do not turn them into passes. Verify that a deliberately empty/skip-only required suite fails the harness and an intentional fast-suite chain deselection is reported correctly. Requirements: R9.1, R9.3, R10.1, R10.3, R10.5.

## 3. Implement canonical records and fingerprints

Dependencies: 2. Goal: prove the content representation independently of blockchain.

- [ ] **3.1 Define model and validation boundaries.** Retain the five Reading fields; reject wrong types/booleans as integers at boundaries. Keep source/physical validation distinct from deterministic serialization so audits can fingerprint a readable changed unit. Requirements: R2.4, R3.1–R3.3.
- [ ] **3.2 Implement versioned canonical bytes and hashes.** Follow the exact JSON settings, domain prefixes and field order in design §4. Keep identity separate from content. Prepare literal golden byte/digest/key vectors independently and commit the fixtures with their derivation notes. Requirements: R3.1–R3.4.
- [ ] **3.3 Gate — run examples and generated properties.** Preserve the nine meaningful existing fingerprint tests. Add fixed-vector, quote/backslash/delimiter/Unicode, field-order, numeric-type and separate-process determinism cases. Exercise P1–P3 with at least 200 generated examples per property. Changing value must preserve key while changing encoded content. Do not describe finite tests as cryptographic proof. Requirements: R3.1–R3.4, R10.1–R10.2.

## 4. Implement the AMPds2 loader

Dependencies: 1–3. Goal: deterministic, documented readings from the selected source.

- [ ] **4.1 Implement the explicit WHE adapter.** Match verified headers, preserve imputation flags, parse exact power values and UTC timestamps, validate order/duplicates/gaps and attach source-row context to errors. Reject unsupported intervals and schema guessing. Requirements: R1.2–R1.5, R2.1–R2.2, R2.6.
- [ ] **4.2 Implement bounded hourly conversion.** Apply half-open UTC hours, complete-interval checks, exact sum/60 and one half-up rounding. Exclude/count partial boundaries; keep deterministic sequence and positive limit behavior. Collect enough preprocessing metadata for the manifest without reading the full source into memory. Requirements: R2.2–R2.6.
- [ ] **4.3 Gate — validate conversion and rejection behavior.** Implement `test_dataset.py` with hand-calculated fixtures and P4. Cover 60 W, fractional/tie rounding, zero power, invalid/non-finite/negative input, timestamp prefix, minute/hour boundaries, duplicate/reversed rows, gaps, empty file, missing header, partial edges, bad limit and unsupported interval. Check repeatability and bounded consumption of a synthetic stream. After these pass, inspect 24 real transformed readings with their provenance; confirm source checksums remain unchanged. Requirements: R1.1–R1.5, R2.1–R2.6, R10.1–R10.2.

## 5. Complete and challenge the registry

Dependencies: 3. Execute after 4 under the one-group-at-a-time workflow. Goal: enforce write authority and append-once state.

- [ ] **5.1 Implement the existing interface.** Add storage, role-checked commit, duplicate/zero-digest guards, getters and exact event emission. Reject zero admin explicitly. Keep zero key valid and remove comments claiming a zero SHA-256 output is impossible. Requirements: R4.1–R4.4.
- [ ] **5.2 Implement the seven existing example tests.** Remove each `vm.skip(true)` only when its assertions are present. Check exact stored fields, event topics/data and custom revert reasons; check rejected writes leave state and successful-event counts unchanged. Requirements: R4.2–R4.4, R7.3–R7.4.
- [ ] **5.3 Extend authorization, fuzz and stateful tests.** Cover admin-without-writer-role, role grant/revocation, unauthorized role management, same-digest duplicates, another aggregator's overwrite, zero digest/key and unknown keys. Use an independent first-commit/role model for P5–P6 and assert nonvacuous handler activity. Requirements: R4.1–R4.5, R7.6, R10.2.
- [ ] **5.4 Gate — verify contract controls.** Run formatting, build, all example tests, at least 256 fuzz cases/test and 128 invariant runs at depth 32. Require zero skipped required cases; inspect coverage of every public function and guard. Save failures/seeds as reproducible regressions. Requirements: R4.1–R4.5, R10.1–R10.4.

## 6. Harden blockchain access and isolated deployment

Dependencies: 2, 5. Goal: distinguish an accepted transaction from an attempted or uncertain one.

- [ ] **6.1 Implement deployment/context records.** Capture chain/address, deployment receipt/block hash, runtime-code hash, role accounts and versions. Validate that context for ingestion and audit. Check the actual deployed code and permissions, not merely a nonempty address. Requirements: R4.6, R6.3, R9.4–R9.5.
- [ ] **6.2 Extend transaction handling.** Preserve preflight errors, known hash/sender/nonce, bounded receipt waiting, status-0 reverts and lost-response uncertainty. Expose enough information for durable preparation/reconciliation in Task 7. Do not treat every revert as the same Python exception or assume gas-estimation failure is a mined receipt. Requirements: R5.2–R5.4, R7.6.
- [ ] **6.3 Implement owned Anvil fixtures.** Use temporary directories, available local ports, readiness timeouts, fresh deployment and finalizer cleanup. Read-only clients must work without wallet keys. Keep developer nodes, personal `.env` and real wallets outside fixtures. Requirements: R6.5, R9.3, R9.5.
- [ ] **6.4 Gate — test the chain boundary.** Test bad/missing ABI/address, absent bytecode, wrong/reset deployment context, unreachable RPC, successful receipt, actual mined reverted transaction and simulated lost response. Confirm emitted event fields against the ABI and verify fixture teardown even when a test fails. Include authorization/duplicate errors from the real contract. Requirements: R4.6, R5.3–R5.4, R6.3, R7.3–R7.4, R9.3, R10.1–R10.2.

## 7. Implement durable storage and resumable ingestion

Dependencies: 3, 4, 6. Goal: preserve records and evidence through partial failures.

- [ ] **7.1 Add schema versions and submission journal.** Preserve the existing readings identity; add explicit transactional migrations and persistence of intent/state/transaction evidence. Use parameterized SQL, exact round-trips and no replacement of conflicting rows. Requirements: R5.1–R5.2, R10.6.
- [ ] **7.2 Add run manifests and writer ownership.** Persist conversion/source/deployment context plus expected keys before sending transactions. Use separate run directories, atomic manifest preparation and an exclusive process-lifetime writer lock. Reject incompatible resumes and a concurrent writer. Requirements: R2.5–R2.6, R5.2, R5.6, R6.4, R9.2.
- [ ] **7.3 Implement ingestion and reconciliation.** Return the specified summary counts. Reconcile existing matching commitments without a new write; stop on changed local records/different digests. Require receipt success and matching registry state before confirmation. Preserve ambiguous outcomes for explicit bounded resume. Requirements: R5.1–R5.6.
- [ ] **7.4 Gate — test persistence, crashes and retries.** Use real temporary SQLite files, reopen them and exercise P7–P8. Test rollback/migrations, duplicate conflict, second-writer rejection, crash before submission, crash after broadcast, status-0 receipt, timeout, success before journal/log failure and same-run resume. Verify original records remain, counts are accurate and reconciliation does not send another transaction. Include real-chain successful/resumed paths and controlled fault injection for difficult timing cases. Requirements: R5.1–R5.6, R7.6, R9.2, R10.1–R10.2.

## 8. Implement complete, read-only audits

Dependencies: 7. Goal: distinguish mismatch, missing evidence and failed checking.

- [ ] **8.1 Introduce AuditResult and explicit outcomes.** Replace ambiguous `MISSING` with the design's missing-evidence outcomes plus `ERROR`; retain explained `TAMPERED`. Include identities, reasons, available digests, context and timing. Update callers and results schema together. Requirements: R6.1–R6.3, R6.6.
- [ ] **8.2 Audit expected identities.** Read the manifest's expected set, validate deployment context, read current records and compare exact fingerprints. Use no signing key and send no transactions. Leave readings/journal unchanged; do not rebuild the expected set from surviving rows. Requirements: R6.4–R6.6.
- [ ] **8.3 Gate — exercise the entire outcome table.** Implement P9–P11 and S5/S6/S8. Test clean/mismatch, each missing combination, deletion/re-keying, changed unit/sequence, corrupt rows, DB/RPC failure, wrong deployment and an empty surviving table. Assert exact outcomes/reasons and unchanged DB/chain state. Confirm an unavailable reference cannot produce a success/missing verdict. Requirements: R6.1–R6.6, R7.6, R10.1–R10.2.

## 9. Deliver the demonstration and security evidence

Dependencies: 5–8. Goal: exercise the actual components as one system.

- [ ] **9.1 Replace destructive demo behavior.** Create a new run directory/registry or explicitly resume a matching run; remove unconditional DB unlinking. Add manifest-based audit commands, documented exit codes and a scenario runner. Report meaningful summaries and failures. Requirements: R5.5, R6.4, R9.1–R9.5.
- [ ] **9.2 Implement the five promised scenarios.** Complete S0 and A1–A4 in `test_attacks.py` against isolated Anvil. Assertions must check exact errors/results and unchanged protected state. A4 must pass by returning `VERIFIED`, with its limitation clearly labelled. Requirements: R7.1–R7.5.
- [ ] **9.3 Add expanded scenarios and structured exports.** Implement S5–S10, scenario IDs, expected/actual outcomes, gas/timing/error fields, and results-write error behavior. Run each attack from an independent clean fixture. Requirements: R7.6, R8.1, R9.2–R9.4.
- [ ] **9.4 Gate — run complete system tests.** Execute a synthetic two-hour CSV through parsing, SQLite, actual registry, audit and exported results. Check clean exit 0, findings exit 2, operational failure exit 1 and all-expected-scenarios success 0. Run a fresh demonstration twice and same-run resume; verify no user database loss, collisions or duplicate commitments. Required integration cases must actually execute with zero skips. Requirements: R7.1–R7.6, R8.1, R9.1–R9.5, R10.1–R10.3.

## 10. Evaluate results and close the evidence gaps

Dependencies: 1–9. Goal: a reproducible course demonstration and a report that respects the evidence.

- [ ] **10.1 Implement evaluation with explicit denominators.** Add `evaluate.py` and tests for known counts, error/exclusion handling, A4 separation, gas availability, timing boundaries, median/nearest-rank p95, empty/small samples and labelled scale projections. Requirements: R8.1–R8.4.
- [ ] **10.2 Run the real-data evaluation.** Use the verified source selection for 24 hourly readings in three independent local runs. Save manifests, checksums, deployment IDs, commands, counts, versions, raw results and code revision/dirty status. Do not present replayed channels as separate households or Anvil latency as public-network performance. Requirements: R1.1, R2.5, R8.1–R8.4.
- [ ] **10.3 Check that security tests detect broken controls.** In an isolated copy, individually omit value from the digest, bypass authorization, permit overwrite, accept receipt status 0 and enumerate only surviving DB keys. Each must trigger a relevant behavioral test failure. Restore the correct implementation, rerun and record the catching test for each defect. Requirements: R10.2–R10.4.
- [ ] **10.4 Reconcile tracked documentation.** Update README, diagrams and report with the implemented commands, schema, trust boundary and result labels. Explain physical-truth/privacy limits, governance assumptions and protected-log alternatives. Link retained specs and curated reproducible evidence. Reconcile outdated local build-guide advice; do not copy its automatic-commit rule. Requirements: R8.4, R9.1, R10.6.
- [ ] **10.5 Gate — complete acceptance and handoff.** Run the full `make check` from a clean disposable checkout, then verify final CI evidence when available. Enforce 85% overall Python line coverage and 90% branch coverage for each critical module; inspect critical contract paths. Map every acceptance criterion to actual test/review evidence, require nonzero suites and zero required skips/xfails, confirm no secret/full dataset/database is tracked, and report any remaining failures. Keep specs in the repository. Requirements: R1.4, R8.4, R9.1–R9.5, R10.1–R10.6.

## Evidence recorded when each group completes

Copy this block under the completed group or link a tracked evidence note:

```text
Group / date:
Changed files and reason:
Acceptance criteria / property / scenario IDs covered:
Commands and environment:
Collected / passed / failed / skipped / deselected counts:
Relevant artifacts and coverage:
Observed limitations or remaining failures:
Code revision plus dirty status:
Next group / exact next action:
```

No results have been prefilled. During implementation, failures belong in this record until resolved; changing an expectation requires an explicit requirement/design decision, not merely a desire for a green test.

## Deferred work, not part of acceptance

A protected-log comparison, Merkle batching, additional meter channels/intervals, meter-origin signatures, a dashboard and multi-party deployment need separately agreed requirements and tests. They are not hidden prerequisites to completing the ten groups above.
