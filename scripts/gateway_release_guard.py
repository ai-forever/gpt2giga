#!/usr/bin/env python3
"""Validate the source repository's gateway-only release tag contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility.
    import tomli as tomllib


class ReleaseGuardError(RuntimeError):
    """Raised when a release event does not match the gateway package."""


def resolve_release(
    *,
    metadata_path: Path,
    event_name: str,
    ref_name: str,
    release_tag: str,
) -> dict[str, str]:
    """Resolve a manual build or an exact gateway release."""
    project = tomllib.loads(metadata_path.read_text(encoding="utf-8"))["project"]
    distribution = str(project["name"])
    version = str(project["version"])
    expected_tag = f"v{version}"

    if distribution != "gpt2giga":
        raise ReleaseGuardError(
            f"distribution {distribution!r} is not the gateway 'gpt2giga'"
        )

    if event_name == "workflow_dispatch":
        if release_tag:
            raise ReleaseGuardError("manual builds cannot carry a release tag")
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
        mode = "publish"
    else:
        raise ReleaseGuardError(f"unsupported event {event_name!r}")

    return {"mode": mode, "tag": expected_tag, "version": version}


def main(argv: list[str] | None = None) -> int:
    """Validate CLI inputs and optionally emit GitHub Actions outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("pyproject.toml"),
    )
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--ref-name", required=True)
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)

    try:
        result = resolve_release(
            metadata_path=args.metadata,
            event_name=args.event_name,
            ref_name=args.ref_name,
            release_tag=args.release_tag,
        )
    except (KeyError, OSError, ValueError, ReleaseGuardError) as error:
        parser.error(str(error))
        return 2

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in sorted(result.items()):
                print(f"{key}={value}", file=output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
