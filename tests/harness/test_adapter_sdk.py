import json
import os
import subprocess
import sys

import pytest

from gpt2giga_harness.adapter_scaffold import scaffold_adapter_package
from gpt2giga_harness.adapter_sdk import (
    ADAPTER_ENTRY_POINT_GROUP,
    ADAPTER_MANIFEST_SCHEMA_VERSION,
    ADAPTER_SDK_API_VERSION,
    CONFORMANCE_ENTRY_POINT_GROUP,
    AdapterConformanceCategory,
    AdapterConformanceClaim,
    AdapterConformanceSubject,
    AdapterManifest,
    FakeProviderProtocol,
    adapter_conformance_report_to_dict,
    adapter_manifest_from_dict,
    adapter_manifest_to_dict,
    run_adapter_conformance,
)
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


def test_adapter_manifest_round_trip_is_strict_and_missing_claims_stay_absent():
    manifest = _manifest(claims=(AdapterConformanceClaim.EXECUTION_RUN,))

    payload = adapter_manifest_to_dict(manifest)
    restored = adapter_manifest_from_dict(payload)

    assert restored == manifest
    assert payload["schema_version"] == ADAPTER_MANIFEST_SCHEMA_VERSION
    assert payload["sdk_api_version"] == ADAPTER_SDK_API_VERSION
    assert restored.supports(AdapterConformanceClaim.EXECUTION_RUN) is True
    assert restored.supports(AdapterConformanceClaim.SESSIONS_LIFECYCLE) is False
    assert restored.supports("future.claim") is False


@pytest.mark.parametrize(
    ("patch", "match"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"sdk_api_version": 2}, "SDK api version"),
        ({"claims": ["future.claim"]}, "unknown conformance claim"),
        ({"extra": True}, "unknown fields"),
    ],
)
def test_adapter_manifest_rejects_future_or_unknown_contracts(patch, match):
    payload = adapter_manifest_to_dict(_manifest())
    payload.update(patch)

    with pytest.raises(ValueError, match=match):
        adapter_manifest_from_dict(payload)


def test_conformance_runs_declared_subset_and_marks_every_missing_claim_unsupported(
    monkeypatch,
):
    fake_provider = FakeProviderProtocol()
    subject = AdapterConformanceSubject(
        manifest=_manifest(
            claims=(
                AdapterConformanceClaim.EXECUTION_RUN,
                AdapterConformanceClaim.PACKAGING_ENTRY_POINT,
            )
        ),
        harness=_SdkHarness(fake_provider),
        fake_provider=fake_provider,
    )
    monkeypatch.setattr(
        "gpt2giga_harness.adapter_sdk.metadata.distribution",
        lambda name: _FakeDistribution(),
    )

    report = run_adapter_conformance(subject)
    payload = adapter_conformance_report_to_dict(report)

    assert report.ok is True
    assert payload["categories"] == [
        category.value for category in AdapterConformanceCategory
    ]
    statuses = {result.claim: result.status for result in report.results}
    assert statuses[AdapterConformanceClaim.EXECUTION_RUN] == "passed"
    assert statuses[AdapterConformanceClaim.PACKAGING_ENTRY_POINT] == "passed"
    assert all(
        status == "unsupported"
        for claim, status in statuses.items()
        if claim
        not in {
            AdapterConformanceClaim.EXECUTION_RUN,
            AdapterConformanceClaim.PACKAGING_ENTRY_POINT,
        }
    )


def test_declared_optional_claim_fails_without_an_explicit_probe():
    fake_provider = FakeProviderProtocol()
    subject = AdapterConformanceSubject(
        manifest=_manifest(claims=(AdapterConformanceClaim.SESSIONS_LIFECYCLE,)),
        harness=_SdkHarness(fake_provider),
        fake_provider=fake_provider,
    )

    report = run_adapter_conformance(subject)

    assert report.ok is False
    result = next(
        result
        for result in report.results
        if result.claim is AdapterConformanceClaim.SESSIONS_LIFECYCLE
    )
    assert result.status == "failed"
    assert result.detail == "declared claim has no conformance probe"


def test_probe_failures_do_not_expose_exception_content():
    fake_provider = FakeProviderProtocol()

    def fail_with_secret(context):
        raise RuntimeError("token=super-secret-value")

    subject = AdapterConformanceSubject(
        manifest=_manifest(claims=(AdapterConformanceClaim.TELEMETRY_CONTENT_FREE,)),
        harness=_SdkHarness(fake_provider),
        fake_provider=fake_provider,
        probes={AdapterConformanceClaim.TELEMETRY_CONTENT_FREE: fail_with_secret},
    )

    report = run_adapter_conformance(subject)
    detail = next(
        result.detail
        for result in report.results
        if result.claim is AdapterConformanceClaim.TELEMETRY_CONTENT_FREE
    )

    assert report.ok is False
    assert detail == "RuntimeError: conformance probe failed"
    assert "super-secret-value" not in detail


def test_scaffold_generates_provider_neutral_package_and_refuses_overwrite(tmp_path):
    root = tmp_path / "sample-adapter"

    result = scaffold_adapter_package("sample-adapter", root)

    assert result.root == root
    assert len(result.files) == 7
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    adapter = (
        root / "src" / "agent_workbench_sample_adapter" / "adapter.py"
    ).read_text(encoding="utf-8")
    manifest = json.loads(
        (
            root / "src" / "agent_workbench_sample_adapter" / "adapter_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert ADAPTER_ENTRY_POINT_GROUP in pyproject
    assert CONFORMANCE_ENTRY_POINT_GROUP in pyproject
    assert "from gpt2giga import" not in adapter
    assert "gpt2giga." not in adapter
    assert manifest["claims"] == ["execution.run", "packaging.entry_point"]
    with pytest.raises(FileExistsError):
        scaffold_adapter_package("sample-adapter", root)


def test_out_of_tree_scaffold_installs_and_passes_declared_subset(tmp_path):
    project = tmp_path / "sample-adapter"
    target = tmp_path / "site-packages"
    scaffold_adapter_package("sample-adapter", project)
    install = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--target",
            str(target),
            "--no-deps",
            str(project),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert install.returncode == 0, install.stderr
    code = """
from gpt2giga_harness.adapter_sdk import (
    adapter_conformance_report_to_dict,
    load_installed_conformance_subject,
    run_adapter_conformance,
)
from gpt2giga_harness.cli import main
subject = load_installed_conformance_subject("sample-adapter")
report = run_adapter_conformance(subject)
payload = adapter_conformance_report_to_dict(report)
assert report.ok is True, payload
assert [item["status"] for item in payload["results"]].count("passed") == 2
assert [item["status"] for item in payload["results"]].count("unsupported") == 7
assert main(["harness", "conformance", "sample-adapter", "--json"]) == 0
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(target), environment.get("PYTHONPATH", ""))
    )
    conformance = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=30,
    )
    assert conformance.returncode == 0, conformance.stderr


def _manifest(*, claims: tuple[AdapterConformanceClaim, ...] = ()) -> AdapterManifest:
    return AdapterManifest(
        adapter_id="sample-adapter",
        adapter_version="0.1.0",
        distribution="agent-workbench-sample-adapter",
        entry_point="sample_adapter.adapter:SampleAdapterHarness",
        claims=claims,
    )


class _SdkHarness(BaseHarness):
    def __init__(self, protocol: FakeProviderProtocol) -> None:
        self._protocol = protocol

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="sample-adapter",
            title="Sample Adapter",
            kind="custom",
            description="SDK conformance test adapter",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return self._protocol.availability()

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return self._protocol.run(request)


class _FakeEntryPoint:
    group = ADAPTER_ENTRY_POINT_GROUP
    name = "sample-adapter"
    value = "sample_adapter.adapter:SampleAdapterHarness"


class _FakeDistribution:
    entry_points = (_FakeEntryPoint(),)
