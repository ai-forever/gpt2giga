#!/usr/bin/env python3
"""Validate one target-owned GigaLoom release or manual attestation run."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility.
    import tomli as tomllib


SHA_RE = re.compile(r"[0-9a-f]{40}")
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?")


class ReleaseGuardError(RuntimeError):
    """Raised when release identity or ancestry is unsafe."""


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        diagnostic = result.stderr.strip() or result.stdout.strip()
        raise ReleaseGuardError(
            f"git {' '.join(arguments)} failed: {diagnostic or result.returncode}"
        )
    return result.stdout.strip()


def _require_ancestor(root: Path, ancestor: str, descendant: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        raise ReleaseGuardError(f"{ancestor} is not an ancestor of {descendant}")
    if result.returncode:
        diagnostic = result.stderr.strip() or result.stdout.strip()
        raise ReleaseGuardError(
            f"cannot verify ancestry {ancestor}..{descendant}: "
            f"{diagnostic or result.returncode}"
        )


def _version_key(value: str) -> tuple[int, int, int, int, int]:
    match = VERSION_RE.fullmatch(value)
    if match is None:
        raise ReleaseGuardError(f"unsupported release version {value!r}")
    major, minor, patch, stage, stage_number = match.groups()
    stage_order = {"a": 0, "b": 1, "rc": 2, None: 3}
    return (
        int(major),
        int(minor),
        int(patch),
        stage_order[stage],
        int(stage_number or 0),
    )


def validate_release(
    *,
    root: Path,
    policy_path: Path,
    metadata_path: Path,
    event_name: str,
    repository: str,
    ref: str,
    commit: str,
    release_tag: str,
    release_target: str,
    main_ref: str,
) -> dict[str, str]:
    """Return guarded release metadata or raise a fail-closed error."""
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    project = tomllib.loads(metadata_path.read_text(encoding="utf-8"))["project"]
    version = str(project["version"])
    distribution = str(project["name"])
    first_release = policy["first_target_release"]
    expected_tag = f"{policy['tag_prefix']}{version}"

    if repository != policy["repository"]:
        raise ReleaseGuardError(
            f"repository {repository!r} is not the target {policy['repository']!r}"
        )
    if distribution != policy["distribution"]:
        raise ReleaseGuardError(
            f"distribution {distribution!r} is not {policy['distribution']!r}"
        )
    if _version_key(version) < _version_key(str(first_release["version"])):
        raise ReleaseGuardError(
            f"version {version!r} predates the first target release"
        )
    if SHA_RE.fullmatch(commit) is None:
        raise ReleaseGuardError("commit must be a full lowercase Git SHA")
    if version == first_release["version"] and expected_tag != first_release["tag"]:
        raise ReleaseGuardError("first target release tag allowlist is inconsistent")

    resolved_commit = _git(root, "rev-parse", f"{commit}^{{commit}}")
    if resolved_commit != commit:
        raise ReleaseGuardError("checked-out commit does not match the requested SHA")
    history_floor = str(first_release["history_floor"])
    if SHA_RE.fullmatch(history_floor) is None:
        raise ReleaseGuardError("history floor must be a full lowercase Git SHA")
    _require_ancestor(root, history_floor, commit)
    _require_ancestor(root, commit, main_ref)

    if event_name == "workflow_dispatch":
        expected_ref = f"refs/heads/{policy['default_branch']}"
        if ref != expected_ref:
            raise ReleaseGuardError(
                f"manual attestation must run from {expected_ref}, not {ref}"
            )
        if release_tag or release_target:
            raise ReleaseGuardError("manual attestation cannot carry release metadata")
        if _git(root, "rev-parse", f"{main_ref}^{{commit}}") != commit:
            raise ReleaseGuardError("manual attestation must use the current main tip")
        mode = "manual"
    elif event_name == "release":
        if release_tag != expected_tag:
            raise ReleaseGuardError(
                f"release tag {release_tag!r} must equal {expected_tag!r}"
            )
        if ref != f"refs/tags/{expected_tag}":
            raise ReleaseGuardError("release ref and package tag do not agree")
        if release_target != policy["default_branch"]:
            raise ReleaseGuardError("release target must be the default branch")
        tag_commit = _git(root, "rev-parse", f"refs/tags/{expected_tag}^{{commit}}")
        if tag_commit != commit:
            raise ReleaseGuardError("release tag and checked-out commit do not agree")
        mode = "publish"
    else:
        raise ReleaseGuardError(f"unsupported event {event_name!r}")

    return {
        "mode": mode,
        "tag": expected_tag,
        "version": version,
    }


def main(argv: list[str] | None = None) -> int:
    """Validate CLI inputs and optionally emit GitHub Actions outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--release-target", default="")
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)

    try:
        result = validate_release(
            root=args.root.resolve(),
            policy_path=args.policy.resolve(),
            metadata_path=args.metadata.resolve(),
            event_name=args.event_name,
            repository=args.repository,
            ref=args.ref,
            commit=args.commit,
            release_tag=args.release_tag,
            release_target=args.release_target,
            main_ref=args.main_ref,
        )
    except (KeyError, OSError, ValueError, ReleaseGuardError) as error:
        parser.error(str(error))

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in sorted(result.items()):
                print(f"{key}={value}", file=output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
