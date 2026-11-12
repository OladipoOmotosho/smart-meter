"""Run the required chain suite; its fixtures own a disposable Anvil (R9.3).

The pytest fixtures in pipeline/tests/conftest.py start, snapshot-isolate and
stop their own local node with throwaway development accounts. This runner
builds the contracts and passes a minimal environment: no RPC URL, private keys
or personal configuration reach the tests.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(report_path: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="smart-meter-integration-") as temporary:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": temporary,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
        try:
            subprocess.run(
                ["forge", "build"], cwd=ROOT / "contracts", env=env, check=True
            )
        except FileNotFoundError as error:
            print(f"Missing integration tool: {error.filename}", file=sys.stderr)
            return 1
        except subprocess.CalledProcessError as error:
            print(f"Integration setup failed: {error}", file=sys.stderr)
            return 1
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                "chain",
                "-ra",
                "--strict-markers",
                "--junitxml",
                str(report_path),
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(Path(temporary) / "pytest"),
            ],
            cwd=ROOT / "pipeline",
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
    output = result.stdout + result.stderr
    print(output, end="")
    if result.returncode:
        return result.returncode
    if re.search(r"\b\d+ skipped\b|\b\d+ xfailed\b|\bno tests ran\b", output):
        print(
            "Required integration tests were skipped, xfailed, or absent.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_integration.py REPORT_PATH")
    raise SystemExit(main(Path(sys.argv[1])))
