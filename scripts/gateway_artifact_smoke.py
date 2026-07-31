#!/usr/bin/env python3
"""Validate an installed gateway wheel in an isolated Python environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import sys


class ArtifactSmokeError(RuntimeError):
    """Raised when the installed gateway violates its artifact contract."""


_PRERELEASE_TOKEN = re.compile(
    r"(?i)(?:^|[._-]|\d)(?:alpha|beta|preview|pre|rc|dev|a|b|c)\d*"
    r"(?=$|[._-]|\d)"
)


def _is_prerelease(version: str) -> bool:
    """Return whether a PEP 440 version has a prerelease or dev segment."""
    public_version = version.partition("+")[0]
    return _PRERELEASE_TOKEN.search(public_version) is not None


def _gigachat_specifiers(requirements: list[str] | None) -> set[str]:
    """Return normalized direct GigaChat requirement specifiers."""
    matches = []
    for requirement in requirements or []:
        normalized = requirement.partition(";")[0].replace(" ", "").lower()
        if normalized.startswith("gigachat"):
            matches.append(normalized.removeprefix("gigachat"))
    if len(matches) != 1:
        raise ArtifactSmokeError(
            "gateway metadata must contain exactly one direct gigachat requirement"
        )
    return set(matches[0].split(","))


def verify_installed_gateway(
    *,
    expected_gateway_version: str,
    expected_gigachat_version: str | None,
) -> dict[str, str]:
    """Verify metadata, imports, entry point, and mounted application routes."""
    from fastapi.testclient import TestClient

    import gpt2giga
    from gpt2giga.app.factory import create_app
    from gpt2giga.models.config import ProxyConfig

    distribution = importlib.metadata.distribution("gpt2giga")
    if distribution.metadata["Name"] != "gpt2giga":
        raise ArtifactSmokeError("installed distribution name must be 'gpt2giga'")
    if distribution.version != expected_gateway_version:
        raise ArtifactSmokeError(
            f"installed gateway version {distribution.version!r} does not match "
            f"{expected_gateway_version!r}"
        )

    gigachat_version = importlib.metadata.version("gigachat")
    if _is_prerelease(gigachat_version):
        raise ArtifactSmokeError(
            f"artifact resolved prerelease gigachat {gigachat_version!r}"
        )
    if (
        expected_gigachat_version is not None
        and gigachat_version != expected_gigachat_version
    ):
        raise ArtifactSmokeError(
            f"installed gigachat version {gigachat_version!r} does not match "
            f"{expected_gigachat_version!r}"
        )
    if _gigachat_specifiers(distribution.requires) != {">=0.2.3", "<0.3.0"}:
        raise ArtifactSmokeError("gateway metadata must require gigachat>=0.2.3,<0.3.0")

    scripts = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    if scripts != {"gpt2giga": "gpt2giga:run"}:
        raise ArtifactSmokeError(f"unexpected console scripts: {scripts!r}")

    package_path = Path(gpt2giga.__file__).resolve()
    if not package_path.is_relative_to(Path(sys.prefix).resolve()):
        raise ArtifactSmokeError(
            f"gpt2giga import escaped the isolated environment: {package_path}"
        )
    if (Path.cwd() / "gpt2giga").exists():
        raise ArtifactSmokeError("wheel install extracted gpt2giga into the checkout")
    if importlib.util.find_spec("gpt2giga_harness") is not None:
        raise ArtifactSmokeError("gateway wheel exposes gpt2giga_harness")
    if importlib.util.find_spec("gpt2giga.harness") is not None:
        raise ArtifactSmokeError("gateway wheel exposes gpt2giga.harness")

    client = TestClient(create_app(ProxyConfig()))
    if client.get("/health").status_code != 200:
        raise ArtifactSmokeError("installed gateway health check failed")
    openapi = client.get("/openapi.json")
    if openapi.status_code != 200:
        raise ArtifactSmokeError("installed gateway OpenAPI check failed")
    paths = openapi.json()["paths"]
    expected_paths = {
        "/v1/chat/completions",
        "/v1/messages",
        "/v1beta/models/{model}:generateContent",
    }
    missing_paths = expected_paths.difference(paths)
    if missing_paths:
        raise ArtifactSmokeError(
            f"installed gateway OpenAPI is missing paths: {sorted(missing_paths)!r}"
        )

    return {
        "gateway_version": distribution.version,
        "gigachat_version": gigachat_version,
    }


def main(argv: list[str] | None = None) -> int:
    """Parse expected versions and report deterministic smoke evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-gateway-version", required=True)
    parser.add_argument("--expected-gigachat-version")
    args = parser.parse_args(argv)

    try:
        result = verify_installed_gateway(
            expected_gateway_version=args.expected_gateway_version,
            expected_gigachat_version=args.expected_gigachat_version,
        )
    except (ArtifactSmokeError, ImportError, OSError, KeyError) as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
