"""Blockchain-based tamper detection for stored smart meter readings.

Module map (see docs/BUILD_GUIDE.md for the build order):
    config       settings loaded from .env                    [provided]
    models       Reading and Verdict types                    [provided]
    db           SQLite "utility database"                    [provided]
    chain        web3 connection, contract loading, signing   [provided]
    results      CSV results log                              [provided]
    fingerprint  canonical bytes, record key, digest          [you, Step 1]
    dataset      AMPds2 loader                                [you, Step 5]
    aggregator   store + fingerprint + commit                 [you, Step 6]
    verifier     recompute + compare + verdict                [you, Step 7]
    demo         end-to-end run                               [provided glue]
"""
