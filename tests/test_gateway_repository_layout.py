"""Repository layout contracts owned by ai-forever/gpt2giga."""

from workspace_split_contract_support import (
    test_gateway_owned_modules_do_not_import_harness as _check_no_harness_imports,
)


FUTURE_REPOSITORY_OWNER = "ai-forever/gpt2giga"


def test_gateway_owned_modules_do_not_import_gigaloom():
    _check_no_harness_imports()
