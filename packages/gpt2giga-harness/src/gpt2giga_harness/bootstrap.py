"""Reviewed, reversible first-run bootstrap workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.doctor import build_doctor_report
from gpt2giga_harness.project import init_project_config, project_config_path
from gpt2giga_harness.sessions.locking import exclusive_file_lock


BOOTSTRAP_SCHEMA_VERSION = 1
BOOTSTRAP_PREVIEW_KIND = "gpt2giga_harness_bootstrap_preview"
BOOTSTRAP_APPLICATION_KIND = "gpt2giga_harness_bootstrap_application"
BOOTSTRAP_STEP_PROJECT = "project_starter"
BOOTSTRAP_STEP_MANAGED_STATE = "managed_state"
BOOTSTRAP_STEP_IDS = (BOOTSTRAP_STEP_MANAGED_STATE, BOOTSTRAP_STEP_PROJECT)
MANAGED_STATE_DIRECTORIES = ("integrations", "native", "support")
MAX_BOOTSTRAP_FILE_BYTES = 1_000_000
_PLAN_ID_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_APPLICATION_ID_RE = re.compile(r"bootstrap_[0-9a-f]{32}\Z")


class BootstrapError(ValueError):
    """Base error for reviewed bootstrap operations."""


class BootstrapConflictError(BootstrapError):
    """Raised when a reviewed bootstrap plan or rollback is stale."""


class BootstrapNotFoundError(BootstrapError):
    """Raised when a bootstrap application journal does not exist."""


class BootstrapService:
    """Preview, apply, inspect, and roll back local reversible setup."""

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.data_root = Path(config.data_dir).expanduser().resolve()
        self.root = self.data_root / "bootstrap"
        self.applications_root = self.root / "applications"
        root_identity = _path_identity(self.data_root)
        self.lock_path = (
            Path(tempfile.gettempdir())
            / f"gpt2giga-bootstrap-{root_identity.removeprefix('path_')}.lock"
        )

    def preview(
        self,
        *,
        workspace: str | Path | None = None,
    ) -> dict[str, Any]:
        """Build a deterministic, side-effect-free local setup preview."""
        project_root = _resolve_workspace(workspace)
        basis = self._basis(project_root)
        steps = _step_projections(basis)
        plan_id = _plan_id(basis, steps)
        doctor = build_doctor_report(self.config, workspace=project_root)
        return {
            "schema_version": BOOTSTRAP_SCHEMA_VERSION,
            "kind": BOOTSTRAP_PREVIEW_KIND,
            "plan": {
                "plan_id": plan_id,
                "workspace_id": basis["workspace_id"],
                "data_root_id": basis["data_root_id"],
                "steps": steps,
                "all_reversible_step_ids": [
                    step["id"] for step in steps if step["available"]
                ],
                "automatic_external_effects": False,
                "support_export": ("giga doctor --json --output doctor-support.json"),
                "remedies": _doctor_remedies(doctor),
            },
            "discovery": doctor,
        }

    def apply(
        self,
        *,
        plan_id: str,
        selected_steps: Sequence[str] = (),
        all_reversible: bool = False,
        workspace: str | Path | None = None,
    ) -> dict[str, Any]:
        """Apply only explicitly selected current reversible setup steps."""
        _validate_plan_id(plan_id)
        if all_reversible and selected_steps:
            raise BootstrapError(
                "choose explicit bootstrap steps or --all-reversible, not both"
            )
        if len(set(selected_steps)) != len(selected_steps):
            raise BootstrapError("bootstrap step selection contains duplicates")
        project_root = _resolve_workspace(workspace)
        initial_basis = self._basis(project_root)
        initial_steps = _step_projections(initial_basis)
        if _plan_id(initial_basis, initial_steps) != plan_id:
            raise BootstrapConflictError("bootstrap plan is stale")
        available = {step["id"] for step in initial_steps if step["available"] is True}
        selected = (
            tuple(step_id for step_id in BOOTSTRAP_STEP_IDS if step_id in available)
            if all_reversible
            else tuple(selected_steps)
        )
        if not selected:
            raise BootstrapError("select at least one available bootstrap step")
        unknown = sorted(set(selected) - set(BOOTSTRAP_STEP_IDS))
        if unknown:
            raise BootstrapError(f"unknown bootstrap step: {unknown[0]}")
        unavailable = sorted(set(selected) - available)
        if unavailable:
            raise BootstrapConflictError(
                f"bootstrap step is not currently available: {unavailable[0]}"
            )
        if not self.data_root.exists() and BOOTSTRAP_STEP_MANAGED_STATE not in selected:
            raise BootstrapError(
                "managed_state must be selected to initialize private bootstrap state"
            )

        with exclusive_file_lock(self.lock_path):
            current_basis = self._basis(project_root)
            current_steps = _step_projections(current_basis)
            if _plan_id(current_basis, current_steps) != plan_id:
                raise BootstrapConflictError("bootstrap plan changed before apply")
            self.applications_root.mkdir(parents=True, exist_ok=True)
            os.chmod(self.data_root, 0o700)
            application_id = f"bootstrap_{uuid4().hex}"
            journal = {
                "schema_version": BOOTSTRAP_SCHEMA_VERSION,
                "kind": BOOTSTRAP_APPLICATION_KIND,
                "application_id": application_id,
                "plan_id": plan_id,
                "workspace_id": current_basis["workspace_id"],
                "data_root_id": current_basis["data_root_id"],
                "status": "applying",
                "selected_steps": list(selected),
                "created": {
                    BOOTSTRAP_STEP_MANAGED_STATE: {
                        "directories": list(
                            current_basis["managed_state"]["missing_directories"]
                        )
                        if BOOTSTRAP_STEP_MANAGED_STATE in selected
                        else []
                    },
                    BOOTSTRAP_STEP_PROJECT: (
                        current_basis["project_starter"]["manifest"]
                        if BOOTSTRAP_STEP_PROJECT in selected
                        else {"directories": [], "files": []}
                    ),
                },
                "error_code": None,
            }
            self._write_journal(journal)
            try:
                for step_id in BOOTSTRAP_STEP_IDS:
                    if step_id == BOOTSTRAP_STEP_MANAGED_STATE and step_id in selected:
                        self._apply_managed_state(journal)
                    elif step_id == BOOTSTRAP_STEP_PROJECT and step_id in selected:
                        self._apply_project_starter(project_root, journal)
                journal["status"] = "applied"
                self._write_journal(journal)
            except Exception:
                journal["status"] = "failed"
                journal["error_code"] = "bootstrap_apply_failed"
                self._write_journal(journal)
                raise
        return _application_projection(journal)

    def status(self, application_id: str) -> dict[str, Any]:
        """Return one bounded bootstrap application projection."""
        return _application_projection(self._read_journal(application_id))

    def rollback(
        self,
        application_id: str,
        *,
        workspace: str | Path | None = None,
    ) -> dict[str, Any]:
        """Remove only unchanged paths created by one bootstrap application."""
        project_root = _resolve_workspace(workspace)
        with exclusive_file_lock(self.lock_path):
            journal = self._read_journal(application_id)
            if journal["status"] == "rolled_back":
                return _application_projection(journal)
            if journal["status"] not in {"applied", "failed"}:
                raise BootstrapConflictError(
                    "bootstrap application is not rollback-eligible"
                )
            if journal["workspace_id"] != _path_identity(project_root):
                raise BootstrapConflictError("bootstrap workspace identity changed")
            if journal["data_root_id"] != _path_identity(self.data_root):
                raise BootstrapConflictError("bootstrap data-root identity changed")
            self._preflight_rollback(project_root, journal)
            self._rollback_project_starter(project_root, journal)
            self._rollback_managed_state(journal)
            journal["status"] = "rolled_back"
            journal["error_code"] = None
            self._write_journal(journal)
        return _application_projection(journal)

    def _basis(self, project_root: Path) -> dict[str, Any]:
        project_config_exists = project_config_path(project_root).is_file()
        starter_manifest = (
            {"directories": [], "files": []}
            if project_config_exists
            else _project_starter_manifest(project_root)
        )
        missing_directories = [
            name
            for name in MANAGED_STATE_DIRECTORIES
            if not (self.data_root / name).is_dir()
        ]
        return {
            "schema_version": BOOTSTRAP_SCHEMA_VERSION,
            "workspace_id": _path_identity(project_root),
            "data_root_id": _path_identity(self.data_root),
            "data_root_exists": self.data_root.is_dir(),
            "project_starter": {
                "configured": project_config_exists,
                "manifest": starter_manifest,
            },
            "managed_state": {
                "missing_directories": missing_directories,
            },
        }

    def _apply_managed_state(self, journal: Mapping[str, Any]) -> None:
        created = journal["created"][BOOTSTRAP_STEP_MANAGED_STATE]
        for relative in created["directories"]:
            destination = self.data_root / relative
            if destination.exists() and not destination.is_dir():
                raise BootstrapConflictError(
                    "managed-state destination is not a directory"
                )
            destination.mkdir(parents=False, exist_ok=True)

    def _apply_project_starter(
        self,
        project_root: Path,
        journal: Mapping[str, Any],
    ) -> None:
        manifest = journal["created"][BOOTSTRAP_STEP_PROJECT]
        init_project_config(project_root, project_name=project_root.name)
        for item in manifest["files"]:
            path = project_root / item["path"]
            if not path.is_file() or _hash_file(path) != item["sha256"]:
                raise BootstrapConflictError(
                    "generated project starter identity does not match preview"
                )

    def _preflight_rollback(
        self,
        project_root: Path,
        journal: Mapping[str, Any],
    ) -> None:
        project_created = journal["created"][BOOTSTRAP_STEP_PROJECT]
        allowed = {item["path"] for item in project_created["files"]} | set(
            project_created["directories"]
        )
        for item in project_created["files"]:
            path = project_root / item["path"]
            if path.exists() and (
                not path.is_file() or _hash_file(path) != item["sha256"]
            ):
                raise BootstrapConflictError(
                    "created project starter file changed after bootstrap"
                )
        for relative in project_created["directories"]:
            directory = project_root / relative
            if not directory.exists():
                continue
            if not directory.is_dir():
                raise BootstrapConflictError(
                    "created project starter directory changed after bootstrap"
                )
            for descendant in directory.rglob("*"):
                relative_descendant = descendant.relative_to(project_root).as_posix()
                if relative_descendant not in allowed:
                    raise BootstrapConflictError(
                        "created project starter directory contains new paths"
                    )
        managed_created = journal["created"][BOOTSTRAP_STEP_MANAGED_STATE]
        for relative in managed_created["directories"]:
            directory = self.data_root / relative
            if directory.exists() and (
                not directory.is_dir() or any(directory.iterdir())
            ):
                raise BootstrapConflictError(
                    "created managed-state directory is no longer empty"
                )

    def _rollback_project_starter(
        self,
        project_root: Path,
        journal: Mapping[str, Any],
    ) -> None:
        created = journal["created"][BOOTSTRAP_STEP_PROJECT]
        for item in reversed(created["files"]):
            (project_root / item["path"]).unlink(missing_ok=True)
        for relative in sorted(
            created["directories"],
            key=lambda value: (value.count("/"), value),
            reverse=True,
        ):
            directory = project_root / relative
            if directory.exists():
                directory.rmdir()

    def _rollback_managed_state(self, journal: Mapping[str, Any]) -> None:
        created = journal["created"][BOOTSTRAP_STEP_MANAGED_STATE]
        for relative in reversed(created["directories"]):
            directory = self.data_root / relative
            if directory.exists():
                directory.rmdir()

    def _journal_path(self, application_id: str) -> Path:
        _validate_application_id(application_id)
        return self.applications_root / f"{application_id}.json"

    def _read_journal(self, application_id: str) -> dict[str, Any]:
        try:
            payload = json.loads(
                self._journal_path(application_id).read_text(encoding="utf-8")
            )
        except FileNotFoundError as exc:
            raise BootstrapNotFoundError("bootstrap application not found") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BootstrapConflictError(
                "bootstrap application journal is unreadable"
            ) from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != BOOTSTRAP_SCHEMA_VERSION
            or payload.get("kind") != BOOTSTRAP_APPLICATION_KIND
            or payload.get("application_id") != application_id
        ):
            raise BootstrapConflictError("bootstrap application journal is invalid")
        return dict(payload)

    def _write_journal(self, journal: Mapping[str, Any]) -> None:
        destination = self._journal_path(str(journal["application_id"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(journal, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def _step_projections(basis: Mapping[str, Any]) -> list[dict[str, Any]]:
    managed_missing = basis["managed_state"]["missing_directories"]
    starter = basis["project_starter"]
    project_files = starter["manifest"]["files"]
    return [
        {
            "id": BOOTSTRAP_STEP_MANAGED_STATE,
            "title": "Initialize private Harness state directories",
            "available": bool(managed_missing),
            "reversible": True,
            "selected_by_default": bool(managed_missing),
            "effect": "local_private_state",
            "created_directory_count": len(managed_missing),
        },
        {
            "id": BOOTSTRAP_STEP_PROJECT,
            "title": "Create safe starter project configuration",
            "available": not starter["configured"],
            "reversible": True,
            "selected_by_default": not starter["configured"],
            "effect": "workspace_starter_files",
            "created_file_count": len(project_files),
        },
    ]


def _project_starter_manifest(project_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gpt2giga-bootstrap-preview-") as temp:
        generated_root = Path(temp) / "workspace"
        generated_root.mkdir()
        init_project_config(generated_root, project_name=project_root.name)
        directories: list[str] = []
        files: list[dict[str, str]] = []
        for path in sorted(generated_root.rglob("*")):
            relative = path.relative_to(generated_root).as_posix()
            current = project_root / relative
            if path.is_dir():
                if not current.exists():
                    directories.append(relative)
                continue
            if not current.exists():
                files.append({"path": relative, "sha256": _hash_file(path)})
        return {"directories": directories, "files": files}


def _doctor_remedies(report: Mapping[str, Any]) -> list[dict[str, str]]:
    remedies: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for check in report.get("checks") or ():
        if not isinstance(check, Mapping):
            continue
        for remedy in check.get("remediation") or ():
            if not isinstance(remedy, Mapping):
                continue
            message = str(remedy.get("message") or "").strip()
            command = str(remedy.get("command") or "").strip()
            if not message or not command or (message, command) in seen:
                continue
            seen.add((message, command))
            remedies.append({"message": message, "command": command})
            if len(remedies) >= 50:
                return remedies
    return remedies


def _application_projection(journal: Mapping[str, Any]) -> dict[str, Any]:
    created = journal.get("created") or {}
    managed = created.get(BOOTSTRAP_STEP_MANAGED_STATE) or {}
    project = created.get(BOOTSTRAP_STEP_PROJECT) or {}
    return {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "kind": BOOTSTRAP_APPLICATION_KIND,
        "application_id": journal["application_id"],
        "plan_id": journal["plan_id"],
        "status": journal["status"],
        "selected_steps": list(journal["selected_steps"]),
        "created": {
            BOOTSTRAP_STEP_MANAGED_STATE: {
                "directory_count": len(managed.get("directories") or ())
            },
            BOOTSTRAP_STEP_PROJECT: {
                "directory_count": len(project.get("directories") or ()),
                "file_count": len(project.get("files") or ()),
            },
        },
        "rollback_available": journal["status"] in {"applied", "failed"},
        "error_code": journal.get("error_code"),
        "content_free": True,
    }


def _plan_id(
    basis: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
) -> str:
    payload = json.dumps(
        {"basis": basis, "steps": list(steps)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"plan_{hashlib.sha256(payload).hexdigest()}"


def _resolve_workspace(workspace: str | Path | None) -> Path:
    path = Path.cwd() if workspace is None else Path(workspace).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError("bootstrap workspace is unavailable") from exc
    if not resolved.is_dir():
        raise BootstrapError("bootstrap workspace must be a directory")
    return resolved


def _path_identity(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
    return f"path_{digest}"


def _hash_file(path: Path) -> str:
    try:
        size = path.stat().st_size
        if size > MAX_BOOTSTRAP_FILE_BYTES:
            raise BootstrapConflictError("bootstrap-managed file is too large")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BootstrapConflictError("bootstrap-managed file is unreadable") from exc


def _validate_plan_id(plan_id: str) -> None:
    if not isinstance(plan_id, str) or _PLAN_ID_RE.fullmatch(plan_id) is None:
        raise BootstrapError("bootstrap plan id is invalid")


def _validate_application_id(application_id: str) -> None:
    if (
        not isinstance(application_id, str)
        or _APPLICATION_ID_RE.fullmatch(application_id) is None
    ):
        raise BootstrapError("bootstrap application id is invalid")
