"""Standalone repository layout contracts owned by krakenalt/gigaloom."""

from pathlib import Path

import tomllib

REPOSITORY_OWNER = "krakenalt/gigaloom"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HARNESS_MEMBER = REPOSITORY_ROOT / "packages/gpt2giga-harness"


def test_gigaloom_is_the_only_workspace_member():
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as file:
        root_metadata = tomllib.load(file)

    assert root_metadata["tool"]["uv"]["workspace"]["members"] == [
        "packages/gpt2giga-harness"
    ]
    assert HARNESS_MEMBER.is_dir()
    assert not (REPOSITORY_ROOT / "packages/gpt2giga").exists()


def test_standalone_metadata_has_exact_gateway_and_committed_lock():
    with (HARNESS_MEMBER / "pyproject.toml").open("rb") as file:
        metadata = tomllib.load(file)

    assert metadata["project"]["name"] == "gpt2giga-harness"
    assert metadata["project"]["optional-dependencies"]["gpt2giga"][0] == (
        "gpt2giga==0.2.6a1"
    )
    assert "sources" not in metadata.get("tool", {}).get("uv", {})
    assert (REPOSITORY_ROOT / "uv.lock").is_file()


def test_standalone_bootstrap_scripts_are_target_owned():
    base = (REPOSITORY_ROOT / "scripts/ci-base.sh").read_text(encoding="utf-8")
    public_gateway = (REPOSITORY_ROOT / "scripts/ci-public-gateway.sh").read_text(
        encoding="utf-8"
    )

    assert "packages/gpt2giga-harness" in base
    assert 'uv sync "${sync_args[@]}"' in base
    assert "--locked" in base
    assert "--all-extras" in base
    assert "gpt2giga-harness" in public_gateway
    assert "https://pypi.org/simple" in public_gateway
    assert "uv.lock" in public_gateway
