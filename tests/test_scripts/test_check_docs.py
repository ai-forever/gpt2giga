import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_docs.py"


def load_docs_module():
    spec = importlib.util.spec_from_file_location("check_docs", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_relative_link_checker_reports_only_missing_local_targets(
    tmp_path: Path,
) -> None:
    docs_module = load_docs_module()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Target\n", encoding="utf-8")
    source = docs / "source.md"
    source.write_text(
        "[valid](target.md#section)\n"
        "[web](https://example.com/page)\n"
        "[route](/quickstart)\n"
        "[missing](absent.md)\n",
        encoding="utf-8",
    )

    issues = docs_module.check_relative_links(tmp_path, [source])

    assert [issue.message for issue in issues] == [
        "line 4: broken relative link 'absent.md'"
    ]


def test_proxy_setting_names_are_derived_from_annotated_fields(tmp_path: Path) -> None:
    docs_module = load_docs_module()
    config = tmp_path / "config.py"
    config.write_text(
        "class Other:\n"
        "    ignored: str\n\n"
        "class ProxySettings:\n"
        "    host: str = 'localhost'\n"
        "    api_key: str | None = None\n"
        "    _private: bool = False\n",
        encoding="utf-8",
    )

    assert docs_module.proxy_setting_names(config) == {
        "GPT2GIGA_API_KEY",
        "GPT2GIGA_HOST",
    }


def test_stale_gateway_release_instructions_are_rejected(tmp_path: Path) -> None:
    docs_module = load_docs_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        'Install "gpt2giga==0.2.3a1" from the package index.\n',
        encoding="utf-8",
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        'Historical "gpt2giga==0.2.3a1" note.\n',
        encoding="utf-8",
    )

    issues = docs_module.check_stale_instructions(tmp_path, [guide, changelog])

    assert [issue.message for issue in issues] == [
        "line 1: obsolete 'gpt2giga==0.2.3a1\"'; do not pin the previous gateway alpha in current install docs",
    ]


def test_package_urls_reject_non_gateway_project_identity(tmp_path: Path) -> None:
    docs_module = load_docs_module()
    package = tmp_path / "packages/gpt2giga"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        """
[project]
name = "gpt2giga"
version = "1.0.0"

[project.urls]
Homepage = "https://github.com/krakenalt/gigaloom"
""".strip(),
        encoding="utf-8",
    )

    issues = docs_module.check_package_urls(tmp_path)

    assert any("project.urls.Repository" in issue.message for issue in issues)
    assert any(
        "must not identify the GigaLoom project" in issue.message for issue in issues
    )
