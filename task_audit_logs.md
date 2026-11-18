# Task audit log

## 2026-11-07 — review of November 6–7 work

Scope: commits after `8587ff8` through `b3ece727b5ea1c2f1b35299d3fdd8787dce8e8dc` (seven commits, 38 changed files), current private specifications and recorded Task 2.5 evidence. Git dates establish the review window; Git alone does not identify which model authored each decision. This review assesses the work attributed to Sol 6.1 by the user, not the model's intentions.

Method: inspected project instructions, design/requirements, changes and current pipeline, registry, tests, CI and check scripts. The initial audit ran targeted reproductions with Python 3.12 and made no implementation changes. The correction pass then added failing regressions, implemented the supported fixes and ran the full local check. No commits or pushes were made. Findings below distinguish resolved defects, test limitations and explicitly unfinished work. P1 means fix before relying on security results; P2 means correct during the next relevant implementation group.

### A01 — ✅ VERIFIED (P1): malformed numeric storage can falsely verify

Location: `pipeline/smart_meter/db.py:58–63`, consumed by `verifier.py`; requirements R6.3 and design §4/§7.

`get_reading` applies `int()` to SQLite values before fingerprint validation. SQLite permits REAL values in these INTEGER-affinity columns. Changing stored `value_wh` from 60 to 60.9 is silently converted back to 60, hiding corruption from the hash comparison. The same issue applies to `seq`. Reproduction with an in-memory database and a controlled registry response returned `Verdict.VERIFIED` after that mutation; raw SQLite data was `(60.9, 'real')`. Expected: `ERROR` for unsupported stored types.

Attribution: the coercion was inherited, not introduced in this window. However, the newly implemented verifier relies on it, and new corruption tests only exercise a nonnumeric string. The integration decision and missed regression are within this review's scope. Fix by preserving and validating stored types before encoding; add fractional-value and fractional-sequence regressions that fail before the fix. Do not normalize corrupt values into apparently valid evidence.

Resolution (2026-11-07): database reads now require exact text and integer storage types before constructing a reading; they no longer apply lossy integer coercion. Regressions for fractional value and sequence fields failed as VERIFIED before the fix and now return ERROR through the verifier.

### A02 — ✅ VERIFIED (P2): bounded loading validates beyond the requested final hour

Location: `pipeline/smart_meter/dataset.py:70–90`; R2.5, design §3.

The loader parses and checks the next row before emitting the previous complete hour and applying `limit`. A valid 60-minute hour followed by a malformed first row of the next hour fails even with `limit=1`. Reproduction produced `ValueError: invalid P at source row 62` instead of the requested single reading. Missing-minute checks on that extra row have the same boundary problem. Emit a complete aligned hour and stop at the configured limit before consuming another row. Add a stream-consumption regression with invalid trailing data.

Resolution (2026-11-07): the loader emits immediately after the sixtieth validated sample and applies the limit before requesting another CSV row. The regression returns 60 Wh, ignores deliberately malformed trailing data and records exactly 60 consumed source rows.

### A03 — ✅ VERIFIED (P2): loader loses provenance and allows an empty transformed result

Location: `pipeline/smart_meter/dataset.py:19–36,98–101`; R2.1, R2.2 and R2.5; open Tasks 4.1–4.3.

The `+` imputation marker is stripped without retaining a flag/count. Incomplete edge hours are discarded without counts, and a nonempty file containing only a partial hour returns no readings without an error. These are observable spec gaps, not merely missing documentation. Add explicit preprocessing metadata and reject zero emitted intervals; retain source markers and exclusion counts for the manifest. Test partial-only input and imputation/exclusion accounting. The task remains open, so this is unfinished implementation rather than a falsely completed Task 4 claim.

Resolution (2026-11-07): LoadMetadata records source rows, emitted intervals, retained imputed samples, excluded boundary rows/hours and the selected half-open range. Partial-only input raises a specific no-complete-interval error while retaining exclusion counts. Decimal input is converted to exact rational values, resolving the arithmetic precision concern recorded below.

### A04 — ✅ VERIFIED (P2): ingestion's timestamp validation accepts invalid identities

Location: `pipeline/smart_meter/aggregator.py:35–40`; R2.4 and design §4.

Checking only `endswith(':00:00Z')` allows `garbage:00:00Z` and invalid calendar dates to reach persistence and signing. Empty meter IDs also pass this boundary because the serializer deliberately permits arbitrary strings. That serializer choice is sound; the aggregator must perform the stricter physical/input validation promised by the design. Add strict canonical UTC parsing and nonempty meter validation before database or chain effects, with tests asserting zero effects on rejection.

Resolution (2026-11-07): ingestion now parses and round-trips the exact canonical UTC format, enforces a whole-hour timestamp and rejects empty or whitespace meter IDs before deriving a key or touching SQLite or chain state. Regressions cover empty ID, malformed text and an impossible calendar date and assert no rows or registry entries are created.

### A05 — ✅ VERIFIED (P2): required-suite guard ignores fuzz test names

Location: `scripts/check_test_report.py:58–70` and `contracts/test/MeterCommitmentRegistry.t.sol`; R10.3–R10.5.

The parser recognizes only names beginning `test_`, but the fuzz case is `testFuzz_FirstCommitRemainsFixed`. The prior real log reports 11 Foundry passes while the guard counts only 10. A synthetic report containing all seven required named passes plus `[SKIP] testFuzz_FirstCommitRemainsFixed(bytes32,bytes32,bytes32)` returned no guard problems. Actual failing Forge tests still cause Make to fail through Forge's exit code; the specific defect is skipped/absent fuzz coverage escaping this report guard. Recognize Forge's supported test naming patterns and explicitly require the expected fuzz case; add a skipped-fuzz regression.

Resolution (2026-11-07): the guard recognizes ordinary, fuzz and invariant Foundry test names and explicitly requires testFuzz_FirstCommitRemainsFixed. Its skipped-fuzz regression failed before the fix and now rejects the report. The real contract run reports and validates all 11 cases with zero skips.

### A06 — SCHEDULED (P2): scenario names provide less assurance than the design requires

Location: `pipeline/tests/test_attacks.py` S5, S8, S9 and S10; design §9 scenario table, R7.6.

S5 supplies a known key directly after deletion; it does not prove manifest-driven completeness or re-key detection. S8 covers corrupt text, not wrong deployment context. S9 demonstrates an unauthorized status-0 transaction, not a lost response or recovery after uncertain submission. S10 creates two directory paths but ingests twice into the same fixture; it does not execute two isolated full runs. Useful tests exist, including a separate unit RPC-failure case, but matching scenario prefixes is not sufficient acceptance evidence for these broader requirements. Split each scenario into explicit behavioral cases and require those cases at the relevant final gate. Keep later tasks open until they execute.

Status (2026-11-07): no broad scenario was relabelled as complete. Tasks 6.4, 7.4, 8.3 and 9.3–9.4 remain unchecked and explicitly require deployment-context failure, uncertain submission and recovery, manifest-driven deletion and re-key audits, and isolated reruns. Implementing those architectures during this defect-correction pass would violate their dependency order. Existing scenario tests remain useful interim checks but are not final acceptance evidence.

### A07 — PARTIAL / OPEN (P2): CI repair crossed architectural task boundaries

Evidence: `75e811e` implemented dataset, ingestion and auditing; `040597a` implemented the registry; `b3ece72` added expanded scenarios while later task groups remained open. `.agent/AGENT_RULES.md` requires dependency order and one group at a time. The user authorized fixing failed checks, but that does not itself make partial implementations of several later groups complete.

Implementing real behaviors rather than weakening failing tests was a good choice. The weaker judgment was bundling broad feature work into CI repair before durable intent, deployment context and manifest boundaries existed. It created a green gate around a partial architecture and leaves more reconciliation work. Subsequent task evidence correctly acknowledges these limitations; there is no basis here to claim the author concealed them. Improve the workflow by explicitly mapping each CI repair to affected task groups, documenting interim interfaces, and reviewing each dependency before expanding scenarios. Coverage percentage should remain supporting evidence, never the completion criterion.

Resolution (2026-11-07): this correction pass maps loader changes to Tasks 4.1–4.2 and leaves wider scenario gates open. This log distinguishes resolved defects from scheduled architecture. No later task checkbox is inferred from a green suite or coverage percentage.

Verification correction (2026-11-07): the preceding process-resolution claim is only partial. The plan's next-action paragraph still points to Task 4.1 although 4.1 and 4.2 are checked. Task 4.1 evidence calls the missing LoadMetadata import a failing regression; that was a collection failure, not a behavioral reproduction of A02/A03. Their later passing tests establish current behavior but do not retroactively establish a valid red-before-green test run. The new metadata interface is also absent from the design's module contract. Reconcile these records and the interface before closing A07. This verification does not certify the broader Task 4.1 checkbox or Task 4.3 gate.

### Design assessment and explicitly deferred risks

The target architecture is appropriate for a bounded course prototype: raw readings stay in SQLite, canonical digests are anchored in an append-only role-controlled registry, and expected keys in an independent manifest permit deletion detection. Domain-separated canonical encodings, immutable first commitments, precise missing/error outcomes, and an explicit pre-commit trust limitation are sound decisions. The design correctly says that a single operator's Anvil chain and editable local manifest do not establish independent governance or physical truth. Retain that boundary in the presentation; the practical security claim depends on the attacker being unable to alter the anchor and expected-key manifest.

The implemented aggregator has no durable submission journal, writer lock or uncertain-outcome state; the auditor has no run-level deployment validation or manifest enumeration. These are already open Tasks 6–9, not newly discovered regressions or evidence of completed acceptance. Until implemented, a timeout can leave unclear progress, concurrent writers can race, and the wrong registry may produce misleading absence outcomes. Do not present happy-path reconciliation as crash-safe recovery. The proposed prepared/submitted/confirmed/failed/uncertain state model is justified by these concrete failure modes and should be kept small rather than removed for simplicity.

The arithmetic precision concern is resolved: parsed finite decimal values are converted exactly to fractions, and summation, division by 60 and half-up rounding use integer and rational operations without the decimal context.

### Areas with no identified defect in this review

- The registry checks writer authority, rejects zero digests, prevents replacement and gives the administrator no implicit writer privilege. No actionable registry logic defect was found in the inspected implementation.
- Canonical encoding includes all five fields, separates identity from content, rejects booleans/floats and uses fixed version domains. No actionable encoding defect was found.
- CI retains distinct Python, contract and integration jobs with an always-run aggregate gate. The integration runner owns its temporary Anvil process. These are sound isolation and reporting choices.
- Task 2.5's recorded clean-checkout pass is supported by the retained command output. Explicit Python-path selection is an environment prerequisite workaround, not evidence of test manipulation. Its completion does not complete later feature gates.

### Verification and remaining audit status

Prior correction-pass evidence: make check passed 72 fast tests, 11 Foundry tests including 256 fuzz runs, and 11 isolated Anvil tests, with zero required skips; reported overall Python coverage was 91%. Those are retained historical results, not a fresh full-suite run in this verification.

Independent verification (2026-11-07): inspected the current database, ingestion, loader, report guard, scenario tests and task records. From pipeline/, ran Python 3.12.14 with `-m pytest tests/test_pipeline_core.py tests/test_dataset.py tests/test_check_harness.py -q -p no:cacheprovider`: **42 passed, zero failed/skipped**, with one dependency deprecation warning. The interpreter was `/private/tmp/smart-meter-clean-Kzn8wq/repo/.venv/bin/python`; imports and tests came from the working repository. A01–A05 are checked for their specific reported defects, not for all future acceptance criteria of their containing modules.

- [x] A01 — fractional stored value and sequence both produce ERROR; no integer truncation.
- [x] A02 — requested complete hour succeeds despite malformed trailing data; 60 consumed rows confirmed.
- [x] A03 — retained imputation and boundary counts are exposed; partial-only input fails.
- [x] A04 — invalid identities fail before database or transaction effects.
- [x] A05 — skipped fuzz report is rejected; required fuzz name is explicitly enforced.
- [ ] A06 — manifest, deployment-context, uncertain-submission and full rerun scenarios remain unimplemented.
- [ ] A07 — process/documentation reconciliation remains incomplete as detailed above.

Exact rational conversion was also confirmed by code inspection. No implementation code or task checkbox was changed during this verification, and nothing was committed or pushed.

## 2026-11-12 - review of Tasks 5.4 through 7.4 (November 9-12 work)

Scope: Task 5.4 (contract gate), 6.1-6.4 (deployment context, transaction classification, owned Anvil fixtures, chain-boundary gate) and 7.1-7.4 (journal, manifests and lock, journaled ingestion, recovery gate). Pushed commits `1295896`, `f2d1532`, `14991ca`, `d9c037d`; uncommitted 6.3-7.4 changes on top of `d9c037d`. Specs and evidence in `spec/tasks.md`.

Method: re-ran `make check` (182 fast, 20 contract, 40 chain, all passing, 90% coverage, branch gate met); recounted collected tests per file against the recorded evidence (all counts match); re-read every new module against design sections 5-6; wrote two targeted reproductions against the real journal and aggregator with a fake chain. No implementation code or checkbox was changed by this review; nothing was committed.

### B01 - CONFIRMED (P2): explicit retry of a FAILED record cannot reconcile an occupied key

Location: `pipeline/smart_meter/aggregator.py` `_Run.submit` and `_conflict`; `pipeline/smart_meter/db.py` `TRANSITIONS`. Requirement R5.4; design section 6 ("if preflight finds the exact expected commitment, reconcile it ... count it as already committed").

Reproduction (fake chain, real SQLite journal): a record whose first attempt was REVERTED is FAILED. If its exact digest is later present in the registry, `ingest(..., retry_failed=True)` raises `JournalError: invalid journal transition FAILED -> FAILED` instead of reconciling. If a different digest is present, the same `JournalError` masks the intended `ConflictError`. Cause: `submit` reconciles only when `sub.state is PREPARED`, so a FAILED intent falls into `_conflict`, which unconditionally transitions to FAILED; `TRANSITIONS` has no FAILED -> CONFIRMED edge. Impact: the failure is safe (run stops, no transaction, state unchanged) but the matching case can never be confirmed through the journal and the error is wrong. Not covered: the 7.3 retry test only covers an empty registry; P8's fake never populates the registry for a FAILED key. Fix: add FAILED -> CONFIRMED to `TRANSITIONS`; in `submit`, treat `stored == expected` as reconciliation for PREPARED or FAILED; make `_conflict` skip the transition when already FAILED. Write the two regressions first.

### B02 - LOW: misleading reason for a mined receipt with an empty registry

Location: `aggregator.py` `_Run.reconcile`. If `lookup` reports a success receipt but the registry has no commitment (wrong deployment or contract), the intent is marked UNCERTAIN with reason "mined with status 1". The outcome is safe; the diagnostic is wrong. Record a distinct reason naming the registry/deployment discrepancy.

### B03 - JUDGEMENT: a defensive branch was removed under coverage pressure

Task 7.3 removed the `if sub.state in IN_FLIGHT` guard in `submit` to meet the 90% branch gate. The branch is unreachable within one pass (reconciliation settles or stops every in-flight intent first), so behavior is unchanged, but deleting a guard to satisfy a metric is the wrong direction. Prefer an explicit guard that raises `JournalError`, and accept the coverage cost or test it directly.

### B04 - PROCESS: the branch-coverage gate does not cover the modules that now hold critical logic

`scripts/check_branch_coverage.py` lists only dataset, fingerprint, aggregator and verifier. `chain.py` (deployment validation, ABI check, transaction classification), `db.py` (journal) and `runs.py` (manifest, lock) are outside the gate; `chain.py` measures 75% in the fast suite because its live paths run only under the chain marker. Those paths are exercised by chain tests and by the recorded broken-control runs, but nothing automated enforces it. Add `db.py` and `runs.py` to the gate (`runs.py` is at 88% and would need one or two tests), and either include chain-suite coverage data or document why `chain.py` is exempt.

### B05 - MAINTAINABILITY: test helpers are shared through module imports

`test_deployment.py` imports from `conftest`; `test_ingestion.py` and `test_recovery.py` import `Registry` from `test_pipeline_core`; `test_ingestion.py` imports `_deployment` from `test_runs` inside a test. `test_fixtures.py`'s isolation pair depends on file order through a module global. These work under the current `pythonpath` but are fragile under reordering or parallel runs. Move `Registry`, `FakeChain`, `Node` and the deployment-context builder into `tests/helpers.py` or fixtures, and replace the order-dependent pair with a self-contained check.

### B06 - DECISION NEEDED: resume compares the absolute source path

`runs._comparable` includes `source.path`, so a byte-identical source at a new location cannot resume a run. This is consistent with "matching configuration" but undocumented. Decide whether checksum and size are sufficient, and record the decision in design section 6.

### B07 - NITS

`db.record_attempt` clears the previous reason on resubmission; `TxState` is a `StrEnum` while `Verdict` and `SubmissionState` are `(str, Enum)`; `_Run.key` holds the signing key next to record keys. `chain.prepare_tx` does not catch `ValueError` from `from_key` on a malformed key, so a configuration error surfaces as a raw exception rather than a typed one.

### B08 - PROCESS: broken-control runs are recorded but not reproducible by command

Every mutation and its result is written in the evidence, and each file was restored byte-for-byte, but the mutations exist only in the transcript. Keep them as a small script or documented list so a later maintainer can rerun them.

### B09 - ENVIRONMENT: the Python interpreter is fragile

The earlier temporary environment was partly wiped mid-session; a fresh one was rebuilt from the lock (correct). The interpreter used is a Codex runtime cache path because `python3.12` is not on `PATH`. Install a durable 3.12 and record it in `docs/TOOLCHAIN.md`.

### B10 - NOT VERIFIED

Remote CI has not been inspected for `14991ca`/`d9c037d` (no `gh` locally) and has not run the uncommitted 6.3-7.4 changes, which alter the integration runner's environment. Local `make check` matches the CI recipe, but CI's result is unknown until pushed and inspected.

### What was done well

Real defects were found by probes and fixed regression-first (6.2 lost-response crash, 6.4 tampered ABI accepted, 7.3 double counting). Every broken-control run was restored byte-for-byte, and one mutation that survived was answered by strengthening the test, not by ignoring it. No threshold was lowered. Create-only manifest files, a crash-released `flock`, journal-before-broadcast (asserted inside the fakes), identical rebroadcast rather than re-signing, and stop-on-uncertain are the right designs. Limitations in the evidence are specific and, on re-check, accurate; recorded test counts match collection today.

### Verdict

The November 9-12 work is sound, well-tested and honestly recorded. One confirmed medium defect (B01) sits in an opt-in retry path and fails safe; it must be fixed, regression-first, before Task 9 builds resume/retry orchestration on it. The 7.3 and 7.4 checkmarks stand for the behavior their tests cover, with B01 recorded as an open limitation of R5.4 until fixed.

- [x] B01 - retry of a FAILED record with an occupied key: reconcile or raise ConflictError (regression first).
- [x] B02 - distinct reason for mined-but-missing commitment.
- [x] B03 - reinstate an explicit in-flight guard.
- [x] B04 - extend the coverage gate to db.py and runs.py; document chain.py.
- [x] B05 - move shared test fakes into helpers/fixtures; remove order dependence.
- [x] B06 - decide and document source-path strictness on resume (kept strict; documented).
- [~] B07 - nits: three fixed; enum style deliberately unchanged (see resolution).
- [x] B08 - make broken-control runs reproducible.
- [~] B09 - documented in docs/TOOLCHAIN.md; the durable install itself is left to the user.
- [x] B10 - CI inspected after push (see resolution below).

### Resolution (2026-11-12, follow-up to this review)

Every confirmed item was handled regression-first where it was a defect. Nothing was committed or pushed.

- B01: new tests `test_retry_of_failed_record_reconciles_matching_commitment` and `test_retry_of_failed_record_with_different_digest_is_a_conflict` failed first with `JournalError: invalid journal transition FAILED -> FAILED`. Fix: `db.TRANSITIONS` allows FAILED -> CONFIRMED; `submit` reconciles a matching digest for PREPARED or FAILED; `_conflict` no longer re-transitions an already-FAILED intent, so the intended `ConflictError` surfaces. Both pass, and a broken control (restricting reconciliation to PREPARED) is caught.
- B02: `test_mined_receipt_without_commitment_names_the_discrepancy` failed first (reason was "mined with status 1"). `reconcile` now records "receipt ... reports success but the registry has no commitment; check the deployment context" and keeps the intent UNCERTAIN.
- B03: the in-flight guard is back in `submit` as an explicit `JournalError`, with a direct test that drives `submit` without `reconcile`.
- B04: `scripts/check_branch_coverage.py` now gates `db.py` and `runs.py` as well; its docstring states why `chain.py` is exempt (live paths run only in the chain suite, guarded by chain tests and the broken-control script). Six error-path tests were added. Measured `db.py` 99%, `runs.py` 95%; the gate passes. One new test initially passed vacuously for the wrong reason (SQLite TEXT affinity turned the injected integer into text); it now uses a BLOB value.
- B05: `tests/helpers.py` holds `Registry` and `deployment_context`; no test imports another test module or `conftest`. `deploy_registry` is reached through a `new_registry` fixture. The order-dependent isolation pair was replaced by one self-contained test that runs an inner two-test session through the real fixtures; the "snapshot not reverted" control is caught by it.
- B06: kept strict (absolute path plus checksum and size) as a conservative default, now documented in `runs._comparable` and design section 6, including that relaxing it would not weaken integrity. User decision if it should change.
- B07: `_Run.key` renamed `signing_key`; a malformed signing key raises `PreflightError(kind="configuration")` without echoing key material and stops the run instead of counting per-record failures (tested); resubmission records "submitted <hash>" instead of clearing the reason (tested). Enum style left unchanged: converting `Verdict`/`SubmissionState` to `StrEnum` changes `str()` output used in messages, for no functional gain.
- B08: `scripts/broken_controls.py` holds 23 controls (19 fast, 4 needing Anvil with `--chain`). It checks the unmutated tests pass, applies each defect, requires the named test to fail, restores the file byte-for-byte and verifies it, and reports STALE if a control no longer matches the code. First run: 22/23 caught. The survivor was real: disabling the ABI *selector* check went unnoticed because the only test used code that also lacked the event topic. Two isolating tests were added (event present but a selector missing; all selectors but no event). Final run: 23/23 caught, sources unchanged, no Anvil left.
- B09: `docs/TOOLCHAIN.md` now says to install a durable Python 3.12 on `PATH` and not to base environments in `/private/tmp`, and records the interim interpreter. The install itself is a system change left to the user.

Verification: after `forge build --force`, `make check VENV=/private/tmp/smart-meter-venv-312 REPORT_DIR=/private/tmp/smart-meter-review` exited 0: 197 fast passed (39 deselected), 20 contract passed, 39 chain passed, zero failures or skips, report guards clean, total coverage 91%, branch gate passing for all six critical modules. `scripts/broken_controls.py --chain` exited 0 with 23/23 caught. `git diff --check` passed; no Anvil process remained.

### B10 resolution (2026-11-12)

The first CI run on the pushed 6.3-7.4 commits (run 43293897666, head `542d5ff`) **failed** in the `python` job at `make test-unit`, while `contracts` and `integration` passed. Cause, reproduced locally in a clean worktree without `contracts/out`: Task 6.4 had pointed 14 fast `test_deployment.py` tests at the compiled Foundry artifact, which the CI Python job never builds. Local runs could not show it because `contracts/out` always existed. This confirms the review's warning that a local pass is not a CI pass. Fix `4a92c82`: the fast tests use a tracked fixture (`pipeline/tests/fixtures/registry_artifact.json`, holding the real ABI and a synthetic runtime with the required selectors and topic), and a chain-suite test fails if that ABI drifts from the compiled contract. Verified locally without build output (197 passed), with the full `make check`, and with 23/23 broken controls caught. CI run 43297741522 on `4a92c82` passed all four jobs. The branch was then merged into `main` as `4c038ba` (tree identical to the branch) and pushed.

## Tasks 8–10 audit, 2026-11-15

C01–C03 fixed regression-first; details in docs/AUDIT_SUMMARY.md. Full gate: 257 fast, 20 contract, 44 chain; 92% combined coverage; 5/5 and 23/23 isolated controls caught. Existing real-data metrics independently reproduced; source checksums unchanged. CI/PNG exports remain open; 10.5 not checked. No commit/push.
