"""Prepare and validate hermetic Harness P0 comparison evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "benchmarks" / "harness_p0" / "manifest.json"
REQUIRED_FIXTURE_FILES = {
    "README.md",
    "pyproject.toml",
    "src/inventory.py",
    "tests/test_inventory.py",
    "benchmark/analysis_expectations.json",
    "benchmark/compatibility_cases.json",
    "benchmark/side_effect.py",
    "benchmark/verify.py",
}
TARGET_IDS = {"harness", "omnigent"}
WORKFLOW_CELLS = {
    "read-only-analysis": {f"W1-S{index}" for index in range(1, 6)},
    "isolated-reviewed-patch": {f"W2-S{index}" for index in range(1, 6)},
    "restart-recovery": {f"W3-S{index}" for index in range(1, 6)},
    "scheduled-compatibility-regression": {f"W4-S{index}" for index in range(1, 6)},
    "policy-refusal-bypass": {f"W5-S{index}" for index in range(1, 6)},
}
RESULT_STATUSES = {"passed", "failed", "invalid", "skipped"}
SEMANTIC_STATUSES = {"passed", "failed", "unsupported", "invalid", "excluded"}
FAILURE_CLASSES = {"product", "adapter", "model", "environment"}
FIXED_GIT_DATE = "2000-01-01T00:00:00+00:00"
SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credentials",
    "password",
    "provider_key",
    "secret",
    "token",
}


class ComparisonContractError(ValueError):
    """Raised when the frozen comparison contract is violated."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComparisonContractError(f"JSON root must be an object: {path}")
    return payload


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComparisonContractError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ComparisonContractError(f"{label} must be an array")
    return value


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"tbd", "todo", "unknown", "latest"}:
        raise ComparisonContractError(f"{label} must be frozen, not {value!r}")
    return text


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture_files(source: Path) -> list[Path]:
    if not source.is_dir():
        raise ComparisonContractError(f"fixture source is missing: {source}")
    files: list[Path] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ComparisonContractError(f"fixture symlinks are forbidden: {path}")
        if path.is_file():
            files.append(path)
    relative = {path.relative_to(source).as_posix() for path in files}
    missing = sorted(REQUIRED_FIXTURE_FILES - relative)
    if missing:
        raise ComparisonContractError(
            f"fixture files are missing: {', '.join(missing)}"
        )
    return files


def fixture_archive_bytes(source: Path, fixture_id: str) -> bytes:
    """Return a deterministic uncompressed ZIP archive for the fixture."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for path in _fixture_files(source):
            relative = path.relative_to(source).as_posix()
            content = path.read_bytes()
            info = zipfile.ZipInfo(
                f"{fixture_id}/{relative}",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _run_git(cwd: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ComparisonContractError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def initialize_fixture_repo(source: Path, destination: Path) -> str:
    """Copy the fixture and create its deterministic seed commit."""
    if destination.exists() and any(destination.iterdir()):
        raise ComparisonContractError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for path in _fixture_files(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o644)
    _run_git(destination, "init", "--quiet", "--initial-branch=main")
    _run_git(destination, "config", "core.autocrlf", "false")
    _run_git(destination, "config", "core.filemode", "false")
    _run_git(destination, "add", "--all")
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_AUTHOR_NAME": "gpt2giga Harness P0",
            "GIT_AUTHOR_EMAIL": "harness-p0@example.invalid",
            "GIT_AUTHOR_DATE": FIXED_GIT_DATE,
            "GIT_COMMITTER_NAME": "gpt2giga Harness P0",
            "GIT_COMMITTER_EMAIL": "harness-p0@example.invalid",
            "GIT_COMMITTER_DATE": FIXED_GIT_DATE,
        }
    )
    _run_git(
        destination,
        "commit",
        "--quiet",
        "-m",
        "fixture: seed inventory",
        env=environment,
    )
    return _run_git(destination, "rev-parse", "HEAD")


def fixture_seed_sha(source: Path) -> str:
    """Compute the deterministic seed commit without retaining a checkout."""
    with tempfile.TemporaryDirectory(prefix="gpt2giga-harness-p0-") as directory:
        return initialize_fixture_repo(source, Path(directory) / "fixture")


def _resolve_repo_path(value: Any, label: str) -> Path:
    relative = Path(_required_text(value, label))
    if relative.is_absolute() or ".." in relative.parts:
        raise ComparisonContractError(f"{label} must be a repository-relative path")
    path = (REPO_ROOT / relative).resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ComparisonContractError(f"{label} escapes the repository") from exc
    return path


def validate_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Validate frozen pins, fixture identity, workflows, and evidence schema."""
    manifest = _load_json(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("status") != "frozen":
        raise ComparisonContractError("manifest must be frozen schema_version 1")
    _required_text(manifest.get("comparison_id"), "comparison_id")
    _required_text(manifest.get("frozen_at"), "frozen_at")

    specification = _mapping(manifest.get("specification"), "specification")
    spec_path = _resolve_repo_path(specification.get("path"), "specification.path")
    spec_sha = _required_text(specification.get("sha256"), "specification.sha256")
    if spec_path.exists() and _sha256_file(spec_path) != spec_sha:
        raise ComparisonContractError("accepted specification SHA-256 does not match")

    fixture = _mapping(manifest.get("fixture"), "fixture")
    fixture_id = _required_text(fixture.get("id"), "fixture.id")
    if fixture_id != "gpt2giga-harness-p0-v1":
        raise ComparisonContractError("fixture.id must match the accepted P0-01 spec")
    source = _resolve_repo_path(fixture.get("source"), "fixture.source")
    archive_sha = _sha256_bytes(fixture_archive_bytes(source, fixture_id))
    if archive_sha != _required_text(
        fixture.get("archive_sha256"), "fixture.archive_sha256"
    ):
        raise ComparisonContractError("fixture archive SHA-256 does not match")
    seed_sha = fixture_seed_sha(source)
    if seed_sha != _required_text(fixture.get("seed_git_sha"), "fixture.seed_git_sha"):
        raise ComparisonContractError("fixture seed Git SHA does not match")

    targets = _sequence(manifest.get("targets"), "targets")
    target_ids = {
        _required_text(_mapping(item, "target").get("id"), "target.id")
        for item in targets
    }
    if target_ids != TARGET_IDS:
        raise ComparisonContractError(
            "targets must contain exactly harness and omnigent"
        )
    for item in targets:
        target = _mapping(item, "target")
        for field in (
            "distribution",
            "version",
            "executable",
            "integration_mode",
            "auth_owner",
        ):
            _required_text(target.get(field), f"target.{field}")
        source_identity = _mapping(target.get("source"), "target.source")
        _required_text(source_identity.get("url"), "target.source.url")
        _required_text(source_identity.get("commit"), "target.source.commit")

    gateway = _mapping(manifest.get("gateway"), "gateway")
    for field in ("distribution", "version", "source_commit", "base_url"):
        _required_text(gateway.get(field), f"gateway.{field}")
    route = _mapping(gateway.get("model_route"), "gateway.model_route")
    _required_text(
        route.get("public_model_alias"), "gateway.model_route.public_model_alias"
    )
    _required_text(route.get("api_mode"), "gateway.model_route.api_mode")
    if route.get("direct_provider_forbidden") is not True:
        raise ComparisonContractError("direct provider routing must be forbidden")

    repetitions = _sequence(manifest.get("repetitions"), "repetitions")
    if repetitions != [1, 2, 3]:
        raise ComparisonContractError("repetitions must be exactly [1, 2, 3]")
    workflows = _sequence(manifest.get("workflows"), "workflows")
    workflow_ids: set[str] = set()
    semantic_ids: set[str] = set()
    for item in workflows:
        workflow = _mapping(item, "workflow")
        workflow_id = _required_text(workflow.get("id"), "workflow.id")
        workflow_ids.add(workflow_id)
        actual_cells = {
            str(value)
            for value in _sequence(
                workflow.get("semantic_cells"), "workflow.semantic_cells"
            )
        }
        if actual_cells != WORKFLOW_CELLS.get(workflow_id):
            raise ComparisonContractError(f"semantic cells do not match {workflow_id}")
        semantic_ids.update(actual_cells)
        if (
            not isinstance(workflow.get("timeout_seconds"), int)
            or workflow["timeout_seconds"] <= 0
        ):
            raise ComparisonContractError(f"{workflow_id} timeout must be positive")
        _required_text(
            workflow.get("failure_injection"), f"{workflow_id}.failure_injection"
        )
        _required_text(workflow.get("prompt"), f"{workflow_id}.prompt")
    if workflow_ids != set(WORKFLOW_CELLS) or len(semantic_ids) != 25:
        raise ComparisonContractError(
            "manifest must freeze five workflows and 25 semantics"
        )

    schema_path = _resolve_repo_path(manifest.get("evidence_schema"), "evidence_schema")
    schema = _load_json(schema_path)
    if schema.get("$id") != "https://gpt2giga.dev/schemas/harness-p0-evidence-v1.json":
        raise ComparisonContractError("unexpected evidence schema identity")
    collector = _mapping(manifest.get("collector"), "collector")
    collector_path = _resolve_repo_path(collector.get("path"), "collector.path")
    collector_sha = _required_text(collector.get("sha256"), "collector.sha256")
    if _sha256_file(collector_path) != collector_sha:
        raise ComparisonContractError("collector SHA-256 does not match")
    if (
        collector.get("content_capture_enabled") is not False
        or collector.get("public_network_enabled") is not False
    ):
        raise ComparisonContractError("collector must remain offline and content-safe")
    return {
        "comparison_id": manifest["comparison_id"],
        "fixture_archive_sha256": archive_sha,
        "fixture_seed_git_sha": seed_sha,
        "targets": sorted(target_ids),
        "workflows": len(workflow_ids),
        "semantic_cells": len(semantic_ids),
        "execution_cells": len(target_ids) * len(workflow_ids) * len(repetitions),
        "live_execution_started": False,
    }


def _manifest_lookup(
    manifest: Mapping[str, Any], collection: str, item_id: str
) -> Mapping[str, Any]:
    for item in _sequence(manifest.get(collection), collection):
        value = _mapping(item, collection[:-1])
        if value.get("id") == item_id:
            return value
    raise ComparisonContractError(f"unknown {collection[:-1]}: {item_id}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def prepare_cell(
    manifest_path: Path,
    destination: Path,
    *,
    target_id: str,
    workflow_id: str,
    repetition: int,
) -> dict[str, Any]:
    """Prepare one disposable fixture checkout and empty evidence boundary."""
    validate_manifest(manifest_path)
    manifest = _load_json(manifest_path)
    target = _manifest_lookup(manifest, "targets", target_id)
    workflow = _manifest_lookup(manifest, "workflows", workflow_id)
    if repetition not in manifest["repetitions"]:
        raise ComparisonContractError(f"unsupported repetition: {repetition}")
    if destination.exists():
        raise ComparisonContractError(f"cell destination already exists: {destination}")
    destination.mkdir(parents=True)
    fixture = _mapping(manifest["fixture"], "fixture")
    source = _resolve_repo_path(fixture["source"], "fixture.source")
    archive = fixture_archive_bytes(source, str(fixture["id"]))
    (destination / "input").mkdir()
    (destination / "input" / "fixture.zip").write_bytes(archive)
    seed_sha = initialize_fixture_repo(source, destination / "workspace")
    (destination / "evidence" / "artifacts").mkdir(parents=True)
    cell_id = f"{target_id}-{workflow_id}-r{repetition}"
    cell = {
        "schema_version": 1,
        "state": "prepared",
        "comparison_id": manifest["comparison_id"],
        "cell_id": cell_id,
        "target": dict(target),
        "environment": dict(manifest["environment"]),
        "input": {
            "fixture_id": fixture["id"],
            "fixture_sha256": fixture["archive_sha256"],
            "seed_git_sha": seed_sha,
            "workflow_id": workflow_id,
            "prompt": workflow["prompt"],
            "permission_contract": workflow["permission_contract"],
            "failure_injection": workflow["failure_injection"],
            "timeout_seconds": workflow["timeout_seconds"],
            "repetition": repetition,
            "model_route": manifest["gateway"]["model_route"],
        },
        "result_path": "evidence/result.json",
        "live_execution_started": False,
    }
    _write_json(destination / "cell.json", cell)
    return cell


def build_artifact_entry(
    root: Path,
    artifact_path: Path,
    *,
    artifact_type: str,
    producer: str,
    created_at: str,
) -> dict[str, Any]:
    """Build a bounded, content-addressed local artifact reference."""
    lexical_root = root.absolute()
    lexical_artifact = artifact_path.absolute()
    try:
        lexical_artifact.relative_to(lexical_root)
    except ValueError as exc:
        raise ComparisonContractError("artifact escapes the evidence root") from exc
    current = lexical_artifact
    while current != lexical_root:
        if current.is_symlink():
            raise ComparisonContractError("artifact symlinks are forbidden")
        current = current.parent
    if lexical_root.is_symlink():
        raise ComparisonContractError("artifact root symlinks are forbidden")
    resolved_root = root.resolve(strict=True)
    resolved_artifact = artifact_path.resolve(strict=True)
    try:
        relative = resolved_artifact.relative_to(resolved_root)
    except ValueError as exc:
        raise ComparisonContractError("artifact escapes the evidence root") from exc
    if not resolved_artifact.is_file():
        raise ComparisonContractError("artifact must be a regular file")
    _required_text(artifact_type, "artifact.type")
    _required_text(producer, "artifact.producer")
    _required_text(created_at, "artifact.created_at")
    media_type = (
        mimetypes.guess_type(resolved_artifact.name)[0] or "application/octet-stream"
    )
    return {
        "type": artifact_type,
        "path": relative.as_posix(),
        "sha256": _sha256_file(resolved_artifact),
        "byte_size": resolved_artifact.stat().st_size,
        "media_type": media_type,
        "producer": producer,
        "created_at": created_at,
    }


def _find_unredacted_secret(value: Any, path: str = "$") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower().replace("-", "_")
            if key_text in SECRET_KEYS and not (
                item is None or item == "" or item == "<redacted>"
            ):
                return f"{path}.{key}"
            found = _find_unredacted_secret(item, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_unredacted_secret(item, f"{path}[{index}]")
            if found:
                return found
    return None


def validate_result(cell_dir: Path) -> dict[str, Any]:
    """Validate one completed result and every local artifact digest."""
    cell = _load_json(cell_dir / "cell.json")
    result = _load_json(cell_dir / "evidence" / "result.json")
    for field in (
        "schema_version",
        "comparison_id",
        "cell_id",
        "target",
        "environment",
        "input",
        "timestamps",
        "status",
        "semantic_cells",
        "artifacts",
        "metrics",
        "redaction",
        "reproduction",
    ):
        if field not in result:
            raise ComparisonContractError(f"result is missing {field}")
    if result["schema_version"] != 1 or result["status"] not in RESULT_STATUSES:
        raise ComparisonContractError("invalid result schema version or status")
    for field in ("comparison_id", "cell_id"):
        if result[field] != cell[field]:
            raise ComparisonContractError(
                f"result {field} does not match prepared cell"
            )
    if _mapping(result["target"], "result.target").get("id") != cell["target"]["id"]:
        raise ComparisonContractError("result target does not match prepared cell")
    for section in ("target", "environment", "input"):
        actual = _mapping(result[section], f"result.{section}")
        expected = _mapping(cell[section], f"cell.{section}")
        for key, value in expected.items():
            if actual.get(key) != value:
                raise ComparisonContractError(
                    f"result {section}.{key} does not match prepared cell"
                )
    timestamps = _mapping(result["timestamps"], "timestamps")
    _required_text(timestamps.get("started_at"), "timestamps.started_at")
    _required_text(timestamps.get("finished_at"), "timestamps.finished_at")
    duration = timestamps.get("monotonic_duration_seconds")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or duration < 0
    ):
        raise ComparisonContractError("monotonic duration must be non-negative")
    failure = result.get("failure")
    if result["status"] == "passed" and failure is not None:
        raise ComparisonContractError("passed result cannot contain a failure")
    if result["status"] != "passed":
        failure_map = _mapping(failure, "failure")
        if failure_map.get("class") not in FAILURE_CLASSES:
            raise ComparisonContractError("failure class is missing or invalid")
        _required_text(failure_map.get("reason_code"), "failure.reason_code")
    expected_cells = WORKFLOW_CELLS[str(cell["input"]["workflow_id"])]
    semantic_rows = _sequence(result["semantic_cells"], "semantic_cells")
    actual_cells: set[str] = set()
    for row in semantic_rows:
        semantic = _mapping(row, "semantic_cell")
        cell_id = _required_text(semantic.get("id"), "semantic_cell.id")
        actual_cells.add(cell_id)
        if semantic.get("status") not in SEMANTIC_STATUSES:
            raise ComparisonContractError(f"invalid semantic status for {cell_id}")
        if semantic.get("status") != "passed":
            _required_text(semantic.get("reason_code"), f"{cell_id}.reason_code")
        if not isinstance(semantic.get("evidence_refs"), list):
            raise ComparisonContractError(f"{cell_id}.evidence_refs must be an array")
    if actual_cells != expected_cells or len(semantic_rows) != len(expected_cells):
        raise ComparisonContractError(
            "result must contain each workflow semantic cell once"
        )
    artifacts_root = (cell_dir / "evidence").resolve()
    for item in _sequence(result["artifacts"], "artifacts"):
        artifact = _mapping(item, "artifact")
        relative = Path(_required_text(artifact.get("path"), "artifact.path"))
        for field in ("type", "sha256", "media_type", "producer", "created_at"):
            _required_text(artifact.get(field), f"artifact.{field}")
        byte_size = artifact.get("byte_size")
        if (
            not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 0
        ):
            raise ComparisonContractError("artifact.byte_size must be non-negative")
        if relative.is_absolute() or ".." in relative.parts:
            raise ComparisonContractError("artifact path must stay below evidence root")
        lexical = (cell_dir / "evidence" / relative).absolute()
        current = lexical
        lexical_root = (cell_dir / "evidence").absolute()
        while current != lexical_root:
            if current.is_symlink():
                raise ComparisonContractError("artifact symlinks are forbidden")
            current = current.parent
        path = (artifacts_root / relative).resolve(strict=True)
        try:
            path.relative_to(artifacts_root)
        except ValueError as exc:
            raise ComparisonContractError(
                "artifact path escapes evidence root"
            ) from exc
        if artifact.get("byte_size") != path.stat().st_size or artifact.get(
            "sha256"
        ) != _sha256_file(path):
            raise ComparisonContractError(
                f"artifact digest or size does not match: {relative}"
            )
    secret_path = _find_unredacted_secret(result)
    if secret_path:
        raise ComparisonContractError(f"unredacted secret-like field at {secret_path}")
    redaction = _mapping(result["redaction"], "redaction")
    if (
        redaction.get("content_capture_enabled") is not False
        or redaction.get("secret_scan_passed") is not True
    ):
        raise ComparisonContractError(
            "redaction evidence must disable content capture and pass secret scan"
        )
    if (
        cell["input"]["workflow_id"] == "policy-refusal-bypass"
        and redaction.get("canary_found") is not False
    ):
        raise ComparisonContractError(
            "policy result must prove that the canary was absent"
        )
    commands = _mapping(result["reproduction"], "reproduction").get("commands")
    if (
        not isinstance(commands, list)
        or not commands
        or any(
            not isinstance(command, list)
            or not command
            or any(not isinstance(arg, str) or not arg for arg in command)
            for command in commands
        )
    ):
        raise ComparisonContractError("reproduction commands are required")
    return {
        "comparison_id": result["comparison_id"],
        "cell_id": result["cell_id"],
        "status": result["status"],
        "semantic_cells": len(actual_cells),
        "artifacts": len(result["artifacts"]),
        "valid": True,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    """Build the comparison plumbing CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    seal = commands.add_parser("seal-fixture")
    seal.add_argument("--output", type=Path, required=True)
    prepare = commands.add_parser("prepare-cell")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--target", choices=sorted(TARGET_IDS), required=True)
    prepare.add_argument("--workflow", choices=sorted(WORKFLOW_CELLS), required=True)
    prepare.add_argument("--repetition", type=int, required=True)
    artifact = commands.add_parser("artifact-entry")
    artifact.add_argument("--root", type=Path, required=True)
    artifact.add_argument("--path", type=Path, required=True)
    artifact.add_argument("--type", required=True)
    artifact.add_argument("--producer", required=True)
    artifact.add_argument("--created-at", default=None)
    result = commands.add_parser("validate-result")
    result.add_argument("--cell-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one offline comparison-plumbing operation."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate_manifest(args.manifest)
        elif args.command == "seal-fixture":
            manifest = _load_json(args.manifest)
            fixture = _mapping(manifest["fixture"], "fixture")
            source = _resolve_repo_path(fixture["source"], "fixture.source")
            content = fixture_archive_bytes(source, str(fixture["id"]))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(content)
            payload = {
                "output": str(args.output),
                "sha256": _sha256_bytes(content),
                "byte_size": len(content),
            }
        elif args.command == "prepare-cell":
            payload = prepare_cell(
                args.manifest,
                args.output,
                target_id=args.target,
                workflow_id=args.workflow,
                repetition=args.repetition,
            )
        elif args.command == "artifact-entry":
            payload = build_artifact_entry(
                args.root,
                args.path,
                artifact_type=args.type,
                producer=args.producer,
                created_at=args.created_at or _utc_now(),
            )
        else:
            payload = validate_result(args.cell_dir)
    except (ComparisonContractError, OSError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
