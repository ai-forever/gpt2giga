from __future__ import annotations

import pytest

from gpt2giga_harness.base_install import (
    BASE_DIRECT_DISTRIBUTIONS,
    MAX_BASE_DISTRIBUTIONS,
    OPTIONAL_INTEGRATION_DISTRIBUTIONS,
    audit_base_install,
)


BASE_REQUIREMENTS = (
    "anyio>=4.10,<5",
    "fastapi>=0.133.0,<1",
    "pydantic>=2.12.0,<3",
    "pyjwt[crypto]>=2.12.0,<3",
    "pyyaml>=6.0,<7",
    "python-dateutil>=2.9.0,<3",
    "starlette>=1.1,<2",
    "textual>=8.2.8,<9",
    "tomli>=2.0,<3; python_version < '3.11'",
    "uvicorn>=0.41.0,<1",
)


def test_base_install_audit_accepts_the_frozen_core_surface():
    installed = set(BASE_DIRECT_DISTRIBUTIONS) | {
        f"transitive-{index}"
        for index in range(MAX_BASE_DISTRIBUTIONS - len(BASE_DIRECT_DISTRIBUTIONS))
    }

    report = audit_base_install(
        harness_requirements=BASE_REQUIREMENTS,
        installed_distributions=installed,
    )

    assert report["status"] == "pass"
    assert report["violations"] == []
    assert report["direct_dependencies"] == {
        "count": len(BASE_DIRECT_DISTRIBUTIONS),
        "maximum": len(BASE_DIRECT_DISTRIBUTIONS),
        "actual": sorted(BASE_DIRECT_DISTRIBUTIONS),
        "missing": [],
        "unexpected": [],
    }
    assert report["installed_distributions"] == {
        "count": MAX_BASE_DISTRIBUTIONS,
        "maximum": MAX_BASE_DISTRIBUTIONS,
    }
    assert all(
        family["status"] == "absent"
        for family in report["optional_integrations"].values()
    )


@pytest.mark.parametrize(
    ("family", "distribution"),
    [
        (family, sorted(distributions)[0])
        for family, distributions in OPTIONAL_INTEGRATION_DISTRIBUTIONS.items()
    ],
)
def test_base_install_audit_rejects_optional_integration_packages(
    family: str, distribution: str
):
    report = audit_base_install(
        harness_requirements=BASE_REQUIREMENTS,
        installed_distributions=set(BASE_DIRECT_DISTRIBUTIONS) | {distribution},
    )

    assert report["status"] == "fail"
    assert report["optional_integrations"][family] == {
        "status": "present",
        "installed": [distribution],
    }
    assert f"optional_integration_present:{family}" in report["violations"]


def test_base_install_audit_rejects_direct_dependency_drift():
    report = audit_base_install(
        harness_requirements=(
            *BASE_REQUIREMENTS,
            "slack-sdk>=3",
        ),
        installed_distributions=BASE_DIRECT_DISTRIBUTIONS,
    )

    assert report["status"] == "fail"
    assert report["direct_dependencies"]["unexpected"] == ["slack-sdk"]
    assert report["violations"][0] == "direct_dependency_drift"


def test_base_install_audit_rejects_distribution_budget_growth():
    installed = set(BASE_DIRECT_DISTRIBUTIONS) | {
        f"transitive-{index}" for index in range(MAX_BASE_DISTRIBUTIONS)
    }

    report = audit_base_install(
        harness_requirements=BASE_REQUIREMENTS,
        installed_distributions=installed,
    )

    assert report["status"] == "fail"
    assert "installed_distribution_budget_exceeded" in report["violations"]
