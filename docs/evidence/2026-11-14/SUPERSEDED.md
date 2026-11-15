# Superseded evidence

This folder is superseded by [2026-11-14-final](../2026-11-14-final/). Do not cite it.

Its `evaluation.json` was produced by an evaluator that counted log rows as `records` and reported commit rows as an empty-string outcome. The evaluator now reports `rows`, per-event counts and outcomes only for rows that carry a verdict, and the real-data runs were repeated with that code. Detection, false-alarm and rejection results, gas and the projection are unchanged; only timings differ, as expected for a fresh run.
