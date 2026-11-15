# Tasks 8–10 audit — 2026-11-15

The reviewed implementation passes its local verification gate after three confirmed reporting/test-harness defects were corrected. The retained real-data results reproduce exactly. This is a source review plus regression, property, integration and mutation verification, not a proof that every defect is excluded. Final release acceptance remains pending current CI and refreshed diagram PNGs.

## Findings and fixes

| ID | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| C01 | Medium | Rejected preflight/broadcast calls, ordinary confirmed resumes, and several reconciliation outcomes updated journal/counts without exporting CSV evidence. Evaluation of CSV alone could omit failures or uncertainty. | Added explicit rejected/reconciled/reconciliation-outcome rows, preserving journal-before-export ordering. Unknown gas and timing remain blank; ordinary resume adds no send-to-receipt measurement. |
| C02 | Medium | Truncated/overlong CSV rows and unknown verdicts were accepted. For example, an A1 verdict typo could disappear from the detection denominator while another detected A1 made the rate appear perfect. | Reject malformed CSV row widths and invalid/missing outcome verdicts with actionable errors. Existing valid results retain identical metrics. |
| C03 | Medium | The older 23-control runner treated collection errors as caught mutations and did not require a genuinely passing baseline for missing/empty tests. | Require exit 0 with nonzero passing tests and no skips/xfails before mutation; require exit 1 with the named FAILED test to count a caught control. Other errors are explicit ERROR results. |

Regression evidence: seven export cases, three evaluation cases and four harness cases were added (14 tests). Export/evaluation failures were observed before fixes. The harness tests reproduced collection-error false positives and missing/empty baseline acceptance; its collection-error baseline refusal already passed. An initial preflight test used the wrong exception constructor, was corrected, and then failed on the actual missing export before the implementation fix. The existing duplicate-ingestion test now expects a commit plus a reconciliation row rather than omitting resume evidence.

## Verification

`make check VENV=/private/tmp/smart-meter-venv-312 REPORT_DIR=/private/tmp/smart-meter-audit15-verified` exited 0 on macOS, Python 3.12.14, Foundry 1.9.0 / Solidity 0.8.24:

- 257 fast tests passed; 44 chain tests intentionally deselected.
- 20 contract tests passed, including 256 fuzz cases and 128 invariant runs at depth 32.
- 44 isolated-chain tests passed; 257 fast tests intentionally deselected.
- Zero failed or skipped required tests. Ruff, formatting, build, report guards and branch gate passed. Combined coverage is 92%; real-data orchestration remains covered by recorded manual execution rather than automated coverage.
- Five required deliberate defects were caught in a disposable source copy, with baseline/restoration checks. All 23 older controls also passed under the corrected runner in a disposable copy. Working source was not mutated by these runs.
- Recomputed each of the three retained run summaries and pooled metrics from the final November 14 CSVs: exact matches. Both full original source CSV SHA-256 values still match the data dictionary. Historical evidence was preserved, not relabelled as a new real-data replay.
- `git diff --check` passed.

See [verification summary](evidence/2026-11-15-audit/summary.json), [full gate log](evidence/2026-11-15-audit/check.txt), [five controls](evidence/2026-11-15-audit/required-controls.json), and [23 controls](evidence/2026-11-15-audit/legacy-controls.txt). The audited base is `4a92c82` with uncommitted work. No commit, push or merge was performed.

## Remaining limitations

Current remote CI cannot validate the uncommitted changes. The three PNG diagram exports still predate their corrected Mermaid sources; use the `.mmd` sources until the PNGs are regenerated (no Mermaid renderer is installed in this environment). The prior clean-disposable-checkout evidence predates these audit fixes; this audit reran the full gate in the working copy, not a second clean installation. Python still uses the previously documented temporary environment/runtime-cache interpreter. None of these limitations is represented as a passing acceptance result.

Evaluation counts observations/log rows; repeated resume observations are not new commits. The demonstration chains are disposable, their operator also controls the manifest, and a VERIFIED result establishes agreement with a commitment rather than physical truth. The earlier real-data timings remain historical measurements of their recorded code snapshot.
