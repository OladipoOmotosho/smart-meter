"""Rerun the recorded broken-control checks (review B08, R10.4).

Each control applies one deliberate defect to a source file, runs the tests
that must catch it, and restores the file byte-for-byte (verified), even when
interrupted. A control passes only if the named test fails. A control whose
code no longer matches exactly is reported as STALE, never skipped silently.

    python scripts/broken_controls.py           # fast controls
    python scripts/broken_controls.py --chain   # also controls needing Anvil

Run with the project's virtual environment so pytest and dependencies resolve.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"


@dataclass(frozen=True)
class Control:
    name: str
    file: str  # relative to the repository root
    edits: tuple[tuple[str, str], ...]  # exact (old, new) replacements
    test: str  # pytest node id relative to pipeline/
    chain: bool = False


AGG = "pipeline/smart_meter/aggregator.py"
CHAIN = "pipeline/smart_meter/chain.py"
DB = "pipeline/smart_meter/db.py"
RUNS = "pipeline/smart_meter/runs.py"

CONTROLS = (
    # Task 6.2: transaction classification
    Control(
        "receipt timeout reported as failure",
        CHAIN,
        (
            (
                'TxState.UNCERTAIN, f"no receipt within {timeout}s")',
                'TxState.REVERTED, f"no receipt within {timeout}s")',
            ),
        ),
        "tests/test_transactions.py::test_receipt_timeout_is_uncertain_not_failed",
    ),
    Control(
        "lost broadcast response escapes",
        CHAIN,
        (
            (
                'return TxResult(*ident, TxState.UNCERTAIN, f"broadcast response lost: {error}")',
                "raise",
            ),
        ),
        "tests/test_transactions.py::test_lost_broadcast_response_is_uncertain_and_not_resent",
    ),
    Control(
        "pending refusal treated as rejection",
        CHAIN,
        (("if known.reason == UNKNOWN:", "if known.state is TxState.UNCERTAIN:"),),
        "tests/test_transactions.py::test_refusal_for_already_known_transaction_waits_for_its_receipt",
    ),
    Control(
        "replacement detection disabled",
        CHAIN,
        (
            (
                'consumed = w3.eth.get_transaction_count(sender, "latest") > nonce',
                "consumed = False",
            ),
        ),
        "tests/test_transactions.py::test_lookup_classifies_mined_pending_unknown_and_replaced",
    ),
    Control(
        "latest instead of pending nonce",
        CHAIN,
        (
            (
                '"nonce": w3.eth.get_transaction_count(sender, "pending"),',
                '"nonce": w3.eth.get_transaction_count(sender, "latest"),',
            ),
        ),
        "tests/test_transactions.py::test_prepare_uses_pending_nonce_for_serial_sends",
    ),
    # Task 6.4: ABI tied to verified code
    Control(
        "ABI selectors not checked against code",
        CHAIN,
        (
            (
                "if bytes(Web3.keccak(text=signature)[:4]) not in code:",
                "if False:",
            ),
        ),
        "tests/test_deployment.py::test_code_with_event_but_missing_selector_is_rejected",
    ),
    # Task 7.1: journal
    Control(
        "migration statements autocommit",
        DB,
        (
            (
                '            conn.execute("BEGIN IMMEDIATE")\n            for statement in statements:',
                "            for statement in statements:",
            ),
            (
                '            conn.execute("COMMIT")\n        except sqlite3.Error',
                "        except sqlite3.Error",
            ),
        ),
        "tests/test_journal.py::test_failed_migration_rolls_back_completely",
    ),
    Control(
        "prepare without transaction",
        DB,
        (
            (
                "    with _Transaction(conn):\n        existing = get_reading(",
                "    if True:\n        existing = get_reading(",
            ),
        ),
        "tests/test_journal.py::test_failed_intent_insert_does_not_leave_the_reading",
    ),
    Control(
        "CONFIRMED not terminal",
        DB,
        (
            (
                "    SubmissionState.CONFIRMED: frozenset(),",
                "    SubmissionState.CONFIRMED: frozenset({SubmissionState.SUBMITTED}),",
            ),
        ),
        "tests/test_journal.py::test_invalid_transitions_are_rejected_and_change_nothing",
    ),
    Control(
        "reading conflict ignored",
        DB,
        (
            (
                "        if existing is not None and existing != reading:",
                "        if False:",
            ),
        ),
        "tests/test_journal.py::test_conflicting_prepare_changes_nothing",
    ),
    # Task 7.2: manifests and lock
    Control(
        "resume ignores deployment",
        RUNS,
        (
            (
                '            "deployment",\n            "expected_records",',
                '            "expected_records",',
            ),
        ),
        "tests/test_runs.py::test_incompatible_resume_is_refused_and_changes_nothing",
    ),
    Control(
        "writer lock is a no-op",
        RUNS,
        (
            (
                "            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)",
                "            pass",
            ),
        ),
        "tests/test_runs.py::test_second_writer_in_process_is_rejected_until_release",
    ),
    Control(
        "prepared run can be overwritten",
        RUNS,
        (
            (
                '        if paths.manifest.exists():\n            raise RunError(f"run {paths.root.name} already prepared; resume it instead")\n',
                "",
            ),
            (
                "        os.link(temporary, path)",
                "        os.replace(temporary, path)\n        temporary.write_bytes(b'')",
            ),
        ),
        "tests/test_runs.py::test_existing_run_is_never_reprepared",
    ),
    # Task 7.3 / 7.4: ingestion and recovery
    Control(
        "reconciliation skipped",
        AGG,
        (("    if not run.reconcile():\n        return run.counts.summary()\n", ""),),
        "tests/test_ingestion.py::test_resume_reconciles_mined_transaction_without_resending",
    ),
    Control(
        "success confirmed without registry check",
        AGG,
        (
            (
                '            if _registry_digest(self.contract, sub.record_key) != sub.digest:\n                evidence["reason"]',
                '            if False:\n                evidence["reason"]',
            ),
        ),
        "tests/test_pipeline_core.py::test_mismatching_confirmation_never_confirms",
    ),
    Control(
        "uncertain counted as confirmed",
        AGG,
        (
            (
                "            self._outcome(sub, SubmissionState.UNCERTAIN, **evidence)\n            self.counts.uncertain += 1\n            return False",
                "            self._outcome(sub, SubmissionState.CONFIRMED, **evidence)\n            self.counts.newly_confirmed += 1\n            return True",
            ),
        ),
        "tests/test_recovery.py::test_p8_faults_never_confirm_and_resume_commits_each_key_once",
    ),
    Control(
        "re-sign instead of identical rebroadcast",
        AGG,
        (
            (
                "                prepared = chain.PreparedTx(\n                    last.tx_hash, last.sender, last.nonce, last.raw_tx\n                )",
                "                prepared = chain.prepare_tx(\n                    self.w3, self.contract.functions.commit(sub.record_key, sub.digest), self.signing_key\n                )",
            ),
        ),
        "tests/test_ingestion.py::test_resume_rebroadcasts_identical_transaction_unknown_to_node",
    ),
    Control(
        "retry of FAILED cannot reconcile (review B01)",
        AGG,
        (
            (
                "        if stored == expected:  # PREPARED, or FAILED under an explicit retry",
                "        if stored == expected and sub.state is SubmissionState.PREPARED:",
            ),
        ),
        "tests/test_ingestion.py::test_retry_of_failed_record_reconciles_matching_commitment",
    ),
    Control(
        "integration runner forwards the environment",
        "scripts/run_integration.py",
        (
            (
                '        env = {\n            "PATH"',
                '        env = {\n            **os.environ,\n            "PATH"',
            ),
        ),
        "tests/test_fixtures.py::test_runner_passes_no_rpc_url_or_keys",
    ),
    # Controls that need the owned Anvil (--chain)
    Control(
        "chain ID not checked",
        CHAIN,
        (("    if chain_id != context.chain_id:", "    if False:"),),
        "tests/test_deployment.py::test_wrong_context_is_rejected_for_audit",
        chain=True,
    ),
    Control(
        "runtime code hash not checked",
        CHAIN,
        (
            (
                "    if _hex(Web3.keccak(code)) != context.runtime_code_hash:",
                "    if False:",
            ),
        ),
        "tests/test_deployment.py::test_replaced_runtime_code_is_rejected",
        chain=True,
    ),
    Control(
        "signer not checked",
        CHAIN,
        (("        if signer != context.aggregator:", "        if False:"),),
        "tests/test_deployment.py::test_writer_must_be_recorded_aggregator_with_current_role",
        chain=True,
    ),
    Control(
        "snapshot not reverted",
        "pipeline/tests/conftest.py",
        (
            (
                '        if _rpc(w3, "evm_revert", snapshot) is not True:',
                "        if False:",
            ),
            ("        if w3.eth.block_number != baseline:", "        if False:"),
        ),
        "tests/test_fixtures.py::test_each_chain_test_starts_from_a_reverted_snapshot",
        chain=True,
    ),
)


def _run_test(node_id: str, chain: bool) -> tuple[bool, str]:
    marker = "chain" if chain else "not chain"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            node_id,
            "-m",
            marker,
            "-q",
            "-x",
            "-p",
            "no:cacheprovider",
        ],
        cwd=PIPELINE,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    caught = result.returncode == 1 and ("failed" in output or "error" in output)
    return caught, output


def run_control(control: Control) -> str:
    path = ROOT / control.file
    original = path.read_bytes()
    text = original.decode()
    for old, _new in control.edits:
        if text.count(old) != 1:
            return "STALE"
    mutated = text
    for old, new in control.edits:
        mutated = mutated.replace(old, new)
    try:
        path.write_text(mutated)
        caught, _output = _run_test(control.test, control.chain)
    finally:
        path.write_bytes(original)
    if path.read_bytes() != original:
        return "RESTORE-FAILED"
    return "CAUGHT" if caught else "SURVIVED"


def main(argv: list[str]) -> int:
    with_chain = "--chain" in argv
    selected = [c for c in CONTROLS if with_chain or not c.chain]
    # The unmutated selection must pass first, or results would be meaningless.
    baseline_failed = []
    for control in selected:
        failed_unmutated, _output = _run_test(control.test, control.chain)
        if failed_unmutated:
            baseline_failed.append(control.test)
    if baseline_failed:
        print("Baseline tests must pass before running controls:", file=sys.stderr)
        for test in sorted(set(baseline_failed)):
            print(f"  {test}", file=sys.stderr)
        return 1
    problems = 0
    for control in selected:
        verdict = run_control(control)
        problems += verdict != "CAUGHT"
        print(f"{verdict:15} {control.name}  [{control.test}]")
    print(f"{len(selected) - problems}/{len(selected)} controls caught")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
