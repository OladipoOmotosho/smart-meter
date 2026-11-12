"""Blockchain plumbing: connect, deployment context, load, sign and send.

Deployment records identify one registry deployment so ingestion and audit can
check they are talking to the recorded code, chain and roles (R4.6, R6.3).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from web3 import Web3
from web3.contract import Contract
from web3.exceptions import TransactionNotFound, Web3Exception

from .fingerprint import KEY_DOMAIN, READING_DOMAIN


@dataclass(frozen=True)
class TxResult:
    tx_hash: str
    gas_used: int
    seconds: float  # wall-clock time from send to mined receipt
    status: int  # 1 = success, 0 = reverted


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
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
        }
    )
    signed = account.sign_transaction(tx)
    start = time.perf_counter()
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    seconds = time.perf_counter() - start
    return TxResult(
        tx_hash.hex(), int(receipt["gasUsed"]), seconds, int(receipt["status"])
    )


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
    return abi, _hex(Web3.keccak(code)), compiler


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
