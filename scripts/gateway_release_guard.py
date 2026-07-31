#!/usr/bin/env python3
"""Validate the source repository's gateway-only release tag contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility.
    import tomli as tomllib


class ReleaseGuardError(RuntimeError):
    """Raised when a release event does not match the gateway package."""


PROJECT_METADATA = Path("pyproject.toml")
_PRERELEASE_TOKEN = re.compile(
    r"(?i)(?:^|[._-]|\d)(?:alpha|beta|preview|pre|rc|dev|a|b|c)\d*"
    r"(?=$|[._-]|\d)"
)
_LOWER_BOUND = re.compile(r"(?:===|==|~=|>=|>)\s*([^\s,;]+)")


def _is_prerelease(version: str) -> bool:
    """Return whether a PEP 440 version has a prerelease or dev segment."""
    public_version = version.partition("+")[0]
    return _PRERELEASE_TOKEN.search(public_version) is not None


def _prerelease_dependency_floors(dependencies: list[object]) -> list[str]:
    """Find direct requirements whose accepted floor is a prerelease."""
    prerelease_floors = []
    for dependency in dependencies:
        requirement = str(dependency)
        if any(
            _is_prerelease(match.group(1))
            for match in _LOWER_BOUND.finditer(requirement)
        ):
            prerelease_floors.append(requirement)
    return prerelease_floors


def _release_prerelease(value: str) -> bool | None:
    """Parse the GitHub release prerelease value, including an absent event."""
    if value == "":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("must be 'true' or 'false'")


def resolve_release(
    *,
    metadata_path: Path,
    event_name: str,
    ref_name: str,
    release_tag: str,
    release_prerelease: bool | None,
) -> dict[str, str]:
    """Resolve a manual build or an exact gateway release."""
    project = tomllib.loads(metadata_path.read_text(encoding="utf-8"))["project"]
    distribution = str(project["name"])
    version = str(project["version"])
    expected_tag = f"v{version}"
    version_is_prerelease = _is_prerelease(version)

    if distribution != "gpt2giga":
        raise ReleaseGuardError(
            f"distribution {distribution!r} is not the gateway 'gpt2giga'"
        )

    prerelease_floors = _prerelease_dependency_floors(
        list(project.get("dependencies", []))
    )
    if not version_is_prerelease and prerelease_floors:
        joined = ", ".join(repr(requirement) for requirement in prerelease_floors)
        raise ReleaseGuardError(
            f"stable version {version!r} cannot use prerelease dependency floors: "
            f"{joined}"
        )

    if event_name == "workflow_dispatch":
        if release_tag:
            raise ReleaseGuardError("manual builds cannot carry a release tag")
        if release_prerelease is not None:
            raise ReleaseGuardError(
                "manual builds cannot carry GitHub release prerelease metadata"
            )
        mode = "manual"
    elif event_name == "release":
        if release_tag != expected_tag:
            raise ReleaseGuardError(
                f"release tag {release_tag!r} must equal {expected_tag!r}"
            )
        if ref_name != expected_tag:
            raise ReleaseGuardError(
                f"release ref {ref_name!r} must equal {expected_tag!r}"
            )
        if release_prerelease is None:
            raise ReleaseGuardError("release events must declare prerelease metadata")
        if release_prerelease != version_is_prerelease:
            expected = str(version_is_prerelease).lower()
            raise ReleaseGuardError(
                f"GitHub Release prerelease must be {expected} for version {version!r}"
            )
        mode = "publish"
    else:
        raise ReleaseGuardError(f"unsupported event {event_name!r}")

    return {"mode": mode, "tag": expected_tag, "version": version}


def main(argv: list[str] | None = None) -> int:
    """Validate CLI inputs and optionally emit GitHub Actions outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--ref-name", required=True)
    parser.add_argument("--release-tag", default="")
    parser.add_argument(
        "--release-prerelease",
        type=_release_prerelease,
        default=None,
    )
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)

    try:
        result = resolve_release(
            metadata_path=PROJECT_METADATA,
            event_name=args.event_name,
            ref_name=args.ref_name,
            release_tag=args.release_tag,
            release_prerelease=args.release_prerelease,
        )
    except (KeyError, OSError, ValueError, ReleaseGuardError) as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 2

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in sorted(result.items()):
                print(f"{key}={value}", file=output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
