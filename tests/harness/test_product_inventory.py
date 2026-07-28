import json
from pathlib import Path

from gpt2giga_harness import cli
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.doctor import build_doctor_report
from gpt2giga_harness.product_inventory import (
    PRODUCT_INVENTORY_KIND,
    build_product_inventory,
    load_product_inventory,
    validate_product_inventory,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app

REPOSITORY_ROOT = Path(__file__).parents[2]


def _current_inventory(tmp_path):
    registry = create_default_registry(include_entry_points=False)
    app = create_app(
        HarnessConfig(data_dir=tmp_path / "inventory-state"),
        registry=registry,
    )
    return build_product_inventory(
        registry,
        cli_parser=cli.build_parser(),
        api_routes=app.routes,
    )


def test_product_inventory_joins_runtime_owners_without_readiness_guessing(
    tmp_path,
):
    inventory = _current_inventory(tmp_path)

    assert inventory["schema_version"] == 1
    assert inventory["kind"] == PRODUCT_INVENTORY_KIND
    assert inventory["product"]["version"]
    assert inventory["product"]["repository"] == (
        "https://github.com/krakenalt/gigaloom"
    )
    assert inventory["content_sha256"]
    assert "harness capabilities" in inventory["interfaces"]["cli_commands"]
    assert "/diagnostics" in {
        item["slash"] for item in inventory["interfaces"]["tui_commands"]
    }
    assert {
        (item["method"], item["path"])
        for item in inventory["interfaces"]["api_operations"]
    } >= {
        ("GET", "/api/doctor"),
        ("GET", "/api/harnesses"),
    }
    assert set(inventory["protocols"]) == {
        "openai_compatible",
        "anthropic_compatible",
        "gemini_compatible",
    }
    assert set(inventory["transports"]) == {
        "native_structured",
        "native_terminal",
        "one_shot",
    }
    assert inventory["readiness"]["installed_executable_proves_account_ready"] is (
        False
    )
    assert {
        item["harness_id"] for item in inventory["readiness"]["provider_cli_contracts"]
    } == {"codex-cli", "claude-code", "gemini-cli"}


def test_packaged_inventory_and_documentation_match_runtime_truth(tmp_path):
    current = _current_inventory(tmp_path)

    assert load_product_inventory() == current
    assert (
        validate_product_inventory(
            current,
            repository_root=REPOSITORY_ROOT,
        )
        == ()
    )


def test_cli_prints_and_checks_complete_product_inventory(capsys, monkeypatch):
    monkeypatch.chdir(REPOSITORY_ROOT)

    assert cli.main(["harness", "capabilities", "--inventory", "--json"]) == 0
    inventory = json.loads(capsys.readouterr().out)
    assert inventory["kind"] == PRODUCT_INVENTORY_KIND

    assert cli.main(["harness", "capabilities", "--inventory", "--check"]) == 0
    assert capsys.readouterr().out == ""


def test_first_run_doctor_consumes_packaged_inventory(tmp_path):
    report = build_doctor_report(
        HarnessConfig(data_dir=tmp_path / "doctor-state"),
        registry=create_default_registry(include_entry_points=False),
        workspace=tmp_path,
        online_checks=False,
    )

    assert report["product_inventory"] == {
        "kind": PRODUCT_INVENTORY_KIND,
        "schema_version": 1,
        "product_version": load_product_inventory()["product"]["version"],
        "content_sha256": load_product_inventory()["content_sha256"],
        "provider_cli_contracts": ["claude-code", "codex-cli", "gemini-cli"],
        "documentation": [
            "agents-guide-en",
            "agents-guide-ru",
            "agent-capability-matrix-en",
            "agent-capability-matrix-ru",
            "provider-authentication-en",
            "provider-authentication-ru",
            "product-capability-admission-en",
            "product-capability-admission-ru",
        ],
    }
