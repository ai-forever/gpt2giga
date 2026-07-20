from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from gpt2giga_harness.gemini_extension_target import (
    GEMINI_EXTENSION_TARGET_ID,
    GeminiExtensionApproval,
    GeminiExtensionCommandError,
    GeminiExtensionCommandResult,
    GeminiExtensionPolicyError,
    GeminiExtensionRequest,
    GeminiExtensionSource,
    GeminiExtensionSourceKind,
    GeminiExtensionTargetDriver,
    gemini_extension_source_checksum,
    gemini_extension_target_plugin,
)
from gpt2giga_harness.integration_installer import (
    InstallationConflictError,
    InstallationScopeError,
)
from gpt2giga_harness.integration_packages import (
    ExtensionTargetRegistry,
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationTargetOverlay,
    IntegrationUpdatePolicy,
)


class FakeGemini:
    def __init__(self, *, fail_install: bool = False) -> None:
        self.fail_install = fail_install
        self.calls: list[tuple[tuple[str, ...], Path, Path, dict[str, str]]] = []
        self.installed: dict[tuple[Path, Path], dict[str, dict[str, object]]] = {}
        self.remote_versions = {"sample": "1.0.0"}

    def __call__(self, argv, env, cwd, _timeout):
        config_home = Path(env["GEMINI_CLI_HOME"])
        assert cwd is not None
        key = (config_home, cwd)
        args = argv[1:]
        self.calls.append((argv, config_home, cwd, dict(env)))
        if args == ("--version",):
            return GeminiExtensionCommandResult(0, "0.46.0\n")
        if args[-1:] == ("--help",):
            return GeminiExtensionCommandResult(
                0,
                "validate <path> --ref --consent --output-format --all --scope\n",
            )
        if args[:2] == ("extensions", "validate"):
            return GeminiExtensionCommandResult(0, "validation passed\n")
        if args == ("extensions", "list", "--output-format", "json"):
            items = list(self.installed.setdefault(key, {}).values())
            if not items:
                return GeminiExtensionCommandResult(0, "", "[]")
            return GeminiExtensionCommandResult(
                0,
                json.dumps(items),
            )
        if args[:2] == ("extensions", "install"):
            if self.fail_install:
                return GeminiExtensionCommandResult(
                    1,
                    "",
                    "token=secret-value-canary must never escape",
                )
            source = args[2]
            if Path(source).is_dir():
                manifest = json.loads(
                    (Path(source) / "gemini-extension.json").read_text(encoding="utf-8")
                )
                name = manifest["name"]
                version = manifest["version"]
                metadata = {"source": str(Path(source).absolute()), "type": "local"}
            else:
                name = "sample"
                version = self.remote_versions[name]
                metadata = {
                    "source": source,
                    "type": "git",
                    "ref": args[args.index("--ref") + 1],
                }
            self.installed.setdefault(key, {})[name] = {
                "name": name,
                "version": version,
                "path": str(config_home / ".gemini" / "extensions" / name),
                "installMetadata": metadata,
                "isActive": True,
            }
            return GeminiExtensionCommandResult(0, f"installed {name}\n")
        if args[:2] == ("extensions", "update"):
            name = args[2]
            item = self.installed.setdefault(key, {})[name]
            source = Path(str(item["installMetadata"]["source"]))
            manifest = json.loads(
                (source / "gemini-extension.json").read_text(encoding="utf-8")
            )
            item["version"] = manifest["version"]
            return GeminiExtensionCommandResult(0, f"updated {name}\n")
        if args[:2] in {
            ("extensions", "enable"),
            ("extensions", "disable"),
        }:
            name = args[2]
            self.installed.setdefault(key, {})[name]["isActive"] = args[1] == "enable"
            return GeminiExtensionCommandResult(0, f"{args[1]}d {name}\n")
        if args[:2] == ("extensions", "uninstall"):
            name = args[2]
            self.installed.setdefault(key, {}).pop(name, None)
            return GeminiExtensionCommandResult(0, f"uninstalled {name}\n")
        raise AssertionError(f"unexpected Gemini argv: {argv!r}")


def test_gemini_extension_lifecycle_is_native_validated_and_verified(tmp_path):
    source = _write_extension(tmp_path / "source")
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "gemini" / "homes" / "fixture"
    root.mkdir(parents=True)
    fake = FakeGemini()
    driver = GeminiExtensionTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, root)

    probe = driver.probe_target()
    registry = ExtensionTargetRegistry()
    registry.register(gemini_extension_target_plugin(lambda: driver))
    assert probe.status == "supported"
    assert probe.version == "0.46.0"
    assert len(probe.capabilities) == 8
    assert probe.gallery_automation == "provider_handoff_required"
    assert registry.create_driver(GEMINI_EXTENSION_TARGET_ID) is driver

    plan = driver.preview_install(request)
    assert plan.expected_version is None
    assert plan.native_scope == "workspace"
    assert plan.source_trust_required is True
    with pytest.raises(GeminiExtensionPolicyError, match="native consent"):
        driver.install(
            request,
            plan,
            GeminiExtensionApproval(plan.plan_id, "test-operator"),
        )

    installed = driver.install(request, plan, _approval(plan.plan_id))
    assert installed.status == "installed"
    assert installed.restart_required is True
    assert driver.health(request).status == "healthy"
    assert driver.discover_installed()[0].name == "sample"

    disable_plan = driver.preview_disable(request)
    disabled = driver.disable(request, disable_plan, _approval(disable_plan.plan_id))
    assert disabled.status == "disabled"
    assert disabled.enabled is False
    enable_plan = driver.preview_enable(request)
    enabled = driver.enable(request, enable_plan, _approval(enable_plan.plan_id))
    assert enabled.status == "enabled"
    assert enabled.enabled is True

    _write_manifest(source, version="1.1.0")
    updated_request = _local_request(source, root, version="1.1.0")
    update_plan = driver.preview_update(updated_request)
    assert update_plan.expected_version == "1.0.0"
    updated = driver.update(
        updated_request,
        update_plan,
        _approval(update_plan.plan_id),
    )
    assert updated.status == "updated"
    assert driver.verify(updated_request).version == "1.1.0"
    assert driver.rollback(updated_request).consent_owner == "gemini_cli"

    uninstall_plan = driver.preview_uninstall(updated_request)
    uninstalled = driver.uninstall(
        updated_request,
        uninstall_plan,
        _approval(uninstall_plan.plan_id),
    )
    assert uninstalled.status == "uninstalled"
    assert driver.discover_installed() == ()
    with pytest.raises(InstallationConflictError, match="rollback requires"):
        driver.rollback(updated_request)
    assert all("GEMINI_API_KEY" not in call[3] for call in fake.calls)
    install_call = next(call for call in fake.calls if "--consent" in call[0])
    assert install_call[3]["GEMINI_CLI_TRUST_WORKSPACE"] == "true"


def test_gemini_extension_project_scope_isolated_and_other_homes_unchanged(tmp_path):
    source = _write_extension(tmp_path / "source")
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()
    codex_canary = tmp_path / "fake-codex" / "config.toml"
    claude_canary = tmp_path / "fake-claude" / "settings.json"
    codex_canary.parent.mkdir()
    claude_canary.parent.mkdir()
    codex_canary.write_text("codex-canary\n", encoding="utf-8")
    claude_canary.write_text('{"claude":"canary"}\n', encoding="utf-8")
    fake = FakeGemini()
    driver = GeminiExtensionTargetDriver(
        data_dir,
        project_roots=(project,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, project, scope=InstallationScope.PROJECT)

    plan = driver.preview_install(request)
    assert plan.native_scope == "workspace"
    installed = driver.install(request, plan, _approval(plan.plan_id))
    assert installed.scope is InstallationScope.PROJECT
    assert fake.calls[-1][2] == project
    assert fake.calls[-1][1] != project
    assert codex_canary.read_text(encoding="utf-8") == "codex-canary\n"
    assert claude_canary.read_text(encoding="utf-8") == '{"claude":"canary"}\n'

    foreign = tmp_path / "foreign-project"
    foreign.mkdir()
    with pytest.raises(InstallationScopeError, match="not explicitly admitted"):
        driver.preview_install(replace(request, root=foreign))


def test_gemini_extension_source_drift_traversal_and_policy_fail_closed(tmp_path):
    source = _write_extension(tmp_path / "source")
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "gemini" / "homes" / "fixture"
    root.mkdir(parents=True)
    fake = FakeGemini()
    driver = GeminiExtensionTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, root)
    plan = driver.preview_install(request)
    manifest_path = source / "gemini-extension.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["description"] = "changed after preview"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(InstallationConflictError, match="checksum"):
        driver.install(request, plan, _approval(plan.plan_id))

    manifest["contextFileName"] = "../outside.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="contextFileName"):
        gemini_extension_source_checksum(source, "sample")

    denied_source = _write_extension(tmp_path / "denied-source")
    denied_driver = GeminiExtensionTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(denied_source,),
        command_runner=FakeGemini(),
        policy=lambda _action, _package, _scope: False,
    )
    denied_request = _local_request(denied_source, root)
    denied_plan = denied_driver.preview_install(denied_request)
    assert denied_plan.policy_status == "managed_policy_denied"
    with pytest.raises(GeminiExtensionPolicyError, match="managed_policy_denied"):
        denied_driver.install(
            denied_request,
            denied_plan,
            _approval(denied_plan.plan_id),
        )


def test_gemini_extension_user_git_gallery_and_failure_boundaries(tmp_path):
    source = _write_extension(tmp_path / "source")
    data_dir = tmp_path / "data"
    managed = data_dir / "native" / "gemini" / "homes" / "fixture"
    managed.mkdir(parents=True)
    user_root = tmp_path / "fake-user"
    user_root.mkdir(parents=True)
    user_driver = GeminiExtensionTargetDriver(
        data_dir,
        source_roots=(source,),
        user_home_root=user_root,
        allow_user_home=True,
        command_runner=FakeGemini(),
    )
    user_request = _local_request(source, user_root, scope=InstallationScope.USER_HOME)
    user_plan = user_driver.preview_install(user_request)
    with pytest.raises(InstallationScopeError, match="explicit approval"):
        user_driver.install(user_request, user_plan, _approval(user_plan.plan_id))

    git_request = _git_request(managed)
    fake = FakeGemini()
    git_driver = GeminiExtensionTargetDriver(
        data_dir,
        managed_roots=(managed,),
        command_runner=fake,
    )
    git_plan = git_driver.preview_install(git_request)
    assert git_plan.network_required is True
    with pytest.raises(GeminiExtensionPolicyError, match="network approval"):
        git_driver.install(git_request, git_plan, _approval(git_plan.plan_id))
    installed = git_driver.install(
        git_request,
        git_plan,
        _approval(git_plan.plan_id, allow_network=True),
    )
    assert installed.status == "installed"

    updated_request = _git_request(managed, version="1.1.0", ref="commit-feedface")
    update_plan = git_driver.preview_update(updated_request)
    assert update_plan.policy_status == "provider_handoff_required"
    handoff = git_driver.update(
        updated_request,
        update_plan,
        GeminiExtensionApproval(update_plan.plan_id, "test-operator"),
    )
    assert handoff.action == "update"
    assert "atomic" in handoff.reason

    gallery_request = _gallery_request(managed)
    gallery_plan = git_driver.preview_install(gallery_request)
    assert gallery_plan.policy_status == "provider_handoff_required"
    gallery = git_driver.install(
        gallery_request,
        gallery_plan,
        GeminiExtensionApproval(gallery_plan.plan_id, "test-operator"),
    )
    assert gallery.action == "select_source"
    assert gallery.command == ()

    failing_root = data_dir / "native" / "gemini" / "homes" / "failing"
    failing_root.mkdir(parents=True)
    failing = FakeGemini(fail_install=True)
    failing_driver = GeminiExtensionTargetDriver(
        data_dir,
        managed_roots=(failing_root,),
        source_roots=(source,),
        command_runner=failing,
    )
    local_request = _local_request(source, failing_root)
    failing_plan = failing_driver.preview_install(local_request)
    with pytest.raises(GeminiExtensionCommandError) as raised:
        failing_driver.install(
            local_request,
            failing_plan,
            _approval(failing_plan.plan_id),
        )
    assert "secret-value-canary" not in str(raised.value)
    assert all(not installed for installed in failing.installed.values())


def _write_extension(root: Path) -> Path:
    (root / "commands" / "sample").mkdir(parents=True)
    (root / "GEMINI.md").write_text("Use the sample extension.\n", encoding="utf-8")
    (root / "commands" / "sample" / "hello.toml").write_text(
        'prompt = "Say hello."\n',
        encoding="utf-8",
    )
    _write_manifest(root, version="1.0.0")
    return root


def _write_manifest(root: Path, *, version: str) -> None:
    manifest = {
        "name": "sample",
        "version": version,
        "description": "Isolated Gemini extension target fixture",
        "contextFileName": "GEMINI.md",
    }
    (root / "gemini-extension.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def _local_request(
    source: Path,
    root: Path,
    *,
    version: str = "1.0.0",
    scope: InstallationScope = InstallationScope.MANAGED_HOME,
) -> GeminiExtensionRequest:
    checksum = gemini_extension_source_checksum(source, "sample")
    return GeminiExtensionRequest(
        package=_package(
            version=version,
            checksum=checksum,
            source_type=IntegrationSourceType.LOCAL,
            source=str(source),
            immutable_ref=f"tree-{checksum[-16:]}",
            scope=scope,
        ),
        scope=scope,
        root=root,
        source=GeminiExtensionSource(
            kind=GeminiExtensionSourceKind.LOCAL,
            location=str(source),
        ),
        extension_name="sample",
    )


def _git_request(
    root: Path,
    *,
    version: str = "1.0.0",
    ref: str = "commit-deadbeef",
) -> GeminiExtensionRequest:
    return GeminiExtensionRequest(
        package=_package(
            version=version,
            checksum="sha256:" + "a" * 64,
            source_type=IntegrationSourceType.GIT,
            source="https://github.com/example/sample.git",
            immutable_ref=ref,
            scope=InstallationScope.MANAGED_HOME,
        ),
        scope=InstallationScope.MANAGED_HOME,
        root=root,
        source=GeminiExtensionSource(
            kind=GeminiExtensionSourceKind.GIT,
            location="https://github.com/example/sample.git",
            ref=ref,
        ),
        extension_name="sample",
    )


def _gallery_request(root: Path) -> GeminiExtensionRequest:
    source = "https://geminicli.com/extensions/browse/sample"
    return GeminiExtensionRequest(
        package=_package(
            version="1.0.0",
            checksum="sha256:" + "b" * 64,
            source_type=IntegrationSourceType.PROVIDER_MARKETPLACE,
            source=source,
            immutable_ref="gallery-entry-sample-v1",
            scope=InstallationScope.MANAGED_HOME,
        ),
        scope=InstallationScope.MANAGED_HOME,
        root=root,
        source=GeminiExtensionSource(
            kind=GeminiExtensionSourceKind.GALLERY,
            location=source,
        ),
        extension_name="gallery-sample",
    )


def _package(
    *,
    version: str,
    checksum: str,
    source_type: IntegrationSourceType,
    source: str,
    immutable_ref: str,
    scope: InstallationScope,
) -> IntegrationPackage:
    return IntegrationPackage(
        id="example.gemini-extension",
        version=version,
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=source_type,
        source=source,
        immutable_ref=immutable_ref,
        checksum=checksum,
        components=(
            IntegrationComponent(
                id="target-extension",
                type=IntegrationComponentType.EXTENSION,
                portable=False,
            ),
        ),
        requirements=(),
        overlays=(
            IntegrationTargetOverlay(
                target_id=GEMINI_EXTENSION_TARGET_ID,
                component_ids=("target-extension",),
            ),
        ),
        compatibility=(IntegrationCompatibility(target_id=GEMINI_EXTENSION_TARGET_ID),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.MANUAL_REVIEW,
        verification_steps=("gemini-extension-list-json",),
        rollback_steps=("restore-reviewed-source", "gemini-extension-install"),
    )


def _approval(plan_id: str, *, allow_network: bool = False) -> GeminiExtensionApproval:
    return GeminiExtensionApproval(
        plan_id,
        "test-operator",
        native_consent_acknowledged=True,
        source_trust_acknowledged=True,
        allow_network=allow_network,
    )
