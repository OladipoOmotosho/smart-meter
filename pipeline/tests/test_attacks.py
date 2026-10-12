"""End-to-end security tests against a live Anvil chain. [YOU + YUSUF WRITE THESE: Step 9]

These are the five tests promised in the presentation. Each one is skipped
until written. They need `make chain` running and `make deploy` done.

Tips:
  - use a fresh database per test: db.connect(":memory:")
  - use a unique meter_id per test (e.g. with uuid4) so keys never collide
    with earlier runs; the chain keeps its history until Anvil restarts
  - an expected revert raises web3.exceptions.ContractLogicError (custom
    Solidity errors arrive as its subclass ContractCustomError)
  - log each outcome with results.log(event="attack_A1", ...) for the report
"""

import pytest

pytestmark = pytest.mark.chain


def test_positive_control_clean_record_verifies():
    """Commit a reading, change nothing, verify. Expected: VERIFIED."""
    pytest.skip("Step 9: not written yet")


def test_A1_post_commit_tampering_is_detected():
    """Commit 5200 Wh, then UPDATE the stored row to 25200 Wh, verify. Expected: TAMPERED."""
    pytest.skip("Step 9: not written yet")


def test_A2_unauthorized_submission_is_rejected():
    """Commit with the attacker key. Expected: ContractLogicError (AccessControlUnauthorizedAccount)."""
    pytest.skip("Step 9: not written yet")


def test_A3_existing_fingerprint_cannot_be_replaced():
    """Commit a reading, then commit a different digest for the same key with the aggregator key.
    Expected: ContractLogicError (AlreadyCommitted), original digest unchanged."""
    pytest.skip("Step 9: not written yet")


def test_A4_boundary_change_before_commit_is_not_detected():
    """Alter the value BEFORE committing (store and commit 25200 instead of 5200), verify.
    Expected: VERIFIED. This documents the limit of the design; it is not a bug."""
    pytest.skip("Step 9: not written yet")
