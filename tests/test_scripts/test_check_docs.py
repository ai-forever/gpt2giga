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


def test_stale_harness_release_instructions_are_rejected(tmp_path: Path) -> None:
    docs_module = load_docs_module()
    guide = tmp_path / "guide.md"
    guide.write_text(
        "Install gpt2giga-harness==0.0.1a4 from feature/harness_enrichment.\n",
        encoding="utf-8",
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "Historical gpt2giga-harness==0.0.1a4 note.\n",
        encoding="utf-8",
    )

    issues = docs_module.check_stale_instructions(tmp_path, [guide, changelog])

    assert [issue.message for issue in issues] == [
        "line 1: obsolete 'feature/harness_enrichment'; use the current Harness preview branch",
        "line 1: obsolete 'gpt2giga-harness==0.0.1a4'; the next Harness release is 0.1.0b1",
    ]


def test_source_repository_links_are_limited_to_history_and_gateway_docs(
    tmp_path: Path,
) -> None:
    docs_module = load_docs_module()
    package = tmp_path / "packages/gpt2giga-harness"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        "[project]\n"
        "name='gpt2giga-harness'\n"
        "version='0.5.1a1'\n"
        "[project.urls]\n"
        "Homepage='https://krakenalt.github.io/gigaloom/'\n"
        "Repository='https://github.com/krakenalt/gigaloom'\n"
        "Documentation='https://krakenalt.github.io/gigaloom/'\n"
        "Issues='https://github.com/krakenalt/gigaloom/issues'\n"
        "Changelog='https://github.com/krakenalt/gigaloom/blob/main/packages/gpt2giga-harness/CHANGELOG_en.md'\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    readme = tmp_path / "README.md"
    readme.write_text(
        "[baseline](badges/gigaloom-coverage.svg)\n",
        encoding="utf-8",
    )
    current_guide = docs / "current.md"
    current_guide.write_text(
        "Current development: https://github.com/ai-forever/gpt2giga\n",
        encoding="utf-8",
    )
    (docs / "operations.md").write_text("baseline 84.59%\n", encoding="utf-8")
    config = tmp_path / "docs-site/docusaurus.config.ts"
    config.parent.mkdir()
    config.write_text(
        "title: 'GigaLoom'\n"
        "baseUrl: '/gigaloom/'\n"
        "organizationName: 'krakenalt'\n"
        "projectName: 'gigaloom'\n"
        "https://github.com/krakenalt/gigaloom/edit/main/docs/\n",
        encoding="utf-8",
    )

    issues = docs_module.check_standalone_identity(tmp_path, [current_guide])

    assert any("not scoped to gateway/history" in issue.message for issue in issues)
