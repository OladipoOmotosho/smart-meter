"""Task 11: local presentation dashboard (R11.1-R11.5)."""

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from smart_meter import dashboard
from smart_meter.config import REPO_ROOT

FINAL = REPO_ROOT / "docs" / "evidence" / "2026-11-14-final"
UNAUTHORIZED = "preflight revert: ('0xe2517d3f0000000000000000000000003c44', 'x')"
DUPLICATE = "preflight revert: ('0xd297b6c5454e68a71f', 'x')"


@pytest.fixture
def evidence(tmp_path):
    """A private copy of the curated set plus deliberately broken sets."""
    root = tmp_path / "evidence"
    shutil.copytree(FINAL, root / "good", ignore=shutil.ignore_patterns("run-*"))
    old = root / "old"
    shutil.copytree(root / "good", old)
    (old / "SUPERSEDED.md").write_text("superseded")
    bad_json = root / "bad-json"
    bad_json.mkdir()
    (bad_json / "evaluation.json").write_text("{not json")
    no_rates = root / "no-rates"
    no_rates.mkdir()
    report = json.loads((root / "good" / "evaluation.json").read_text())
    del report["pooled"]["detection"]["denominator"]
    (no_rates / "evaluation.json").write_text(json.dumps(report))
    no_csv = root / "no-csv"
    shutil.copytree(root / "good", no_csv)
    (no_csv / "scenarios.csv").unlink()
    return root


# --- Evidence parsing (R11.2-R11.3) ---------------------------------------------


def test_curated_set_loads_with_rates_and_every_scenario(evidence):
    ev = dashboard.load_set("good", evidence)
    recorded = json.loads((FINAL / "evaluation.json").read_text())
    assert ev["pooled"] == recorded["pooled"]  # passed through, never recomputed
    assert ev["provenance"] == recorded["provenance"]
    assert ev["problems"] == [] and ev["superseded"] is False
    by_id = {s["scenario"]: s for s in ev["scenarios"]}
    assert len(by_id) == 12 and all(s["passed"] is True for s in by_id.values())
    assert by_id["A1"]["actual"] == "TAMPERED"
    assert by_id["A4"]["expected"] == "VERIFIED"
    assert "AccessControlUnauthorizedAccount" in by_id["A2"]["reason"]
    assert "AlreadyCommitted" in by_id["A3"]["reason"]
    assert by_id["A2"]["note"].startswith("preflight revert")  # original kept


def test_sets_are_listed_newest_first_and_default_skips_superseded(evidence):
    names = [s["name"] for s in dashboard.list_sets(evidence)]
    assert names == sorted(names, reverse=True)
    assert {"good", "old", "bad-json", "no-rates", "no-csv"} == set(names)
    assert {s["name"]: s["superseded"] for s in dashboard.list_sets(evidence)}["old"]
    assert dashboard.default_set(evidence) != "old"
    assert dashboard.load_set("old", evidence)["superseded"] is True


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("bad-json", "unreadable"),
        ("no-rates", "numerator/denominator"),
        ("missing", "no evidence set"),
        ("../evidence", "letters, digits"),
        ("..", "letters, digits"),
        ("/etc", "letters, digits"),
        ("", "letters, digits"),
    ],
)
def test_bad_or_escaping_sets_are_explicit_errors(evidence, name, message):
    with pytest.raises(dashboard.EvidenceError, match=message):
        dashboard.load_set(name, evidence)


def test_missing_scenarios_are_reported_not_invented(evidence):
    ev = dashboard.load_set("no-csv", evidence)
    assert ev["scenarios"] is None
    assert ev["problems"] == ["scenarios.csv not found"]


def test_scenario_file_without_required_columns_is_rejected(tmp_path):
    path = tmp_path / "scenarios.csv"
    path.write_text("event,verdict\nscenario,VERIFIED\n")
    with pytest.raises(dashboard.EvidenceError, match="lacks scenario columns"):
        dashboard.read_scenarios(path)


def test_unknown_pass_value_is_not_reported_as_pass(tmp_path):
    path = tmp_path / "scenarios.csv"
    path.write_text(
        "event,scenario_id,verdict,expected_outcome,passed\n"
        "scenario,S0,VERIFIED,VERIFIED,\n"
    )
    (row,) = dashboard.read_scenarios(path)
    assert row["passed"] is None  # shown as N/A, never as PASS


def test_revert_reasons_are_decoded_from_computed_selectors():
    assert dashboard.explain(UNAUTHORIZED).endswith("AccessControlUnauthorizedAccount")
    assert dashboard.explain(DUPLICATE).endswith("AlreadyCommitted")
    assert dashboard.explain("preflight revert: ('0xdeadbeef', '')").startswith(
        "preflight revert"
    )
    assert dashboard.explain("fingerprints match") == "fingerprints match"


# --- Loopback only (R11.1) --------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_loopback_hosts_are_accepted(host):
    assert dashboard.is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com", ""])
def test_other_hosts_are_refused(host):
    assert not dashboard.is_loopback(host)
    with pytest.raises(ValueError, match="loopback only"):
        dashboard.create_server(host, 0)


# --- HTTP and live runs (R11.4) ---------------------------------------------------


class Server:
    def __init__(self, evidence, live):
        self.httpd = dashboard.create_server(
            "127.0.0.1", 0, evidence_root=evidence, live=live
        )
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def call(self, path, *, method="GET", headers=None, body=None):
        request = urllib.request.Request(
            self.base + path, data=body, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def start_run(self, **headers):
        return self.call(
            "/api/live-run",
            method="POST",
            headers={"Content-Type": "application/json", **headers},
            body=b"{}",
        )

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def gated_runner(gate, code=0, error=None):
    """A fake scenario runner that writes real-format rows, then waits."""

    def run(directory: Path) -> int:
        directory.mkdir(parents=True)
        shutil.copyfile(FINAL / "scenarios.csv", directory / "scenarios.csv")
        gate.wait(10)
        if error:
            raise error
        return code

    return run


@pytest.fixture
def server(evidence, tmp_path):
    gate = threading.Event()
    live = dashboard.LiveRun(tmp_path / "results", gated_runner(gate))
    srv = Server(evidence, live)
    srv.gate, srv.live = gate, live
    try:
        yield srv
    finally:
        gate.set()
        live.wait(10)
        srv.close()


def test_page_and_read_endpoints(server):
    status, headers, page = server.call("/")
    assert status == 200 and b"Evidence Dashboard" in page
    assert headers["Content-Type"].startswith("text/html")
    assert b"<script src=" not in page and b"https://" not in page  # works offline
    status, _, body = server.call("/api/sets")
    assert status == 200 and json.loads(body)["default"]
    status, _, body = server.call("/api/evidence?set=good")
    assert status == 200 and len(json.loads(body)["scenarios"]) == 12
    for path in (
        "/api/evidence?set=..%2Fevidence",
        "/api/evidence?set=missing",
        "/nope",
    ):
        status, _, body = server.call(path)
        assert status == 404 and "error" in json.loads(body)


def test_run_requires_json_and_same_origin(server):
    status, _, _ = server.call(
        "/api/live-run",
        method="POST",
        headers={"Content-Type": "text/plain"},
        body=b"x",
    )
    assert status == 415
    status, _, _ = server.start_run(Origin="https://attacker.example")
    assert status == 403
    status, _, _ = server.call("/api/other", method="POST", body=b"{}")
    assert status == 404
    assert json.loads(server.call("/api/live-run")[2])["state"] == "idle"


def test_one_live_run_at_a_time_and_rows_are_read_from_its_csv(server, tmp_path):
    status, _, body = server.start_run(Origin=server.base)
    assert status == 202 and json.loads(body)["state"] == "running"
    status, _, body = server.start_run()
    assert status == 409 and "already in progress" in json.loads(body)["error"]
    server.gate.set()
    server.live.wait(10)
    st = json.loads(server.call("/api/live-run")[2])
    assert st["state"] == "passed" and st["error"] is None
    assert len(st["rows"]) == 12 and all(r["passed"] for r in st["rows"])
    assert set(st["expected"]) == {r["scenario"] for r in st["rows"]}
    assert Path(st["directory"]).parent == tmp_path / "results"
    status, _, _ = server.start_run()  # a finished run allows a new one
    assert status == 202


@pytest.mark.parametrize(
    ("code", "error", "state", "message"),
    [
        (1, None, "mismatch", "did not match"),
        (0, RuntimeError("Anvil missing"), "failed", "RuntimeError: Anvil missing"),
    ],
)
def test_runner_mismatch_or_failure_is_reported(tmp_path, code, error, state, message):
    gate = threading.Event()
    gate.set()
    live = dashboard.LiveRun(tmp_path / "results", gated_runner(gate, code, error))
    live.start()
    live.wait(10)
    st = live.status()
    assert st["state"] == state and message in st["error"]


@pytest.mark.chain
def test_real_live_run_on_an_owned_chain(evidence, tmp_path):
    """The real runner: a disposable chain, all twelve scenarios, nothing curated touched."""
    curated = {p: p.read_bytes() for p in FINAL.rglob("*") if p.is_file()}
    live = dashboard.LiveRun(tmp_path / "results")
    srv = Server(evidence, live)
    try:
        assert srv.start_run()[0] == 202
        live.wait(120)
        st = json.loads(srv.call("/api/live-run")[2])
    finally:
        srv.close()
    assert st["state"] == "passed", st
    assert len(st["rows"]) == 12
    assert all(r["passed"] and r["actual"] == r["expected"] for r in st["rows"])
    assert {p: p.read_bytes() for p in FINAL.rglob("*") if p.is_file()} == curated
