from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from gpt2giga_harness.codex_plugin_target import (
    CODEX_PLUGIN_TARGET_ID,
    CodexPluginApproval,
    CodexPluginCommandError,
    CodexPluginCommandResult,
    CodexPluginPolicyError,
    CodexPluginRequest,
    CodexPluginSource,
    CodexPluginSourceKind,
    CodexPluginTargetDriver,
    codex_plugin_source_checksum,
    codex_plugin_target_plugin,
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


class FakeCodex:
    def __init__(self, *, fail_add: bool = False) -> None:
        self.fail_add = fail_add
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self.marketplaces: dict[Path, dict[str, dict[str, object]]] = {}
        self.installed: dict[Path, dict[str, dict[str, object]]] = {}
        self.remote_versions = {"sample@remote-market": "1.0.0"}

    def __call__(self, argv, env, _cwd, _timeout):
        root = Path(env["CODEX_HOME"])
        args = argv[1:]
        self.calls.append((argv, root))
        if args == ("--version",):
            return CodexPluginCommandResult(0, "codex-cli 0.144.5\n")
        if args[-1:] == ("--help",):
            return CodexPluginCommandResult(0, "Options: --json\n")
        if args == ("plugin", "marketplace", "list", "--json"):
            return self._json(
                {"marketplaces": list(self.marketplaces.setdefault(root, {}).values())}
            )
        if args[:3] == ("plugin", "marketplace", "add"):
            location = args[3]
            if args[-1] != "--json":
                raise AssertionError(args)
            if Path(location).is_dir():
                manifest = json.loads(
                    (
                        Path(location) / ".agents" / "plugins" / "marketplace.json"
                    ).read_text(encoding="utf-8")
                )
                name = manifest["name"]
                source = {
                    "sourceType": "local",
                    "source": str(Path(location).resolve()),
                }
            else:
                name = "remote-market"
                source = {"sourceType": "git", "source": location}
                if "--ref" in args:
                    source["ref"] = args[args.index("--ref") + 1]
            markets = self.marketplaces.setdefault(root, {})
            already_added = name in markets
            markets[name] = {
                "name": name,
                "root": str(Path(location).resolve()),
                "marketplaceSource": source,
            }
            return self._json(
                {
                    "marketplaceName": name,
                    "installedRoot": str(Path(location).resolve()),
                    "alreadyAdded": already_added,
                }
            )
        if args[:3] == ("plugin", "marketplace", "upgrade"):
            return self._json({"marketplaceName": args[3], "upgraded": True})
        if args[:3] == ("plugin", "marketplace", "remove"):
            name = args[3]
            self.marketplaces.setdefault(root, {}).pop(name, None)
            return self._json({"marketplaceName": name, "installedRoot": None})
        if args == ("plugin", "list", "--available", "--json"):
            installed = list(self.installed.setdefault(root, {}).values())
            available = []
            for marketplace in self.marketplaces.setdefault(root, {}).values():
                if marketplace["marketplaceSource"]["sourceType"] != "local":
                    selector = f"sample@{marketplace['name']}"
                    if selector not in self.installed[root]:
                        available.append(self._remote_plugin_item(marketplace))
                    continue
                marketplace_root = Path(marketplace["root"])
                catalog = json.loads(
                    (
                        marketplace_root / ".agents" / "plugins" / "marketplace.json"
                    ).read_text(encoding="utf-8")
                )
                for entry in catalog["plugins"]:
                    selector = f"{entry['name']}@{catalog['name']}"
                    if selector in self.installed[root]:
                        continue
                    available.append(
                        self._plugin_item(marketplace_root, entry, catalog)
                    )
            return self._json({"installed": installed, "available": available})
        if args[:2] == ("plugin", "add"):
            selector = args[2]
            if self.fail_add:
                return CodexPluginCommandResult(
                    1,
                    "",
                    "token=secret-value-canary must never escape",
                )
            plugin_name, marketplace_name = selector.split("@", 1)
            marketplace = self.marketplaces[root][marketplace_name]
            if marketplace["marketplaceSource"]["sourceType"] == "local":
                marketplace_root = Path(marketplace["root"])
                catalog = json.loads(
                    (
                        marketplace_root / ".agents" / "plugins" / "marketplace.json"
                    ).read_text(encoding="utf-8")
                )
                entry = next(
                    item for item in catalog["plugins"] if item["name"] == plugin_name
                )
                item = self._plugin_item(marketplace_root, entry, catalog)
            else:
                item = self._remote_plugin_item(marketplace)
            item["installed"] = True
            item["enabled"] = True
            self.installed.setdefault(root, {})[selector] = item
            return self._json(
                {
                    "pluginId": selector,
                    "name": plugin_name,
                    "marketplaceName": marketplace_name,
                    "version": item["version"],
                    "installedPath": str(root / "plugins" / "cache" / selector),
                    "authPolicy": "ON_INSTALL",
                }
            )
        if args[:2] == ("plugin", "remove"):
            selector = args[2]
            self.installed.setdefault(root, {}).pop(selector, None)
            name, marketplace = selector.split("@", 1)
            return self._json(
                {
                    "pluginId": selector,
                    "name": name,
                    "marketplaceName": marketplace,
                }
            )
        raise AssertionError(f"unexpected Codex argv: {argv!r}")

    def _plugin_item(self, root, entry, catalog):
        source = entry["source"]
        relative = source["path"] if isinstance(source, dict) else source
        plugin_root = root / relative.removeprefix("./")
        manifest = json.loads(
            (plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        selector = f"{entry['name']}@{catalog['name']}"
        return {
            "pluginId": selector,
            "name": entry["name"],
            "marketplaceName": catalog["name"],
            "version": manifest["version"],
            "installed": False,
            "enabled": False,
            "source": {"source": "local", "path": str(plugin_root.resolve())},
            "marketplaceSource": {
                "sourceType": "local",
                "source": str(root.resolve()),
            },
            "installPolicy": entry["policy"]["installation"],
            "authPolicy": entry["policy"]["authentication"],
        }

    def _remote_plugin_item(self, marketplace):
        selector = f"sample@{marketplace['name']}"
        return {
            "pluginId": selector,
            "name": "sample",
            "marketplaceName": marketplace["name"],
            "version": self.remote_versions[selector],
            "installed": False,
            "enabled": False,
            "source": {"source": "git-subdir", "path": "./plugins/sample"},
            "marketplaceSource": marketplace["marketplaceSource"],
            "installPolicy": "AVAILABLE",
            "authPolicy": "ON_INSTALL",
        }

    @staticmethod
    def _json(value):
        return CodexPluginCommandResult(0, json.dumps(value))


def test_codex_plugin_lifecycle_is_native_verified_and_handoffs_are_explicit(
    tmp_path,
):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "homes" / "fixture"
    root.mkdir(parents=True)
    fake = FakeCodex()
    driver = CodexPluginTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, root)

    probe = driver.probe_target()
    registry = ExtensionTargetRegistry()
    registry.register(codex_plugin_target_plugin(lambda: driver))
    assert probe.status == "supported"
    assert probe.version == "codex-cli 0.144.5"
    assert len(probe.capabilities) == 7
    assert registry.create_driver(CODEX_PLUGIN_TARGET_ID) is driver

    plan = driver.preview_install(request)
    assert plan.expected_version is None
    assert plan.native_consent_required is True
    assert plan.restart_required is True
    with pytest.raises(CodexPluginPolicyError, match="native consent"):
        driver.install(
            request,
            plan,
            CodexPluginApproval(plan.plan_id, "test-operator"),
        )

    installed = driver.install(
        request,
        plan,
        CodexPluginApproval(
            plan.plan_id,
            "test-operator",
            native_consent_acknowledged=True,
        ),
    )
    assert installed.status == "installed"
    assert installed.restart_required is True
    assert driver.health(request).status == "healthy"
    assert driver.discover_installed()[0].plugin_id == "sample@gigaloom-probe"

    disabled = driver.disable(request)
    enabled = driver.enable(request)
    assert disabled.interaction.startswith("open /plugins")
    assert enabled.consent_owner == "codex"
    assert enabled.command == ("codex",)

    _write_plugin_manifest(source, version="1.1.0")
    updated_request = _local_request(source, root, version="1.1.0")
    update_plan = driver.preview_update(updated_request)
    assert update_plan.expected_version == "1.0.0"
    updated = driver.update(
        updated_request,
        update_plan,
        CodexPluginApproval(
            update_plan.plan_id,
            "test-operator",
            native_consent_acknowledged=True,
        ),
    )
    assert updated.status == "updated"
    assert driver.verify(updated_request).version == "1.1.0"
    assert driver.rollback(updated_request).interaction.startswith("restore")

    uninstall_plan = driver.preview_uninstall(updated_request)
    uninstalled = driver.uninstall(
        updated_request,
        uninstall_plan,
        CodexPluginApproval(
            uninstall_plan.plan_id,
            "test-operator",
            native_consent_acknowledged=True,
        ),
    )
    assert uninstalled.status == "uninstalled"
    assert driver.discover_installed() == ()


def test_codex_plugin_rejects_source_drift_traversal_and_project_scope(tmp_path):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "homes" / "fixture"
    root.mkdir(parents=True)
    driver = CodexPluginTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(source,),
        command_runner=FakeCodex(),
    )
    request = _local_request(source, root)
    plan = driver.preview_install(request)
    catalog_path = source / ".agents" / "plugins" / "marketplace.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["plugins"][0]["policy"]["authentication"] = "ON_FIRST_USE"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(InstallationConflictError, match="changed after preview"):
        driver.install(
            request,
            plan,
            CodexPluginApproval(
                plan.plan_id,
                "test-operator",
                native_consent_acknowledged=True,
            ),
        )

    (source / "plugins" / "sample" / "skills" / "hello" / "SKILL.md").write_text(
        "changed after review\n",
        encoding="utf-8",
    )
    with pytest.raises(InstallationConflictError, match="checksum"):
        driver.preview_install(request)

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["plugins"][0]["source"]["path"] = "./../outside"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="path"):
        codex_plugin_source_checksum(source, "gigaloom-probe", "sample")

    project = tmp_path / "project"
    project.mkdir()
    project_request = replace(
        request,
        package=replace(request.package, scopes=(InstallationScope.PROJECT,)),
        scope=InstallationScope.PROJECT,
        root=project,
    )
    with pytest.raises(InstallationScopeError, match="home-scoped"):
        driver.preview_install(project_request)


def test_codex_plugin_policy_user_home_and_git_network_fail_closed(tmp_path):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    managed = data_dir / "native" / "codex" / "homes" / "fixture"
    managed.mkdir(parents=True)
    fake = FakeCodex()
    denied_driver = CodexPluginTargetDriver(
        data_dir,
        managed_roots=(managed,),
        source_roots=(source,),
        command_runner=fake,
        policy=lambda _action, _package, _scope: False,
    )
    request = _local_request(source, managed)
    denied_plan = denied_driver.preview_install(request)
    assert denied_plan.policy_status == "managed_policy_denied"
    with pytest.raises(CodexPluginPolicyError, match="managed_policy_denied"):
        denied_driver.install(
            request,
            denied_plan,
            CodexPluginApproval(
                denied_plan.plan_id,
                "test-operator",
                native_consent_acknowledged=True,
            ),
        )

    user_root = tmp_path / "fake-user" / ".codex"
    user_root.mkdir(parents=True)
    user_driver = CodexPluginTargetDriver(
        data_dir,
        source_roots=(source,),
        user_home_root=user_root,
        allow_user_home=True,
        command_runner=FakeCodex(),
    )
    user_request = _local_request(
        source,
        user_root,
        scope=InstallationScope.USER_HOME,
    )
    user_plan = user_driver.preview_install(user_request)
    with pytest.raises(InstallationScopeError, match="explicit approval"):
        user_driver.install(
            user_request,
            user_plan,
            CodexPluginApproval(
                user_plan.plan_id,
                "test-operator",
                native_consent_acknowledged=True,
            ),
        )

    git_request = _git_request(managed)
    git_driver = CodexPluginTargetDriver(
        data_dir,
        managed_roots=(managed,),
        command_runner=FakeCodex(),
    )
    git_plan = git_driver.preview_install(git_request)
    assert git_plan.network_required is True
    with pytest.raises(CodexPluginPolicyError, match="network approval"):
        git_driver.install(
            git_request,
            git_plan,
            CodexPluginApproval(
                git_plan.plan_id,
                "test-operator",
                native_consent_acknowledged=True,
            ),
        )

    installed = git_driver.install(
        git_request,
        git_plan,
        CodexPluginApproval(
            git_plan.plan_id,
            "test-operator",
            native_consent_acknowledged=True,
            allow_network=True,
        ),
    )
    assert installed.status == "installed"
    assert git_driver.verify(git_request).status == "healthy"

    updated_git_request = _git_request(
        managed,
        version="1.1.0",
        ref="commit-feedface",
    )
    update_plan = git_driver.preview_update(updated_git_request)
    assert update_plan.policy_status == "provider_handoff_required"
    handoff = git_driver.update(
        updated_git_request,
        update_plan,
        CodexPluginApproval(update_plan.plan_id, "test-operator"),
    )
    assert handoff.action == "update"
    assert "immutable Git ref" in handoff.interaction

    uninstall_plan = git_driver.preview_uninstall(git_request)
    removed = git_driver.uninstall(
        git_request,
        uninstall_plan,
        CodexPluginApproval(
            uninstall_plan.plan_id,
            "test-operator",
            native_consent_acknowledged=True,
        ),
    )
    assert removed.status == "uninstalled"


def test_codex_plugin_native_failure_is_redacted_and_registration_is_reverted(
    tmp_path,
):
    source = _write_marketplace(tmp_path / "source")
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "homes" / "fixture"
    root.mkdir(parents=True)
    fake = FakeCodex(fail_add=True)
    driver = CodexPluginTargetDriver(
        data_dir,
        managed_roots=(root,),
        source_roots=(source,),
        command_runner=fake,
    )
    request = _local_request(source, root)
    plan = driver.preview_install(request)

    with pytest.raises(CodexPluginCommandError) as raised:
        driver.install(
            request,
            plan,
            CodexPluginApproval(
                plan.plan_id,
                "test-operator",
                native_consent_acknowledged=True,
            ),
        )

    assert "secret-value-canary" not in str(raised.value)
    assert fake.marketplaces[root] == {}
    assert fake.installed.get(root, {}) == {}


def _write_marketplace(root: Path) -> Path:
    (root / ".agents" / "plugins").mkdir(parents=True)
    (root / "plugins" / "sample" / ".codex-plugin").mkdir(parents=True)
    (root / "plugins" / "sample" / "skills" / "hello").mkdir(parents=True)
    catalog = {
        "name": "gigaloom-probe",
        "interface": {"displayName": "GigaLoom Probe"},
        "plugins": [
            {
                "name": "sample",
                "source": {"source": "local", "path": "./plugins/sample"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }
    (root / ".agents" / "plugins" / "marketplace.json").write_text(
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
        "description": "Isolated Codex plugin target fixture",
        "skills": "./skills/",
    }
    (root / "plugins" / "sample" / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def _local_request(
    source: Path,
    root: Path,
    *,
    version: str = "1.0.0",
    scope: InstallationScope = InstallationScope.MANAGED_HOME,
) -> CodexPluginRequest:
    checksum = codex_plugin_source_checksum(source, "gigaloom-probe", "sample")
    return CodexPluginRequest(
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
        source=CodexPluginSource(
            marketplace_name="gigaloom-probe",
            kind=CodexPluginSourceKind.LOCAL,
            location=str(source),
        ),
        plugin_name="sample",
    )


def _git_request(
    root: Path,
    *,
    version: str = "1.0.0",
    ref: str = "commit-deadbeef",
) -> CodexPluginRequest:
    return CodexPluginRequest(
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
        source=CodexPluginSource(
            marketplace_name="remote-market",
            kind=CodexPluginSourceKind.GIT,
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
        id="example.codex-plugin",
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
                target_id=CODEX_PLUGIN_TARGET_ID,
                component_ids=("target-plugin",),
            ),
        ),
        compatibility=(IntegrationCompatibility(target_id=CODEX_PLUGIN_TARGET_ID),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.MANUAL_REVIEW,
        verification_steps=("codex-plugin-list-json",),
        rollback_steps=("restore-reviewed-source", "codex-plugin-add"),
    )
