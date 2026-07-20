from __future__ import annotations

from dataclasses import replace
import json

import pytest

from gpt2giga_harness import cli
from gpt2giga_harness.integration_packages import (
    ExtensionTargetDescriptor,
    InstallationScope,
    IntegrationComponentType,
    extension_target_descriptor_from_dict,
    extension_target_descriptor_to_dict,
)
from gpt2giga_harness.integration_scaffold import scaffold_integration_package
from gpt2giga_harness.integration_sdk import (
    INTEGRATION_SDK_API_VERSION,
    integration_conformance_report_to_dict,
    integration_sdk_policy_to_dict,
    load_extension_target_document,
    load_integration_package_document,
    load_integration_sdk_resource,
    run_integration_conformance,
)


def test_packaged_docs_schemas_and_samples_are_strict_and_conform(tmp_path):
    guide = load_integration_sdk_resource("README.md")
    adapter_schema = json.loads(
        load_integration_sdk_resource("adapter-manifest.schema.json")
    )
    package_schema = json.loads(
        load_integration_sdk_resource("integration-package.schema.json")
    )
    target_schema = json.loads(
        load_integration_sdk_resource("extension-target.schema.json")
    )
    package_path = _copy_resource(
        tmp_path,
        "samples/codex-mcp/integration-package.json",
    )
    target_path = _copy_resource(
        tmp_path,
        "samples/codex-mcp/target-descriptor.json",
    )

    package = load_integration_package_document(package_path)
    target = load_extension_target_document(target_path)
    report = run_integration_conformance(
        package,
        target_descriptors=(target,),
    )
    payload = integration_conformance_report_to_dict(report)

    assert "Compatibility policy" in guide
    assert "Deprecation policy" in guide
    assert adapter_schema["properties"]["sdk_api_version"] == {"const": 1}
    assert package_schema["additionalProperties"] is False
    assert target_schema["additionalProperties"] is False
    assert package_schema["properties"]["schema_version"] == {"const": 1}
    assert target_schema["properties"]["schema_version"] == {"const": 1}
    assert report.ok is True
    assert payload["sdk_api_version"] == INTEGRATION_SDK_API_VERSION
    assert payload["install_authorized"] is False
    assert payload["public_marketplace_release"] is False


def test_portable_sample_needs_no_target_descriptor(tmp_path):
    path = _copy_resource(
        tmp_path,
        "samples/portable-skill/integration-package.json",
    )

    report = run_integration_conformance(load_integration_package_document(path))

    assert report.ok is True
    assert report.target_ids == ()


def test_target_descriptor_round_trip_rejects_unknown_and_future_fields():
    descriptor = _descriptor()
    payload = extension_target_descriptor_to_dict(descriptor)

    assert extension_target_descriptor_from_dict(payload) == descriptor
    with pytest.raises(ValueError, match="unknown fields"):
        extension_target_descriptor_from_dict({**payload, "future": True})
    with pytest.raises(ValueError, match="unsupported extension target"):
        extension_target_descriptor_from_dict({**payload, "schema_version": 2})


def test_conformance_fails_closed_for_missing_or_incompatible_target(tmp_path):
    path = _copy_resource(
        tmp_path,
        "samples/codex-mcp/integration-package.json",
    )
    package = load_integration_package_document(path)

    missing = run_integration_conformance(package)
    incompatible = run_integration_conformance(
        package,
        target_descriptors=(replace(_descriptor(), capabilities=("mcp.verify",)),),
    )
    old_revision = run_integration_conformance(
        package,
        target_descriptors=(replace(_descriptor(), revision="0.0.9"),),
    )

    assert missing.ok is False
    assert incompatible.ok is False
    assert old_revision.ok is False
    assert "exactly match" in missing.results[-1].detail
    assert "missing required capabilities" in incompatible.results[-1].detail
    assert "below the declared minimum" in old_revision.results[-1].detail


def test_document_loader_rejects_duplicates_symlinks_and_resource_traversal(
    tmp_path,
):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version": 1, "schema_version": 1}\n')
    link = tmp_path / "link.json"
    link.symlink_to(duplicate)

    with pytest.raises(ValueError, match="duplicate keys"):
        load_integration_package_document(duplicate)
    with pytest.raises(ValueError, match="non-symlink"):
        load_integration_package_document(link)
    with pytest.raises(ValueError, match="path is invalid"):
        load_integration_sdk_resource("../README.md")


def test_scaffold_and_cli_conformance_form_one_offline_authoring_flow(
    tmp_path,
    capsys,
):
    root = tmp_path / "sample-package"

    result = scaffold_integration_package("sample-package", root)

    assert len(result.files) == 3
    assert (
        cli.main(
            [
                "integration",
                "conformance",
                str(root / "integration-package.json"),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["install_authorized"] is False
    with pytest.raises(FileExistsError):
        scaffold_integration_package("sample-package", root)

    cli_root = tmp_path / "cli-package"
    assert (
        cli.main(
            [
                "integration",
                "scaffold",
                "cli-package",
                "--output",
                str(cli_root),
            ]
        )
        == 0
    )
    assert (cli_root / "integration-package.json").is_file()


def test_preview_policy_is_machine_readable_and_explicitly_internal():
    payload = integration_sdk_policy_to_dict()

    assert payload == {
        "sdk_api_version": 1,
        "adapter_sdk_api_version": 1,
        "adapter_manifest_schema_version": 1,
        "package_schema_version": 1,
        "target_schema_version": 1,
        "stability": "internal_preview",
        "unknown_fields": "reject",
        "future_versions": "reject",
        "deprecation": {"minimum_releases": 2, "minimum_days": 30},
        "public_marketplace_release": False,
    }


def _copy_resource(tmp_path, resource_name):
    path = tmp_path / resource_name.replace("/", "-")
    path.write_text(load_integration_sdk_resource(resource_name), encoding="utf-8")
    return path


def _descriptor() -> ExtensionTargetDescriptor:
    return ExtensionTargetDescriptor(
        id="sample-codex-mcp",
        revision="0.1.0",
        component_types=(IntegrationComponentType.MCP,),
        scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
        capabilities=("mcp.install", "mcp.verify"),
        trust_evidence=(
            load_extension_target_document_from_sample().trust_evidence[0],
        ),
    )


def load_extension_target_document_from_sample() -> ExtensionTargetDescriptor:
    payload = json.loads(
        load_integration_sdk_resource("samples/codex-mcp/target-descriptor.json")
    )
    return extension_target_descriptor_from_dict(payload)
