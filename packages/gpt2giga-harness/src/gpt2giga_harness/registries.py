"""Versioned registry primitives shared by workbench extension families."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar


RegistryItem = TypeVar("RegistryItem")


@dataclass(frozen=True)
class EntryPointFamily:
    """Describe one versioned entry-point family and its compatibility aliases."""

    registry_id: str
    api_version: int
    primary_group: str
    compatibility_groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.registry_id.strip():
            raise ValueError("Registry id is required.")
        if self.api_version < 1:
            raise ValueError("Registry API version must be positive.")
        if not self.primary_group.strip():
            raise ValueError("Primary entry-point group is required.")

    @property
    def groups(self) -> tuple[str, ...]:
        """Return the primary group followed by unique compatibility groups."""
        return tuple(dict.fromkeys((self.primary_group, *self.compatibility_groups)))


class RegistrationOutcome(str, Enum):
    """Result of adding one item to a registry kernel."""

    ADDED = "added"
    EQUIVALENT_DUPLICATE = "equivalent_duplicate"


@dataclass(frozen=True)
class RegistryRecord(Generic[RegistryItem]):
    """Retain one registered item together with collision-safe provenance."""

    item_id: str
    item: RegistryItem
    identity: str
    source: str


class RegistryCollisionError(ValueError):
    """Raised when two non-equivalent items claim the same registry id."""

    def __init__(
        self,
        *,
        item_id: str,
        existing_source: str,
        incoming_source: str,
    ) -> None:
        super().__init__("registry id collision")
        self.item_id = item_id
        self.existing_source = existing_source
        self.incoming_source = incoming_source


class VersionedRegistryKernel(Generic[RegistryItem]):
    """Store one versioned extension family with deterministic collision rules."""

    def __init__(self, family: EntryPointFamily) -> None:
        self.family = family
        self._records: dict[str, RegistryRecord[RegistryItem]] = {}

    def register(
        self,
        *,
        item_id: str,
        item: RegistryItem,
        identity: str,
        source: str,
        allow_equivalent_duplicate: bool = False,
    ) -> RegistrationOutcome:
        """Register an item or reject a non-equivalent duplicate id."""
        if not item_id.strip():
            raise ValueError("Registry item id is required.")
        if not identity.strip():
            raise ValueError("Registry item identity is required.")
        if not source.strip():
            raise ValueError("Registry item source is required.")

        existing = self._records.get(item_id)
        if existing is not None:
            if allow_equivalent_duplicate and existing.identity == identity:
                return RegistrationOutcome.EQUIVALENT_DUPLICATE
            raise RegistryCollisionError(
                item_id=item_id,
                existing_source=existing.source,
                incoming_source=source,
            )

        self._records[item_id] = RegistryRecord(
            item_id=item_id,
            item=item,
            identity=identity,
            source=source,
        )
        return RegistrationOutcome.ADDED

    def get(self, item_id: str) -> RegistryItem | None:
        """Return one item, if registered."""
        record = self._records.get(item_id)
        return None if record is None else record.item

    def values(self) -> tuple[RegistryItem, ...]:
        """Return registered items in deterministic registration order."""
        return tuple(record.item for record in self._records.values())

    def ids(self) -> tuple[str, ...]:
        """Return registered ids in sorted order."""
        return tuple(sorted(self._records))
