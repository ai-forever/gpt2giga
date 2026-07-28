"""Release, documentation, and CI contracts owned by krakenalt/gigaloom."""

from workspace_split_contract_support import (
    test_ci_builds_and_smokes_both_workspace_artifacts_when_present as _check_artifact_ci,
    test_pr_labeler_tracks_harness_owned_paths as _check_labeler,
    test_release_workflow_routes_and_publishes_both_workspace_members as _check_release_workflow,
    test_split_install_and_namespace_migration_are_documented as _check_migration_docs,
)


FUTURE_REPOSITORY_OWNER = "krakenalt/gigaloom"


def test_gigaloom_artifact_ci_builds_and_smokes_distribution():
    _check_artifact_ci()


def test_gigaloom_paths_have_release_label_ownership():
    _check_labeler()


def test_gigaloom_release_workflow_routes_only_owned_distribution():
    _check_release_workflow()


def test_gigaloom_install_and_namespace_migration_are_documented():
    _check_migration_docs()
