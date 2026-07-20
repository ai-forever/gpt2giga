from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import stat

import pytest

from gpt2giga_harness.integration_installer import (
    FileInstallMutation,
    InstallationApproval,
    InstallationConflictError,
    InstallationRequest,
    InstallationScopeError,
    InstallationStateError,
    InstallationTarget,
    InstallationVerificationError,
    TransactionalIntegrationInstaller,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationPolicyClass,
    IntegrationRequirement,
    IntegrationRequirementType,
    IntegrationSourceType,
    IntegrationUpdatePolicy,
)


_DIGEST = "sha256:" + "a" * 64


def test_preview_is_content_free_and_apply_requires_bound_approval(tmp_path):
    service = TransactionalIntegrationInstaller(tmp_path / "data")
    request = _request(tmp_path / "data" / "native" / "codex" / "home")

    plan = service.preview(request)

    assert plan.changed is True
    assert plan.scope is InstallationScope.MANAGED_HOME
    assert plan.mutations[0].relative_path == "config/settings.json"
    assert not hasattr(plan.mutations[0], "content")
    assert "secret-value-canary" not in repr(plan)
    with pytest.raises(InstallationConflictError, match="approval"):
        service.apply(
            request,
            plan,
            InstallationApproval("plan_" + "f" * 64, "test-operator"),
            verifier=_verifier,
        )
    assert not request.target.root.exists()


def test_managed_install_is_idempotent_discoverable_verified_and_reversible(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    root.mkdir(parents=True)
    original = root / "config" / "existing.txt"
    original.parent.mkdir(parents=True)
    original.write_text("before\n", encoding="utf-8")
    request = _request(
        root,
        mutations=(
            FileInstallMutation("config/existing.txt", b"after\n"),
            FileInstallMutation("payload/new.txt", b"secret-value-canary\n"),
        ),
    )
    service = TransactionalIntegrationInstaller(data_dir)
    plan = service.preview(request)
    approval = InstallationApproval(plan.plan_id, "test-operator")

    first = service.apply(request, plan, approval, verifier=_verifier)
    retried = service.apply(request, plan, approval, verifier=_verifier)

    assert first == retried
    assert first.status == "committed"
    assert original.read_text(encoding="utf-8") == "after\n"
    assert (root / "payload" / "new.txt").read_text(encoding="utf-8") == (
        "secret-value-canary\n"
    )
    installed = service.discover()
    assert len(installed) == 1
    assert installed[0].current is True
    assert service.verify(first.transaction_id).current is True
    assert (
        stat.S_IMODE((data_dir / "integrations" / "installations").stat().st_mode)
        == 0o700
    )
    for state_file in (data_dir / "integrations" / "installations").rglob("*.json"):
        assert "secret-value-canary" not in state_file.read_text(encoding="utf-8")
        assert stat.S_IMODE(state_file.stat().st_mode) == 0o600

    rolled_back = service.rollback(first.transaction_id)

    assert rolled_back.status == "rolled_back"
    assert original.read_text(encoding="utf-8") == "before\n"
    assert not (root / "payload" / "new.txt").exists()
    assert service.discover() == ()


def test_update_is_atomic_idempotent_and_rolls_back_to_previous_owner(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    service = TransactionalIntegrationInstaller(data_dir)
    initial_request = _request(
        root,
        mutations=(FileInstallMutation("config/settings.json", b"one"),),
    )
    initial_plan = service.preview(initial_request)
    initial = service.apply(
        initial_request,
        initial_plan,
        InstallationApproval(initial_plan.plan_id, "test-operator"),
        verifier=_verifier,
    )
    updated_request = replace(
        initial_request,
        package=replace(initial_request.package, version="2.0.0"),
        mutations=(FileInstallMutation("config/settings.json", b"two"),),
    )
    update_plan = service.preview(updated_request)
    approval = InstallationApproval(update_plan.plan_id, "test-operator")

    updated = service.update(
        updated_request,
        update_plan,
        approval,
        verifier=_verifier,
    )
    retried = service.update(
        updated_request,
        update_plan,
        approval,
        verifier=_verifier,
    )

    assert updated == retried
    assert (root / "config" / "settings.json").read_bytes() == b"two"
    assert service.discover()[0].package_version == "2.0.0"

    rolled_back = service.rollback(updated.transaction_id)

    assert rolled_back.owner_revision == initial.owner_revision
    assert (root / "config" / "settings.json").read_bytes() == b"one"
    restored = service.discover()[0]
    assert restored.transaction_id == initial.transaction_id
    assert restored.package_version == "1.0.0"


def test_interrupted_update_recovers_without_losing_previous_owner(tmp_path):
    class SimulatedProcessLoss(BaseException):
        pass

    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    stable = TransactionalIntegrationInstaller(data_dir)
    initial_request = _request(
        root,
        mutations=(FileInstallMutation("config/settings.json", b"one"),),
    )
    initial_plan = stable.preview(initial_request)
    initial = stable.apply(
        initial_request,
        initial_plan,
        InstallationApproval(initial_plan.plan_id, "test-operator"),
        verifier=_verifier,
    )
    update_request = replace(
        initial_request,
        package=replace(initial_request.package, version="2.0.0"),
        mutations=(FileInstallMutation("config/settings.json", b"two"),),
    )

    def crash(phase, _transaction_id):
        if phase == "apply:1":
            raise SimulatedProcessLoss

    crashing = TransactionalIntegrationInstaller(data_dir, fault_injector=crash)
    update_plan = crashing.preview(update_request)
    with pytest.raises(SimulatedProcessLoss):
        crashing.update(
            update_request,
            update_plan,
            InstallationApproval(update_plan.plan_id, "test-operator"),
            verifier=_verifier,
        )

    assert stable.discover()[0].transaction_id == initial.transaction_id
    recovered = stable.recover({"codex": _verifier})

    assert recovered[0].outcome == "completed"
    assert (root / "config" / "settings.json").read_bytes() == b"two"
    assert stable.discover()[0].package_version == "2.0.0"


def test_stale_active_symlink_and_external_drift_fail_closed(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    request = _request(root)
    active = False
    service = TransactionalIntegrationInstaller(
        data_dir, target_active=lambda _root: active
    )
    stale = service.preview(request)
    root.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "settings.json").write_text("changed", encoding="utf-8")
    with pytest.raises(InstallationConflictError, match="changed after preview"):
        service.apply(
            request,
            stale,
            InstallationApproval(stale.plan_id, "test-operator"),
            verifier=_verifier,
        )

    fresh = service.preview(request)
    active = True
    with pytest.raises(InstallationConflictError, match="active"):
        service.apply(
            request,
            fresh,
            InstallationApproval(fresh.plan_id, "test-operator"),
            verifier=_verifier,
        )
    active = False
    result = service.apply(
        request,
        fresh,
        InstallationApproval(fresh.plan_id, "test-operator"),
        verifier=_verifier,
    )
    os.chmod(root / "config" / "settings.json", 0o644)
    assert service.discover()[0].current is False
    with pytest.raises(InstallationConflictError, match="outside"):
        service.rollback(result.transaction_id)

    symlink_root = data_dir / "native" / "gemini" / "home"
    symlink_root.parent.mkdir(parents=True)
    symlink_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(InstallationScopeError, match="symlink"):
        service.preview(_request(symlink_root, target_id="gemini"))


def test_paths_and_blocked_trust_policy_fail_before_mutation(tmp_path):
    with pytest.raises(ValueError, match="relative path"):
        FileInstallMutation("../escape", b"no")

    data_dir = tmp_path / "data"
    request = _request(data_dir / "native" / "codex" / "home")
    blocked = replace(
        request,
        package=replace(
            request.package,
            requirements=(
                IntegrationRequirement(
                    id="forbidden-root",
                    type=IntegrationRequirementType.PERMISSION,
                    classification=IntegrationPolicyClass.FORBIDDEN,
                    reason="The integration requests an unsupported privilege.",
                ),
            ),
        ),
    )

    with pytest.raises(InstallationScopeError, match="trust policy"):
        TransactionalIntegrationInstaller(data_dir).preview(blocked)

    assert not blocked.target.root.exists()


def test_verification_failure_restores_prior_snapshot(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    root.mkdir(parents=True)
    target = root / "config" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")
    request = _request(root)
    service = TransactionalIntegrationInstaller(data_dir)
    plan = service.preview(request)

    with pytest.raises(InstallationVerificationError, match="verification failed"):
        service.apply(
            request,
            plan,
            InstallationApproval(plan.plan_id, "test-operator"),
            verifier=lambda _root, _plan: False,
        )

    assert target.read_text(encoding="utf-8") == "before"
    assert service.discover() == ()
    journal = json.loads(service.journal_path(plan.transaction_id).read_text())
    assert journal["status"] == "rolled_back"
    assert journal["failure"] == {
        "code": "verification_failed",
        "error_type": "InstallationVerificationError",
    }


def test_concurrent_duplicate_retry_commits_one_owned_transaction(tmp_path):
    data_dir = tmp_path / "data"
    request = _request(data_dir / "native" / "codex" / "home")
    first_service = TransactionalIntegrationInstaller(data_dir)
    second_service = TransactionalIntegrationInstaller(data_dir)
    plan = first_service.preview(request)
    approval = InstallationApproval(plan.plan_id, "test-operator")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda service: service.apply(
                    request, plan, approval, verifier=_verifier
                ),
                (first_service, second_service),
            )
        )

    assert results[0] == results[1]
    assert len(first_service.discover()) == 1
    assert len(tuple(first_service.transactions_root.glob("txn_*"))) == 1


def test_recovery_completes_interrupted_apply_or_restores_without_verifier(tmp_path):
    class SimulatedProcessLoss(BaseException):
        pass

    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    request = _request(
        root,
        mutations=(
            FileInstallMutation("config/settings.json", b"one"),
            FileInstallMutation("payload/two.txt", b"two"),
        ),
    )

    def crash(phase, _transaction_id):
        if phase == "apply:1":
            raise SimulatedProcessLoss

    crashing = TransactionalIntegrationInstaller(data_dir, fault_injector=crash)
    plan = crashing.preview(request)
    with pytest.raises(SimulatedProcessLoss):
        crashing.apply(
            request,
            plan,
            InstallationApproval(plan.plan_id, "test-operator"),
            verifier=_verifier,
        )

    recovered = TransactionalIntegrationInstaller(data_dir).recover(
        {"codex": _verifier}
    )

    assert recovered[0].outcome == "completed"
    assert (root / "config" / "settings.json").read_bytes() == b"one"
    assert (root / "payload" / "two.txt").read_bytes() == b"two"
    assert TransactionalIntegrationInstaller(data_dir).discover()[0].current is True

    second_data = tmp_path / "second-data"
    second_root = second_data / "native" / "codex" / "home"
    second = _request(second_root, mutations=request.mutations)
    crashing = TransactionalIntegrationInstaller(second_data, fault_injector=crash)
    second_plan = crashing.preview(second)
    with pytest.raises(SimulatedProcessLoss):
        crashing.apply(
            second,
            second_plan,
            InstallationApproval(second_plan.plan_id, "test-operator"),
            verifier=_verifier,
        )

    restored = TransactionalIntegrationInstaller(second_data).recover()

    assert restored[0].outcome == "restored"
    assert not second_root.exists() or not any(second_root.rglob("*"))


def test_recovery_finishes_an_interrupted_rollback(tmp_path):
    class SimulatedProcessLoss(BaseException):
        pass

    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    root.mkdir(parents=True)
    first_path = root / "one.txt"
    second_path = root / "two.txt"
    first_path.write_text("old-one", encoding="utf-8")
    second_path.write_text("old-two", encoding="utf-8")
    request = _request(
        root,
        mutations=(
            FileInstallMutation("one.txt", b"new-one"),
            FileInstallMutation("two.txt", b"new-two"),
        ),
    )
    stable = TransactionalIntegrationInstaller(data_dir)
    plan = stable.preview(request)
    result = stable.apply(
        request,
        plan,
        InstallationApproval(plan.plan_id, "test-operator"),
        verifier=_verifier,
    )

    def crash(phase, _transaction_id):
        if phase == "rollback:1":
            raise SimulatedProcessLoss

    with pytest.raises(SimulatedProcessLoss):
        TransactionalIntegrationInstaller(data_dir, fault_injector=crash).rollback(
            result.transaction_id
        )

    recovered = TransactionalIntegrationInstaller(data_dir).recover()

    assert recovered[0].outcome == "rolled_back"
    assert first_path.read_text(encoding="utf-8") == "old-one"
    assert second_path.read_text(encoding="utf-8") == "old-two"
    assert TransactionalIntegrationInstaller(data_dir).discover() == ()


def test_project_and_user_scopes_require_explicit_roots_and_user_opt_in(tmp_path):
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    user_home = tmp_path / "fake-user-home"
    project.mkdir()
    project_request = _request(
        project / ".agent",
        scope=InstallationScope.PROJECT,
    )
    user_request = _request(
        user_home,
        scope=InstallationScope.USER_HOME,
    )
    default = TransactionalIntegrationInstaller(data_dir)

    with pytest.raises(InstallationScopeError, match="project root"):
        default.preview(project_request)
    with pytest.raises(InstallationScopeError, match="disabled"):
        default.preview(user_request)

    scoped = TransactionalIntegrationInstaller(
        data_dir,
        project_roots=(project,),
        user_home_root=user_home,
        allow_user_home=True,
    )
    project_plan = scoped.preview(project_request)
    scoped.apply(
        project_request,
        project_plan,
        InstallationApproval(project_plan.plan_id, "test-operator"),
        verifier=_verifier,
    )
    user_plan = scoped.preview(user_request)
    with pytest.raises(InstallationScopeError, match="approval"):
        scoped.apply(
            user_request,
            user_plan,
            InstallationApproval(user_plan.plan_id, "test-operator"),
            verifier=_verifier,
        )
    scoped.apply(
        user_request,
        user_plan,
        InstallationApproval(user_plan.plan_id, "test-operator", allow_user_home=True),
        verifier=_verifier,
    )
    assert (user_home / "config" / "settings.json").exists()


def test_corrupt_or_future_journal_blocks_recovery_without_target_mutation(tmp_path):
    data_dir = tmp_path / "data"
    root = data_dir / "native" / "codex" / "home"
    root.mkdir(parents=True)
    sentinel = root / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    service = TransactionalIntegrationInstaller(data_dir)
    service.transactions_root.mkdir(parents=True)
    transaction = service.transactions_root / ("txn_" + "a" * 32)
    transaction.mkdir()
    journal = transaction / "journal.json"
    journal.write_text('{"schema_version": 999}', encoding="utf-8")

    with pytest.raises(InstallationStateError, match="journal"):
        service.recover()

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def _request(
    root: Path,
    *,
    target_id: str = "codex",
    scope: InstallationScope = InstallationScope.MANAGED_HOME,
    mutations: tuple[FileInstallMutation, ...] | None = None,
) -> InstallationRequest:
    return InstallationRequest(
        package=_package(scope=scope, target_id=target_id),
        target=InstallationTarget(
            id=target_id,
            scope=scope,
            root=root,
            owner_id="proj_fixture",
        ),
        mutations=mutations
        or (
            FileInstallMutation(
                "config/settings.json", b'{"token":"secret-value-canary"}\n'
            ),
        ),
    )


def _package(*, scope: InstallationScope, target_id: str) -> IntegrationPackage:
    return IntegrationPackage(
        id="example.integration",
        version="1.0.0",
        publisher="example-publisher",
        license="Apache-2.0",
        source_type=IntegrationSourceType.GIT,
        source="https://git.example/integration",
        immutable_ref="commit-deadbeef",
        checksum=_DIGEST,
        components=(
            IntegrationComponent(
                id="portable-mcp",
                type=IntegrationComponentType.MCP,
                portable=True,
            ),
        ),
        requirements=(),
        overlays=(),
        compatibility=(IntegrationCompatibility(target_id=target_id),),
        scopes=(scope,),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("snapshot-hash",),
        rollback_steps=("restore-snapshot",),
    )


def _verifier(root: Path, plan) -> bool:
    return all(
        (root / mutation.relative_path).is_file()
        and _sha256(root / mutation.relative_path) == mutation.desired_sha256
        for mutation in plan.mutations
    )


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
