"""Prepare and validate the hermetic Harness P2.5 reference workload."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = REPO_ROOT / "benchmarks" / "harness_p2_5" / "profile.json"
REFERENCE_PROFILE_ID = "gpt2giga-harness-p2.5-v1"
WORKLOAD_NAMES = {"reference", "smoke"}
REQUIRED_SIGNALS = {
    "network",
    "handler",
    "storage",
    "serialization",
    "event_loop_lag",
    "event_to_paint",
    "main_thread",
    "dom_nodes",
    "heap",
    "queue_depth",
    "payload_bytes",
}
REQUIRED_BUDGETS = {
    "critical_assets_compressed_bytes": 204_800,
    "initial_javascript_compressed_bytes": 102_400,
    "lazy_chunk_compressed_bytes": 153_600,
    "cold_shell_interactive_p95_ms": 1_500,
    "session_switch_uncached_p95_ms": 500,
    "session_switch_cached_p95_ms": 150,
    "input_response_p95_ms": 50,
    "inp_ms": 200,
    "event_to_paint_p95_ms": 100,
    "main_thread_task_ms": 50,
    "list_records": 100,
    "normal_response_bytes": 1_048_576,
    "mounted_message_rows": 100,
    "mounted_event_rows": 200,
    "active_view_dom_nodes": 1_500,
    "event_loop_lag_p95_ms": 20,
    "event_loop_lag_p99_ms": 50,
    "canonical_event_loss": 0,
    "canonical_event_duplicates": 0,
    "soak_heap_growth_percent": 10,
}
REFERENCE_DIMENSIONS = {
    "sessions": 1_000,
    "large_session_messages": 5_000,
    "large_session_events": 50_000,
    "artifact_bytes_each": 10 * 1024 * 1024,
    "native_output_chars": 50_000,
    "sustained_sse_events_per_second": 100,
    "sustained_sse_seconds": 60,
    "burst_sse_events_per_second": 500,
    "rest_clients": 20,
    "sse_clients": 50,
    "sqlite_contention_rows": 10_000,
    "sqlite_readers": 16,
    "sqlite_writers": 4,
    "soak_seconds": 1_800,
}
FIXED_START = datetime(2026, 7, 15, tzinfo=timezone.utc)


class BaselineContractError(ValueError):
    """Raised when the frozen P2.5 baseline contract is violated."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BaselineContractError(f"JSON root must be an object: {path}")
    return payload


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BaselineContractError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise BaselineContractError(f"{label} must be an array")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _timestamp(offset: int = 0) -> str:
    return (
        (FIXED_START + timedelta(milliseconds=offset))
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_profile(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    """Validate and summarize the frozen machine-readable profile."""
    profile = _load_json(path)
    if profile.get("schema_version") != 1:
        raise BaselineContractError("profile.schema_version must be 1")
    if profile.get("profile_id") != REFERENCE_PROFILE_ID:
        raise BaselineContractError("profile_id does not match the frozen contract")
    if profile.get("status") != "frozen":
        raise BaselineContractError("profile.status must be frozen")
    reference = _mapping(profile.get("reference_workload"), "reference_workload")
    for key, expected in REFERENCE_DIMENSIONS.items():
        if reference.get(key) != expected:
            raise BaselineContractError(
                f"reference_workload.{key} must be {expected!r}"
            )
    if reference.get("artifact_kinds") != ["diff", "report"]:
        raise BaselineContractError("artifact kinds must be diff and report")
    signals = set(_sequence(profile.get("required_signals"), "required_signals"))
    if signals != REQUIRED_SIGNALS:
        raise BaselineContractError("required_signals do not match the frozen contract")
    budgets = dict(_mapping(profile.get("budgets"), "budgets"))
    if budgets != REQUIRED_BUDGETS:
        raise BaselineContractError("budgets do not match the frozen contract")
    viewports = _sequence(profile.get("viewports"), "viewports")
    observed_viewports = {
        (item.get("id"), item.get("width"), item.get("height"))
        for item in viewports
        if isinstance(item, Mapping)
    }
    if observed_viewports != {("desktop", 1440, 900), ("mobile-390", 390, 844)}:
        raise BaselineContractError("desktop and 390 px viewports must be frozen")
    return {
        "profile_id": REFERENCE_PROFILE_ID,
        "reference_sessions": reference["sessions"],
        "reference_messages": reference["large_session_messages"],
        "reference_events": reference["large_session_events"],
        "required_signals": sorted(signals),
        "budget_count": len(budgets),
        "viewports": ["desktop", "mobile-390"],
    }


def _session_manifest(
    session_id: str, *, title: str, updated_offset: int
) -> dict[str, Any]:
    return {
        "id": session_id,
        "title": title,
        "created_at": _timestamp(),
        "updated_at": _timestamp(updated_offset),
        "workspace": None,
        "default_harness_id": "echo",
        "default_model": None,
        "default_api_mode": "v2",
        "default_mode": "plan",
        "pinned": False,
        "archived": False,
        "tags": ["p2.5-reference"],
        "native": {},
        "metadata": {"fixture": REFERENCE_PROFILE_ID},
    }


def _message_rows(session_id: str, count: int) -> list[dict[str, Any]]:
    content = "Hermetic retained message payload. " * 8
    return [
        {
            "id": f"msg_ref_{index:05d}",
            "session_id": session_id,
            "run_id": "run_ref_hot",
            "role": "user" if index % 2 == 0 else "assistant",
            "content": content,
            "created_at": _timestamp(index),
            "harness_id": "echo",
            "model": None,
            "api_mode": "v2",
            "metadata": {"sequence": index},
        }
        for index in range(count)
    ]


def _event_rows(session_id: str, count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"evt_ref_{index:06d}",
            "session_id": session_id,
            "run_id": "run_ref_hot",
            "type": "assistant_delta" if index % 5 else "tool_progress",
            "message": "Hermetic reference event",
            "payload": {"sequence": index, "canonical": index % 5 == 0},
            "created_at": _timestamp(index),
            "sequence": index,
            "trace_id": "trace_ref_hot",
            "span_id": f"span_ref_{index:06d}",
        }
        for index in range(count)
    ]


def _stream_rows(count: int, *, phase: str) -> list[dict[str, Any]]:
    return [
        {
            "event_id": f"{phase}-{index:06d}",
            "sequence": index,
            "phase": phase,
            "canonical": True,
            "payload": {"kind": "delta", "content": "fixture"},
        }
        for index in range(count)
    ]


def _write_repeated(path: Path, size: int, seed: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    remaining = size
    with path.open("wb") as handle:
        while remaining:
            chunk = seed[: min(len(seed), remaining)]
            handle.write(chunk)
            remaining -= len(chunk)


def _write_contention_db(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE reference_rows (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO reference_rows(id, payload) VALUES (?, ?)",
            ((index, f"contention-row-{index:06d}") for index in range(rows)),
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def prepare_fixture(
    destination: Path,
    *,
    workload: str = "reference",
    profile_path: Path = DEFAULT_PROFILE,
) -> dict[str, Any]:
    """Materialize a deterministic workload outside the source checkout."""
    validate_profile(profile_path)
    if workload not in WORKLOAD_NAMES:
        raise BaselineContractError(f"unknown workload: {workload}")
    if destination.exists():
        raise BaselineContractError(f"destination already exists: {destination}")
    profile = _load_json(profile_path)
    dimensions = dict(_mapping(profile[f"{workload}_workload"], f"{workload}_workload"))
    destination.mkdir(parents=True)
    data_dir = destination / "data"
    sessions_root = data_dir / "sessions"
    index_rows: list[dict[str, str]] = []
    hot_session_id = "sess_ref_hot"
    session_ids = [hot_session_id] + [
        f"sess_ref_{index:06d}" for index in range(1, dimensions["sessions"])
    ]
    for index, session_id in enumerate(session_ids):
        session_dir = sessions_root / "2026" / "07" / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "artifacts").mkdir()
        _write_json(
            session_dir / "manifest.json",
            _session_manifest(
                session_id,
                title=(
                    "P2.5 large retained session"
                    if session_id == hot_session_id
                    else f"P2.5 reference session {index:04d}"
                ),
                updated_offset=dimensions["sessions"] - index,
            ),
        )
        index_rows.append({"id": session_id, "path": f"2026/07/{session_id}"})
    _write_json(sessions_root / "index.json", {"sessions": index_rows})

    hot_dir = sessions_root / "2026" / "07" / hot_session_id
    _write_jsonl(
        hot_dir / "messages.jsonl",
        _message_rows(hot_session_id, dimensions["large_session_messages"]),
    )
    _write_jsonl(
        hot_dir / "runs.jsonl",
        [
            {
                "id": "run_ref_hot",
                "session_id": hot_session_id,
                "harness_id": "echo",
                "status": "succeeded",
                "prompt": "Hermetic reference prompt",
                "model": None,
                "api_mode": "v2",
                "capability": "chat_completions",
                "mode": "plan",
                "invocation_mode": "headless",
                "workspace": None,
                "created_at": _timestamp(),
                "updated_at": _timestamp(1),
                "started_at": _timestamp(),
                "finished_at": _timestamp(1),
                "error": None,
                "command": [],
                "native_session_id": None,
                "metadata": {"fixture": REFERENCE_PROFILE_ID},
            }
        ],
    )
    _write_jsonl(
        hot_dir / "events.jsonl",
        _event_rows(hot_session_id, dimensions["large_session_events"]),
    )

    artifact_paths: dict[str, Path] = {}
    for kind in dimensions["artifact_kinds"]:
        artifact_path = hot_dir / "artifacts" / f"large-{kind}.txt"
        _write_repeated(
            artifact_path,
            dimensions["artifact_bytes_each"],
            f"P2.5 {kind} fixture line\n".encode(),
        )
        artifact_paths[kind] = artifact_path

    native_output = destination / "inputs" / "native-output.txt"
    _write_repeated(
        native_output, dimensions["native_output_chars"], b"native-output\n"
    )
    sustained_count = (
        dimensions["sustained_sse_events_per_second"]
        * dimensions["sustained_sse_seconds"]
    )
    _write_jsonl(
        destination / "inputs" / "sse-sustained.jsonl",
        _stream_rows(sustained_count, phase="sustained"),
    )
    _write_jsonl(
        destination / "inputs" / "sse-burst.jsonl",
        _stream_rows(dimensions["burst_sse_events_per_second"], phase="burst"),
    )
    _write_contention_db(
        destination / "inputs" / "sqlite-contention.sqlite3",
        dimensions["sqlite_contention_rows"],
    )

    manifest = {
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "profile_sha256": _sha256_file(profile_path),
        "workload": workload,
        "generated_at": _timestamp(),
        "data_dir": "data",
        "hot_session_id": hot_session_id,
        "dimensions": dimensions,
        "files": {
            "messages": "data/sessions/2026/07/sess_ref_hot/messages.jsonl",
            "events": "data/sessions/2026/07/sess_ref_hot/events.jsonl",
            "native_output": "inputs/native-output.txt",
            "sse_sustained": "inputs/sse-sustained.jsonl",
            "sse_burst": "inputs/sse-burst.jsonl",
            "sqlite_contention": "inputs/sqlite-contention.sqlite3",
            "artifacts": {
                kind: path.relative_to(destination).as_posix()
                for kind, path in artifact_paths.items()
            },
        },
        "concurrency": {
            "rest_clients": dimensions["rest_clients"],
            "sse_clients": dimensions["sse_clients"],
            "sqlite_readers": dimensions["sqlite_readers"],
            "sqlite_writers": dimensions["sqlite_writers"],
        },
        "reconnect": {
            "cursor_source": "inputs/sse-sustained.jsonl",
            "expected_event_loss": 0,
            "expected_event_duplicates": 0,
        },
        "soak_seconds": dimensions["soak_seconds"],
    }
    _write_json(destination / "manifest.json", manifest)
    return inspect_fixture(destination, profile_path=profile_path)


def _line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def inspect_fixture(
    fixture: Path, *, profile_path: Path = DEFAULT_PROFILE
) -> dict[str, Any]:
    """Verify that a materialized fixture matches its declared workload."""
    validate_profile(profile_path)
    manifest = _load_json(fixture / "manifest.json")
    if manifest.get("profile_id") != REFERENCE_PROFILE_ID:
        raise BaselineContractError("fixture profile_id is not frozen")
    if manifest.get("profile_sha256") != _sha256_file(profile_path):
        raise BaselineContractError("fixture profile digest does not match")
    dimensions = _mapping(manifest.get("dimensions"), "fixture.dimensions")
    files = _mapping(manifest.get("files"), "fixture.files")
    index = _load_json(fixture / "data" / "sessions" / "index.json")
    sessions = _sequence(index.get("sessions"), "fixture sessions")
    if len(sessions) != dimensions.get("sessions"):
        raise BaselineContractError("fixture session count does not match")
    expected_lines = {
        "messages": dimensions["large_session_messages"],
        "events": dimensions["large_session_events"],
        "sse_sustained": (
            dimensions["sustained_sse_events_per_second"]
            * dimensions["sustained_sse_seconds"]
        ),
        "sse_burst": dimensions["burst_sse_events_per_second"],
    }
    observed_lines: dict[str, int] = {}
    for key, expected in expected_lines.items():
        path = fixture / str(files[key])
        observed_lines[key] = _line_count(path)
        if observed_lines[key] != expected:
            raise BaselineContractError(f"fixture {key} count does not match")
    native_path = fixture / str(files["native_output"])
    if native_path.stat().st_size != dimensions["native_output_chars"]:
        raise BaselineContractError("fixture native output size does not match")
    artifact_files = _mapping(files.get("artifacts"), "fixture artifacts")
    for kind in ("diff", "report"):
        path = fixture / str(artifact_files.get(kind) or "")
        if path.stat().st_size != dimensions["artifact_bytes_each"]:
            raise BaselineContractError(f"fixture {kind} size does not match")
    database = sqlite3.connect(fixture / str(files["sqlite_contention"]))
    try:
        row_count = database.execute("SELECT COUNT(*) FROM reference_rows").fetchone()[
            0
        ]
    finally:
        database.close()
    if row_count != dimensions["sqlite_contention_rows"]:
        raise BaselineContractError("fixture SQLite row count does not match")
    return {
        "valid": True,
        "profile_id": REFERENCE_PROFILE_ID,
        "workload": manifest["workload"],
        "sessions": len(sessions),
        "messages": observed_lines["messages"],
        "events": observed_lines["events"],
        "artifact_bytes_each": dimensions["artifact_bytes_each"],
        "sustained_sse_events": observed_lines["sse_sustained"],
        "burst_sse_events": observed_lines["sse_burst"],
        "sqlite_contention_rows": row_count,
    }


def validate_result(
    path: Path, *, profile_path: Path = DEFAULT_PROFILE
) -> dict[str, Any]:
    """Validate a measured-or-unavailable baseline evidence envelope."""
    validate_profile(profile_path)
    result = _load_json(path)
    if result.get("schema_version") != 1:
        raise BaselineContractError("result.schema_version must be 1")
    if result.get("profile_id") != REFERENCE_PROFILE_ID:
        raise BaselineContractError("result.profile_id does not match")
    environment = _mapping(result.get("environment"), "result.environment")
    for key in ("captured_at", "os", "architecture", "python", "browser", "commit"):
        if not str(environment.get(key) or "").strip():
            raise BaselineContractError(f"result.environment.{key} is required")
    signals = _mapping(result.get("signals"), "result.signals")
    if set(signals) != REQUIRED_SIGNALS:
        raise BaselineContractError("result signals do not match the frozen profile")
    measured = 0
    unavailable = 0
    for signal_id, raw in signals.items():
        signal = _mapping(raw, f"result.signals.{signal_id}")
        status = signal.get("status")
        if status == "measured":
            values = _mapping(
                signal.get("values"), f"result.signals.{signal_id}.values"
            )
            if not values:
                raise BaselineContractError(
                    f"measured signal {signal_id} has no values"
                )
            if any(not isinstance(value, (int, float)) for value in values.values()):
                raise BaselineContractError(
                    f"measured signal {signal_id} is non-numeric"
                )
            measured += 1
        elif status == "unavailable":
            if not str(signal.get("reason") or "").strip():
                raise BaselineContractError(
                    f"unavailable signal {signal_id} requires a reason"
                )
            unavailable += 1
        else:
            raise BaselineContractError(f"invalid signal status for {signal_id}")
    viewports = _sequence(result.get("viewports"), "result.viewports")
    viewport_ids = {item.get("id") for item in viewports if isinstance(item, Mapping)}
    if viewport_ids != {"desktop", "mobile-390"}:
        raise BaselineContractError("result must include desktop and mobile-390")
    scenarios = _mapping(result.get("scenarios"), "result.scenarios")
    required_scenarios = {
        "cold_boot",
        "large_history",
        "large_artifacts",
        "sustained_and_burst_sse",
        "native_output",
        "sqlite_contention",
        "disconnect_reconnect",
        "soak",
    }
    if set(scenarios) != required_scenarios:
        raise BaselineContractError("result scenarios do not match the frozen profile")
    return {
        "valid": True,
        "profile_id": REFERENCE_PROFILE_ID,
        "measured_signals": measured,
        "unavailable_signals": unavailable,
        "viewports": sorted(viewport_ids),
        "scenarios": sorted(scenarios),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-profile")
    prepare = subparsers.add_parser("prepare-fixture")
    prepare.add_argument("destination", type=Path)
    prepare.add_argument(
        "--workload", choices=sorted(WORKLOAD_NAMES), default="reference"
    )
    inspect = subparsers.add_parser("inspect-fixture")
    inspect.add_argument("fixture", type=Path)
    validate = subparsers.add_parser("validate-result")
    validate.add_argument("result", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one baseline contract command."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-profile":
            payload = validate_profile(args.profile)
        elif args.command == "prepare-fixture":
            payload = prepare_fixture(
                args.destination,
                workload=args.workload,
                profile_path=args.profile,
            )
        elif args.command == "inspect-fixture":
            payload = inspect_fixture(args.fixture, profile_path=args.profile)
        else:
            payload = validate_result(args.result, profile_path=args.profile)
    except BaselineContractError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
