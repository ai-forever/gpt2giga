from pathlib import Path

from gpt2giga.app import admin_ui


def test_get_admin_ui_resources_prefers_repo_checkout(monkeypatch):
    admin_ui.get_admin_ui_resources.cache_clear()
    monkeypatch.setattr(
        admin_ui,
        "import_module",
        lambda _: (_ for _ in ()).throw(
            AssertionError("installed package should not be used")
        ),
    )

    resources = admin_ui.get_admin_ui_resources()

    assert resources is not None
    expected_root = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "gpt2giga-ui"
        / "src"
        / "gpt2giga_ui"
    )
    assert resources.package_root == expected_root
    assert resources.static_dir == expected_root / "static"
    assert resources.console_html_path == expected_root / "templates" / "console.html"

    admin_ui.get_admin_ui_resources.cache_clear()
