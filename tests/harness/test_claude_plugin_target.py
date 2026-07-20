from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from gpt2giga_harness.claude_plugin_target import (
    CLAUDE_PLUGIN_TARGET_ID,
    ClaudePluginApproval,
    ClaudePluginCommandError,
    ClaudePluginCommandResult,
    ClaudePluginPolicyError,
    ClaudePluginRequest,
    ClaudePluginSource,
    ClaudePluginSourceKind,
    ClaudePluginTargetDriver,
    claude_plugin_source_checksum,
    claude_plugin_target_plugin,
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


class FakeClaude:
    def __init__(self, *, fail_install: bool = False) -> None:
        self.fail_install = fail_install
        self.calls: list[tuple[tuple[str, ...], Path, Path | None, dict[str, str]]] = []
        self.marketplaces: dict[
            tuple[Path, Path | None], dict[str, dict[str, object]]
        ] = {}
        self.installed: dict[
            tuple[Path, Path | None], dict[str, dict[str, object]]
        ] = {}
        self.remote_versions = {"sample@remote-market": "1.0.0"}

    def __call__(self, argv, env, cwd, _timeout):
        config_dir = Path(env["CLAUDE_CONFIG_DIR"])
        key = (config_dir, cwd)
        args = argv[1:]
        self.calls.append((argv, config_dir, cwd, dict(env)))
        if args == ("--version",):
            return ClaudePluginCommandResult(0, "2.1.212 (Claude Code)\n")
        if args[-1:] == ("--help",):
            return ClaudePluginCommandResult(
                0, "Options: --json --scope --strict update\n"
            )
        if args[:3] == ("plugin", "validate", "--strict"):
            return ClaudePluginCommandResult(0, "Validation passed\n")
        if args == ("plugin", "marketplace", "list", "--json"):
            return self._json(list(self.marketplaces.setdefault(key, {}).values()))
        if args[:3] == ("plugin", "marketplace", "add"):
            location = args[3]
            native_scope = args[args.index("--scope") + 1]
            if Path(location).is_dir():
                manifest = json.loads(
                    (Path(location) / ".claude-plugin" / "marketplace.json").read_text(
                        encoding="utf-8"
                    )
                )
                name = manifest["name"]
                source = {
                    "name": name,
                    "source": "directory",
                    "path": str(Path(location).resolve()),
                    "installLocation": str(Path(location).resolve()),
                    "scope": native_scope,
                }
            else:
                name = "remote-market"
                source = {
                    "name": name,
                    "source": "git",
                    "sourceLocation": location,
                    "ref": location.rsplit("#", 1)[-1],
                    "scope": native_scope,
                }
                if "--sparse" in args:
                    source["sparse"] = list(args[args.index("--sparse") + 1 :])
            self.marketplaces.setdefault(key, {})[name] = source
            return ClaudePluginCommandResult(0, f"added {name}\n")
        if args[:3] == ("plugin", "marketplace", "update"):
            return ClaudePluginCommandResult(0, f"updated {args[3]}\n")
        if args[:3] == ("plugin", "marketplace", "remove"):
            self.marketplaces.setdefault(key, {}).pop(args[3], None)
            return ClaudePluginCommandResult(0, f"removed {args[3]}\n")
        if args == ("plugin", "list", "--json"):
            return self._json(list(self.installed.setdefault(key, {}).values()))
        if args[:2] == ("plugin", "install"):
            if self.fail_install:
                return ClaudePluginCommandResult(
                    1,
                    "",
                    "token=secret-value-canary must never escape",
                )
            selector = args[2]
            native_scope = args[args.index("--scope") + 1]
            item = self._plugin_item(key, selector, native_scope)
            self.installed.setdefault(key, {})[selector] = item
            return ClaudePluginCommandResult(0, f"installed {selector}\n")
        if args[:2] == ("plugin", "update"):
            selector = args[2]
            native_scope = args[args.index("--scope") + 1]
            self.installed.setdefault(key, {})[selector] = self._plugin_item(
                key, selector, native_scope
            )
            return ClaudePluginCommandResult(0, f"updated {selector}\n")
        if args[:2] in {("plugin", "enable"), ("plugin", "disable")}:
            selector = args[2]
            self.installed.setdefault(key, {})[selector]["enabled"] = (
                args[1] == "enable"
            )
            return ClaudePluginCommandResult(0, f"{args[1]}d {selector}\n")
        if args[:2] == ("plugin", "uninstall"):
            selector = args[2]
            self.installed.setdefault(key, {}).pop(selector, None)
            return ClaudePluginCommandResult(0, f"uninstalled {selector}\n")
        raise AssertionError(f"unexpected Claude argv: {argv!r}")

    def _plugin_item(self, key, selector, native_scope):
        plugin_name, marketplace_name = selector.split("@", 1)
        marketplace = self.marketplaces[key][marketplace_name]
        if marketplace["source"] == "directory":
            marketplace_root = Path(marketplace["path"])
            catalog = json.loads(
                (marketplace_root / ".claude-plugin" / "marketplace.json").read_text(
                    encoding="utf-8"
                )
            )
            entry = next(
                item for item in catalog["plugins"] if item["name"] == plugin_name
            )
            plugin_root = marketplace_root / entry["source"].removeprefix("./")
            manifest = json.loads(
                (plugin_root / ".claude-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            version = manifest["version"]
        else:
            version = self.remote_versions[selector]
        return {
            "id": selector,
            "version": version,
            "scope": native_scope,
            "enabled": True,
            "installPath": str(key[0] / "plugins" / "cache" / selector),
        }

    @staticmethod
    def _json(value):
        return ClaudePluginCommandResult(0, json.dumps(value))


def test_claude_plugin_lifecycle_is_native_validated_and_verified(tmp_path):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "claude" / "homes" / "fixture"
    root.mkdir(parents=True)
    fake = FakeClaude()
    driver = ClaudePluginTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, root)

    probe = driver.probe_target()
    registry = ExtensionTargetRegistry()
    registry.register(claude_plugin_target_plugin(lambda: driver))
    assert probe.status == "supported"
    assert probe.version == "2.1.212 (Claude Code)"
    assert len(probe.capabilities) == 11
    assert registry.create_driver(CLAUDE_PLUGIN_TARGET_ID) is driver

    plan = driver.preview_install(request)
    assert plan.expected_version is None
    assert plan.native_scope == "user"
    assert plan.native_consent_required is True
    with pytest.raises(ClaudePluginPolicyError, match="native consent"):
        driver.install(
            request,
            plan,
            ClaudePluginApproval(plan.plan_id, "test-operator"),
        )

    installed = driver.install(request, plan, _approval(plan.plan_id))
    assert installed.status == "installed"
    assert installed.restart_required is True
    assert driver.health(request).status == "healthy"
    assert driver.discover_installed()[0].plugin_id == "sample@gigaloom-probe"

    disable_plan = driver.preview_disable(request)
    disabled = driver.disable(request, disable_plan, _approval(disable_plan.plan_id))
    assert disabled.status == "disabled"
    assert disabled.enabled is False
    enable_plan = driver.preview_enable(request)
    enabled = driver.enable(request, enable_plan, _approval(enable_plan.plan_id))
    assert enabled.status == "enabled"
    assert enabled.enabled is True

    _write_plugin_manifest(source, version="1.1.0")
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
    assert driver.rollback(updated_request).consent_owner == "claude"

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
    assert all("ANTHROPIC_API_KEY" not in call[3] for call in fake.calls)


def test_claude_plugin_project_scope_isolated_and_other_homes_unchanged(tmp_path):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()
    codex_canary = tmp_path / "fake-codex" / "config.toml"
    gemini_canary = tmp_path / "fake-gemini" / "settings.json"
    codex_canary.parent.mkdir()
    gemini_canary.parent.mkdir()
    codex_canary.write_text("codex-canary\n", encoding="utf-8")
    gemini_canary.write_text('{"gemini":"canary"}\n', encoding="utf-8")
    fake = FakeClaude()
    driver = ClaudePluginTargetDriver(
        data_dir,
        project_roots=(project,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, project, scope=InstallationScope.PROJECT)

    plan = driver.preview_install(request)
    assert plan.native_scope == "project"
    installed = driver.install(request, plan, _approval(plan.plan_id))
    assert installed.scope is InstallationScope.PROJECT
    assert fake.calls[-1][2] == project
    assert fake.calls[-1][1] != project
    assert codex_canary.read_text(encoding="utf-8") == "codex-canary\n"
    assert gemini_canary.read_text(encoding="utf-8") == '{"gemini":"canary"}\n'

    foreign = tmp_path / "foreign-project"
    foreign.mkdir()
    with pytest.raises(InstallationScopeError, match="not explicitly admitted"):
        driver.preview_install(
            replace(request, root=foreign, package=replace(request.package))
        )


def test_claude_plugin_source_drift_traversal_and_policy_fail_closed(tmp_path):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "claude" / "homes" / "fixture"
    root.mkdir(parents=True)
    fake = FakeClaude()
    driver = ClaudePluginTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, root)
    plan = driver.preview_install(request)
    catalog_path = source / ".claude-plugin" / "marketplace.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["description"] = "changed after preview"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(InstallationConflictError, match="changed after preview"):
        driver.install(request, plan, _approval(plan.plan_id))

    (source / "plugins" / "sample" / "skills" / "hello" / "SKILL.md").write_text(
        "changed after review\n",
        encoding="utf-8",
    )
    with pytest.raises(InstallationConflictError, match="checksum"):
        driver.preview_install(request)

    catalog["plugins"][0]["source"] = "./../outside"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="source"):
        claude_plugin_source_checksum(source, "gigaloom-probe", "sample")

    denied_source = _write_marketplace(tmp_path / "denied-source")
    denied_driver = ClaudePluginTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(denied_source,),
        command_runner=FakeClaude(),
        policy=lambda _action, _package, _scope: False,
    )
    denied_request = _local_request(denied_source, root)
    denied_plan = denied_driver.preview_install(denied_request)
    assert denied_plan.policy_status == "managed_policy_denied"
    with pytest.raises(ClaudePluginPolicyError, match="managed_policy_denied"):
        denied_driver.install(
            denied_request,
            denied_plan,
            _approval(denied_plan.plan_id),
        )


def test_claude_plugin_user_git_network_and_failure_cleanup(tmp_path):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    managed = data_dir / "native" / "claude" / "homes" / "fixture"
    managed.mkdir(parents=True)
    user_root = tmp_path / "fake-user" / ".claude"
    user_root.mkdir(parents=True)
    user_driver = ClaudePluginTargetDriver(
        data_dir,
        source_roots=(source,),
        user_home_root=user_root,
        allow_user_home=True,
        command_runner=FakeClaude(),
    )
    user_request = _local_request(
        source,
        user_root,
        scope=InstallationScope.USER_HOME,
    )
    user_plan = user_driver.preview_install(user_request)
    with pytest.raises(InstallationScopeError, match="explicit approval"):
        user_driver.install(user_request, user_plan, _approval(user_plan.plan_id))

    git_request = _git_request(managed)
    fake = FakeClaude()
    git_driver = ClaudePluginTargetDriver(
        data_dir,
        managed_roots=(managed,),
        command_runner=fake,
    )
    git_plan = git_driver.preview_install(git_request)
    assert git_plan.network_required is True
    with pytest.raises(ClaudePluginPolicyError, match="network approval"):
        git_driver.install(git_request, git_plan, _approval(git_plan.plan_id))
    installed = git_driver.install(
        git_request,
        git_plan,
        _approval(git_plan.plan_id, allow_network=True),
    )
    assert installed.status == "installed"
    git_key = (managed, None)
    marketplace = fake.marketplaces[git_key]["remote-market"]
    original_source = marketplace["sourceLocation"]
    marketplace["sourceLocation"] = git_request.source.location
    marketplace.pop("ref")
    assert git_driver.verify(git_request).status == "degraded"
    marketplace["sourceLocation"] = original_source
    marketplace["ref"] = git_request.source.ref

    updated_request = _git_request(managed, version="1.1.0", ref="commit-feedface")
    update_plan = git_driver.preview_update(updated_request)
    assert update_plan.policy_status == "provider_handoff_required"
    handoff = git_driver.update(
        updated_request,
        update_plan,
        ClaudePluginApproval(update_plan.plan_id, "test-operator"),
    )
    assert handoff.action == "update"
    assert "non-atomic" in handoff.reason

    failing = FakeClaude(fail_install=True)
    failing_driver = ClaudePluginTargetDriver(
        data_dir,
        managed_roots=(managed,),
        source_roots=(source,),
        command_runner=failing,
    )
    local_request = _local_request(source, managed)
    failing_plan = failing_driver.preview_install(local_request)
    with pytest.raises(ClaudePluginCommandError) as raised:
        failing_driver.install(
            local_request,
            failing_plan,
            _approval(failing_plan.plan_id),
        )
    assert "secret-value-canary" not in str(raised.value)
    assert failing.marketplaces[git_key] == {}
    assert failing.installed.get(git_key, {}) == {}


def _write_marketplace(root: Path) -> Path:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / "plugins" / "sample" / ".claude-plugin").mkdir(parents=True)
    (root / "plugins" / "sample" / "skills" / "hello").mkdir(parents=True)
    catalog = {
        "name": "gigaloom-probe",
        "description": "Isolated Claude plugin target fixture marketplace",
        "owner": {"name": "GigaLoom"},
        "plugins": [
            {
                "name": "sample",
                "source": "./plugins/sample",
                "description": "Isolated Claude plugin target fixture",
            }
        ],
    }
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    _write_plugin_manifest(root, version="1.0.0")
    (root / "plugins" / "sample" / "skills" / "hello" / "SKILL.md").write_text(
        "---\nname: hello\ndescription: Return a greeting.\n---\n\nSay hello.\n",
        encoding="utf-8",
    )
    return root


def _write_plugin_manifest(root: Path, *, version: str) -> None:
    manifest = {
        "name": "sample",
        "version": version,
        "description": "Isolated Claude plugin target fixture",
        "author": {"name": "GigaLoom"},
        "skills": "./skills/",
    }
    (root / "plugins" / "sample" / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def _local_request(
    source: Path,
    root: Path,
    *,
    version: str = "1.0.0",
    scope: InstallationScope = InstallationScope.MANAGED_HOME,
) -> ClaudePluginRequest:
    checksum = claude_plugin_source_checksum(source, "gigaloom-probe", "sample")
    return ClaudePluginRequest(
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
        source=ClaudePluginSource(
            marketplace_name="gigaloom-probe",
            kind=ClaudePluginSourceKind.LOCAL,
            location=str(source),
        ),
        plugin_name="sample",
    )


def _git_request(
    root: Path,
    *,
    version: str = "1.0.0",
    ref: str = "commit-deadbeef",
) -> ClaudePluginRequest:
    return ClaudePluginRequest(
        package=_package(
            version=version,
            checksum="sha256:" + "a" * 64,
            source_type=IntegrationSourceType.GIT,
            source="https://github.com/example/plugins.git",
            immutable_ref=ref,
            scope=InstallationScope.MANAGED_HOME,
        ),
        scope=InstallationScope.MANAGED_HOME,
        root=root,
        source=ClaudePluginSource(
            marketplace_name="remote-market",
            kind=ClaudePluginSourceKind.GIT,
            location="https://github.com/example/plugins.git",
            ref=ref,
            sparse=("plugins/sample",),
        ),
        plugin_name="sample",
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
        id="example.claude-plugin",
        version=version,
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=source_type,
        source=source,
        immutable_ref=immutable_ref,
        checksum=checksum,
        components=(
            IntegrationComponent(
                id="target-plugin",
                type=IntegrationComponentType.PLUGIN,
                portable=False,
            ),
        ),
        requirements=(),
        overlays=(
            IntegrationTargetOverlay(
                target_id=CLAUDE_PLUGIN_TARGET_ID,
                component_ids=("target-plugin",),
            ),
        ),
        compatibility=(IntegrationCompatibility(target_id=CLAUDE_PLUGIN_TARGET_ID),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.MANUAL_REVIEW,
        verification_steps=("claude-plugin-list-json",),
        rollback_steps=("restore-reviewed-source", "claude-plugin-update"),
    )


def _approval(plan_id: str, *, allow_network: bool = False) -> ClaudePluginApproval:
    return ClaudePluginApproval(
        plan_id,
        "test-operator",
        native_consent_acknowledged=True,
        allow_network=allow_network,
    )
