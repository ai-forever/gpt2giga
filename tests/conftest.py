from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply test-type markers from the directory layout."""
    for item in items:
        parts = Path(str(item.path)).parts

        if "unit" in parts:
            item.add_marker(pytest.mark.unit)

        if "integration" in parts or "smoke" in parts:
            item.add_marker(pytest.mark.integration)
