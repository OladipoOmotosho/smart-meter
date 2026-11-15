"""Owned disposable Anvil for demonstrations; public throwaway accounts only."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from web3 import Web3

from . import chain
from .config import ARTIFACT_PATH

DEV_MNEMONIC = "test test test test test test test test test test test junk"


def accounts():
    api = Web3().eth.account
    api.enable_unaudited_hdwallet_features()
    return tuple(
        api.from_mnemonic(DEV_MNEMONIC, account_path=f"m/44'/60'/0'/0/{i}")
        for i in range(3)
    )


def local_client(url: str) -> Web3:
    endpoint = urlsplit(url)
    if endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("demonstration writes require a loopback Anvil endpoint")
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 5}))
    if "anvil" not in w3.client_version.lower():
        raise ValueError("demonstration writes require Anvil")
    return w3


@contextmanager
def owned_node():
    binary = shutil.which("anvil")
    if binary is None:
        raise RuntimeError("Anvil missing; install the pinned Foundry toolchain")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="smart-meter-demo-") as directory:
        with (Path(directory) / "anvil.log").open("wb") as log:
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
                cwd=directory,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                w3 = Web3(
                    Web3.HTTPProvider(
                        f"http://127.0.0.1:{port}", request_kwargs={"timeout": 1}
                    )
                )
                deadline = time.monotonic() + 15
                while not w3.is_connected():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError(
                            "owned Anvil failed to start within 15 seconds"
                        )
                    time.sleep(0.05)
                yield w3
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def deploy(w3: Web3, artifact_path: Path = ARTIFACT_PATH) -> chain.DeploymentContext:
    admin, writer, _ = accounts()
    artifact = json.loads(artifact_path.read_text())
    factory = w3.eth.contract(
        abi=artifact["abi"], bytecode=artifact["bytecode"]["object"]
    )
    created = chain.send_tx(w3, factory.constructor(admin.address), admin.key.hex())
    receipt = w3.eth.get_transaction_receipt(created.tx_hash)
    contract = w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])
    chain.send_tx(
        w3,
        contract.functions.grantRole(
            contract.functions.AGGREGATOR_ROLE().call(), writer.address
        ),
        admin.key.hex(),
    )
    return chain.capture_deployment(
        w3,
        created.tx_hash,
        artifact_path,
        admin=admin.address,
        aggregator=writer.address,
    )
