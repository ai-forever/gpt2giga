"""Standalone GigaLoom governance and security contracts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")


def _yaml(relative: str) -> dict:
    return yaml.load(_read(relative), Loader=yaml.BaseLoader)


def _words(relative: str) -> str:
    return " ".join(_read(relative).split())


def test_named_ownership_is_fail_closed_until_distinct_backups_accept():
    policy = json.loads(_read(".github/repository-policy.json"))

    assert policy["primary_owner"] == {
        "github": {
            "account": "krakenalt",
            "name": "Ruslan Yakupov",
        },
        "pypi": {
            "account": "blocked_pending_S5_04_verification",
            "name": "Ruslan Yakupov",
            "role": "primary-pypi-owner",
        },
    }
    assert policy["backup_owners"] == {
        "github": {
            "acceptance_gate": "S5-02",
            "distinct_from_primary": True,
            "role": "backup-github-maintainer",
            "state": "blocked_pending_acceptance",
            "two_factor_authentication_required": True,
        },
        "pypi": {
            "acceptance_gate": "S5-04",
            "distinct_from_primary": True,
            "role": "backup-pypi-owner",
            "state": "blocked_pending_acceptance",
            "two_factor_authentication_required": True,
        },
    }

    governance = _words("GOVERNANCE.md")
    for contract in (
        "@krakenalt",
        "backup-github-maintainer",
        "backup-pypi-owner",
        "primary-pypi-owner",
        "blocked_pending_acceptance",
        "blocked_pending_S5_04_verification",
        "distinct GitHub account",
        "distinct PyPI owner",
        "not transferred objects",
        "not a migration",
    ):
        assert contract in governance
    assert "ai-forever" in governance
    assert "No source-organization team, secret, bot, or publisher is inherited" in (
        governance
    )
    checklist = _words(".github/OWNER_RECOVERY_CHECKLIST.md")
    for contract in (
        "S5-02",
        "S5-04",
        "backup-github-maintainer",
        "backup-pypi-owner",
        "2FA enabled",
        "primary-owner-unavailable drill",
        "does not claim transferred comments",
        "Public push remains blocked until S5-01",
    ):
        assert contract in checklist


def test_codeowners_and_templates_are_target_owned_and_bilingual():
    codeowners = _read(".github/CODEOWNERS")
    assert codeowners.count("@krakenalt") >= 6
    assert "ai-forever" not in codeowners

    for english, russian in (
        (
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/bug_report.ru.md",
        ),
        (
            ".github/ISSUE_TEMPLATE/feature_request.md",
            ".github/ISSUE_TEMPLATE/feature_request.ru.md",
        ),
        (
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/PULL_REQUEST_TEMPLATE/ru.md",
        ),
    ):
        english_text = _read(english)
        russian_text = _read(russian)
        assert "GigaLoom" in english_text
        assert "GigaLoom" in russian_text
        assert "gpt2giga version" not in english_text
        assert "GigaChat Configuration" not in english_text
        if "PULL_REQUEST" in english:
            assert "uv.lock" in english_text

    config = _yaml(".github/ISSUE_TEMPLATE/config.yml")
    assert config["contact_links"][0]["url"].endswith("/security/advisories/new")


def test_security_policy_has_private_intake_sla_and_immutable_recovery():
    security = _words("SECURITY.md")
    for contract in (
        "Do not open a public issue",
        "/security/advisories/new",
        "within 3 business days",
        "within 7 business days",
        "within 14 business days",
        "backup-github-maintainer",
        "freeze releases",
        "new immutable package version",
        "Never force-push accepted history",
        "overwrite a PyPI version",
    ):
        assert contract in security

    recovery = _words(".github/RELEASE_RECOVERY.md")
    for contract in (
        "backup-github-maintainer",
        "backup-pypi-owner",
        "blocked_pending_acceptance",
        "Compromised publisher",
        "Primary owner unavailable",
        "must never delete or overwrite it",
    ):
        assert contract in recovery


def test_ruleset_checks_match_the_always_running_quality_workflow():
    policy = json.loads(_read(".github/repository-policy.json"))
    quality = _yaml(".github/workflows/ci.yaml")

    assert "paths" not in quality["on"]["pull_request"]
    jobs = quality["jobs"]
    required = {
        jobs["frontend"]["name"],
        jobs["package"]["name"],
        jobs["performance"]["name"],
        jobs["registry-readiness"]["name"],
    }
    for version in jobs["python"]["strategy"]["matrix"]["python-version"]:
        required.add(f"Python / {version}")
    terminal_matrix = jobs["terminal"]["strategy"]["matrix"]
    for operating_system in terminal_matrix["os"]:
        for version in terminal_matrix["python-version"]:
            required.add(f"Terminal / {operating_system} / {version}")

    main_ruleset = policy["rulesets"]["main"]
    assert main_ruleset["name"] == "protect-main"
    assert set(main_ruleset["required_checks"]) == required
    assert main_ruleset["target"] == "refs/heads/main"
    assert main_ruleset["block_deletions"] is True
    assert main_ruleset["block_force_pushes"] is True
    assert main_ruleset["require_code_owner_review"] is True
    assert main_ruleset["require_last_push_approval"] is True

    tag_ruleset = policy["rulesets"]["release_tags"]
    assert tag_ruleset["name"] == "protect-gigaloom-release-tags"
    assert tag_ruleset["target"] == "refs/tags/gigaloom-v*"
    assert tag_ruleset["restrict_creation"] is True
    assert tag_ruleset["restrict_updates"] is True


def test_actions_permissions_and_security_automation_are_specialized():
    policy = json.loads(_read(".github/repository-policy.json"))
    actions = policy["actions"]
    assert actions["default_workflow_permissions"] == "read"
    assert actions["can_approve_pull_request_reviews"] is False
    assert actions["elevated_jobs"] == [
        {
            "job": "Release / attest and trusted publish",
            "permissions": ["attestations:write", "id-token:write"],
            "purpose": "PyPI trusted publishing and artifact attestations",
            "workflow": ".github/workflows/publish-pypi.yml",
        },
        {
            "job": "Deploy docs",
            "permissions": ["id-token:write", "pages:write"],
            "purpose": "GitHub Pages deployment",
            "workflow": ".github/workflows/docs-pages.yaml",
        },
    ]

    dependabot = _yaml(".github/dependabot.yml")
    updates = {
        (update["package-ecosystem"], update["directory"])
        for update in dependabot["updates"]
    }
    assert updates == {
        ("github-actions", "/"),
        ("pip", "/packages/gpt2giga-harness"),
        ("npm", "/packages/gpt2giga-harness/frontend"),
        ("npm", "/docs-site"),
    }

    codeql = _yaml(".github/workflows/codeql.yaml")
    assert codeql["jobs"]["analyze"]["strategy"]["matrix"]["language"] == [
        "python",
        "javascript-typescript",
    ]
    assert codeql["permissions"] == {
        "actions": "read",
        "contents": "read",
        "security-events": "write",
    }

    stale = _yaml(".github/workflows/stale-issues.yaml")
    stale_options = stale["jobs"]["stale"]["steps"][0]["with"]
    assert stale_options["exempt-issue-labels"] == "security,pinned,priority"
    assert stale_options["days-before-pr-stale"] == "-1"

    labels = _yaml(".github/labeler.yml")
    assert {"governance", "security", "release"} <= labels.keys()
    drafter = _yaml(".github/release-drafter.yml")
    category_labels = {
        label for category in drafter["categories"] for label in category["labels"]
    }
    assert {"governance", "security", "release", "terminal", "frontend"} <= (
        category_labels
    )
