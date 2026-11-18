"""Local presentation dashboard over recorded evidence (Task 11, R11.1-R11.5).

Serves one self-contained page plus a small JSON API, using only the standard
library. Every number comes from a curated evidence set under docs/evidence/
read at request time; nothing is recomputed or edited here. A live run executes
the existing scenario runner on a disposable chain this process owns, writing
only to a new directory under results/.

    python -m smart_meter.dashboard            # http://127.0.0.1:8765
    python -m smart_meter.dashboard --port 0   # any free port
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .config import REPO_ROOT

EVIDENCE_ROOT = REPO_ROOT / "docs" / "evidence"
RESULTS_ROOT = REPO_ROOT / "results"
PAGE = Path(__file__).with_name("dashboard.html")
SET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
RATE_KEYS = ("detection", "false_alarms", "rejections")
# Registry custom errors, decoded for display; selectors computed, not copied.
CONTRACT_ERRORS = (
    "AccessControlUnauthorizedAccount(address,bytes32)",
    "AlreadyCommitted(bytes32)",
    "ZeroDigest()",
)
REVERT_DATA = re.compile(r"0x([0-9a-fA-F]{8})")


def _selectors() -> dict[str, str]:
    from web3 import Web3

    return {
        bytes(Web3.keccak(text=sig)[:4]).hex(): sig.split("(")[0]
        for sig in CONTRACT_ERRORS
    }


def explain(note: str) -> str:
    """A readable reason; a recognised contract revert is named, else unchanged."""
    if "revert" in note:
        match = REVERT_DATA.search(note)
        name = _selectors().get(match.group(1).lower()) if match else None
        if name:
            return f"Contract rejected the call: {name}"
    return note


class EvidenceError(ValueError):
    """An evidence set is missing, unreadable or not in the expected shape."""


# --- Evidence (read-only) -------------------------------------------------------


def _set_dir(name: str, root: Path) -> Path:
    if not isinstance(name, str) or not SET_NAME.fullmatch(name):
        raise EvidenceError("evidence set names are letters, digits, '.', '_' or '-'")
    path = (root / name).resolve()
    if path.parent != root.resolve() or not path.is_dir():
        raise EvidenceError(f"no evidence set named {name!r}")
    return path


def list_sets(root: Path = EVIDENCE_ROOT) -> list[dict]:
    """Evidence sets that hold an evaluation, newest name first."""
    if not root.is_dir():
        return []
    sets = [
        {"name": d.name, "superseded": (d / "SUPERSEDED.md").exists()}
        for d in root.iterdir()
        if d.is_dir() and (d / "evaluation.json").is_file()
    ]
    return sorted(sets, key=lambda s: s["name"], reverse=True)


def default_set(root: Path = EVIDENCE_ROOT) -> str | None:
    current = [s["name"] for s in list_sets(root) if not s["superseded"]]
    return current[0] if current else None


def read_scenarios(path: Path) -> list[dict]:
    """Scenario rows exactly as recorded; malformed files raise EvidenceError."""
    try:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            needed = {"scenario_id", "verdict", "expected_outcome", "passed"}
            if not reader.fieldnames or not needed <= set(reader.fieldnames):
                raise EvidenceError(f"{path.name} lacks scenario columns")
            rows = list(reader)
    except FileNotFoundError as error:
        raise EvidenceError(f"{path.name} not found") from error
    except (OSError, csv.Error, UnicodeDecodeError) as error:
        raise EvidenceError(f"{path.name} unreadable: {error}") from error
    out = []
    for row in rows:
        if row.get("event", "scenario") != "scenario":
            continue
        passed = row.get("passed")
        out.append(
            {
                "scenario": row["scenario_id"],
                "expected": row["expected_outcome"],
                "actual": row["verdict"],
                "passed": {"True": True, "False": False}.get(passed),
                "note": row.get("note", ""),
                "reason": explain(row.get("note", "")),
                "gas_used": row.get("gas_used") or None,
                "seconds": row.get("seconds") or None,
            }
        )
    return out


def _check_shape(report: object) -> None:
    if not isinstance(report, dict):
        raise EvidenceError("evaluation.json must be a JSON object")
    for key in ("provenance", "runs", "pooled"):
        if key not in report:
            raise EvidenceError(f"evaluation.json lacks {key!r}")
    pooled = report["pooled"]
    for key in RATE_KEYS:
        rate = pooled.get(key) if isinstance(pooled, dict) else None
        if not isinstance(rate, dict) or not {"numerator", "denominator"} <= set(rate):
            raise EvidenceError(f"pooled {key!r} lacks numerator/denominator")


def load_set(name: str, root: Path = EVIDENCE_ROOT) -> dict:
    """The evidence a page needs, read now; problems are reported, not hidden."""
    directory = _set_dir(name, root)
    try:
        report = json.loads((directory / "evaluation.json").read_text())
    except FileNotFoundError as error:
        raise EvidenceError("evaluation.json not found") from error
    except (OSError, ValueError) as error:
        raise EvidenceError(f"evaluation.json unreadable: {error}") from error
    _check_shape(report)
    problems = []
    try:
        scenario_rows = read_scenarios(directory / "scenarios.csv")
    except EvidenceError as error:
        scenario_rows, problems = None, [str(error)]
    return {
        "set": directory.name,
        "superseded": (directory / "SUPERSEDED.md").exists(),
        "provenance": report["provenance"],
        "runs": report["runs"],
        "pooled": report["pooled"],
        "projection": report.get("projection"),
        "limitations": report.get("limitations"),
        "scenarios": scenario_rows,
        "problems": problems,
    }


# --- Live scenario run ----------------------------------------------------------


def _scenario_runner(directory: Path) -> int:
    """Run the tested scenario suite on a disposable chain this process owns."""
    from . import local_chain, scenarios

    with local_chain.owned_node() as w3:
        return scenarios.run_scenarios(directory, w3)


def expected_scenarios() -> dict[str, str]:
    from . import scenarios

    return dict(scenarios.EXPECTED)


class LiveRun:
    """One background scenario run at a time; status is read from its CSV."""

    def __init__(
        self,
        results_root: Path = RESULTS_ROOT,
        runner: Callable[[Path], int] = _scenario_runner,
    ):
        self.results_root, self.runner = results_root, runner
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state, self.directory, self.error = "idle", None, None
        self.started = self.finished = None

    def start(self) -> dict:
        with self._lock:
            if self.state == "running":
                raise RuntimeError("a live run is already in progress")
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            self.directory = self.results_root / f"dashboard-{stamp}"
            self.state, self.error = "running", None
            self.started, self.finished = time.time(), None
            self._thread = threading.Thread(target=self._work, daemon=True)
            self._thread.start()
        return self.status()

    def _work(self) -> None:
        try:
            self.results_root.mkdir(parents=True, exist_ok=True)
            code = self.runner(self.directory)
            state = "passed" if code == 0 else "mismatch"
            error = None if code == 0 else "one or more scenarios did not match"
        except Exception as error_:  # report every runner failure to the page
            state, error = "failed", f"{type(error_).__name__}: {error_}"
        with self._lock:
            self.state, self.error, self.finished = state, error, time.time()

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def status(self) -> dict:
        with self._lock:
            state, directory, error = self.state, self.directory, self.error
            started, finished = self.started, self.finished
        rows, problems = [], []
        if directory is not None and (directory / "scenarios.csv").exists():
            try:
                rows = read_scenarios(directory / "scenarios.csv")
            except EvidenceError as problem:
                problems.append(str(problem))
        end = finished if finished is not None else time.time()
        return {
            "state": state,
            "directory": str(directory.relative_to(REPO_ROOT))
            if directory is not None and directory.is_relative_to(REPO_ROOT)
            else (str(directory) if directory else None),
            "error": error,
            "elapsed": round(end - started, 1) if started else None,
            "expected": expected_scenarios(),
            "rows": rows,
            "problems": problems,
        }


# --- HTTP -----------------------------------------------------------------------


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def make_handler(evidence_root: Path, live: LiveRun):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SmartMeterDashboard/1"

        def log_message(self, fmt, *args):  # keep the presenter's terminal quiet
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, allow_nan=False).encode()
            self._send(status, body, "application/json")

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/":
                try:
                    self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                except OSError as error:
                    self._json(500, {"error": f"page unavailable: {error}"})
            elif url.path == "/api/sets":
                self._json(
                    200,
                    {
                        "sets": list_sets(evidence_root),
                        "default": default_set(evidence_root),
                    },
                )
            elif url.path == "/api/evidence":
                name = parse_qs(url.query).get("set", [default_set(evidence_root)])[0]
                if name is None:
                    self._json(404, {"error": "no evidence sets found"})
                    return
                try:
                    self._json(200, load_set(name, evidence_root))
                except EvidenceError as error:
                    self._json(404, {"error": str(error)})
            elif url.path == "/api/live-run":
                self._json(200, live.status())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/live-run":
                self._json(404, {"error": "not found"})
                return
            # Only same-origin page script may start a run: browsers cannot send
            # this content type cross-origin without a preflight we never answer.
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "start a run from the dashboard page"})
                return
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).hostname not in {
                "127.0.0.1",
                "localhost",
                "::1",
            }:
                self._json(403, {"error": "cross-origin requests are refused"})
                return
            try:
                self._json(202, live.start())
            except RuntimeError as error:
                self._json(409, {"error": str(error)})

    return Handler


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    evidence_root: Path = EVIDENCE_ROOT,
    live: LiveRun | None = None,
) -> ThreadingHTTPServer:
    if not is_loopback(host):
        raise ValueError(f"the dashboard serves loopback only, not {host!r}")
    handler = make_handler(evidence_root, live or LiveRun())
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local evidence dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        server = create_server(args.host, args.port)
    except (ValueError, OSError) as error:
        parser.exit(1, f"dashboard failed to start: {error}\n")
    host, port = server.server_address[:2]
    print(f"Dashboard: http://{host}:{port}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
