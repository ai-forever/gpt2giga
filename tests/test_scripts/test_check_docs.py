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
