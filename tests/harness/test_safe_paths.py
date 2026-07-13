from pathlib import Path

import pytest

from gpt2giga_harness.safe_paths import (
    PathBoundaryError,
    resolve_operator_path,
    resolve_path_within,
)


def test_resolve_operator_path_canonicalizes_selected_root(tmp_path):
    selected = tmp_path / "nested" / ".." / "workspace"

    assert resolve_operator_path(selected) == tmp_path / "workspace"


def test_resolve_path_within_accepts_nested_child(tmp_path):
    child = tmp_path / "src" / "app.py"

    assert resolve_path_within(tmp_path, "src/app.py") == child
    assert resolve_path_within(tmp_path, ".") == tmp_path


@pytest.mark.parametrize("value", ["../outside.txt", "../../outside.txt"])
def test_resolve_path_within_rejects_traversal(tmp_path, value):
    with pytest.raises(PathBoundaryError, match="escapes"):
        resolve_path_within(tmp_path, value)


def test_resolve_path_within_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathBoundaryError, match="escapes"):
        resolve_path_within(workspace, Path("linked") / "secret.txt")
