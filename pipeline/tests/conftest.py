"""Owned local chain fixtures for `chain` tests (Task 6.3, R6.5, R9.3, R9.5).

The session starts its own Anvil on a free loopback port inside a temporary
directory, using only the public development mnemonic. Each test runs inside an
EVM snapshot that is reverted and verified afterwards, and deploys a fresh
registry. Nothing here reads `.env`, personal keys or a developer's node.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.signers.local import LocalAccount
from smart_meter import chain
from smart_meter.config import ARTIFACT_PATH
from web3 import Web3
from web3.contract import Contract

DEV_MNEMONIC = "test test test test test test test test test test test junk"
READY_TIMEOUT = 15.0
STOP_TIMEOUT = 5.0


@dataclass(frozen=True)
class AnvilNode:
    rpc_url: str
    process: subprocess.Popen
    admin: LocalAccount
    aggregator: LocalAccount
    attacker: LocalAccount


@dataclass(frozen=True)
class Deployment:
    w3: Web3
    registry: Contract
    context: chain.DeploymentContext
    node: AnvilNode

    @property
    def admin(self) -> str:
        return self.node.admin.address

    @property
    def aggregator(self) -> str:
        return self.node.aggregator.address

    @property
    def attacker(self) -> str:
        return self.node.attacker.address

    @property
    def aggregator_key(self) -> str:
        return _key(self.node.aggregator)

    @property
    def attacker_key(self) -> str:
        return _key(self.node.attacker)


def _key(account: LocalAccount) -> str:
    return "0x" + bytes(account.key).hex()


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _ready(w3: Web3) -> bool:
    try:
        return w3.eth.chain_id > 0
    except (OSError, ValueError):
        return False


def _rpc(w3: Web3, method: str, *params):
    response = w3.provider.make_request(method, list(params))
    if "error" in response:
        raise RuntimeError(f"{method} failed: {response['error']}")
    return response["result"]


def _stop(process: subprocess.Popen, port: int) -> None:
    process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=STOP_TIMEOUT)
    deadline = time.monotonic() + STOP_TIMEOUT
    while _port_open(port) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _port_open(port):
        raise RuntimeError(f"owned Anvil port {port} still open after stop")


@pytest.fixture(scope="session")
def anvil_node(tmp_path_factory) -> Iterator[AnvilNode]:
    binary = shutil.which("anvil")
    if binary is None:
        pytest.fail("anvil is not installed; chain tests require Foundry v1.9.0")
    if not ARTIFACT_PATH.exists():
        pytest.fail(f"{ARTIFACT_PATH} missing; run `make build` first")
    workdir: Path = tmp_path_factory.mktemp("anvil")
    port = _free_port()
    log = (workdir / "anvil.log").open("wb")
    process = subprocess.Popen(
        [
            binary,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--mnemonic",
            DEV_MNEMONIC,
            "--silent",
        ],
        cwd=workdir,
        env={"PATH": "/usr/bin:/bin", "HOME": str(workdir)},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        rpc_url = f"http://127.0.0.1:{port}"
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 2}))
        deadline = time.monotonic() + READY_TIMEOUT
        while not _ready(w3):
            if process.poll() is not None:
                pytest.fail(f"owned Anvil exited early with code {process.returncode}")
            if time.monotonic() > deadline:
                pytest.fail(f"owned Anvil not ready within {READY_TIMEOUT}s")
            time.sleep(0.1)
        Account.enable_unaudited_hdwallet_features()
        admin, aggregator, attacker = (
            Account.from_mnemonic(DEV_MNEMONIC, account_path=f"m/44'/60'/0'/0/{i}")
            for i in range(3)
        )
        yield AnvilNode(rpc_url, process, admin, aggregator, attacker)
    finally:
        try:
            _stop(process, port)
        finally:
            log.close()


@pytest.fixture
def chain_w3(anvil_node) -> Iterator[Web3]:
    """A connected client inside a snapshot that is reverted and verified."""
    w3 = chain.connect(anvil_node.rpc_url)
    baseline = w3.eth.block_number
    snapshot = _rpc(w3, "evm_snapshot")
    try:
        yield w3
    finally:
        _rpc(w3, "evm_setAutomine", True)
        if _rpc(w3, "evm_revert", snapshot) is not True:
            raise RuntimeError("snapshot revert failed; later chain tests are unsafe")
        if w3.eth.block_number != baseline:
            raise RuntimeError("snapshot revert did not restore the block height")


@pytest.fixture
def reader(anvil_node) -> Web3:
    """A keyless client for audits: it holds no account or signing key."""
    return Web3(Web3.HTTPProvider(anvil_node.rpc_url))


def deploy_registry(w3: Web3, node: AnvilNode) -> tuple[str, Contract]:
    """Deploy a fresh registry with the throwaway admin and grant the aggregator."""
    artifact = json.loads(ARTIFACT_PATH.read_text())
    factory = w3.eth.contract(
        abi=artifact["abi"], bytecode=artifact["bytecode"]["object"]
    )
    admin_key = _key(node.admin)
    created = chain.send_tx(w3, factory.constructor(node.admin.address), admin_key)
    assert created.state is chain.TxState.SUCCEEDED, created
    receipt = w3.eth.get_transaction_receipt(created.tx_hash)
    registry = w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])
    granted = chain.send_tx(
        w3,
        registry.functions.grantRole(
            registry.functions.AGGREGATOR_ROLE().call(), node.aggregator.address
        ),
        admin_key,
    )
    assert granted.state is chain.TxState.SUCCEEDED, granted
    return created.tx_hash, registry


@pytest.fixture
def new_registry(anvil_node):
    """Deploy another fresh registry on demand: `new_registry(w3)`."""
    return lambda w3: deploy_registry(w3, anvil_node)


@pytest.fixture
def deployment(chain_w3, anvil_node) -> Deployment:
    tx_hash, registry = deploy_registry(chain_w3, anvil_node)
    context = chain.capture_deployment(
        chain_w3,
        tx_hash,
        ARTIFACT_PATH,
        admin=anvil_node.admin.address,
        aggregator=anvil_node.aggregator.address,
    )
    return Deployment(chain_w3, registry, context, anvil_node)
