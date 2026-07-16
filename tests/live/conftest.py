"""Keep every test in this directory explicit opt-in."""

from pathlib import Path

import pytest


_LIVE_TESTS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply the generic live marker to current and future live tests."""
    for item in items:
        if item.path.is_relative_to(_LIVE_TESTS_DIR):
            item.add_marker(pytest.mark.live)
