#!/usr/bin/env python3
"""Validate public documentation contracts without third-party dependencies."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility.
    import tomli as tomllib

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
FENCE_RE = re.compile(r"^```", re.MULTILINE)
CHANGELOG_VERSION_RE = re.compile(r"^## \[([^]]+)]", re.MULTILINE)
PUBLIC_DOC_PREFIX = "docs/"
RU_DOC_ROOT = Path("docs-site/i18n/ru/docusaurus-plugin-content-docs/current")


@dataclass(frozen=True)
class Issue:
    """One actionable documentation validation failure."""

    path: Path
    message: str

    def render(self, root: Path) -> str:
        """Render a stable repository-relative diagnostic."""
        try:
            path = self.path.relative_to(root)
        except ValueError:
            path = self.path
        return f"{path}: {self.message}"


def tracked_markdown_files(root: Path) -> list[Path]:
    """Return tracked public Markdown sources, excluding local coordination docs."""
    result = subprocess.run(
        ["git", "ls-files", "*.md", "*.mdx"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    excluded = ("docs/internal/", "docs/codex/", "local/")
    return [
        root / relative
        for relative in result.stdout.splitlines()
        if relative and not relative.startswith(excluded)
    ]


def _link_destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split(maxsplit=1)[0]


def check_relative_links(root: Path, files: list[Path]) -> list[Issue]:
    """Check local Markdown link targets without making network requests."""
    issues: list[Issue] = []
    ignored_schemes = ("http://", "https://", "mailto:", "tel:", "data:")
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_RE.finditer(text):
            destination = unquote(_link_destination(match.group(1)))
            if (
                not destination
                or destination.startswith(("#", "/", *ignored_schemes))
                or "{{" in destination
                or "${" in destination
            ):
                continue
            target_text = destination.split("#", 1)[0].split("?", 1)[0]
            if not target_text:
                continue
            target = (path.parent / target_text).resolve()
            if not target.exists():
                line = text.count("\n", 0, match.start()) + 1
                issues.append(
                    Issue(path, f"line {line}: broken relative link {destination!r}")
                )
    return issues


def check_locale_coverage(root: Path) -> list[Issue]:
    """Require a Russian counterpart with comparable navigational structure."""
    issues: list[Issue] = []
    for source in sorted((root / PUBLIC_DOC_PREFIX).rglob("*.md")):
        relative = source.relative_to(root / PUBLIC_DOC_PREFIX)
        if relative.parts[0] in {"internal", "codex"}:
            continue
        locale = root / RU_DOC_ROOT / relative
        if not locale.exists():
            issues.append(
                Issue(source, f"missing Russian locale {locale.relative_to(root)}")
            )
            continue
        source_text = source.read_text(encoding="utf-8")
        locale_text = locale.read_text(encoding="utf-8")
        source_headings = len(HEADING_RE.findall(source_text))
        locale_headings = len(HEADING_RE.findall(locale_text))
        if source_headings and locale_headings / source_headings < 0.75:
            issues.append(
                Issue(
                    locale,
                    f"heading coverage is {locale_headings}/{source_headings}; expected at least 75%",
                )
            )
        source_fences = len(FENCE_RE.findall(source_text))
        locale_fences = len(FENCE_RE.findall(locale_text))
        if source_fences and locale_fences / source_fences < 0.45:
            issues.append(
                Issue(
                    locale,
                    f"code-fence coverage is {locale_fences}/{source_fences}; expected at least 45%",
                )
            )
    return issues


def proxy_setting_names(config_path: Path) -> set[str]:
    """Extract documented environment names from ProxySettings annotations."""
    tree = ast.parse(config_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ProxySettings":
            return {
                f"GPT2GIGA_{item.target.id.upper()}"
                for item in node.body
                if isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and not item.target.id.startswith("_")
            }
    raise ValueError(f"ProxySettings not found in {config_path}")


def check_proxy_settings(root: Path) -> list[Issue]:
    """Require the configuration reference to name every public proxy setting."""
    config_path = root / "packages/gpt2giga/src/gpt2giga/models/config.py"
    docs_path = root / "docs/configuration.md"
    locale_path = root / RU_DOC_ROOT / "configuration.md"
    names = proxy_setting_names(config_path)
    issues: list[Issue] = []
    for path in (docs_path, locale_path):
        content = path.read_text(encoding="utf-8")
        missing = sorted(name for name in names if name not in content)
        if missing:
            issues.append(
                Issue(path, f"undocumented ProxySettings: {', '.join(missing)}")
            )
    return issues


def check_package_versions(root: Path) -> list[Issue]:
    """Require each shipped changelog to begin with its package metadata version."""
    issues: list[Issue] = []
    for package in ("gpt2giga", "gpt2giga-harness"):
        package_root = root / "packages" / package
        metadata = tomllib.loads(
            (package_root / "pyproject.toml").read_text(encoding="utf-8")
        )
        version = metadata["project"]["version"]
        for filename in ("CHANGELOG.md", "CHANGELOG_en.md"):
            path = package_root / filename
            match = CHANGELOG_VERSION_RE.search(path.read_text(encoding="utf-8"))
            if not match or match.group(1) != version:
                actual = match.group(1) if match else "missing"
                issues.append(
                    Issue(
                        path,
                        f"top changelog version {actual!r} does not match {version!r}",
                    )
                )
    return issues


def check_stale_instructions(root: Path, files: list[Path]) -> list[Issue]:
    """Reject known obsolete public installation instructions."""
    forbidden = {
        "feature/unified_harness": "use the current Harness preview branch",
        "feature/harness_enrichment": "use the current Harness preview branch",
        "gpt2giga-harness==0.0.1a4": "the next Harness release is 0.1.0b1",
        'gpt2giga==0.2.3a1"': "do not pin the previous gateway alpha in current install docs",
        'gpt2giga-harness==0.0.1"': "do not pin the pre-split Harness version",
    }
    issues: list[Issue] = []
    for path in files:
        if "CHANGELOG" in path.name:
            continue
        content = path.read_text(encoding="utf-8")
        for needle, guidance in forbidden.items():
            if needle in content:
                line = content.count("\n", 0, content.index(needle)) + 1
                issues.append(
                    Issue(path, f"line {line}: obsolete {needle!r}; {guidance}")
                )
    return issues


def validate(root: Path) -> list[Issue]:
    """Run the complete public documentation contract."""
    files = tracked_markdown_files(root)
    return [
        *check_relative_links(root, files),
        *check_locale_coverage(root),
        *check_proxy_settings(root),
        *check_package_versions(root),
        *check_stale_instructions(root, files),
    ]


def main(argv: list[str] | None = None) -> int:
    """Run validation and print actionable diagnostics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    issues = validate(root)
    if issues:
        for issue in issues:
            print(issue.render(root), file=sys.stderr)
        print(
            f"Documentation validation failed with {len(issues)} issue(s).",
            file=sys.stderr,
        )
        return 1
    print("Documentation validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
