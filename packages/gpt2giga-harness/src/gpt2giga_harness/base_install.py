"""Deterministic policy audit for a clean Harness base installation."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
import importlib.metadata
import json
import re
import sys
from typing import Any


AUDIT_KIND = "gpt2giga_harness_base_install_audit"
AUDIT_SCHEMA_VERSION = 1
MAX_BASE_DISTRIBUTIONS = 64
BASE_DIRECT_DISTRIBUTIONS = frozenset(
    {
        "anyio",
        "fastapi",
        "gigachat",
        "gpt2giga",
        "pydantic",
        "python-dateutil",
        "pyyaml",
        "starlette",
        "tomli",
        "uvicorn",
    }
)
OPTIONAL_INTEGRATION_DISTRIBUTIONS = {
    "office": frozenset(
        {
            "odfpy",
            "openpyxl",
            "pandas",
            "pyxlsb",
            "python-docx",
            "python-pptx",
            "xlrd",
            "xlsxwriter",
        }
    ),
    "remote_channels": frozenset(
        {
            "discord-py",
            "mattermostdriver",
            "pymsteams",
            "python-telegram-bot",
            "slack-sdk",
            "twilio",
        }
    ),
    "external_clients": frozenset(
        {
            "aionui",
            "openai-agents",
            "omnigent",
        }
    ),
    "sandbox_providers": frozenset(
        {
            "docker",
            "e2b",
            "kubernetes",
            "modal",
            "podman-py",
        }
    ),
}

_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_EXTRA_MARKER = re.compile(r"\bextra\s*==", re.IGNORECASE)
_EXACT_GATEWAY_REQUIREMENT = re.compile(
    r"^gpt2giga==[^\s;,]+(?:\s*;.*)?$", re.IGNORECASE
)


def _normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _requirement_name(requirement: str) -> str:
    match = _REQUIREMENT_NAME.match(requirement.strip())
    if match is None:
        raise ValueError(f"Invalid distribution requirement: {requirement!r}")
    return _normalize_distribution_name(match.group(0))


def _base_requirements(requirements: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        requirement
        for requirement in requirements
        if not _EXTRA_MARKER.search(requirement.split(";", 1)[-1])
    )


def _installed_distribution_names() -> set[str]:
    names: set[str] = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            names.add(_normalize_distribution_name(name))
    return names


def audit_base_install(
    *,
    harness_requirements: Sequence[str] | None = None,
    installed_distributions: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Audit direct metadata and an installed clean-environment inventory."""
    if harness_requirements is None:
        distribution = importlib.metadata.distribution("gpt2giga-harness")
        harness_requirements = tuple(distribution.requires or ())
    if installed_distributions is None:
        installed = _installed_distribution_names()
    else:
        installed = {
            _normalize_distribution_name(name) for name in installed_distributions
        }

    base_requirements = _base_requirements(harness_requirements)
    direct = {_requirement_name(requirement) for requirement in base_requirements}
    missing = sorted(BASE_DIRECT_DISTRIBUTIONS - direct)
    unexpected = sorted(direct - BASE_DIRECT_DISTRIBUTIONS)
    gateway_requirements = [
        requirement
        for requirement in base_requirements
        if _requirement_name(requirement) == "gpt2giga"
    ]
    gateway_exact = len(gateway_requirements) == 1 and bool(
        _EXACT_GATEWAY_REQUIREMENT.fullmatch(gateway_requirements[0].strip())
    )

    optional_integrations: dict[str, dict[str, Any]] = {}
    violations: list[str] = []
    if missing or unexpected:
        violations.append("direct_dependency_drift")
    if not gateway_exact:
        violations.append("gateway_dependency_not_exact")
    if len(installed) > MAX_BASE_DISTRIBUTIONS:
        violations.append("installed_distribution_budget_exceeded")

    for family, forbidden in OPTIONAL_INTEGRATION_DISTRIBUTIONS.items():
        present = sorted(installed & forbidden)
        optional_integrations[family] = {
            "status": "absent" if not present else "present",
            "installed": present,
        }
        if present:
            violations.append(f"optional_integration_present:{family}")

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "kind": AUDIT_KIND,
        "status": "pass" if not violations else "fail",
        "direct_dependencies": {
            "count": len(direct),
            "maximum": len(BASE_DIRECT_DISTRIBUTIONS),
            "actual": sorted(direct),
            "missing": missing,
            "unexpected": unexpected,
            "gateway_exact": gateway_exact,
        },
        "installed_distributions": {
            "count": len(installed),
            "maximum": MAX_BASE_DISTRIBUTIONS,
        },
        "optional_integrations": optional_integrations,
        "violations": violations,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a clean gpt2giga-harness base installation."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the versioned machine-readable audit report.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the clean-environment base-install audit."""
    arguments = _build_parser().parse_args(argv)
    report = audit_base_install()
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "Harness base install: "
            f"{report['status']} "
            f"({report['installed_distributions']['count']}/"
            f"{report['installed_distributions']['maximum']} distributions)"
        )
        for violation in report["violations"]:
            print(f"- {violation}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover - exercised in artifact smoke
    sys.exit(main())
