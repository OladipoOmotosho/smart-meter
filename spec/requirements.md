# Requirements: Smart-meter integrity auditing

Status: implementation specification; acceptance is not yet demonstrated.  
Reviewed against the repository on 2026-10-15.  
Companion documents: [Design](design.md) · [Tasks](tasks.md)

## 1. Purpose

Build a local, reproducible experiment that stores smart-meter readings in SQLite, commits a fingerprint of each reading to a smart contract, and later checks whether the stored record still matches that fingerprint. A fingerprint is a short representation of the record's exact contents. Changing the contents should change the fingerprint.

The project addresses retrospective data integrity within the course topic **Blockchain in Smart Grid Security**. It must demonstrate both what this mechanism detects and what it cannot detect. The research question is: **Under the stated trust assumptions, which changes to stored meter records can this design reveal, and what processing and blockchain overhead does it introduce?**

The three-file format retains the reference template's user stories, acceptance criteria, design properties and dependency-ordered tasks. All requirements and task statuses below refer to this project. No completion claims are inherited from the reference project.

## 2. Scope and trust boundary

### Required scope

- One AMPds2 whole-house channel, converted into hourly energy readings using a documented method; smaller synthetic fixtures for automated tests.
- Python pipeline, local SQLite storage, SHA-256 fingerprints, Solidity registry and local Anvil chain.
- Authorized submissions, one immutable commitment per record key, read-only audits, reproducible attack experiments and measurements.
- Explicit handling of bad input, deleted records, interrupted submissions, repeat runs and unavailable dependencies.
- Source documentation, runnable setup, automated checks and an evidence-based report.

### Deferred extensions

Merkle batching, a conventional protected-log implementation, multi-organization deployment, meter-signed measurements, dashboards, public-chain deployment, billing, demand-response control, trading and privacy-preserving protocols are not prerequisites for this prototype. A comparison with a protected log would strengthen the research question, but implementing it requires a separate scope decision. The required report must still explain why an independent reference matters and where blockchain adds little value.

### Assumptions and limits

1. The aggregator is trusted to select and transform the intended readings before commitment. A compromised aggregator can submit a false value for a new key.
2. The attacker in the main experiment can edit or delete SQLite readings after commitment, but cannot rewrite the chain or the independent expected-key manifest.
3. The auditor uses the intended registry, ABI, serialization version and chain instance. If that context cannot be established, the audit fails with an operational error.
4. Anvil is controlled by the experiment operator. The experiment does not demonstrate decentralized governance, resistance to chain resets, public-chain finality or utility-scale deployment.
5. A hash match demonstrates consistency with a reference, not physical truth, confidentiality, legal identity or recovery of lost values. A mismatch establishes inconsistency; it does not establish intent.
6. A local manifest helps discover deleted records only while it remains independent of the attacked readings table. Losing or rewriting every reference is outside the claim.
7. AMPds2 channels belong to one household. Replaying additional channels or copying records does not create evidence from independent households.

## 3. Glossary and operator journey

| Term | Meaning |
| --- | --- |
| Reading | Meter ID, UTC interval start, integer energy in Wh, unit and sequence number |
| Record key | SHA-256 of the reading's identity: meter ID and interval start |
| Digest / fingerprint | SHA-256 of the versioned, canonical representation of all reading fields |
| Canonical bytes | One explicitly specified byte representation for the same record |
| Commitment | Digest, submitter account and block timestamp stored by the registry |
| Manifest | Run context and expected reading keys kept outside the readings table |
| Confirmed | A successful local receipt and matching registry entry have been observed |
| Operational error | An audit or submission could not be completed reliably |

Operator journey: **document data → prepare tools → validate and transform a bounded sample → deploy a fresh registry → ingest → audit clean records → run isolated attack scenarios → inspect results and limitations**. Resuming an interrupted run preserves its context; starting a new run uses a new run directory and registry.

## 4. Requirements and acceptance criteria

Each criterion has a stable identifier. SHALL identifies required behavior; extensions are explicitly deferred above. The traceability matrix in `design.md` connects every requirement to tests and tasks.

### R1 — Document and select the dataset

**User story:** As a student, I want to know exactly what each selected column means so that my experiment uses the right quantities and can be reproduced.

- **R1.1** Before real-data ingestion, the project SHALL record source title, DOI/URL, dataset version when available, local file name, SHA-256 file checksum, retrieval date if known, relevant usage terms and the selected time window. Unknown metadata SHALL be labelled unknown rather than invented.
- **R1.2** The data dictionary SHALL identify the exact header names, meter identity, source unit, timestamp convention, sampling interval, imputation markers and source locations supporting those interpretations. A header alone SHALL NOT establish a unit.
- **R1.3** The initial source adapter SHALL support the existing `data/raw/Electricity_WHE.csv` using `unix_ts` and `P`, subject to source confirmation of their interpretation. The alternative `Electricity_P.csv` has `UNIX_TS` and `WHE`; using it SHALL require an explicit adapter selection rather than silent column guessing.
- **R1.4** Original source files SHALL remain unchanged. Generated files SHALL use separate paths. Full datasets, private keys and generated databases SHALL remain untracked; small original synthetic fixtures SHALL be tracked.
- **R1.5** If the unit, timestamp or selected quantity cannot be confirmed, real-data ingestion SHALL stop with a specific explanation. Synthetic tests may continue.

### R2 — Transform samples into unambiguous readings

**User story:** As an evaluator, I want deterministic conversion so that parsing mistakes are not mistaken for tampering.

- **R2.1** The loader SHALL use explicit headers, parse Unix seconds as UTC and preserve an imputation marker before numeric conversion. Selected rows with invalid timestamps, missing/non-finite values or a wrong source schema SHALL produce a source-location error.
- **R2.2** The initial replay SHALL use complete, UTC-aligned, half-open hourly intervals. Each included interval SHALL contain exactly 60 distinct, one-minute samples. Duplicate timestamps, out-of-order rows, internal gaps and unsupported negative power SHALL fail validation. Incomplete leading/trailing intervals SHALL be excluded and counted; an empty result SHALL fail.
- **R2.3** Once source units are confirmed as watts, the adapter SHALL estimate interval energy as the exact sum of 60 one-minute power samples divided by 60, then round once to integer Wh using round-half-up. It SHALL document that this is an estimate under a constant-power-per-minute assumption, not silently substitute cumulative energy or relabel W as Wh.
- **R2.4** Each reading SHALL have a nonempty meter ID, canonical UTC timestamp, nonnegative integer `value_wh`, unit `Wh` and nonnegative integer `seq`. Boolean values SHALL NOT pass as integers. Sequences SHALL be deterministic from the first retained interval of the fixed run selection; resume SHALL NOT renumber records.
- **R2.5** A positive limit SHALL cap emitted intervals deterministically. The run manifest SHALL record the actual selected range, interval length, imputation counts, excluded boundary samples, rounding rule and any accepted processing choices. The loader SHALL avoid loading the full dataset merely to emit a small bounded sample.
- **R2.6** Unsupported interval lengths or conversion modes SHALL be rejected until separately specified. A given registry/run SHALL use one fixed conversion configuration; changing it SHALL require a new run context.

### R3 — Canonical representation and identity

**User story:** As an auditor, I want an independent recomputation to produce the same digest for the same record.

- **R3.1** The serializer SHALL follow the exact versioned UTF-8 JSON-array format in `design.md`, with fixed field order, separators and encoding. All five reading fields SHALL be covered by the digest.
- **R3.2** `digest` and `record_key` SHALL return the 32-byte SHA-256 outputs of their specified byte representations. The record key SHALL include only identity fields and its domain/version prefix; edits to value, unit or sequence SHALL NOT change that identity.
- **R3.3** Serialized representations SHALL distinguish field boundaries and types, including quotes, separators and backslashes. There SHALL be no implicit trimming, local-time conversion, float formatting or Unicode normalization in the serializer.
- **R3.4** Tests SHALL include literal canonical byte vectors and independently derived expected digest/key values, not only comparisons between calls to the same implementation. Tests SHALL NOT claim to prove SHA-256 collision resistance.

### R4 — Controlled, immutable registry

**User story:** As an auditor, I want a stable reference that an unauthorized writer cannot create or replace.

- **R4.1** Deployment SHALL grant `DEFAULT_ADMIN_ROLE` to the chosen nonzero administrator. Administrator status alone SHALL NOT imply `AGGREGATOR_ROLE`.
- **R4.2** Only an account with `AGGREGATOR_ROLE` SHALL be allowed to commit. Unauthorized calls SHALL revert without changing storage or emitting a successful commitment event.
- **R4.3** The registry SHALL reject an all-zero digest and every attempt to reuse an occupied record key, including the same digest, a different authorized aggregator or the administrator. Zero-digest rejection is an API convention, not a mathematical assertion about SHA-256.
- **R4.4** A successful commit SHALL store the exact digest, caller and block timestamp, and emit exactly one correctly populated `Committed` event. Unknown keys SHALL report absence consistently through both query functions.
- **R4.5** The administrator SHALL be able to grant and revoke the aggregator role. Unauthorized role changes SHALL fail. Revocation SHALL prevent future writes without changing previous commitments; the contract SHALL offer no update/delete path for existing commitments.
- **R4.6** The deployment record SHALL contain chain ID, registry address, deployment transaction/block identity, runtime-code hash, contract/tool versions and authorized role addresses, excluding private keys.

### R5 — Off-chain persistence and interrupted ingestion

**User story:** As an operator, I want failed or repeated ingestion to preserve evidence and report what actually happened.

- **R5.1** Validated readings SHALL round-trip through SQLite without changing hashed fields. `(meter_id, interval_start)` SHALL remain unique. Production ingestion SHALL never overwrite a conflicting reading to make a retry succeed.
- **R5.2** The pipeline SHALL durably record each intended key and digest before submission, then distinguish prepared, submitted, confirmed, failed and uncertain states. SQLite and blockchain SHALL NOT be described as a single atomic transaction.
- **R5.3** A new commitment SHALL count as confirmed only after a receipt with success status and an exact matching registry entry are observed. A reverted receipt, submission exception or timeout SHALL NOT increment success counts.
- **R5.4** Resume SHALL reconcile the persisted intent, current stored record and registry state. An existing identical commitment may be recognized without another write; a different digest or changed reading SHALL stop with a conflict. An ambiguous in-flight transaction SHALL be reconciled before another submission.
- **R5.5** Logs SHALL distinguish new confirmations from previously confirmed/reconciled records. A logging failure after a successful transaction SHALL surface as an error without pretending the on-chain write was undone or sending it again blindly.
- **R5.6** The ingestion path SHALL be single-writer for this prototype. A second writer or incompatible run configuration SHALL fail clearly rather than race for sequence numbers, nonces or state.

### R6 — Explainable audits, including deletion

**User story:** As an auditor, I want the result to distinguish disagreement, missing evidence and an inability to check.

- **R6.1** With a readable record and matching commitment, the audit SHALL return `VERIFIED`. With a readable record and different digest, it SHALL return `TAMPERED`, explained as a fingerprint mismatch rather than proof of malicious intent.
- **R6.2** With a record but no commitment, the audit SHALL return `MISSING_COMMITMENT`; with a commitment but no record, `MISSING_RECORD`; with neither, `MISSING_BOTH`. These SHALL be distinct from a failed audit.
- **R6.3** Unavailable RPC, invalid/missing deployment context, malformed chain response, corrupt stored fields or database read failure SHALL produce `ERROR` with a reason. No such error SHALL be converted into `VERIFIED`, a missing-evidence verdict or `TAMPERED`.
- **R6.4** Auditing a run SHALL use the persisted expected-key manifest, not only the surviving SQLite rows. Deleting or re-keying a committed row SHALL therefore leave an auditable missing-record case. Discovery of arbitrary extra records is outside this completeness claim.
- **R6.5** Audits SHALL require no signing key, send no transactions and leave readings and registry state unchanged. Audit results may be written to their separate results file.
- **R6.6** Each result SHALL include run ID, identity/key, outcome, reason, expected/observed digest where available, registry context and duration. A manifest/deployment validation error SHALL abort the run audit instead of reporting all records as missing.

### R7 — Reproducible security scenarios

**User story:** As a reviewer, I want experiments that could expose a broken security control, including a successful attack outside the claimed boundary.

- **R7.1** The required clean control SHALL ingest and audit unchanged records as `VERIFIED`.
- **R7.2** A1 SHALL alter the stored value after commitment and require `TAMPERED`, while checking that the original registry entry remains unchanged.
- **R7.3** A2 SHALL submit from an unauthorized account and require the specific authorization failure plus unchanged state.
- **R7.4** A3 SHALL attempt replacement with an authorized account and require the specific duplicate-key failure plus unchanged original digest, submitter and timestamp.
- **R7.5** A4 SHALL alter a value before both storing and committing it, and require `VERIFIED`. The report SHALL count this as an expected limit, never as successful detection or a defect to conceal.
- **R7.6** Additional required scenarios SHALL cover deleted/re-keyed records, absent commitments, revoked roles, RPC outage, reverted receipts, ambiguous submission and safe reruns. Each scenario SHALL have an independent fixture and explicit expected result.

### R8 — Measured results and defensible conclusions

**User story:** As a presenter, I want results that support exactly the claims made in the report.

- **R8.1** Results SHALL record scenario ID, expected/actual outcome, pass/fail, counts, gas from real receipts, separate submission-to-receipt and audit timings, and failed/uncertain operations. Unmeasured values SHALL remain unavailable, never fabricated as zero.
- **R8.2** Evaluation SHALL separate post-commit mismatch detection, authorization/overwrite rejection and the pre-commit limitation. Detection rate SHALL use only eligible post-commit corruption cases; clean-control false alarms SHALL use only successfully evaluated clean cases. Errors and exclusions SHALL be reported separately with denominators; no eligible observations means `N/A`.
- **R8.3** Timing summaries SHALL report sample count, median, the specified 95th-percentile method and run conditions. Local Anvil measurements SHALL NOT be presented as public-network throughput, finality or currency cost. Scale calculations SHALL be labelled projections with their assumptions.
- **R8.4** The final report SHALL link results to source checksums, code revision plus dirty status, manifest, runtime/tool versions, deployment and commands. It SHALL describe limitations, the trusted reference owner and circumstances in which a conventional protected log could provide sufficient integrity evidence.

### R9 — Repeatable and non-destructive operation

**User story:** As a teammate, I want documented commands that work from a clean checkout without risking existing experiment data.

- **R9.1** Documented setup commands SHALL exist and dependencies SHALL be pinned in reproducible lock/revision records. Setup SHALL precede implementation tests, and confirmed dataset interpretation SHALL precede real-data ingestion.
- **R9.2** New runs SHALL use separate directories and registry instances. Resume SHALL require matching configuration and deployment context. No normal demo/test command SHALL unlink an existing user database or reset an unrelated chain.
- **R9.3** Integration tests SHALL start and stop an isolated local Anvil process they own, use temporary databases, and deploy fresh contracts. They SHALL NOT depend on a developer's running node, `.env` secrets or full dataset.
- **R9.4** CLI success SHALL mean its promised work completed. Audit commands SHALL distinguish clean success, completed audit with findings and operational failure using documented exit codes. Missing prerequisites SHALL produce actionable errors.
- **R9.5** Only throwaway local accounts SHALL be used for the demonstration. Configuration and logs SHALL exclude private keys; test configuration SHALL not fall back to personal environment files.

### R10 — Tests and engineering gates

**User story:** As a developer, I want failures to be caught before I claim a task or the project is finished.

- **R10.1** Every implementation task group SHALL end with relevant tests; bug fixes SHALL begin with a reproducing regression test. Completed tasks SHALL record commands, outcomes and limitations.
- **R10.2** Verification SHALL include example-based tests, generated property tests, contract fuzz/stateful invariant tests, real temporary SQLite integration, isolated Anvil integration and a complete synthetic end-to-end run. Mocks SHALL be used for controlled faults, not as a substitute for all real-component tests.
- **R10.3** Required checks SHALL detect zero collected tests, skipped required tests, unexpected expected-fail markers and unimplemented core paths. Explicit fast-suite deselection of chain tests is allowed only when the separate required chain job runs them.
- **R10.4** Coverage SHALL meet the design thresholds and critical branches SHALL have explicit behavioral tests. Coverage alone SHALL NOT establish correctness; deliberate broken-control checks SHALL demonstrate that key tests can fail for the intended reason.
- **R10.5** CI SHALL require formatting/lint, Python tests, contract tests and isolated integration checks. Failures SHALL block a completion claim; unavailable tools or a CI run not performed SHALL be reported honestly.
- **R10.6** Changes SHALL follow applicable setup principles: small task branches, Conventional Commits, type hints, parameterized SQL, narrow error handling, pinned dependencies and no secrets. No commit/push/merge is authorized by creating these specs. The specs SHALL remain as maintained project records.

## 5. Completion definition

The required scope is accepted when every criterion above maps to passing evidence, the clean and attack demonstrations run reproducibly, the report states the trust boundary and all task groups have completed their gates. A populated scaffold, a green suite of skipped tests, a screenshot or a high coverage percentage alone is insufficient. The specifications do not guarantee that software is bug-free; they define the evidence required for this project's claims.
