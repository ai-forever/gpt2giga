"""Durable compensating transactions across supported integration targets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from gpt2giga_harness.external_mcp import HARNESS_MANAGED_MCP_TARGET_ID
from gpt2giga_harness.integration_flows import (
    IntegrationFlowService,
    IntegrationFlowStatus,
    _public_plan as _child_public_plan,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationComponentType,
    integration_package_semantic_hash,
)
from gpt2giga_harness.portable_skills import (
    CLAUDE_SKILL_TARGET_ID,
    CODEX_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock


INTEGRATION_GROUP_SCHEMA_VERSION = 1
MAX_INTEGRATION_GROUPS = 200
_GROUP_ID_RE = re.compile(r"group_[0-9a-f]{32}\Z")
_PLAN_ID_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_AUTHORITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_SKILL_TARGETS = (
    CODEX_SKILL_TARGET_ID,
    CLAUDE_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
)
_MCP_TARGETS = (
    "codex-mcp",
    "claude-mcp",
    "gemini-mcp",
    HARNESS_MANAGED_MCP_TARGET_ID,
)


class IntegrationGroupError(RuntimeError):
    """Base error for all-target integration operations."""


class IntegrationGroupNotFoundError(IntegrationGroupError):
    """Raised when a group id is unknown."""


class IntegrationGroupConflictError(IntegrationGroupError):
    """Raised when approval, recovery, or rollback is unsafe."""


class IntegrationGroupStatus(str, Enum):
    """Durable group lifecycle states."""

    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    VERIFIED = "verified"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    REPAIR_REQUIRED = "repair_required"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class IntegrationGroupChild:
    """One exact child preview and current transaction state."""

    target_id: str
    scope: str
    flow_id: str
    plan_id: str
    status: str
    receipt_id: str | None = None
    verification_status: str = "not_started"
    rollback_status: str = "not_started"
    error_code: str | None = None


@dataclass(frozen=True)
class IntegrationGroupRecord:
    """Private journal for one recoverable cross-root operation."""

    id: str
    plan_id: str
    status: IntegrationGroupStatus
    component: str
    source: str
    catalog_id: str
    package_id: str
    package_version: str
    manifest_sha256: str
    target_mode: str
    target_ids: tuple[str, ...]
    request: Mapping[str, Any]
    children: tuple[IntegrationGroupChild, ...]
    aggregate_risk: str
    approval_hash: str | None
    repair_actions: tuple[str, ...]
    error_code: str | None
    created_at: str
    updated_at: str


class GroupedIntegrationService:
    """Coordinate exact child transactions through durable compensation."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        flow_service: IntegrationFlowService | None = None,
        now: Any | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root = self.data_dir / "integrations"
        self.path = self.root / "groups.json"
        self.lock_path = self.root / ".groups.json.lock"
        self.flows = flow_service or IntegrationFlowService(self.data_dir)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def list(self) -> tuple[IntegrationGroupRecord, ...]:
        """Return recent group operations in reverse update order."""
        return tuple(
            sorted(
                self._read().values(), key=lambda item: item.updated_at, reverse=True
            )[:MAX_INTEGRATION_GROUPS]
        )

    def get(self, group_id: str) -> IntegrationGroupRecord:
        """Return one exact durable group record."""
        _validate_group_id(group_id)
        record = self._read().get(group_id)
        if record is None:
            raise IntegrationGroupNotFoundError(group_id)
        return record

    def preview(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Preview every explicit supported target before any target mutation."""
        request = _normalize_request(payload)
        self.flows.inventory()
        entry = self.flows.catalog.get(request["catalog_id"])
        if entry is None:
            raise ValueError("group catalog selection was not found")
        if entry.package is not None:
            component_types = {item.type for item in entry.package.components}
            if component_types == {IntegrationComponentType.SKILL}:
                component = "skill"
                supported = {item.target_id for item in entry.package.compatibility}
                target_ids = tuple(item for item in _SKILL_TARGETS if item in supported)
                package_id = entry.package.id
                package_version = entry.package.version
                manifest_hash = integration_package_semantic_hash(entry.package)
            else:
                raise ValueError("all-target groups support only Skills or MCP")
        elif entry.mcp_response is not None:
            component = "mcp"
            target_ids = _MCP_TARGETS
            package_id = entry.package_id
            package_version = entry.version
            manifest_hash = entry.content_hash
        else:
            raise ValueError("catalog entry is discovery-only and cannot be installed")
        if not target_ids:
            raise ValueError("catalog package has no supported all-target expansion")

        child_payloads = [
            {
                "source": "catalog",
                "catalog_id": request["catalog_id"],
                "target_id": target_id,
                "scope": request["scope"],
                "workspace": request.get("workspace"),
                "configuration": request["configuration"],
            }
            for target_id in target_ids
        ]
        previews: list[dict[str, Any]] = []
        try:
            for child_payload in child_payloads:
                preview = self.flows.preview(child_payload)
                if not preview["plan"]["target"]["executable"]:
                    raise ValueError("all-target child requires an executable owner")
                previews.append(preview)
        except Exception as exc:
            raise ValueError("all child previews must succeed before approval") from exc

        semantic = {
            "schema_version": INTEGRATION_GROUP_SCHEMA_VERSION,
            "source": "catalog",
            "catalog_id": request["catalog_id"],
            "package_id": package_id,
            "package_version": package_version,
            "manifest_sha256": manifest_hash,
            "component": component,
            "target_mode": "all_supported",
            "target_ids": list(target_ids),
            "scope": request["scope"],
            "workspace": request.get("workspace"),
            "children": [
                {
                    "target_id": item["plan"]["target"]["id"],
                    "flow_id": item["flow"]["id"],
                    "plan_id": item["plan"]["plan_id"],
                }
                for item in previews
            ],
        }
        plan_id = f"plan_{_json_hash(semantic)}"
        aggregate_risk = _aggregate_risk(previews)
        timestamp = self._timestamp()
        record = IntegrationGroupRecord(
            id=f"group_{uuid4().hex}",
            plan_id=plan_id,
            status=IntegrationGroupStatus.AWAITING_APPROVAL,
            component=component,
            source="catalog",
            catalog_id=request["catalog_id"],
            package_id=package_id,
            package_version=package_version,
            manifest_sha256=manifest_hash,
            target_mode="all_supported",
            target_ids=target_ids,
            request=request,
            children=tuple(
                IntegrationGroupChild(
                    target_id=item["plan"]["target"]["id"],
                    scope=item["plan"]["target"]["scope"],
                    flow_id=item["flow"]["id"],
                    plan_id=item["plan"]["plan_id"],
                    status=item["flow"]["status"],
                )
                for item in previews
            ),
            aggregate_risk=aggregate_risk,
            approval_hash=None,
            repair_actions=(),
            error_code=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._put(record)
        return {
            "group": integration_group_record_to_dict(record),
            "plan": _public_plan(record, previews),
        }

    def apply(
        self,
        group_id: str,
        *,
        plan_id: str,
        authority: str,
        allow_network: bool = False,
        allow_user_home: bool = False,
        native_consent_acknowledged: bool = False,
    ) -> dict[str, Any]:
        """Apply ordered children and compensate safely after any failure."""
        record = self.get(group_id)
        _validate_plan_id(plan_id)
        _validate_authority(authority)
        if record.plan_id != plan_id:
            raise IntegrationGroupConflictError("approval does not match group preview")
        if _record_plan_id(record) != record.plan_id:
            raise IntegrationGroupConflictError("group target expansion is stale")
        if record.status in {
            IntegrationGroupStatus.VERIFIED,
            IntegrationGroupStatus.COMPENSATED,
            IntegrationGroupStatus.ROLLED_BACK,
        }:
            return {"group": integration_group_record_to_dict(record)}
        if record.status is not IntegrationGroupStatus.AWAITING_APPROVAL:
            raise IntegrationGroupConflictError("group requires recovery in its state")
        child_plans = [self._child_plan(item) for item in record.children]
        network = any(item["permissions"]["network"] for item in child_plans)
        native = any(item["permissions"]["native_consent"] for item in child_plans)
        user_home = any(item["permissions"]["user_home"] for item in child_plans)
        if network and not allow_network:
            raise IntegrationGroupConflictError(
                "group network access requires approval"
            )
        if native and not native_consent_acknowledged:
            raise IntegrationGroupConflictError(
                "group native consent requires acknowledgement"
            )
        if user_home and not allow_user_home:
            raise IntegrationGroupConflictError(
                "group user-home access requires approval"
            )
        approval_hash = _json_hash(
            {
                "plan_id": plan_id,
                "authority": authority,
                "allow_network": allow_network,
                "allow_user_home": allow_user_home,
                "native_consent_acknowledged": native_consent_acknowledged,
            }
        )
        record = self._transition(
            record,
            IntegrationGroupStatus.APPLYING,
            approval_hash=approval_hash,
        )
        try:
            for child in record.children:
                result = self.flows.apply(
                    child.flow_id,
                    plan_id=child.plan_id,
                    authority=authority,
                    allow_network=allow_network,
                    allow_user_home=allow_user_home,
                    native_consent_acknowledged=native_consent_acknowledged,
                )
                flow = result["flow"]
                if flow["status"] != IntegrationFlowStatus.VERIFIED.value:
                    raise IntegrationGroupError("group child did not verify")
                record = self._update_child(
                    record,
                    child.target_id,
                    status=flow["status"],
                    verification_status=flow["verification_status"],
                    receipt_id=flow.get("receipt_id"),
                )
            record = self._transition(record, IntegrationGroupStatus.VERIFIED)
            return {"group": integration_group_record_to_dict(record)}
        except Exception as exc:
            return self._compensate(record, cause=exc)

    def recover(self, group_id: str) -> dict[str, Any]:
        """Deterministically compensate interrupted or repair-required work."""
        record = self.get(group_id)
        if record.status in {
            IntegrationGroupStatus.COMPENSATED,
            IntegrationGroupStatus.ROLLED_BACK,
            IntegrationGroupStatus.VERIFIED,
        }:
            return {"group": integration_group_record_to_dict(record)}
        if record.status not in {
            IntegrationGroupStatus.APPLYING,
            IntegrationGroupStatus.COMPENSATING,
            IntegrationGroupStatus.REPAIR_REQUIRED,
            IntegrationGroupStatus.ROLLING_BACK,
        }:
            raise IntegrationGroupConflictError("group has no recoverable work")
        terminal_rollback = record.status is IntegrationGroupStatus.ROLLING_BACK or (
            record.status is IntegrationGroupStatus.REPAIR_REQUIRED
            and record.error_code == "rollback_failed"
        )
        return self._compensate(
            record,
            cause=None,
            terminal_rollback=terminal_rollback,
        )

    def rollback(self, group_id: str) -> dict[str, Any]:
        """Roll back every verified child in reverse deterministic order."""
        record = self.get(group_id)
        if record.status is IntegrationGroupStatus.ROLLED_BACK:
            return {"group": integration_group_record_to_dict(record)}
        if record.status is not IntegrationGroupStatus.VERIFIED:
            raise IntegrationGroupConflictError("group is not verified")
        record = self._transition(record, IntegrationGroupStatus.ROLLING_BACK)
        return self._compensate(record, cause=None, terminal_rollback=True)

    def _compensate(
        self,
        record: IntegrationGroupRecord,
        *,
        cause: Exception | None,
        terminal_rollback: bool = False,
    ) -> dict[str, Any]:
        state = (
            IntegrationGroupStatus.ROLLING_BACK
            if terminal_rollback
            else IntegrationGroupStatus.COMPENSATING
        )
        record = self._transition(record, state, error_code=_error_code(cause))
        repair_actions: list[str] = []
        for child in reversed(record.children):
            try:
                flow = self.flows.get(child.flow_id)
            except Exception:
                repair_actions.append(
                    f"inspect-child:{child.target_id}:{child.flow_id}"
                )
                continue
            if flow.status is IntegrationFlowStatus.ROLLED_BACK:
                record = self._update_child(
                    record, child.target_id, rollback_status="rolled_back"
                )
                continue
            if flow.status is not IntegrationFlowStatus.VERIFIED:
                continue
            try:
                result = self.flows.rollback(child.flow_id)["flow"]
                record = self._update_child(
                    record,
                    child.target_id,
                    status=result["status"],
                    rollback_status="rolled_back",
                )
            except Exception:
                repair_actions.append(
                    f"retry-safe-rollback:{child.target_id}:{child.flow_id}"
                )
                record = self._update_child(
                    record,
                    child.target_id,
                    rollback_status="repair_required",
                    error_code="rollback_failed",
                )
        if repair_actions:
            record = self._transition(
                record,
                IntegrationGroupStatus.REPAIR_REQUIRED,
                repair_actions=tuple(repair_actions),
                error_code=_error_code(cause) or "rollback_failed",
            )
        else:
            record = self._transition(
                record,
                (
                    IntegrationGroupStatus.ROLLED_BACK
                    if terminal_rollback
                    else IntegrationGroupStatus.COMPENSATED
                ),
                repair_actions=(),
                error_code=_error_code(cause),
            )
        return {"group": integration_group_record_to_dict(record)}

    def _child_plan(self, child: IntegrationGroupChild) -> dict[str, Any]:
        flow = self.flows.get(child.flow_id)
        resolved = self.flows._resolve_preview(flow.request, existing=True)
        plan = _child_public_plan(flow.request, resolved)
        if plan["plan_id"] != child.plan_id:
            raise IntegrationGroupConflictError("group child preview is stale")
        return plan

    def _update_child(
        self,
        record: IntegrationGroupRecord,
        target_id: str,
        **changes: Any,
    ) -> IntegrationGroupRecord:
        children = tuple(
            replace(item, **changes) if item.target_id == target_id else item
            for item in record.children
        )
        updated = replace(record, children=children, updated_at=self._timestamp())
        self._put(updated)
        return updated

    def _transition(
        self,
        record: IntegrationGroupRecord,
        status: IntegrationGroupStatus,
        *,
        approval_hash: str | None = None,
        repair_actions: tuple[str, ...] | None = None,
        error_code: str | None = None,
    ) -> IntegrationGroupRecord:
        updated = replace(
            record,
            status=status,
            approval_hash=(
                approval_hash if approval_hash is not None else record.approval_hash
            ),
            repair_actions=(
                repair_actions if repair_actions is not None else record.repair_actions
            ),
            error_code=error_code,
            updated_at=self._timestamp(),
        )
        self._put(updated)
        return updated

    def _timestamp(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _put(self, record: IntegrationGroupRecord) -> None:
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            records = self._read_unlocked()
            records[record.id] = record
            if len(records) > MAX_INTEGRATION_GROUPS:
                ordered = sorted(records.values(), key=lambda item: item.updated_at)
                records = {item.id: item for item in ordered[-MAX_INTEGRATION_GROUPS:]}
            self._write_unlocked(records)

    def _read(self) -> dict[str, IntegrationGroupRecord]:
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            return self._read_unlocked()

    def _read_unlocked(self) -> dict[str, IntegrationGroupRecord]:
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or not self.path.is_file():
            raise IntegrationGroupError("integration group state is unsafe")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise IntegrationGroupError(
                "integration group state is unreadable"
            ) from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != INTEGRATION_GROUP_SCHEMA_VERSION
            or not isinstance(payload.get("groups"), list)
            or len(payload["groups"]) > MAX_INTEGRATION_GROUPS
        ):
            raise IntegrationGroupError("integration group state is invalid")
        records = tuple(_record_from_dict(item) for item in payload["groups"])
        if len({item.id for item in records}) != len(records):
            raise IntegrationGroupError("integration group state has duplicate ids")
        return {item.id: item for item in records}

    def _write_unlocked(self, records: Mapping[str, IntegrationGroupRecord]) -> None:
        payload = {
            "schema_version": INTEGRATION_GROUP_SCHEMA_VERSION,
            "groups": [_private_record(records[key]) for key in sorted(records)],
        }
        fd, raw_path = tempfile.mkstemp(prefix=".groups-", dir=self.root)
        temp_path = Path(raw_path)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _ensure_root(self) -> None:
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise IntegrationGroupError("integration group root is unsafe")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)


def integration_group_record_to_dict(record: IntegrationGroupRecord) -> dict[str, Any]:
    """Return one content-free group lifecycle projection."""
    return {
        "id": record.id,
        "plan_id": record.plan_id,
        "status": record.status.value,
        "component": record.component,
        "source": record.source,
        "catalog_id": record.catalog_id,
        "package_id": record.package_id,
        "package_version": record.package_version,
        "manifest_sha256": record.manifest_sha256,
        "target_mode": record.target_mode,
        "target_ids": list(record.target_ids),
        "aggregate_risk": record.aggregate_risk,
        "approval_hash": record.approval_hash,
        "children": [
            {
                "target_id": item.target_id,
                "scope": item.scope,
                "flow_id": item.flow_id,
                "plan_id": item.plan_id,
                "status": item.status,
                "verification_status": item.verification_status,
                "rollback_status": item.rollback_status,
                "error_code": item.error_code,
            }
            for item in record.children
        ],
        "repair_actions": list(record.repair_actions),
        "error_code": record.error_code,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "rollback_available": record.status is IntegrationGroupStatus.VERIFIED,
        "content_free": True,
    }


def _public_plan(
    record: IntegrationGroupRecord, previews: list[dict[str, Any]]
) -> dict[str, Any]:
    permissions = {
        "network": any(item["plan"]["permissions"]["network"] for item in previews),
        "native_consent": any(
            item["plan"]["permissions"]["native_consent"] for item in previews
        ),
        "user_home": any(item["plan"]["permissions"]["user_home"] for item in previews),
    }
    return {
        "plan_id": record.plan_id,
        "package": {
            "id": record.package_id,
            "version": record.package_version,
            "manifest_sha256": record.manifest_sha256,
        },
        "component": record.component,
        "target_mode": "all_supported",
        "target_ids": list(record.target_ids),
        "aggregate_risk": record.aggregate_risk,
        "permissions": permissions,
        "children": [
            {
                "target_id": item["plan"]["target"]["id"],
                "scope": item["plan"]["target"]["scope"],
                "plan_id": item["plan"]["plan_id"],
                "configuration_diff": item["plan"]["configuration"]["diff"],
                "restart_required": item["plan"]["configuration"]["restart_required"],
                "verification_steps": item["plan"]["verification_steps"],
                "rollback_steps": item["plan"]["rollback_steps"],
            }
            for item in previews
        ],
        "atomicity": "recoverable_compensating_transaction",
        "approval_required": True,
        "content_free": True,
    }


def _normalize_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("integration group request must be an object")
    allowed = {
        "source",
        "catalog_id",
        "scope",
        "workspace",
        "configuration",
        "target_mode",
    }
    if set(payload) - allowed:
        raise ValueError("integration group request contains unknown fields")
    if payload.get("source", "catalog") != "catalog":
        raise ValueError("all-target groups require a reviewed catalog source")
    if payload.get("target_mode", "all_supported") != "all_supported":
        raise ValueError("integration group target_mode must be all_supported")
    catalog_id = str(payload.get("catalog_id") or "")
    if not catalog_id or len(catalog_id) > 256:
        raise ValueError("integration group catalog_id is invalid")
    scope = InstallationScope(str(payload.get("scope") or "managed_home"))
    if scope is InstallationScope.USER_HOME:
        raise ValueError("all-target user-home expansion is not implicit")
    workspace = payload.get("workspace")
    if scope is InstallationScope.PROJECT:
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("project group requires an explicit workspace")
        workspace = str(Path(workspace).expanduser().resolve())
    elif workspace is not None:
        raise ValueError("managed-home group cannot include a workspace")
    configuration = payload.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ValueError("integration group configuration must be an object")
    return {
        "source": "catalog",
        "catalog_id": catalog_id,
        "scope": scope.value,
        "workspace": workspace,
        "configuration": _json_value(configuration),
        "target_mode": "all_supported",
    }


def _aggregate_risk(previews: list[dict[str, Any]]) -> str:
    decisions = {item["plan"]["risk"]["decision"] for item in previews}
    for decision in ("blocked", "provider_handoff", "review_required", "reviewed"):
        if decision in decisions:
            return decision
    return sorted(decisions)[0] if decisions else "review_required"


def _record_plan_id(record: IntegrationGroupRecord) -> str:
    semantic = {
        "schema_version": INTEGRATION_GROUP_SCHEMA_VERSION,
        "source": record.source,
        "catalog_id": record.catalog_id,
        "package_id": record.package_id,
        "package_version": record.package_version,
        "manifest_sha256": record.manifest_sha256,
        "component": record.component,
        "target_mode": record.target_mode,
        "target_ids": list(record.target_ids),
        "scope": record.request["scope"],
        "workspace": record.request.get("workspace"),
        "children": [
            {
                "target_id": item.target_id,
                "flow_id": item.flow_id,
                "plan_id": item.plan_id,
            }
            for item in record.children
        ],
    }
    return f"plan_{_json_hash(semantic)}"


def _private_record(record: IntegrationGroupRecord) -> dict[str, Any]:
    return {
        **integration_group_record_to_dict(record),
        "request": record.request,
        "children": [item.__dict__ for item in record.children],
    }


def _record_from_dict(value: Any) -> IntegrationGroupRecord:
    if not isinstance(value, Mapping):
        raise IntegrationGroupError("integration group record is invalid")
    try:
        record = IntegrationGroupRecord(
            id=str(value["id"]),
            plan_id=str(value["plan_id"]),
            status=IntegrationGroupStatus(str(value["status"])),
            component=str(value["component"]),
            source=str(value["source"]),
            catalog_id=str(value["catalog_id"]),
            package_id=str(value["package_id"]),
            package_version=str(value["package_version"]),
            manifest_sha256=str(value["manifest_sha256"]),
            target_mode=str(value["target_mode"]),
            target_ids=tuple(str(item) for item in value["target_ids"]),
            request=_normalize_request(value["request"]),
            children=tuple(
                IntegrationGroupChild(
                    target_id=str(item["target_id"]),
                    scope=str(item["scope"]),
                    flow_id=str(item["flow_id"]),
                    plan_id=str(item["plan_id"]),
                    status=str(item["status"]),
                    receipt_id=(
                        str(item["receipt_id"]) if item.get("receipt_id") else None
                    ),
                    verification_status=str(item["verification_status"]),
                    rollback_status=str(item["rollback_status"]),
                    error_code=(
                        str(item["error_code"]) if item.get("error_code") else None
                    ),
                )
                for item in value["children"]
            ),
            aggregate_risk=str(value["aggregate_risk"]),
            approval_hash=(
                str(value["approval_hash"]) if value.get("approval_hash") else None
            ),
            repair_actions=tuple(str(item) for item in value["repair_actions"]),
            error_code=(str(value["error_code"]) if value.get("error_code") else None),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrationGroupError("integration group record is invalid") from exc
    _validate_group_id(record.id)
    _validate_plan_id(record.plan_id)
    return record


def _json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("integration group payload is too deep")
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError("integration group text is too long")
        return value
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("integration group object is too large")
        return {
            str(key): _json_value(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise ValueError("integration group list is too large")
        return [_json_value(item, depth=depth + 1) for item in value]
    raise ValueError("integration group payload must contain JSON values only")


def _error_code(exc: Exception | None) -> str | None:
    return type(exc).__name__ if exc is not None else None


def _validate_group_id(value: str) -> None:
    if not _GROUP_ID_RE.fullmatch(value):
        raise ValueError("integration group id is invalid")


def _validate_plan_id(value: str) -> None:
    if not _PLAN_ID_RE.fullmatch(value):
        raise ValueError("integration group plan id is invalid")


def _validate_authority(value: str) -> None:
    if not _AUTHORITY_RE.fullmatch(value):
        raise ValueError("integration group approval authority is invalid")


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "GroupedIntegrationService",
    "IntegrationGroupConflictError",
    "IntegrationGroupError",
    "IntegrationGroupNotFoundError",
    "IntegrationGroupRecord",
    "IntegrationGroupStatus",
    "integration_group_record_to_dict",
]
