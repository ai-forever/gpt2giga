"""Exact private ownership for provider-neutral Harness-managed MCP entries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from gpt2giga_harness.external_mcp import (
    ExternalMCPDescriptor,
    external_mcp_descriptor_to_dict,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import utc_now


MANAGED_MCP_INVENTORY_SCHEMA_VERSION = 1
_PLAN_RE = re.compile(r"plan_[0-9a-f]{64}\Z")
_TRANSACTION_RE = re.compile(r"txn_[0-9a-f]{32}\Z")


class ManagedMCPInventoryError(RuntimeError):
    """Raised when exact private MCP inventory ownership cannot be proven."""


@dataclass(frozen=True)
class ManagedMCPInventoryPlan:
    """Content-free preview for one exact descriptor owner."""

    plan_id: str
    transaction_id: str
    package_id: str
    descriptor_sha256: str
    expected_revision: str | None
    changed: bool


@dataclass(frozen=True)
class ManagedMCPInventoryResult:
    """Content-free terminal inventory evidence."""

    transaction_id: str
    package_id: str
    descriptor_sha256: str
    revision: str | None
    status: str
    updated_at: str


class ManagedMCPInventoryStore:
    """Persist reviewed MCP descriptors under one exact reversible owner."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root = self.data_dir / "integrations"
        self.path = self.root / "managed_mcp_inventory.json"
        self.lock_path = self.root / ".managed_mcp_inventory.lock"

    def preview(self, descriptor: ExternalMCPDescriptor) -> ManagedMCPInventoryPlan:
        """Bind a descriptor to the current exact owner revision without mutation."""
        serialized = external_mcp_descriptor_to_dict(descriptor)
        descriptor_hash = _json_hash(serialized)
        state = self._read()
        owner = state["entries"].get(descriptor.id)
        if owner is not None and owner["descriptor_sha256"] != descriptor_hash:
            raise ManagedMCPInventoryError(
                "managed MCP inventory already owns a different descriptor"
            )
        expected_revision = str(owner["revision"]) if owner is not None else None
        semantic = {
            "schema_version": MANAGED_MCP_INVENTORY_SCHEMA_VERSION,
            "package_id": descriptor.id,
            "descriptor_sha256": descriptor_hash,
            "expected_revision": expected_revision,
        }
        digest = _json_hash(semantic)
        return ManagedMCPInventoryPlan(
            plan_id=f"plan_{digest}",
            transaction_id=f"txn_{digest[:32]}",
            package_id=descriptor.id,
            descriptor_sha256=descriptor_hash,
            expected_revision=expected_revision,
            changed=owner is None,
        )

    def apply(
        self,
        descriptor: ExternalMCPDescriptor,
        plan: ManagedMCPInventoryPlan,
        *,
        authority: str,
    ) -> ManagedMCPInventoryResult:
        """Publish one exact descriptor or return the idempotent prior result."""
        if not authority.strip() or len(authority) > 256:
            raise ValueError("managed MCP inventory authority is invalid")
        current = self.preview(descriptor)
        if current != plan or not _PLAN_RE.fullmatch(plan.plan_id):
            raise ManagedMCPInventoryError("managed MCP inventory preview is stale")
        with exclusive_file_lock(self.lock_path):
            state = self._read_unlocked()
            journal = state["transactions"].get(plan.transaction_id)
            if journal is not None:
                return _result(journal)
            owner = state["entries"].get(descriptor.id)
            revision = (
                str(owner["revision"])
                if owner is not None
                else _json_hash(
                    {
                        "transaction_id": plan.transaction_id,
                        "descriptor_sha256": plan.descriptor_sha256,
                    }
                )
            )
            timestamp = utc_now()
            state["entries"][descriptor.id] = {
                "package_id": descriptor.id,
                "descriptor_sha256": plan.descriptor_sha256,
                "descriptor": external_mcp_descriptor_to_dict(descriptor),
                "revision": revision,
                "transaction_id": plan.transaction_id,
                "updated_at": timestamp,
            }
            journal = {
                "transaction_id": plan.transaction_id,
                "plan_id": plan.plan_id,
                "package_id": descriptor.id,
                "descriptor_sha256": plan.descriptor_sha256,
                "revision": revision,
                "authority_hash": hashlib.sha256(authority.encode()).hexdigest(),
                "status": "committed",
                "updated_at": timestamp,
            }
            state["transactions"][plan.transaction_id] = journal
            self._write_unlocked(state)
        return _result(journal)

    def verify(self, transaction_id: str) -> ManagedMCPInventoryResult:
        """Prove that one transaction still owns its exact descriptor."""
        _validate_transaction(transaction_id)
        state = self._read()
        journal = state["transactions"].get(transaction_id)
        if journal is None or journal["status"] != "committed":
            raise ManagedMCPInventoryError("managed MCP transaction is not committed")
        owner = state["entries"].get(journal["package_id"])
        if (
            owner is None
            or owner["transaction_id"] != transaction_id
            or owner["revision"] != journal["revision"]
            or _json_hash(owner["descriptor"]) != journal["descriptor_sha256"]
        ):
            raise ManagedMCPInventoryError("managed MCP inventory ownership drifted")
        return _result(journal)

    def rollback(self, transaction_id: str) -> ManagedMCPInventoryResult:
        """Remove one exact current owner without touching drifted inventory."""
        _validate_transaction(transaction_id)
        with exclusive_file_lock(self.lock_path):
            state = self._read_unlocked()
            journal = state["transactions"].get(transaction_id)
            if journal is None:
                raise ManagedMCPInventoryError("managed MCP transaction is unknown")
            if journal["status"] == "rolled_back":
                return _result(journal)
            owner = state["entries"].get(journal["package_id"])
            if (
                owner is None
                or owner["transaction_id"] != transaction_id
                or owner["revision"] != journal["revision"]
                or _json_hash(owner["descriptor"]) != journal["descriptor_sha256"]
            ):
                raise ManagedMCPInventoryError(
                    "managed MCP inventory changed outside its owner"
                )
            del state["entries"][journal["package_id"]]
            journal = {**journal, "status": "rolled_back", "updated_at": utc_now()}
            state["transactions"][transaction_id] = journal
            self._write_unlocked(state)
        return _result(journal)

    def _read(self) -> dict[str, Any]:
        self._ensure_root()
        with exclusive_file_lock(self.lock_path):
            return self._read_unlocked()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": MANAGED_MCP_INVENTORY_SCHEMA_VERSION,
                "entries": {},
                "transactions": {},
            }
        if self.path.is_symlink() or not self.path.is_file():
            raise ManagedMCPInventoryError("managed MCP inventory path is unsafe")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ManagedMCPInventoryError(
                "managed MCP inventory is unreadable"
            ) from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != MANAGED_MCP_INVENTORY_SCHEMA_VERSION
            or not isinstance(payload.get("entries"), Mapping)
            or not isinstance(payload.get("transactions"), Mapping)
        ):
            raise ManagedMCPInventoryError("managed MCP inventory state is invalid")
        return {
            "schema_version": MANAGED_MCP_INVENTORY_SCHEMA_VERSION,
            "entries": dict(payload["entries"]),
            "transactions": dict(payload["transactions"]),
        }

    def _write_unlocked(self, payload: Mapping[str, Any]) -> None:
        self._ensure_root()
        fd, raw_path = tempfile.mkstemp(prefix=".managed-mcp-", dir=self.root)
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
            raise ManagedMCPInventoryError("managed MCP inventory root is unsafe")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)


def _result(journal: Mapping[str, Any]) -> ManagedMCPInventoryResult:
    return ManagedMCPInventoryResult(
        transaction_id=str(journal["transaction_id"]),
        package_id=str(journal["package_id"]),
        descriptor_sha256=str(journal["descriptor_sha256"]),
        revision=(str(journal["revision"]) if journal.get("revision") else None),
        status=str(journal["status"]),
        updated_at=str(journal["updated_at"]),
    )


def _validate_transaction(value: str) -> None:
    if not _TRANSACTION_RE.fullmatch(value):
        raise ValueError("managed MCP transaction id is invalid")


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "ManagedMCPInventoryError",
    "ManagedMCPInventoryPlan",
    "ManagedMCPInventoryResult",
    "ManagedMCPInventoryStore",
]
