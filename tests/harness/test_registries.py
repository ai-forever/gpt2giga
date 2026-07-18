import pytest

from gpt2giga_harness.registries import (
    EntryPointFamily,
    RegistrationOutcome,
    RegistryCollisionError,
    VersionedRegistryKernel,
)


def test_entry_point_family_prioritizes_primary_and_deduplicates_aliases():
    family = EntryPointFamily(
        registry_id="example",
        api_version=1,
        primary_group="agent_workbench.examples.v1",
        compatibility_groups=("legacy.examples", "agent_workbench.examples.v1"),
    )

    assert family.groups == (
        "agent_workbench.examples.v1",
        "legacy.examples",
    )


def test_versioned_registry_kernel_accepts_equivalent_alias_once():
    kernel = VersionedRegistryKernel[str](
        EntryPointFamily(
            registry_id="example",
            api_version=1,
            primary_group="agent_workbench.examples.v1",
        )
    )

    assert (
        kernel.register(
            item_id="sample",
            item="primary",
            identity="package:factory",
            source="primary",
        )
        is RegistrationOutcome.ADDED
    )
    assert (
        kernel.register(
            item_id="sample",
            item="compatibility",
            identity="package:factory",
            source="legacy",
            allow_equivalent_duplicate=True,
        )
        is RegistrationOutcome.EQUIVALENT_DUPLICATE
    )
    assert kernel.values() == ("primary",)


def test_versioned_registry_kernel_rejects_non_equivalent_collision():
    kernel = VersionedRegistryKernel[str](
        EntryPointFamily(
            registry_id="example",
            api_version=1,
            primary_group="agent_workbench.examples.v1",
        )
    )
    kernel.register(
        item_id="sample",
        item="primary",
        identity="package:primary",
        source="primary",
    )

    with pytest.raises(RegistryCollisionError) as caught:
        kernel.register(
            item_id="sample",
            item="collision",
            identity="package:collision",
            source="legacy",
            allow_equivalent_duplicate=True,
        )

    assert caught.value.item_id == "sample"
    assert caught.value.existing_source == "primary"
    assert caught.value.incoming_source == "legacy"
    assert kernel.values() == ("primary",)
