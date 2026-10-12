"""Blockchain plumbing: connect, load the contract, sign and send. [provided]

Your code in aggregator.py, verifier.py and the attack tests calls these
helpers. They hide web3 boilerplate, not project logic.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from web3 import Web3
from web3.contract import Contract


@dataclass(frozen=True)
class TxResult:
    tx_hash: str
    gas_used: int
    seconds: float      # wall-clock time from send to mined receipt
    status: int         # 1 = success, 0 = reverted


def connect(rpc_url: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"No node at {rpc_url}. Is Anvil running? (make chain)")
    return w3


def load_contract(w3: Web3, address: str, artifact_path: Path) -> Contract:
    """Load the deployed registry using the ABI that `forge build` writes."""
    if not address:
        raise ValueError("CONTRACT_ADDRESS is empty. Run `make deploy` and copy the address into .env")
    if not Path(artifact_path).exists():
        raise FileNotFoundError(f"{artifact_path} not found. Run `make build` first.")
    abi = json.loads(Path(artifact_path).read_text())["abi"]
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


def send_tx(w3: Web3, contract_fn, private_key: str) -> TxResult:
    """Sign a contract call with private_key, send it, and wait for the receipt.

    Example:
        send_tx(w3, contract.functions.commit(key, digest), settings.aggregator_key)

    If the contract would revert (wrong role, already committed), web3 raises
    web3.exceptions.ContractLogicError while estimating gas, before anything is
    sent. Your attack tests should expect that exception.
    """
    account = w3.eth.account.from_key(private_key)
    tx = contract_fn.build_transaction(
        {"from": account.address, "nonce": w3.eth.get_transaction_count(account.address)}
    )
    signed = account.sign_transaction(tx)
    start = time.perf_counter()
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    seconds = time.perf_counter() - start
    return TxResult(tx_hash.hex(), int(receipt["gasUsed"]), seconds, int(receipt["status"]))
