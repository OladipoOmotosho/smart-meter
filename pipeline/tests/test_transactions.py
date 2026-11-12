"""Task 6.2: transaction outcomes are classified, never guessed (R5.2-R5.4, R7.6).

Fast cases inject faults through a minimal fake node. Chain cases use the
owned Anvil fixtures in conftest.py for a real mined revert, a real receipt timeout and a
real nonce replacement.
"""

from types import SimpleNamespace

import pytest
from eth_abi import encode
from requests.exceptions import ConnectionError as RequestsConnectionError
from smart_meter import chain
from web3 import Web3
from web3.exceptions import (
    ContractCustomError,
    TimeExhausted,
    TransactionNotFound,
    Web3RPCError,
)

THROWAWAY_KEY = "0x" + "11" * 32
SENDER = Web3().eth.account.from_key(THROWAWAY_KEY).address
OTHER = Web3.to_checksum_address("0x" + "22" * 20)
BLOCK_HASH = bytes.fromhex("ab" * 32)


class FakeCall:
    """A contract function whose preflight either builds a transaction or fails."""

    def __init__(self, error=None):
        self.error = error

    def build_transaction(self, params):
        if self.error is not None:
            raise self.error
        tx = {
            "to": OTHER,
            "data": "0x",
            "value": 0,
            "chainId": 31337,
            "maxFeePerGas": 2_000_000_000,
            "maxPriorityFeePerGas": 1_000_000_000,
            "type": 2,
        }
        tx.setdefault("gas", params.get("gas", 50_000))
        return tx | params


class FakeEth:
    def __init__(self):
        self.account = Web3().eth.account
        self.sent = []
        self.latest_nonce = 7
        self.pending_nonce = 7
        self.send_error = None
        self.receipts = {}
        self.pending = set()
        self.wait_error = None
        self.lookup_error = None

    def get_transaction_count(self, address, block="latest"):
        assert address == SENDER
        return self.pending_nonce if block == "pending" else self.latest_nonce

    def send_raw_transaction(self, raw):
        self.sent.append(bytes(raw))
        if self.send_error is not None:
            raise self.send_error
        return Web3.keccak(raw)

    def wait_for_transaction_receipt(self, tx_hash, timeout, poll_latency):
        assert 0 < timeout <= chain.DEFAULT_RECEIPT_TIMEOUT and poll_latency > 0
        if self.wait_error is not None:
            raise self.wait_error
        return self.receipts[bytes(Web3.to_bytes(hexstr=tx_hash))]

    def get_transaction_receipt(self, tx_hash):
        if self.lookup_error is not None:
            raise self.lookup_error
        key = bytes(Web3.to_bytes(hexstr=tx_hash))
        if key not in self.receipts:
            raise TransactionNotFound("not found")
        return self.receipts[key]

    def get_transaction(self, tx_hash):
        if self.lookup_error is not None:
            raise self.lookup_error
        if bytes(Web3.to_bytes(hexstr=tx_hash)) not in self.pending:
            raise TransactionNotFound("not found")
        return {"hash": tx_hash}


def _receipt(status, gas_used=48_000):
    return {
        "status": status,
        "gasUsed": gas_used,
        "blockNumber": 9,
        "blockHash": BLOCK_HASH,
    }


@pytest.fixture
def node():
    return SimpleNamespace(eth=FakeEth())


def _mine_on_send(node, status):
    original = node.eth.send_raw_transaction

    def send(raw):
        tx_hash = original(raw)
        node.eth.receipts[bytes(tx_hash)] = _receipt(status)
        return tx_hash

    node.eth.send_raw_transaction = send


# --- Preflight: nothing is broadcast ----------------------------------------


def test_contract_revert_in_preflight_preserves_error_data(node):
    error = ContractCustomError("0x1234abcd", data="0x1234abcd")
    with pytest.raises(chain.PreflightError) as caught:
        chain.send_tx(node, FakeCall(error), THROWAWAY_KEY)
    assert caught.value.kind == "revert"
    assert caught.value.data == "0x1234abcd"
    assert caught.value.sender == SENDER
    assert caught.value.__cause__ is error
    assert node.eth.sent == []


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (Web3RPCError("insufficient funds for gas"), "rejected"),
        (RequestsConnectionError("connection refused"), "unavailable"),
    ],
)
def test_node_rejection_and_outage_in_preflight_are_distinct(node, error, kind):
    with pytest.raises(chain.PreflightError) as caught:
        chain.send_tx(node, FakeCall(error), THROWAWAY_KEY)
    assert caught.value.kind == kind
    assert caught.value.data is None
    assert node.eth.sent == []


def test_malformed_key_is_a_typed_configuration_error_without_key_echo(node):
    bad = "0xnot-a-key-secret-material"
    with pytest.raises(chain.PreflightError) as caught:
        chain.prepare_tx(node, FakeCall(), bad)
    assert caught.value.kind == "configuration"
    assert "secret-material" not in str(caught.value)
    assert node.eth.sent == []


# --- Signed identity is known before broadcast ------------------------------


def test_prepared_transaction_identity_precedes_broadcast(node):
    prepared = chain.prepare_tx(node, FakeCall(), THROWAWAY_KEY)
    assert node.eth.sent == []
    assert prepared.sender == SENDER
    assert prepared.nonce == 7
    assert prepared.tx_hash == "0x" + bytes(Web3.keccak(prepared.raw)).hex()
    assert "raw" not in repr(prepared) and THROWAWAY_KEY[2:] not in repr(prepared)


def test_prepare_uses_pending_nonce_for_serial_sends(node):
    node.eth.pending_nonce = 9
    assert chain.prepare_tx(node, FakeCall(), THROWAWAY_KEY).nonce == 9


# --- Broadcast outcomes -----------------------------------------------------


def test_success_receipt_records_block_gas_and_latency(node):
    _mine_on_send(node, 1)
    result = chain.send_tx(node, FakeCall(), THROWAWAY_KEY)
    assert result.state is chain.TxState.SUCCEEDED
    assert (result.status, result.gas_used, result.block_number) == (1, 48_000, 9)
    assert result.block_hash == "0x" + BLOCK_HASH.hex()
    assert (result.sender, result.nonce) == (SENDER, 7)
    assert result.seconds is not None and result.seconds >= 0
    assert len(node.eth.sent) == 1


def test_mined_status_zero_is_reverted_with_evidence(node):
    _mine_on_send(node, 0)
    result = chain.send_tx(node, FakeCall(), THROWAWAY_KEY)
    assert result.state is chain.TxState.REVERTED
    assert (result.status, result.gas_used, result.block_number) == (0, 48_000, 9)
    assert "status 0" in result.reason


def test_receipt_timeout_is_uncertain_not_failed(node):
    node.eth.wait_error = TimeExhausted("no receipt")
    result = chain.send_tx(node, FakeCall(), THROWAWAY_KEY, timeout=0.5)
    assert result.state is chain.TxState.UNCERTAIN
    assert result.status is None and result.gas_used is None
    assert result.seconds is None
    assert "0.5" in result.reason
    assert result.tx_hash.startswith("0x") and result.nonce == 7
    assert len(node.eth.sent) == 1


def test_lost_broadcast_response_is_uncertain_and_not_resent(node):
    node.eth.send_error = RequestsConnectionError("connection reset")
    result = chain.send_tx(node, FakeCall(), THROWAWAY_KEY)
    assert result.state is chain.TxState.UNCERTAIN
    assert "response lost" in result.reason
    assert len(node.eth.sent) == 1


def test_lost_response_during_wait_is_uncertain(node):
    node.eth.wait_error = RequestsConnectionError("connection reset")
    result = chain.send_tx(node, FakeCall(), THROWAWAY_KEY)
    assert result.state is chain.TxState.UNCERTAIN
    assert "receipt" in result.reason


def test_definite_node_refusal_raises_with_identity(node):
    node.eth.send_error = Web3RPCError("nonce too low")
    with pytest.raises(chain.BroadcastRejected) as caught:
        chain.send_tx(node, FakeCall(), THROWAWAY_KEY)
    assert "nonce too low" in caught.value.reason
    assert (caught.value.sender, caught.value.nonce) == (SENDER, 7)
    assert caught.value.tx_hash.startswith("0x")


def test_refusal_for_already_known_transaction_waits_for_its_receipt(node):
    prepared = chain.prepare_tx(node, FakeCall(), THROWAWAY_KEY)
    key = bytes(Web3.keccak(prepared.raw))
    node.eth.pending.add(key)  # in the pool, no receipt yet
    node.eth.send_error = Web3RPCError("already known")
    waited = []

    def wait(tx_hash, timeout, poll_latency):
        waited.append(tx_hash)
        return _receipt(1)

    node.eth.wait_for_transaction_receipt = wait
    result = chain.broadcast(node, prepared)
    assert result.state is chain.TxState.SUCCEEDED
    assert waited == [prepared.tx_hash]
    assert len(node.eth.sent) == 1


# --- Later reconciliation by known identity ---------------------------------


def test_lookup_classifies_mined_pending_unknown_and_replaced(node):
    prepared = chain.prepare_tx(node, FakeCall(), THROWAWAY_KEY)
    key = bytes(Web3.keccak(prepared.raw))
    ident = (prepared.tx_hash, prepared.sender, prepared.nonce)

    unknown = chain.lookup(node, *ident)
    assert unknown.state is chain.TxState.UNCERTAIN and "unknown" in unknown.reason

    node.eth.pending.add(key)
    pending = chain.lookup(node, *ident)
    assert pending.state is chain.TxState.UNCERTAIN and "pending" in pending.reason

    node.eth.receipts[key] = _receipt(0)
    node.eth.latest_nonce = 8
    mined = chain.lookup(node, *ident)
    assert mined.state is chain.TxState.REVERTED and mined.seconds is None

    del node.eth.receipts[key]
    node.eth.pending.clear()
    replaced = chain.lookup(node, *ident)
    assert replaced.state is chain.TxState.REPLACED
    assert "another transaction" in replaced.reason


def test_lookup_outage_is_uncertain(node):
    node.eth.lookup_error = RequestsConnectionError("down")
    result = chain.lookup(node, "0x" + "01" * 32, SENDER, 7)
    assert result.state is chain.TxState.UNCERTAIN
    assert "lookup failed" in result.reason


# --- Real chain behavior on the runner's owned Anvil -------------------------


def _rpc(w3, method, *params):
    response = w3.provider.make_request(method, list(params))
    assert "error" not in response, response
    return response["result"]


@pytest.fixture
def registry(deployment):
    return deployment.w3, deployment.registry, deployment


@pytest.mark.chain
def test_real_success_receipt_matches_chain(registry):
    w3, contract, d = registry
    key, value = Web3.keccak(text="tx-success"), Web3.keccak(text="digest")
    result = chain.send_tx(
        w3,
        contract.functions.commit(key, value),
        d.aggregator_key,
    )
    assert result.state is chain.TxState.SUCCEEDED
    block = w3.eth.get_block(result.block_number)
    assert result.block_hash == "0x" + bytes(block["hash"]).hex()
    assert contract.functions.getCommitment(key).call()[0] == value
    assert chain.lookup(w3, result.tx_hash, result.sender, result.nonce).state is (
        chain.TxState.SUCCEEDED
    )


@pytest.mark.chain
def test_real_preflight_rejection_is_not_broadcast(registry):
    w3, contract, d = registry
    attacker = d.attacker_key
    sender = w3.eth.account.from_key(attacker).address
    nonce = w3.eth.get_transaction_count(sender, "pending")
    with pytest.raises(chain.PreflightError) as caught:
        chain.send_tx(
            w3,
            contract.functions.commit(Web3.keccak(text="k"), Web3.keccak(text="d")),
            attacker,
        )
    role = contract.functions.AGGREGATOR_ROLE().call()
    selector = Web3.keccak(text="AccessControlUnauthorizedAccount(address,bytes32)")
    expected = (
        "0x" + (selector[:4] + encode(["address", "bytes32"], [sender, role])).hex()
    )
    assert caught.value.kind == "revert" and caught.value.data == expected
    assert w3.eth.get_transaction_count(sender, "pending") == nonce


@pytest.mark.chain
def test_real_mined_revert_is_reverted_with_receipt(registry):
    w3, contract, d = registry
    attacker = d.attacker_key
    key = Web3.keccak(text="tx-revert")
    prepared = chain.prepare_tx(
        w3,
        contract.functions.commit(key, Web3.keccak(text="digest")),
        attacker,
        gas=200_000,  # skip estimation so the revert is mined
    )
    result = chain.broadcast(w3, prepared)
    assert result.state is chain.TxState.REVERTED
    assert result.status == 0 and result.gas_used > 0 and result.block_number
    assert w3.eth.get_transaction_receipt(prepared.tx_hash)["status"] == 0
    assert not contract.functions.isCommitted(key).call()


@pytest.mark.chain
def test_real_timeout_is_uncertain_then_reconciles_after_mining(registry):
    w3, contract, d = registry
    key, value = Web3.keccak(text="tx-timeout"), Web3.keccak(text="digest")
    _rpc(w3, "evm_setAutomine", False)
    try:
        result = chain.send_tx(
            w3,
            contract.functions.commit(key, value),
            d.aggregator_key,
            timeout=0.5,
        )
        assert result.state is chain.TxState.UNCERTAIN
        pending = chain.lookup(w3, result.tx_hash, result.sender, result.nonce)
        assert pending.state is chain.TxState.UNCERTAIN and "pending" in pending.reason
        _rpc(w3, "evm_mine")
    finally:
        _rpc(w3, "evm_setAutomine", True)
    mined = chain.lookup(w3, result.tx_hash, result.sender, result.nonce)
    assert mined.state is chain.TxState.SUCCEEDED
    assert contract.functions.getCommitment(key).call()[0] == value


@pytest.mark.chain
def test_real_nonce_reuse_marks_unsent_transaction_replaced(registry):
    w3, contract, d = registry
    aggregator_key = d.aggregator_key
    key = Web3.keccak(text="tx-replaced")
    unsent = chain.prepare_tx(
        w3, contract.functions.commit(key, Web3.keccak(text="a")), aggregator_key
    )
    other = chain.send_tx(
        w3,
        contract.functions.commit(Web3.keccak(text="other"), Web3.keccak(text="b")),
        aggregator_key,
    )
    assert other.nonce == unsent.nonce and other.state is chain.TxState.SUCCEEDED
    replaced = chain.lookup(w3, unsent.tx_hash, unsent.sender, unsent.nonce)
    assert replaced.state is chain.TxState.REPLACED
    assert not contract.functions.isCommitted(key).call()
