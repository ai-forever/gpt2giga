"""Repository layout contracts owned by krakenalt/gigaloom."""

from workspace_split_contract_support import (
    test_pre_split_relocation_sources_are_present as _check_relocation_sources,
    test_workspace_member_metadata_and_source_ownership_when_present as _check_workspace_ownership,
)


FUTURE_REPOSITORY_OWNER = "krakenalt/gigaloom"


def test_relocation_sources_remain_owned_during_cutover():
    _check_relocation_sources()


def test_gigaloom_workspace_metadata_and_sources_have_one_owner():
    _check_workspace_ownership()
