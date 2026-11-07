"""Own a disposable Anvil instance for the required chain test command."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from eth_account import Account


ROOT = Path(__file__).resolve().parents[1]
DEV_MNEMONIC = "test test test test test test test test test test test junk"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def ready(rpc_url: str) -> bool:
    request = urllib.request.Request(
        rpc_url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=0.5) as response:
            return bool(json.load(response).get("result"))
    except (OSError, urllib.error.URLError, ValueError):
        return False


def main() -> int:
    """Start, deploy, test, and stop only this command's local chain."""
    python = Path(sys.executable)
    port = available_port()
    rpc_url = f"http://127.0.0.1:{port}"
    Account.enable_unaudited_hdwallet_features()
    accounts = [
        Account.from_mnemonic(DEV_MNEMONIC, account_path=f"m/44'/60'/0'/0/{index}")
        for index in range(3)
    ]
    with tempfile.TemporaryDirectory(prefix="smart-meter-integration-") as temporary:
        temp = Path(temporary)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(temp),
            "RPC_URL": rpc_url,
            "ADMIN_PRIVATE_KEY": accounts[0].key.hex(),
            "AGGREGATOR_ADDRESS": accounts[1].address,
            "AGGREGATOR_PRIVATE_KEY": accounts[1].key.hex(),
            "ATTACKER_PRIVATE_KEY": accounts[2].key.hex(),
            "DATASET_PATH": str(ROOT / "pipeline" / "tests" / "fixtures" / "valid_60w_hour.csv"),
            "DB_PATH": str(temp / "readings.sqlite"),
            "RESULTS_PATH": str(temp / "results.csv"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
        try:
            with (temp / "anvil.log").open("wb") as log:
                node = subprocess.Popen(
                    ["anvil", "--host", "127.0.0.1", "--port", str(port),
                     "--mnemonic", DEV_MNEMONIC, "--silent"],
                    cwd=temp,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline and node.poll() is None:
                        if ready(rpc_url):
                            break
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("owned Anvil did not become ready within 15 seconds")

                    subprocess.run(
                        ["forge", "script", "script/Deploy.s.sol:Deploy", "--rpc-url",
                         rpc_url, "--broadcast"],
                        cwd=ROOT / "contracts", env=env, check=True,
                    )
                    result = subprocess.run(
                        [str(python), "-m", "pytest", "-m", "chain", "-ra", "-p", "no:cacheprovider"],
                        cwd=ROOT / "pipeline", env=env, check=False,
                        capture_output=True, text=True,
                    )
                    output = result.stdout + result.stderr
                    print(output, end="")
                    if result.returncode:
                        return result.returncode
                    if re.search(r"\b\d+ skipped\b|\b\d+ xfailed\b|\bno tests ran\b", output):
                        print("Required integration tests were skipped, xfailed, or absent.", file=sys.stderr)
                        return 1
                    return 0
                finally:
                    node.terminate()
                    try:
                        node.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        node.kill()
                        node.wait(timeout=5)
        except FileNotFoundError as error:
            print(f"Missing integration tool: {error.filename}", file=sys.stderr)
            return 1
        except (RuntimeError, subprocess.CalledProcessError) as error:
            print(f"Integration setup failed: {error}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
