"""Durable product lifecycle for installed integrations and extension packs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
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

from gpt2giga_harness.integration_catalog import (
    CatalogConflictError,
    CatalogSourceType,
)
from gpt2giga_harness.integration_flows import (
    BUILTIN_FLOW_TARGETS,
    IntegrationFlowRecord,
    IntegrationFlowService,
    IntegrationFlowStatus,
)
from gpt2giga_harness.integration_groups import (
    GroupedIntegrationService,
    IntegrationGroupStatus,
)
from gpt2giga_harness.integration_packages import IntegrationComponentType
from gpt2giga_harness.integration_runtime import IntegrationRuntimeStore
from gpt2giga_harness.product_capabilities import IntegrationLifecycle
from gpt2giga_harness.sessions.locking import exclusive_file_lock


INTEGRATION_LIFECYCLE_SCHEMA_VERSION = 1
MAX_LIFECYCLE_OPERATIONS = 500
_OPERATION_ID_RE = re.compile(r"iop_[0-9a-f]{32}\Z")
_PLAN_ID_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,255}\Z")


class IntegrationLifecycleAction(str, Enum):
    """Distinct product verbs; none is an alias for another."""

    ENABLE = "enable"
    DISABLE = "disable"
    UNINSTALL = "uninstall"
    DELETE_DEFINITION = "delete_definition"


class IntegrationLifecycleOperationStatus(str, Enum):
    """Durable lifecycle operation outcomes."""

    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    SUCCEEDED = "succeeded"
    COMPENSATED = "compensated"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class IntegrationLifecycleError(RuntimeError):
    """Base error for product lifecycle operations."""


class IntegrationLifecycleConflictError(IntegrationLifecycleError):
    """Raised when state or approval changed after preview."""


class IntegrationLifecycleNotFoundError(IntegrationLifecycleError):
    """Raised when a lifecycle operation does not exist."""


class IntegrationLifecycleService:
    """Coordinate exact lifecycle previews, approvals, and recovery receipts."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        flow_service: IntegrationFlowService,
        group_service: GroupedIntegrationService,
        runtime_store: IntegrationRuntimeStore | None = None,
        now: Callable[[], datetime] | None = None,
        fault_injector: Callable[[str, str], None] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root = self.data_dir / "integrations"
        self.path = self.root / "lifecycle.json"
        self.lock_path = self.root / ".lifecycle.json.lock"
        self.flows = flow_service
        self.groups = group_service
        self.runtime = runtime_store or IntegrationRuntimeStore(self.data_dir)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._fault_injector = fault_injector

    def inventory(self) -> dict[str, Any]:
        """Return effective installations and a source-derived capability matrix."""
        stored = self._read()
        installations = [
            self._state_projection(flow, stored["states"].get(flow.id))
            for flow in self.flows.list()
            if flow.status
            in {
                IntegrationFlowStatus.VERIFIED,
                IntegrationFlowStatus.ROLLED_BACK,
            }
        ]
        return {
            "schema_version": INTEGRATION_LIFECYCLE_SCHEMA_VERSION,
            "installations": installations,
            "capability_matrix": [
                self._target_capability_projection(target.id)
                for target in BUILTIN_FLOW_TARGETS
            ],
            "operations": [
                self._public_operation(item)
                for item in sorted(
                    stored["operations"].values(),
                    key=lambda value: str(value["updated_at"]),
                    reverse=True,
                )[:MAX_LIFECYCLE_OPERATIONS]
            ],
            "content_free": True,
        }

    def preview_flow(
        self,
        flow_id: str,
        action: str,
    ) -> dict[str, Any]:
        """Persist one exact lifecycle preview for an installed flow."""
        flow = self.flows.get(flow_id)
        parsed_action = self._parse_action(action)
        return self._preview(
            kind="flow",
            target_id=flow_id,
            flows=(flow,),
            action=parsed_action,
        )

    def preview_group(
        self,
        group_id: str,
        action: str,
    ) -> dict[str, Any]:
        """Persist one exact lifecycle preview for every verified group child."""
        parsed_action = self._parse_action(action)
        if parsed_action is IntegrationLifecycleAction.DELETE_DEFINITION:
            raise ValueError("group definition deletion is not supported")
        group = self.groups.get(group_id)
        if group.status is not IntegrationGroupStatus.VERIFIED:
            raise IntegrationLifecycleConflictError(
                "group lifecycle requires a verified installation"
            )
        flows = tuple(self.flows.get(item.flow_id) for item in group.children)
        return self._preview(
            kind="group",
            target_id=group_id,
            flows=flows,
            action=parsed_action,
        )

    def apply(
        self,
        operation_id: str,
        *,
        plan_id: str,
        authority: str,
        expected_revisions: Mapping[str, int],
        confirm_id: str | None = None,
        allow_user_home: bool = False,
    ) -> dict[str, Any]:
        """Apply one exact operation and return a durable recovery receipt."""
        _validate_operation_id(operation_id)
        _validate_plan_id(plan_id)
        _validate_identity(authority, field_name="lifecycle authority")
        if not isinstance(expected_revisions, Mapping):
            raise ValueError("expected_revisions must be an object")
        with exclusive_file_lock(self.lock_path):
            stored = self._read_unlocked()
            operation = stored["operations"].get(operation_id)
            if operation is None:
                raise IntegrationLifecycleNotFoundError(operation_id)
            if operation["plan_id"] != plan_id:
                raise IntegrationLifecycleConflictError(
                    "lifecycle approval does not match the preview"
                )
            if (
                operation["status"]
                == IntegrationLifecycleOperationStatus.SUCCEEDED.value
            ):
                return self._operation_result(operation)
            if operation["status"] not in {
                IntegrationLifecycleOperationStatus.AWAITING_APPROVAL.value,
                IntegrationLifecycleOperationStatus.PARTIAL_FAILURE.value,
                IntegrationLifecycleOperationStatus.FAILED.value,
            }:
                raise IntegrationLifecycleConflictError(
                    "lifecycle operation cannot be applied in its state"
                )
            expected = {
                str(key): _revision(value) for key, value in expected_revisions.items()
            }
            if expected != operation["expected_revisions"]:
                raise IntegrationLifecycleConflictError(
                    "lifecycle revisions do not match the preview"
                )
            if operation["confirmation_required"]:
                if confirm_id != operation["confirmation_id"]:
                    raise IntegrationLifecycleConflictError(
                        "exact lifecycle confirmation is required"
                    )
            for flow_id, revision in expected.items():
                if flow_id in operation["completed_flow_ids"]:
                    continue
                flow = self.flows.get(flow_id)
                state = self._state_projection(flow, stored["states"].get(flow_id))
                if state["revision"] != revision:
                    raise IntegrationLifecycleConflictError(
                        "integration lifecycle changed after preview"
                    )
            operation["status"] = IntegrationLifecycleOperationStatus.APPLYING.value
            operation["authority_sha256"] = _json_hash({"authority": authority})
            operation["updated_at"] = self._timestamp()
            stored["operations"][operation_id] = operation
            self._write_unlocked(stored)

        applied: list[tuple[str, dict[str, Any]]] = []
        try:
            for flow_id in operation["flow_ids"]:
                if flow_id in operation["completed_flow_ids"]:
                    continue
                with exclusive_file_lock(self.lock_path):
                    stored = self._read_unlocked()
                    flow = self.flows.get(flow_id)
                    before = self._state_projection(flow, stored["states"].get(flow_id))
                if (
                    operation["action"] == IntegrationLifecycleAction.UNINSTALL.value
                    and self._active_sessions(flow)
                ):
                    raise IntegrationLifecycleConflictError(
                        "active sessions retain this revision; uninstall is blocked"
                    )
                if self._fault_injector is not None:
                    self._fault_injector(operation["action"], flow_id)
                self._apply_effect(
                    flow,
                    IntegrationLifecycleAction(operation["action"]),
                    before,
                    authority=authority,
                    allow_user_home=allow_user_home,
                    catalog_revision=operation.get("catalog_revision"),
                )
                after = self._next_state(
                    before,
                    IntegrationLifecycleAction(operation["action"]),
                    operation_id=operation_id,
                )
                with exclusive_file_lock(self.lock_path):
                    stored = self._read_unlocked()
                    current = self._state_projection(
                        flow, stored["states"].get(flow_id)
                    )
                    if current["revision"] != before["revision"]:
                        raise IntegrationLifecycleConflictError(
                            "integration lifecycle changed during apply"
                        )
                    stored["states"][flow_id] = after
                    operation = stored["operations"][operation_id]
                    operation["completed_flow_ids"] = [
                        *operation["completed_flow_ids"],
                        flow_id,
                    ]
                    operation["updated_at"] = self._timestamp()
                    stored["operations"][operation_id] = operation
                    self._write_unlocked(stored)
                applied.append((flow_id, before))
        except Exception as exc:
            return self._record_failure(operation_id, applied, cause=exc)

        with exclusive_file_lock(self.lock_path):
            stored = self._read_unlocked()
            operation = stored["operations"][operation_id]
            operation["status"] = IntegrationLifecycleOperationStatus.SUCCEEDED.value
            operation["recovery_actions"] = []
            operation["error_code"] = None
            operation["receipt_id"] = f"lrec_{_json_hash(operation)[:32]}"
            operation["updated_at"] = self._timestamp()
            stored["operations"][operation_id] = operation
            self._write_unlocked(stored)
        return self._operation_result(operation)

    def admitted_flows(self) -> tuple[IntegrationFlowRecord, ...]:
        """Return only enabled installed revisions for newly created sessions."""
        stored = self._read()
        return tuple(
            flow
            for flow in self.flows.list()
            if self._state_projection(flow, stored["states"].get(flow.id))["state"]
            == IntegrationLifecycle.ENABLED.value
        )

    def _preview(
        self,
        *,
        kind: str,
        target_id: str,
        flows: Sequence[IntegrationFlowRecord],
        action: IntegrationLifecycleAction,
    ) -> dict[str, Any]:
        if not flows:
            raise IntegrationLifecycleConflictError(
                "lifecycle operation requires an installed target"
            )
        with exclusive_file_lock(self.lock_path):
            stored = self._read_unlocked()
            states = [
                self._state_projection(flow, stored["states"].get(flow.id))
                for flow in flows
            ]
            for flow, state in zip(flows, states, strict=True):
                self._validate_transition(flow, state, action)
            active = {flow.id: self._active_sessions(flow) for flow in flows}
            if action is IntegrationLifecycleAction.UNINSTALL and any(active.values()):
                raise IntegrationLifecycleConflictError(
                    "active sessions retain this revision; uninstall is blocked"
                )
            catalog_revision: int | None = None
            if action is IntegrationLifecycleAction.DELETE_DEFINITION:
                catalog_revision = self._validate_definition_deletion(flows[0], stored)
            expected_revisions = {
                state["flow_id"]: state["revision"] for state in states
            }
            confirmation_id = (
                self.groups.get(target_id).package_id
                if kind == "group"
                else flows[0].package_id
            )
            semantic = {
                "schema_version": INTEGRATION_LIFECYCLE_SCHEMA_VERSION,
                "kind": kind,
                "target_id": target_id,
                "action": action.value,
                "flow_ids": [flow.id for flow in flows],
                "expected_revisions": expected_revisions,
                "receipts": [state["receipt_id"] for state in states],
                "catalog_revision": catalog_revision,
            }
            operation_id = f"iop_{uuid4().hex}"
            timestamp = self._timestamp()
            operation = {
                "id": operation_id,
                "plan_id": f"plan_{_json_hash(semantic)}",
                "kind": kind,
                "target_id": target_id,
                "action": action.value,
                "flow_ids": [flow.id for flow in flows],
                "expected_revisions": expected_revisions,
                "catalog_revision": catalog_revision,
                "status": IntegrationLifecycleOperationStatus.AWAITING_APPROVAL.value,
                "confirmation_required": action
                in {
                    IntegrationLifecycleAction.UNINSTALL,
                    IntegrationLifecycleAction.DELETE_DEFINITION,
                },
                "confirmation_id": confirmation_id,
                "active_sessions": {
                    flow_id: [item["session_id"] for item in items]
                    for flow_id, items in active.items()
                },
                "completed_flow_ids": [],
                "authority_sha256": None,
                "receipt_id": None,
                "recovery_actions": [],
                "error_code": None,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            stored["operations"][operation_id] = operation
            if len(stored["operations"]) > MAX_LIFECYCLE_OPERATIONS:
                oldest = sorted(
                    stored["operations"].values(),
                    key=lambda value: str(value["updated_at"]),
                )
                stored["operations"] = {
                    item["id"]: item for item in oldest[-MAX_LIFECYCLE_OPERATIONS:]
                }
            self._write_unlocked(stored)
        return {
            "operation": self._public_operation(operation),
            "plan": {
                "plan_id": operation["plan_id"],
                "kind": kind,
                "target_id": target_id,
                "action": action.value,
                "expected_revisions": expected_revisions,
                "confirmation_required": operation["confirmation_required"],
                "confirmation_id": confirmation_id,
                "active_session_count": sum(len(items) for items in active.values()),
                "active_sessions_retain_revision": action
                is IntegrationLifecycleAction.DISABLE,
                "effects": [
                    self._effect_projection(flow, action, active[flow.id])
                    for flow in flows
                ],
                "approval_required": True,
                "content_free": True,
            },
        }

    def _validate_transition(
        self,
        flow: IntegrationFlowRecord,
        state: Mapping[str, Any],
        action: IntegrationLifecycleAction,
    ) -> None:
        current = state["state"]
        allowed = {
            IntegrationLifecycleAction.ENABLE: {
                IntegrationLifecycle.DISABLED.value,
            },
            IntegrationLifecycleAction.DISABLE: {
                IntegrationLifecycle.ENABLED.value,
            },
            IntegrationLifecycleAction.UNINSTALL: {
                IntegrationLifecycle.ENABLED.value,
                IntegrationLifecycle.DISABLED.value,
            },
            IntegrationLifecycleAction.DELETE_DEFINITION: {
                IntegrationLifecycle.DEFINITION_ONLY.value,
                IntegrationLifecycle.UNINSTALLED.value,
            },
        }[action]
        if current not in allowed:
            raise IntegrationLifecycleConflictError(
                f"{action.value} is unavailable while integration is {current}"
            )
        capabilities = self._target_capability_projection(flow.target_id)
        action_capability = next(
            item for item in capabilities["actions"] if item["action"] == action.value
        )
        if not action_capability["supported"]:
            raise IntegrationLifecycleConflictError(str(action_capability["reason"]))

    def _validate_definition_deletion(
        self,
        flow: IntegrationFlowRecord,
        stored: Mapping[str, Any],
    ) -> int:
        catalog_id = str(flow.request.get("catalog_id") or "")
        entry = self.flows.catalog.get(catalog_id) if catalog_id else None
        if entry is None:
            raise IntegrationLifecycleConflictError(
                "integration has no deletable catalog definition"
            )
        if entry.source_type not in {CatalogSourceType.GIT, CatalogSourceType.LOCAL}:
            raise IntegrationLifecycleConflictError(
                "only user-owned Git or local definitions can be deleted"
            )
        dependents = [
            candidate.id
            for candidate in self.flows.list()
            if candidate.request.get("catalog_id") == catalog_id
            and self._state_projection(candidate, stored["states"].get(candidate.id))[
                "state"
            ]
            in {
                IntegrationLifecycle.ENABLED.value,
                IntegrationLifecycle.DISABLED.value,
            }
        ]
        if dependents:
            raise IntegrationLifecycleConflictError(
                "definition has installed dependents; uninstall them first"
            )
        return self.flows.catalog.snapshot().revision

    def _apply_effect(
        self,
        flow: IntegrationFlowRecord,
        action: IntegrationLifecycleAction,
        state: Mapping[str, Any],
        *,
        authority: str,
        allow_user_home: bool,
        catalog_revision: int | None,
    ) -> None:
        if action in {
            IntegrationLifecycleAction.ENABLE,
            IntegrationLifecycleAction.DISABLE,
        }:
            return
        if action is IntegrationLifecycleAction.UNINSTALL:
            receipt_id = state.get("receipt_id")
            if not isinstance(receipt_id, str) or not receipt_id:
                raise IntegrationLifecycleConflictError(
                    "installed integration receipt is missing"
                )
            self.flows.uninstall_owned(
                flow.id,
                receipt_id=receipt_id,
                authority=authority,
                allow_user_home=allow_user_home,
            )
            return
        catalog_id = str(flow.request.get("catalog_id") or "")
        if catalog_revision is None:
            raise IntegrationLifecycleConflictError("catalog revision is missing")
        try:
            self.flows.catalog.delete_definition(
                catalog_id,
                expected_revision=catalog_revision,
            )
        except CatalogConflictError as exc:
            raise IntegrationLifecycleConflictError(str(exc)) from exc

    def _record_failure(
        self,
        operation_id: str,
        applied: Sequence[tuple[str, dict[str, Any]]],
        *,
        cause: Exception,
    ) -> dict[str, Any]:
        with exclusive_file_lock(self.lock_path):
            stored = self._read_unlocked()
            operation = stored["operations"][operation_id]
            reversible = operation["action"] in {
                IntegrationLifecycleAction.ENABLE.value,
                IntegrationLifecycleAction.DISABLE.value,
            }
            if reversible:
                for flow_id, before in reversed(applied):
                    current = stored["states"].get(flow_id)
                    restored = {
                        **before,
                        "revision": int(current["revision"]) + 1 if current else 1,
                        "last_operation_id": operation_id,
                        "updated_at": self._timestamp(),
                    }
                    stored["states"][flow_id] = restored
                operation["status"] = (
                    IntegrationLifecycleOperationStatus.COMPENSATED.value
                )
                operation["recovery_actions"] = []
            elif applied:
                operation["status"] = (
                    IntegrationLifecycleOperationStatus.PARTIAL_FAILURE.value
                )
                remaining = [
                    flow_id
                    for flow_id in operation["flow_ids"]
                    if flow_id not in operation["completed_flow_ids"]
                ]
                operation["recovery_actions"] = [
                    f"retry-safe-{operation['action']}:{flow_id}"
                    for flow_id in remaining
                ]
            else:
                operation["status"] = IntegrationLifecycleOperationStatus.FAILED.value
                operation["recovery_actions"] = [
                    f"retry-safe-{operation['action']}:{operation['target_id']}"
                ]
            operation["error_code"] = type(cause).__name__
            operation["receipt_id"] = f"lrec_{_json_hash(operation)[:32]}"
            operation["updated_at"] = self._timestamp()
            stored["operations"][operation_id] = operation
            self._write_unlocked(stored)
        if isinstance(cause, IntegrationLifecycleConflictError):
            raise cause
        return self._operation_result(operation)

    def _next_state(
        self,
        before: Mapping[str, Any],
        action: IntegrationLifecycleAction,
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        state = {
            IntegrationLifecycleAction.ENABLE: IntegrationLifecycle.ENABLED,
            IntegrationLifecycleAction.DISABLE: IntegrationLifecycle.DISABLED,
            IntegrationLifecycleAction.UNINSTALL: IntegrationLifecycle.UNINSTALLED,
            IntegrationLifecycleAction.DELETE_DEFINITION: (
                IntegrationLifecycle.DEFINITION_DELETED
            ),
        }[action]
        return {
            **before,
            "state": state.value,
            "enabled": state is IntegrationLifecycle.ENABLED,
            "installed": state
            in {IntegrationLifecycle.ENABLED, IntegrationLifecycle.DISABLED},
            "revision": int(before["revision"]) + 1,
            "last_operation_id": operation_id,
            "updated_at": self._timestamp(),
        }

    def _state_projection(
        self,
        flow: IntegrationFlowRecord,
        stored: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if stored is not None:
            return dict(stored)
        if flow.status is IntegrationFlowStatus.VERIFIED:
            state = IntegrationLifecycle.ENABLED
        elif flow.status is IntegrationFlowStatus.ROLLED_BACK:
            state = IntegrationLifecycle.UNINSTALLED
        else:
            state = IntegrationLifecycle.DEFINITION_ONLY
        return {
            "flow_id": flow.id,
            "package_id": flow.package_id,
            "package_version": flow.package_version,
            "target_id": flow.target_id,
            "scope": flow.scope.value,
            "state": state.value,
            "enabled": state is IntegrationLifecycle.ENABLED,
            "installed": state
            in {IntegrationLifecycle.ENABLED, IntegrationLifecycle.DISABLED},
            "revision": 1,
            "receipt_id": flow.receipt_id,
            "catalog_id": flow.request.get("catalog_id"),
            "last_operation_id": None,
            "updated_at": flow.updated_at,
            "content_free": True,
        }

    def _target_capability_projection(self, target_id: str) -> dict[str, Any]:
        target = next(item for item in BUILTIN_FLOW_TARGETS if item.id == target_id)
        executable = target_id != "harness-adapter-package"
        component = (
            target.component_types[0].value if target.component_types else "unknown"
        )
        actions = []
        for action in IntegrationLifecycleAction:
            supported = executable
            reason: str | None = None
            if action is IntegrationLifecycleAction.DELETE_DEFINITION:
                supported = True
            elif action is IntegrationLifecycleAction.UNINSTALL and component not in {
                IntegrationComponentType.SKILL.value,
                IntegrationComponentType.MCP.value,
                IntegrationComponentType.PLUGIN.value,
            }:
                supported = False
                reason = "target has no application-owned uninstall surface"
            elif not executable:
                supported = False
                reason = "target lifecycle remains provider-owned"
            actions.append(
                {
                    "action": action.value,
                    "supported": supported,
                    "reason": reason,
                }
            )
        actions.append(
            {
                "action": "rollback",
                "supported": "rollback" in target.capabilities
                or component == IntegrationComponentType.SKILL.value,
                "reason": None,
            }
        )
        return {
            "target_id": target_id,
            "component_types": [item.value for item in target.component_types],
            "actions": actions,
            "content_free": True,
        }

    def _active_sessions(self, flow: IntegrationFlowRecord) -> list[dict[str, Any]]:
        return list(
            self.runtime.bindings_for_integration(
                package_id=flow.package_id,
                target_id=flow.target_id,
            )
        )

    def _effect_projection(
        self,
        flow: IntegrationFlowRecord,
        action: IntegrationLifecycleAction,
        active_sessions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "flow_id": flow.id,
            "package_id": flow.package_id,
            "target_id": flow.target_id,
            "scope": flow.scope.value,
            "mutation": (
                "admission_state_only"
                if action
                in {
                    IntegrationLifecycleAction.ENABLE,
                    IntegrationLifecycleAction.DISABLE,
                }
                else (
                    "installer_owned_material_only"
                    if action is IntegrationLifecycleAction.UNINSTALL
                    else "user_owned_definition_only"
                )
            ),
            "active_session_count": len(active_sessions),
            "content_free": True,
        }

    def _public_operation(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": operation["id"],
            "plan_id": operation["plan_id"],
            "kind": operation["kind"],
            "target_id": operation["target_id"],
            "action": operation["action"],
            "flow_ids": list(operation["flow_ids"]),
            "expected_revisions": dict(operation["expected_revisions"]),
            "status": operation["status"],
            "confirmation_required": operation["confirmation_required"],
            "confirmation_id": operation["confirmation_id"],
            "active_session_count": sum(
                len(items) for items in operation["active_sessions"].values()
            ),
            "completed_flow_ids": list(operation["completed_flow_ids"]),
            "receipt_id": operation["receipt_id"],
            "recovery_actions": list(operation["recovery_actions"]),
            "error_code": operation["error_code"],
            "created_at": operation["created_at"],
            "updated_at": operation["updated_at"],
            "content_free": True,
        }

    def _operation_result(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "operation": self._public_operation(operation),
            "receipt": {
                "id": operation["receipt_id"],
                "action": operation["action"],
                "outcome": operation["status"],
                "completed_flow_ids": list(operation["completed_flow_ids"]),
                "recovery_actions": list(operation["recovery_actions"]),
                "content_free": True,
            },
        }

    def _parse_action(self, value: str) -> IntegrationLifecycleAction:
        try:
            return IntegrationLifecycleAction(value)
        except ValueError as exc:
            raise ValueError("integration lifecycle action is invalid") from exc

    def _timestamp(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _read(self) -> dict[str, Any]:
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            return self._read_unlocked()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": INTEGRATION_LIFECYCLE_SCHEMA_VERSION,
                "states": {},
                "operations": {},
            }
        if self.path.is_symlink() or not self.path.is_file():
            raise IntegrationLifecycleError("integration lifecycle state is unsafe")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise IntegrationLifecycleError(
                "integration lifecycle state is unreadable"
            ) from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != INTEGRATION_LIFECYCLE_SCHEMA_VERSION
            or not isinstance(payload.get("states"), Mapping)
            or not isinstance(payload.get("operations"), Mapping)
        ):
            raise IntegrationLifecycleError(
                "integration lifecycle state schema is unsupported"
            )
        return {
            "schema_version": INTEGRATION_LIFECYCLE_SCHEMA_VERSION,
            "states": {
                str(key): dict(value) for key, value in payload["states"].items()
            },
            "operations": {
                str(key): dict(value) for key, value in payload["operations"].items()
            },
        }

    def _write_unlocked(self, payload: Mapping[str, Any]) -> None:
        self._ensure_root()
        raw = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        handle, temporary = tempfile.mkstemp(
            prefix=".lifecycle-",
            suffix=".tmp",
            dir=self.root,
            text=True,
        )
        try:
            os.fchmod(handle, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            with suppress(OSError):
                os.close(handle)
            with suppress(OSError):
                os.unlink(temporary)
            raise

    def _ensure_root(self) -> None:
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise IntegrationLifecycleError("integration lifecycle root is unsafe")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)


def _revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("integration lifecycle revision is invalid")
    return value


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_operation_id(value: str) -> None:
    if _OPERATION_ID_RE.fullmatch(value) is None:
        raise ValueError("integration lifecycle operation id is invalid")


def _validate_plan_id(value: str) -> None:
    if _PLAN_ID_RE.fullmatch(value) is None:
        raise ValueError("integration lifecycle plan id is invalid")


def _validate_identity(value: str, *, field_name: str) -> None:
    if _IDENTITY_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")


__all__ = [
    "IntegrationLifecycleAction",
    "IntegrationLifecycleConflictError",
    "IntegrationLifecycleError",
    "IntegrationLifecycleNotFoundError",
    "IntegrationLifecycleService",
]
