"""Run manifests, expected records and single-writer ownership (Task 7.2).

A run directory binds one source selection, one fixed conversion policy and one
registry deployment. `open_run` prepares a new run or verifies a resume before
any submission: the expected-record list and manifest are written create-only,
the manifest last, so a partially prepared run is detectable. The writer lock is
an OS advisory lock held for the process lifetime and released on exit or crash.
These files are integrity aids under the operator's control, not a trust root.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import web3

from . import chain, dataset
from .config import RunPaths
from .fingerprint import KEY_DOMAIN, READING_DOMAIN, digest, record_key
from .models import Reading

MANIFEST_FORMAT = "smart-meter/manifest/v1"
EXPECTED_FORMAT = "smart-meter/expected-records/v1"
# The only supported conversion (design section 3). Changing it needs a new run.
CONVERSION = {
    "adapter": "AMPds2 Electricity_WHE.csv",
    "timestamp_column": "unix_ts",
    "power_column": "P",
    "power_unit": "W",
    "interval_minutes": 60,
    "energy": "sum of 60 one-minute P_W samples / 60, exact rational",
    "rounding": "half-up once per interval to integer Wh",
    "imputation": "'+'-prefixed timestamps retained and counted",
    "boundaries": "incomplete leading/trailing hours excluded and counted",
    "unit": "Wh",
}


class RunError(RuntimeError):
    """A run cannot be prepared, resumed or owned as requested."""


class IncompatibleRun(RunError):
    """Stored run files disagree with the requested configuration or deployment."""


class WriterBusy(RunError):
    """Another process already owns this run's writer lock."""


@dataclass(frozen=True)
class RunConfig:
    source_path: Path
    meter_id: str = "AMPDS2-WHE"
    limit: int | None = None
    interval_minutes: int = 60


@dataclass(frozen=True)
class ExpectedRecord:
    meter_id: str
    interval_start: str
    seq: int
    record_key: bytes
    digest: bytes

    def to_json(self) -> dict[str, object]:
        return {
            "meter_id": self.meter_id,
            "interval_start": self.interval_start,
            "seq": self.seq,
            "record_key": "0x" + self.record_key.hex(),
            "digest": "0x" + self.digest.hex(),
        }


@dataclass(frozen=True)
class PreparedRun:
    paths: RunPaths
    manifest: dict
    expected: tuple[ExpectedRecord, ...]
    readings: tuple[Reading, ...]
    resumed: bool


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _canonical(document: object) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def _create_only(path: Path, content: bytes) -> None:
    """Write via a temporary file and hard link, never replacing an existing file."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(content)
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise RunError(f"{path.name} already exists in {path.parent}") from error
    finally:
        temporary.unlink()


def _load(config: RunConfig) -> tuple[tuple[Reading, ...], dataset.LoadMetadata]:
    metadata = dataset.LoadMetadata()
    readings = tuple(
        dataset.load_readings(
            config.source_path,
            meter_id=config.meter_id,
            interval_minutes=config.interval_minutes,
            limit=config.limit,
            metadata=metadata,
        )
    )
    return readings, metadata


def _expected(readings: tuple[Reading, ...]) -> tuple[ExpectedRecord, ...]:
    return tuple(
        ExpectedRecord(
            r.meter_id,
            r.interval_start,
            r.seq,
            record_key(r.meter_id, r.interval_start),
            digest(r),
        )
        for r in readings
    )


def _parse_expected(content: bytes) -> tuple[ExpectedRecord, ...]:
    try:
        document = json.loads(content)
        if document["format"] != EXPECTED_FORMAT:
            raise ValueError(f"unsupported format {document['format']!r}")
        records = tuple(
            ExpectedRecord(
                item["meter_id"],
                item["interval_start"],
                item["seq"],
                bytes.fromhex(item["record_key"].removeprefix("0x")),
                bytes.fromhex(item["digest"].removeprefix("0x")),
            )
            for item in document["records"]
        )
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise IncompatibleRun(f"expected records unreadable: {error}") from error
    keys = [r.record_key for r in records]
    if len(set(keys)) != len(keys) or any(len(k) != 32 for k in keys):
        raise IncompatibleRun("expected records contain duplicate or malformed keys")
    return records


def _comparable(manifest: dict) -> dict:
    """The fields a resume must match exactly (environment may differ).

    `source` includes the absolute path as well as the checksum and size, so a
    byte-identical copy at another location cannot resume the run. This is a
    deliberate, conservative choice (review B06): a run is tied to the file it
    was prepared from. Relaxing it to checksum and size alone is safe for
    integrity, because the expected records are still reproduced and compared.
    """
    return {
        name: manifest.get(name)
        for name in (
            "format",
            "run_id",
            "source",
            "conversion",
            "selection",
            "formats",
            "deployment",
            "expected_records",
        )
    }


def _build_manifest(
    paths: RunPaths,
    config: RunConfig,
    deployment: chain.DeploymentContext,
    metadata: dataset.LoadMetadata,
    expected_bytes: bytes,
    record_count: int,
) -> dict:
    source = Path(config.source_path)
    return {
        "format": MANIFEST_FORMAT,
        "run_id": paths.root.name,
        "source": {
            "path": str(source.resolve()),
            "sha256": _sha256_file(source),
            "bytes": source.stat().st_size,
        },
        "conversion": dict(CONVERSION),
        "selection": {
            "meter_id": config.meter_id,
            "limit": config.limit,
            **asdict(metadata),
        },
        "formats": {"reading": READING_DOMAIN, "key": KEY_DOMAIN},
        "deployment": deployment.to_json(),
        "expected_records": {
            "file": paths.expected.name,
            "sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "count": record_count,
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "web3": web3.__version__,
        },
    }


def open_run(
    paths: RunPaths,
    config: RunConfig,
    deployment: chain.DeploymentContext,
    *,
    resume: bool = False,
) -> PreparedRun:
    """Prepare a new run, or verify that a resume matches it exactly.

    Raises before any submission if the manifest cannot be persisted or any
    recorded fact (source bytes, selection, policy, formats, deployment or
    expected records) differs.
    """
    if config.interval_minutes != CONVERSION["interval_minutes"]:
        raise IncompatibleRun("only 60-minute intervals are supported")
    readings, metadata = _load(config)
    expected = _expected(readings)
    expected_bytes = _canonical(
        {"format": EXPECTED_FORMAT, "records": [r.to_json() for r in expected]}
    )
    manifest = _build_manifest(
        paths, config, deployment, metadata, expected_bytes, len(expected)
    )
    if not resume:
        if paths.manifest.exists():
            raise RunError(f"run {paths.root.name} already prepared; resume it instead")
        if paths.expected.exists():
            # An earlier preparation stopped before its manifest was written.
            if paths.expected.read_bytes() != expected_bytes:
                raise IncompatibleRun(
                    "partially prepared run has different expected records"
                )
        else:
            _create_only(paths.expected, expected_bytes)
        _create_only(paths.manifest, _canonical(manifest))
        return PreparedRun(paths, manifest, expected, readings, resumed=False)

    try:
        stored = json.loads(paths.manifest.read_text())
    except FileNotFoundError as error:
        raise IncompatibleRun(f"no manifest to resume in {paths.root}") from error
    except (OSError, ValueError) as error:
        raise IncompatibleRun(f"manifest unreadable: {error}") from error
    try:
        stored_expected = paths.expected.read_bytes()
    except FileNotFoundError as error:
        raise IncompatibleRun("expected records missing for this run") from error
    recorded = stored.get("expected_records", {}).get("sha256")
    if hashlib.sha256(stored_expected).hexdigest() != recorded:
        raise IncompatibleRun("expected records changed since the run was prepared")
    if _parse_expected(stored_expected) != expected:
        raise IncompatibleRun("source no longer reproduces the expected records")
    want, have = _comparable(stored), _comparable(manifest)
    for name in want:
        if want[name] != have[name]:
            raise IncompatibleRun(f"resume differs from the prepared run in {name!r}")
    return PreparedRun(paths, stored, expected, readings, resumed=True)


def load_expected(paths: RunPaths) -> tuple[ExpectedRecord, ...]:
    """Read the expected records of a prepared run, checking the manifest hash."""
    try:
        manifest = json.loads(paths.manifest.read_text())
        content = paths.expected.read_bytes()
    except FileNotFoundError as error:
        raise IncompatibleRun(f"run files missing: {error.filename}") from error
    except (OSError, ValueError) as error:
        raise IncompatibleRun(f"run files unreadable: {error}") from error
    if hashlib.sha256(content).hexdigest() != manifest.get("expected_records", {}).get(
        "sha256"
    ):
        raise IncompatibleRun("expected records changed since the run was prepared")
    return _parse_expected(content)


@contextmanager
def writer_lock(paths: RunPaths) -> Iterator[None]:
    """Hold the run's exclusive writer lock for the duration of the block.

    `flock` locks belong to the open file and the kernel releases them when the
    process exits or crashes, so a stale lock file never blocks a later run.
    """
    paths.root.mkdir(parents=True, exist_ok=True)
    handle = paths.lock.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WriterBusy(
                f"another writer owns run {paths.root.name}; stop it before resuming"
            ) from error
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid {os.getpid()}\n")  # diagnostic only; the lock is the flock
        handle.flush()
        yield
    finally:
        handle.close()  # releases the flock
