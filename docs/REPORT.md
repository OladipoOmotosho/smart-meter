# Smart-meter integrity experiment

This prototype detects changes to stored meter readings relative to an append-once reference, under a trusted aggregator and independent-manifest assumption. It does not establish truthful measurements, confidentiality, independent governance, public-chain finality, or novelty for hashing and anchoring data.

## Reproducible evidence

The November 14 evaluation is in [evaluation.json](evidence/2026-11-14-final/evaluation.json). It records revision 4a92c82 with local changes, module checksums, tool versions, exact command and before/after checksums of both original datasets. Each run directory contains its deployment manifest, expected identities, raw commitment results and raw audit results. No private keys, raw source dataset or databases are included. The source interpretation, attribution and unknown retrieval date are in [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

The selection is one AMPds2 whole-house channel, 24 complete hours from 2012-04-01 07:00 UTC through 2012-04-02 07:00 UTC. One-minute watts are integrated as exact sum/60, then rounded once half-up to Wh, assuming constant power within each minute. Each run processed 1,440 rows with zero imputed samples and zero incomplete boundaries. The three runs replay the same household; they are not three households.

## Observations

All three independent local nodes/registries confirmed 24 readings and audited all 24 as VERIFIED: 72/72 clean readings overall. Each same-run resume reconciled 24 entries with no new transaction. Both original CSV checksums were unchanged.

The independent scenario campaign had 12 expected results: S0, A1–A4, S5, two S6 missing-evidence cases, S7–S10. All matched. Post-commit detection was 2/2 eligible scenario cases (A1 value change and S5 deletion). Clean-control false alarms were 0/1 eligible S0 scenario case. Authorization/overwrite/revocation rejection was 3/3. These are small, deterministic behavioral checks; they are not population estimates. A4 returned VERIFIED and is counted separately as a pre-commit limitation. S8's injected corrupt record returned ERROR; errors are excluded from detection/false-alarm denominators, even when expected by a scenario. The 72 clean replay audits are reported separately from the scenario denominator.

For 72 successful commitments, pooled send-to-receipt latency had median 0.0009905 s and nearest-rank p95 0.001458 s. The 72 per-record audits had median 0.0020055 s and p95 0.002374 s. Median and p95 gas were 72,577 per successful commitment. See the JSON for each run's n, median and p95. These values describe this local serial Anvil execution only; load, hardware, instrument overhead and sample size limit generalization.

Commit timing starts immediately before broadcast and ends when a successful receipt is observed; it excludes source parsing, signing and gas estimation. Reconciliation is excluded because it observes no new send-to-receipt interval. Audit timing covers SQLite lookup, hashing and registry read; context validation is recorded separately. Unknown gas/timing is blank in CSV and null in JSON. p95 is sorted observation at ceil(0.95*n), not interpolation.

A hypothetical 1,000-meter hourly deployment would require 24,000 transactions/day and 1,741,848,000 gas/day at the observed median gas. This arithmetic projection is not tested throughput, a currency estimate or a supported scale claim. A 15-minute projection is hypothetical; the loader supports only 60-minute intervals.

## Trust and limitations

Changing an on-disk record after commitment causes a digest mismatch; deleting/re-keying it remains visible because audits enumerate the independent expected-key manifest. Corrupt fields, unavailable RPC and invalid deployment context are operational errors. Audit uses a fixed chain block and read-only SQLite snapshot and sends no transactions.

An attacker controlling both data and a neighboring stored hash can rewrite both. A separately protected append-only log could supply the same independent-reference property. Blockchain can be useful when independently governed participants need a shared reference, but this Anvil operator can reset the chain and also controls the manifest. Administrator compromise can grant new writers, although existing commitments remain append-once through the contract ABI. Hashes offer no encryption and low-entropy readings may be guessable. Pre-commit alteration, meter authenticity, chain-finality engineering, public deployment, batching and a comparative log implementation remain outside scope.

The retained CSV/manifests are evidence artifacts; the disposable evaluation chains stop on completion. Rerunning produces fresh chain identities and timings. The initial mutation harness selected zero Solidity tests and therefore did not establish those controls; [verified controls](evidence/2026-11-14-final/controls-verified/summary.json) records the corrected named-test run.

## Implementation audit follow-up — 2026-11-15

The [Tasks 8–10 audit summary](AUDIT_SUMMARY.md) records three corrected defects: missing rejection/resume exports, acceptance of malformed evaluation evidence, and false-positive handling in the older mutation runner. The updated code passes 257 fast, 20 contract and 44 chain tests with 92% combined coverage; both mutation suites pass. The saved three-run metrics were independently recomputed and match exactly, and both original CSV checksums still match. The retained timing results above remain the historical November 14 measurements. Current CI and refreshed PNG diagrams remain outstanding acceptance items.
