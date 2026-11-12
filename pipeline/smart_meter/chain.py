"""Blockchain plumbing: connect, deployment context, load, sign and send.

Deployment records identify one registry deployment so ingestion and audit can
check they are talking to the recorded code, chain and roles (R4.6, R6.3).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from web3 import Web3
from web3.contract import Contract
from web3.exceptions import (
    ContractLogicError,
    TimeExhausted,
    TransactionNotFound,
    Web3Exception,
    Web3RPCError,
)

from .fingerprint import KEY_DOMAIN, READING_DOMAIN

DEFAULT_RECEIPT_TIMEOUT = 30.0
DEFAULT_POLL_SECONDS = 0.1
PENDING = "pending without receipt"
UNKNOWN = "unknown to node; nonce unused"


class TxState(StrEnum):
    """What is known about one signed transaction."""

    SUCCEEDED = "SUCCEEDED"  # mined with status 1
    REVERTED = "REVERTED"  # mined with status 0: definite failure
    REPLACED = "REPLACED"  # its nonce was used by another transaction: never mined
    UNCERTAIN = "UNCERTAIN"  # may or may not take effect; reconcile before resending


@dataclass(frozen=True)
class PreparedTx:
    """A signed transaction whose identity is known before broadcast.

    `raw` is the signed payload (not the key); it can be rebroadcast unchanged.
    """

    tx_hash: str
    sender: str
    nonce: int
    raw: bytes = field(repr=False)


@dataclass(frozen=True)
class TxResult:
    tx_hash: str
    sender: str
    nonce: int
    state: TxState
    reason: str
    status: int | None = None  # receipt status when mined
    gas_used: int | None = None
    block_number: int | None = None
    block_hash: str | None = None
    seconds: float | None = None  # send-to-receipt time; None when not observed


class SubmissionError(Exception):
    """Base for transaction failures that are definite, not uncertain."""


class PreflightError(SubmissionError):
    """Nothing was broadcast. kind: 'revert', 'rejected', 'unavailable' or
    'configuration' (a malformed signing key)."""

    def __init__(self, kind: str, reason: str, sender: str, data: str | None = None):
        super().__init__(f"preflight {kind}: {reason}")
        self.kind, self.reason, self.sender, self.data = kind, reason, sender, data


class BroadcastRejected(SubmissionError):
    """The node refused this signed transaction and does not know its hash."""

    def __init__(self, prepared: PreparedTx, reason: str):
        super().__init__(f"broadcast rejected for {prepared.tx_hash}: {reason}")
        self.tx_hash, self.sender, self.nonce = (
            prepared.tx_hash,
            prepared.sender,
            prepared.nonce,
        )
        self.reason = reason


class TransactionReverted(SubmissionError):
    """A mined receipt reported failure."""

    def __init__(self, result: TxResult):
        super().__init__(f"transaction reverted: {result.tx_hash}")
        self.result = result


class SubmissionUncertain(Exception):
    """The outcome is unknown; reconcile by hash before any further submission."""

    def __init__(self, result: TxResult):
        super().__init__(f"submission uncertain for {result.tx_hash}: {result.reason}")
        self.result = result


def connect(rpc_url: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"No node at {rpc_url}. Is Anvil running? (make chain)")
    return w3


def load_contract(w3: Web3, address: str, artifact_path: Path) -> Contract:
    """Load the deployed registry using the ABI that `forge build` writes."""
    if not address:
        raise ValueError(
            "CONTRACT_ADDRESS is empty. Run `make deploy` and copy the address into .env"
        )
    if not Path(artifact_path).exists():
        raise FileNotFoundError(f"{artifact_path} not found. Run `make build` first.")
    abi = json.loads(Path(artifact_path).read_text())["abi"]
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


def _revert_data(error: ContractLogicError) -> str | None:
    data = getattr(error, "data", None)
    return data if isinstance(data, str) and data.startswith("0x") else None


def prepare_tx(
    w3: Web3, contract_fn, private_key: str, *, gas: int | None = None
) -> PreparedTx:
    """Preflight (unless gas is given) and sign, without broadcasting.

    Raises PreflightError if the call would revert, the node refuses it or the
    node is unreachable; in every case nothing has been sent.
    """
    try:
        account = w3.eth.account.from_key(private_key)
    except (ValueError, TypeError) as error:
        # Never echo the key material; the message names only the problem.
        raise PreflightError("configuration", "signing key is malformed", "") from error
    sender = account.address
    try:
        params = {
            "from": sender,
            "nonce": w3.eth.get_transaction_count(sender, "pending"),
        }
        if gas is not None:
            params["gas"] = gas
        tx = contract_fn.build_transaction(params)
    except ContractLogicError as error:
        raise PreflightError(
            "revert", str(error), sender, _revert_data(error)
        ) from error
    except Web3RPCError as error:
        raise PreflightError("rejected", str(error), sender) from error
    except (Web3Exception, OSError) as error:
        raise PreflightError("unavailable", str(error), sender) from error
    signed = account.sign_transaction(tx)
    return PreparedTx(
        _hex(signed.hash), sender, int(tx["nonce"]), bytes(signed.raw_transaction)
    )


def _from_receipt(
    tx_hash: str, sender: str, nonce: int, receipt, seconds: float | None
) -> TxResult:
    status = int(receipt["status"])
    return TxResult(
        tx_hash,
        sender,
        nonce,
        TxState.SUCCEEDED if status == 1 else TxState.REVERTED,
        "mined with status 1" if status == 1 else "mined with status 0",
        status=status,
        gas_used=int(receipt["gasUsed"]),
        block_number=int(receipt["blockNumber"]),
        block_hash=_hex(receipt["blockHash"]),
        seconds=seconds,
    )


def broadcast(
    w3: Web3,
    prepared: PreparedTx,
    *,
    timeout: float = DEFAULT_RECEIPT_TIMEOUT,
    poll: float = DEFAULT_POLL_SECONDS,
) -> TxResult:
    """Send once and wait a bounded time. Never resends or picks a new nonce."""
    ident = (prepared.tx_hash, prepared.sender, prepared.nonce)
    start = time.perf_counter()
    try:
        w3.eth.send_raw_transaction(prepared.raw)
    except Web3RPCError as error:
        # The node answered. Proceed only if it already knows this exact hash.
        known = lookup(w3, *ident)
        if known.reason == UNKNOWN:
            raise BroadcastRejected(prepared, str(error)) from error
        if known.reason != PENDING:
            return known  # mined, replaced, or the lookup itself failed
    except (Web3Exception, OSError) as error:
        return TxResult(*ident, TxState.UNCERTAIN, f"broadcast response lost: {error}")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(
            prepared.tx_hash, timeout=timeout, poll_latency=poll
        )
    except TimeExhausted:
        return TxResult(*ident, TxState.UNCERTAIN, f"no receipt within {timeout}s")
    except (Web3Exception, OSError) as error:
        return TxResult(*ident, TxState.UNCERTAIN, f"receipt wait failed: {error}")
    return _from_receipt(*ident, receipt, time.perf_counter() - start)


def lookup(w3: Web3, tx_hash: str, sender: str, nonce: int) -> TxResult:
    """Classify a previously signed transaction from chain state alone."""
    ident = (tx_hash, sender, nonce)
    try:
        # Read the mined nonce first: if it already passed ours and no receipt
        # exists afterwards, another transaction consumed it.
        consumed = w3.eth.get_transaction_count(sender, "latest") > nonce
        try:
            return _from_receipt(*ident, w3.eth.get_transaction_receipt(tx_hash), None)
        except TransactionNotFound:
            pass
        if consumed:
            return TxResult(
                *ident, TxState.REPLACED, "nonce used by another transaction"
            )
        try:
            w3.eth.get_transaction(tx_hash)
        except TransactionNotFound:
            return TxResult(*ident, TxState.UNCERTAIN, UNKNOWN)
        return TxResult(*ident, TxState.UNCERTAIN, PENDING)
    except (Web3Exception, OSError) as error:
        return TxResult(*ident, TxState.UNCERTAIN, f"lookup failed: {error}")


def send_tx(
    w3: Web3,
    contract_fn,
    private_key: str,
    *,
    timeout: float = DEFAULT_RECEIPT_TIMEOUT,
) -> TxResult:
    """Prepare, broadcast once and classify. See prepare_tx and broadcast.

    Example:
        send_tx(w3, contract.functions.commit(key, digest), settings.aggregator_key)
    """
    return broadcast(w3, prepare_tx(w3, contract_fn, private_key), timeout=timeout)


# --- Deployment context (Task 6.1, R4.6, R6.3) ---------------------------------

DEPLOYMENT_FORMAT = "smart-meter/deployment/v1"
CONTRACT_NAME = "MeterCommitmentRegistry"
DEFAULT_ADMIN_ROLE = bytes(32)
_VERSION_FIELDS = (
    "contract",
    "compiler",
    "node_client",
    "reading_format",
    "key_format",
)
_RECORD_FIELDS = (
    "format",
    "chain_id",
    "registry_address",
    "deployment_tx_hash",
    "deployment_block_number",
    "deployment_block_hash",
    "runtime_code_hash",
    "admin",
    "aggregator",
    "versions",
)


class DeploymentContextError(ValueError):
    """The recorded deployment is missing, malformed or differs from the chain."""


@dataclass(frozen=True)
class DeploymentContext:
    """Public identity of one registry deployment. Contains no private keys."""

    chain_id: int
    registry_address: str
    deployment_tx_hash: str
    deployment_block_number: int
    deployment_block_hash: str
    runtime_code_hash: str
    admin: str
    aggregator: str
    versions: dict[str, str]

    def to_json(self) -> dict[str, object]:
        record: dict[str, object] = {"format": DEPLOYMENT_FORMAT}
        record.update(
            {name: getattr(self, name) for name in _RECORD_FIELDS if name != "format"}
        )
        record["versions"] = dict(self.versions)
        return record

    @classmethod
    def from_json(cls, record: object) -> DeploymentContext:
        """Strictly parse a record; unknown fields (such as keys) are rejected."""
        if not isinstance(record, dict):
            raise DeploymentContextError("deployment record must be a JSON object")
        if set(record) != set(_RECORD_FIELDS):
            missing = sorted(set(_RECORD_FIELDS) - set(record))
            extra = sorted(set(record) - set(_RECORD_FIELDS))
            raise DeploymentContextError(
                f"deployment record fields differ: missing={missing} unexpected={extra}"
            )
        if record["format"] != DEPLOYMENT_FORMAT:
            raise DeploymentContextError(
                f"unsupported deployment record format: {record['format']!r}"
            )
        versions = record["versions"]
        if (
            not isinstance(versions, dict)
            or set(versions) != set(_VERSION_FIELDS)
            or not all(isinstance(v, str) and v for v in versions.values())
        ):
            raise DeploymentContextError(
                f"deployment versions must contain nonempty {list(_VERSION_FIELDS)}"
            )
        return cls(
            chain_id=_positive_int(record["chain_id"], "chain_id"),
            registry_address=_address(record["registry_address"], "registry_address"),
            deployment_tx_hash=_hash32(
                record["deployment_tx_hash"], "deployment_tx_hash"
            ),
            deployment_block_number=_positive_int(
                record["deployment_block_number"], "deployment_block_number", zero=True
            ),
            deployment_block_hash=_hash32(
                record["deployment_block_hash"], "deployment_block_hash"
            ),
            runtime_code_hash=_hash32(record["runtime_code_hash"], "runtime_code_hash"),
            admin=_address(record["admin"], "admin"),
            aggregator=_address(record["aggregator"], "aggregator"),
            versions=dict(versions),
        )


def _positive_int(value: object, name: str, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        kind = "nonnegative" if zero else "positive"
        raise DeploymentContextError(f"{name} must be a {kind} integer")
    return value


def _address(value: object, name: str) -> str:
    if not isinstance(value, str) or not Web3.is_checksum_address(value):
        raise DeploymentContextError(f"{name} must be a checksummed address")
    if int(value, 16) == 0:
        raise DeploymentContextError(f"{name} must not be the zero address")
    return value


def _hash32(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 66
        or not value.startswith("0x")
        or value != value.lower()
    ):
        raise DeploymentContextError(
            f"{name} must be 0x-prefixed lowercase 32-byte hex"
        )
    try:
        bytes.fromhex(value[2:])
    except ValueError as error:
        raise DeploymentContextError(f"{name} is not hexadecimal") from error
    return value


def _hex(value: bytes) -> str:
    return "0x" + bytes(value).hex()


def save_deployment(path: Path, context: DeploymentContext) -> None:
    """Atomically write the record; an existing record is never replaced."""
    path = Path(path)
    if path.exists():
        raise DeploymentContextError(f"deployment record already exists: {path}")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(context.to_json(), indent=2, sort_keys=True) + "\n")
    try:
        os.link(temporary, path)  # fails instead of overwriting a concurrent record
    except FileExistsError as error:
        raise DeploymentContextError(
            f"deployment record already exists: {path}"
        ) from error
    finally:
        temporary.unlink()


def load_deployment(path: Path) -> DeploymentContext:
    try:
        record = json.loads(Path(path).read_text())
    except FileNotFoundError as error:
        raise DeploymentContextError(
            f"deployment record not found: {path}. Capture it after deploying."
        ) from error
    except (OSError, ValueError) as error:
        raise DeploymentContextError(
            f"deployment record unreadable: {error}"
        ) from error
    return DeploymentContext.from_json(record)


def _artifact(artifact_path: Path) -> tuple[list, str, str]:
    """Return ABI, expected runtime-code hash and compiler version."""
    try:
        artifact = json.loads(Path(artifact_path).read_text())
        abi = artifact["abi"]
        runtime = artifact["deployedBytecode"]["object"]
        compiler = artifact["metadata"]["compiler"]["version"]
        code = bytes.fromhex(runtime.removeprefix("0x"))
    except FileNotFoundError as error:
        raise DeploymentContextError(
            f"{artifact_path} not found. Run `make build` first."
        ) from error
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise DeploymentContextError(
            f"contract artifact is malformed: {error}"
        ) from error
    if not code:
        raise DeploymentContextError("contract artifact has no runtime bytecode")
    _check_interface(abi, code)
    return abi, _hex(Web3.keccak(code)), compiler


# The registry interface the pipeline calls, as canonical signature -> outputs.
REQUIRED_FUNCTIONS = {
    "commit(bytes32,bytes32)": (),
    "getCommitment(bytes32)": ("(bytes32,uint64,address)",),
    "isCommitted(bytes32)": ("bool",),
    "AGGREGATOR_ROLE()": ("bytes32",),
    "hasRole(bytes32,address)": ("bool",),
}
REQUIRED_EVENT = (
    "Committed(bytes32,bytes32,address,uint64)",
    (True, False, True, False),  # recordKey and submitter are indexed
)


def _abi_type(param: dict) -> str:
    kind = param["type"]
    if kind.startswith("tuple"):
        inner = ",".join(_abi_type(c) for c in param["components"])
        return f"({inner}){kind[len('tuple') :]}"
    return kind


def _check_interface(abi: object, code: bytes) -> None:
    """Require the exact interface used, implemented by the artifact's code.

    The code hash is compared with the chain separately; requiring each function
    selector and the event topic in that code ties the ABI to the verified code.
    """
    try:
        functions: dict[str, tuple[str, ...]] = {}
        events: dict[str, tuple[bool, ...]] = {}
        for entry in abi:  # type: ignore[union-attr]
            if entry.get("type") not in {"function", "event"}:
                continue
            signature = (
                f"{entry['name']}({','.join(_abi_type(p) for p in entry['inputs'])})"
            )
            if entry["type"] == "function":
                functions[signature] = tuple(_abi_type(p) for p in entry["outputs"])
            else:
                events[signature] = tuple(bool(p["indexed"]) for p in entry["inputs"])
    except (AttributeError, KeyError, TypeError) as error:
        raise DeploymentContextError(f"contract ABI is malformed: {error}") from error
    for signature, outputs in REQUIRED_FUNCTIONS.items():
        if functions.get(signature) != outputs:
            raise DeploymentContextError(
                f"contract ABI lacks {signature} returning {outputs or 'nothing'}"
            )
        if bytes(Web3.keccak(text=signature)[:4]) not in code:
            raise DeploymentContextError(f"{signature} is not implemented by the code")
    event, indexed = REQUIRED_EVENT
    if events.get(event) != indexed:
        raise DeploymentContextError(f"contract ABI lacks event {event} as deployed")
    if bytes(Web3.keccak(text=event)) not in code:
        raise DeploymentContextError(f"event {event} is not implemented by the code")


def _chain_read(description: str, read):
    try:
        return read()
    except TransactionNotFound as error:
        raise DeploymentContextError(
            f"{description}: deployment transaction not found (chain reset or wrong chain?)"
        ) from error
    except (Web3Exception, OSError, ValueError, TypeError) as error:
        raise DeploymentContextError(f"{description} failed: {error}") from error


def capture_deployment(
    w3: Web3,
    deployment_tx_hash: str,
    artifact_path: Path,
    *,
    admin: str,
    aggregator: str,
) -> DeploymentContext:
    """Build a record from a mined deployment and check its code and roles."""
    tx_hash = _hash32(deployment_tx_hash.lower(), "deployment_tx_hash")
    _, artifact_hash, compiler = _artifact(artifact_path)
    receipt = _chain_read(
        "deployment receipt", lambda: w3.eth.get_transaction_receipt(tx_hash)
    )
    if receipt["status"] != 1 or not receipt.get("contractAddress"):
        raise DeploymentContextError("deployment transaction did not create a contract")
    context = DeploymentContext(
        chain_id=_chain_read("chain ID", lambda: int(w3.eth.chain_id)),
        registry_address=Web3.to_checksum_address(receipt["contractAddress"]),
        deployment_tx_hash=tx_hash,
        deployment_block_number=int(receipt["blockNumber"]),
        deployment_block_hash=_hex(receipt["blockHash"]),
        runtime_code_hash=artifact_hash,
        admin=_address(Web3.to_checksum_address(admin), "admin"),
        aggregator=_address(Web3.to_checksum_address(aggregator), "aggregator"),
        versions={
            "contract": CONTRACT_NAME,
            "compiler": compiler,
            "node_client": _chain_read("node version", lambda: str(w3.client_version)),
            "reading_format": READING_DOMAIN,
            "key_format": KEY_DOMAIN,
        },
    )
    contract = validate_deployment(w3, context, artifact_path, writer=aggregator)
    if not _chain_read(
        "admin role check",
        lambda: contract.functions.hasRole(DEFAULT_ADMIN_ROLE, context.admin).call(),
    ):
        raise DeploymentContextError(
            f"{context.admin} does not hold DEFAULT_ADMIN_ROLE"
        )
    return context


def validate_deployment(
    w3: Web3,
    context: DeploymentContext,
    artifact_path: Path,
    *,
    writer: str | None = None,
) -> Contract:
    """Check the live chain matches the record; return the registry contract.

    Audits pass writer=None. Ingestion passes the signing address, which must be
    the recorded aggregator and currently hold AGGREGATOR_ROLE.
    """
    abi, artifact_hash, _ = _artifact(artifact_path)
    if context.runtime_code_hash != artifact_hash:
        raise DeploymentContextError(
            "contract artifact does not match the recorded runtime code; "
            "use the artifact that built this deployment"
        )
    chain_id = _chain_read("chain ID", lambda: int(w3.eth.chain_id))
    if chain_id != context.chain_id:
        raise DeploymentContextError(
            f"chain ID {chain_id} differs from recorded {context.chain_id}"
        )
    address = context.registry_address
    code = bytes(_chain_read("runtime code", lambda: w3.eth.get_code(address)))
    if not code:
        raise DeploymentContextError(
            f"no contract code at {address} (chain reset or wrong address?)"
        )
    if _hex(Web3.keccak(code)) != context.runtime_code_hash:
        raise DeploymentContextError(f"runtime code at {address} differs from record")
    receipt = _chain_read(
        "deployment receipt",
        lambda: w3.eth.get_transaction_receipt(context.deployment_tx_hash),
    )
    created = receipt.get("contractAddress")
    if (
        receipt["status"] != 1
        or not created
        or Web3.to_checksum_address(created) != address
    ):
        raise DeploymentContextError(
            "recorded deployment transaction did not create this registry"
        )
    if (
        int(receipt["blockNumber"]) != context.deployment_block_number
        or _hex(receipt["blockHash"]) != context.deployment_block_hash
    ):
        raise DeploymentContextError(
            "deployment block differs from record (chain reset or reorganized?)"
        )
    contract = w3.eth.contract(address=address, abi=abi)
    if writer is not None:
        signer = Web3.to_checksum_address(writer)
        if signer != context.aggregator:
            raise DeploymentContextError(
                f"signer {signer} is not the recorded aggregator {context.aggregator}"
            )
        role = _chain_read(
            "writer role", lambda: contract.functions.AGGREGATOR_ROLE().call()
        )
        if not _chain_read(
            "writer role check", lambda: contract.functions.hasRole(role, signer).call()
        ):
            raise DeploymentContextError(f"{signer} does not hold AGGREGATOR_ROLE")
    return contract
