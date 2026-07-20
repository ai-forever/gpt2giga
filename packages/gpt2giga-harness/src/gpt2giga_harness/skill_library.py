"""Root Skill inventory, federated search, and immutable Git imports."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from gpt2giga_harness.builtin_skills import (
    BUILTIN_SKILL_SOURCE_ID,
    get_builtin_skill_bundle,
)
from gpt2giga_harness.external_skills import ExternalSkillStore, parse_external_skill
from gpt2giga_harness.federated_catalog import (
    FederatedCatalogCandidate,
    FederatedCatalogComponent,
    FederatedCatalogSource,
    NeuralDeepFederatedCatalogSource,
    SkillsShFederatedCatalogSource,
)
from gpt2giga_harness.integration_catalog import (
    CatalogEntry,
    CatalogSourceType,
    IntegrationCatalogStore,
)
from gpt2giga_harness.integration_packages import (
    InstallationScope,
    IntegrationCompatibility,
    IntegrationComponent,
    IntegrationComponentType,
    IntegrationPackage,
    IntegrationSourceType,
    IntegrationTargetOverlay,
    IntegrationTrustEvidence,
    IntegrationTrustKind,
    IntegrationTrustStatus,
    IntegrationUpdatePolicy,
    integration_package_from_dict,
    integration_package_to_dict,
)
from gpt2giga_harness.portable_skills import (
    CLAUDE_SKILL_TARGET_ID,
    CODEX_SKILL_TARGET_ID,
    GEMINI_SKILL_TARGET_ID,
    PortableSkill,
)
from gpt2giga_harness.skills_catalog_proxy_client import SkillsCatalogProxyFetcher


MAX_ROOT_SKILLS = 512
MAX_GIT_CANDIDATES = 256
MAX_PREVIEW_CHARS = 40_000
GIT_TIMEOUT_SECONDS = 90.0
_GITHUB_PART_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
_GIT_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+~-]{0,255}\Z")


@dataclass(frozen=True)
class GitCommandResult:
    """Bounded Git subprocess result returned by an injectable runner."""

    returncode: int
    stdout: str
    stderr: str = ""


GitCommandRunner = Callable[[tuple[str, ...], Path | None, float], GitCommandResult]


@dataclass(frozen=True)
class _RootSkill:
    id: str
    name: str
    description: str
    path: Path
    target_ids: tuple[str, ...]
    origin: str


@dataclass(frozen=True)
class _GitSnapshot:
    repository_url: str
    requested_ref: str | None
    commit: str
    root: Path


class SkillLibraryService:
    """Project safe Skill discovery without mutating native user homes."""

    def __init__(
        self,
        data_dir: Path,
        *,
        root_skill_roots: Sequence[tuple[Path, Sequence[str], str]] | None = None,
        federated_sources: Sequence[FederatedCatalogSource] | None = None,
        git_runner: GitCommandRunner | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.catalog = IntegrationCatalogStore(self.data_dir)
        self.external_store = ExternalSkillStore(
            self.data_dir / "integrations" / "external-skills"
        )
        self.git_cache = self.data_dir / "integrations" / "git-snapshots"
        self._root_skill_roots = tuple(
            root_skill_roots
            if root_skill_roots is not None
            else _default_root_skill_roots()
        )
        use_default_sources = federated_sources is None
        self._federated_sources = tuple(
            federated_sources if federated_sources is not None else _default_sources()
        )
        self._unconfigured_source_ids = (
            ("skills-sh",)
            if use_default_sources and not os.environ.get("GIGA_SKILLS_PROXY_ORIGIN")
            else ()
        )
        self._git_runner = git_runner or _run_git

    def root_skills(self) -> list[dict[str, Any]]:
        """Return deduplicated global/native Skill metadata without instructions."""
        return [_root_projection(item) for item in self._scan_root_skills()]

    async def search(
        self,
        query: str,
        *,
        components: Sequence[str] = ("skill", "mcp"),
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search configured read-only catalogs and retain source failures."""
        query = query.strip()
        if not 2 <= len(query) <= 200:
            raise ValueError("catalog search query must contain 2 to 200 characters")
        if not 1 <= limit <= 100:
            raise ValueError("catalog search limit must be between 1 and 100")
        selected_components = {FederatedCatalogComponent(item) for item in components}
        if not selected_components:
            raise ValueError("catalog search requires at least one component")

        async def search_source(source: FederatedCatalogSource):
            if not selected_components.intersection(source.descriptor.components):
                return source.descriptor.source_id, (), None
            try:
                candidates = await source.search(query, limit=limit)
                return source.descriptor.source_id, candidates, None
            except Exception as exc:
                return source.descriptor.source_id, (), type(exc).__name__

        results = await asyncio.gather(
            *(search_source(source) for source in self._federated_sources)
        )
        items: list[dict[str, Any]] = []
        sources = []
        for source_id, candidates, error_type in results:
            sources.append(
                {
                    "id": source_id,
                    "status": "ready" if error_type is None else "unavailable",
                    "error_type": error_type,
                }
            )
            items.extend(
                _federated_projection(item)
                for item in candidates
                if item.component in selected_components
            )
        sources.extend(
            {
                "id": source_id,
                "status": "configuration_required",
                "error_type": None,
            }
            for source_id in self._unconfigured_source_ids
        )
        sources.sort(key=lambda item: str(item["id"]))
        items.sort(
            key=lambda item: (
                -int(item["curated"]),
                -int(item["popularity"] or 0),
                str(item["title"]).casefold(),
            )
        )
        return {
            "query": query,
            "items": items[:limit],
            "sources": sources,
            "install_authorized": False,
        }

    async def inspect_git(
        self, repository_url: str, *, ref: str | None = None
    ) -> dict[str, Any]:
        """Clone one admitted GitHub ref and inspect bounded install candidates."""
        return await asyncio.to_thread(self._inspect_git, repository_url, ref)

    def import_git_skill(self, candidate_id: str) -> CatalogEntry:
        """Import one previously inspected Skill into the offline catalog."""
        candidate = self._load_candidate(candidate_id)
        if candidate.get("type") != "skill":
            raise ValueError("selected Git candidate is not a Skill")
        snapshot_root = self._existing_snapshot_root(str(candidate["snapshot_id"]))
        relative_dir = _safe_relative_path(str(candidate["relative_dir"]))
        skill_root = snapshot_root / relative_dir
        files = _read_skill_files(skill_root)
        files["SKILL.md"] = _normalize_skill_markdown(
            files["SKILL.md"].decode("utf-8")
        ).encode("utf-8")
        digest = _artifact_hash(files)
        artifact = self.external_store.import_artifact(
            source_id=str(candidate["repository_url"]),
            immutable_ref=str(candidate["commit"]),
            license_evidence=str(candidate["license"]),
            files=files,
            expected_sha256=digest,
        )
        skill = parse_external_skill(artifact)
        package = _external_skill_package(candidate, skill, artifact.sha256)
        return self.catalog.import_package(
            package,
            source_id=f"git-{str(candidate['snapshot_id'])[:24]}",
            source_type=CatalogSourceType.GIT,
        )

    def preview(self, preview_id: str) -> dict[str, Any]:
        """Return bounded Skill markdown only after an explicit item selection."""
        if preview_id.startswith("root:"):
            item = next(
                (skill for skill in self._scan_root_skills() if skill.id == preview_id),
                None,
            )
            if item is None:
                raise KeyError(preview_id)
            markdown = item.path.read_text(encoding="utf-8")
            return _preview_projection(
                item.name, item.description, markdown, item.origin, item.target_ids
            )
        if preview_id.startswith("catalog:"):
            catalog_id = preview_id.removeprefix("catalog:")
            entry = self.catalog.get(catalog_id)
            if entry is None or entry.package is None:
                raise KeyError(preview_id)
            if entry.source_id == BUILTIN_SKILL_SOURCE_ID:
                skill = get_builtin_skill_bundle(entry.package_id).skill
                return _preview_projection(
                    skill.name,
                    skill.description,
                    _portable_skill_markdown(skill),
                    "built-in",
                    tuple(item.target_id for item in entry.package.compatibility),
                )
            digest = entry.package.checksum.removeprefix("sha256:")
            skill = parse_external_skill(self.external_store.resolve(digest))
            return _preview_projection(
                skill.name,
                skill.description,
                _portable_skill_markdown(skill),
                entry.source_id,
                tuple(item.target_id for item in entry.package.compatibility),
            )
        if preview_id.startswith("git:"):
            candidate = self._load_candidate(preview_id.removeprefix("git:"))
            if candidate.get("type") != "skill":
                raise KeyError(preview_id)
            relative_dir = _safe_relative_path(str(candidate["relative_dir"]))
            path = (
                self._existing_snapshot_root(str(candidate["snapshot_id"]))
                / relative_dir
                / "SKILL.md"
            )
            markdown = path.read_text(encoding="utf-8")
            return _preview_projection(
                str(candidate["title"]),
                str(candidate["description"]),
                markdown,
                str(candidate["repository_url"]),
                (
                    CODEX_SKILL_TARGET_ID,
                    CLAUDE_SKILL_TARGET_ID,
                    GEMINI_SKILL_TARGET_ID,
                ),
            )
        raise KeyError(preview_id)

    def _inspect_git(self, repository_url: str, ref: str | None) -> dict[str, Any]:
        canonical_url, embedded_ref = _canonical_github_repository(repository_url)
        selected_ref = ref.strip() if ref is not None and ref.strip() else embedded_ref
        if selected_ref is not None and _GIT_REF_RE.fullmatch(selected_ref) is None:
            raise ValueError("Git ref is invalid")
        self.git_cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        clone_root = Path(tempfile.mkdtemp(prefix=".inspect-", dir=self.git_cache))
        try:
            argv = [
                "git",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--filter=blob:none",
            ]
            if selected_ref is not None:
                argv.extend(("--branch", selected_ref))
            argv.extend(("--", canonical_url, str(clone_root / "repo")))
            result = self._git_runner(tuple(argv), None, GIT_TIMEOUT_SECONDS)
            if result.returncode != 0:
                raise ValueError("Git repository could not be inspected")
            repo = clone_root / "repo"
            commit_result = self._git_runner(
                ("git", "rev-parse", "HEAD"), repo, GIT_TIMEOUT_SECONDS
            )
            commit = commit_result.stdout.strip()
            if commit_result.returncode != 0 or not re.fullmatch(
                r"[0-9a-f]{40}", commit
            ):
                raise ValueError(
                    "Git repository did not resolve to an immutable commit"
                )
            snapshot_id = hashlib.sha256(
                f"{canonical_url}\0{commit}".encode()
            ).hexdigest()
            destination = self._snapshot_root(snapshot_id)
            if destination.exists():
                if destination.is_symlink() or not destination.is_dir():
                    raise ValueError("Git snapshot cache is invalid")
                shutil.rmtree(clone_root)
            else:
                os.replace(repo, destination)
                shutil.rmtree(clone_root)
            snapshot = _GitSnapshot(
                repository_url=canonical_url,
                requested_ref=selected_ref,
                commit=commit,
                root=destination,
            )
            candidates = self._git_candidates(snapshot, snapshot_id)
            return {
                "repository_url": canonical_url,
                "requested_ref": selected_ref,
                "commit": commit,
                "snapshot_id": snapshot_id,
                "candidates": candidates,
            }
        except Exception:
            if clone_root.exists():
                shutil.rmtree(clone_root)
            raise

    def _git_candidates(
        self, snapshot: _GitSnapshot, snapshot_id: str
    ) -> list[dict[str, Any]]:
        candidates = []
        license_evidence = _license_evidence(snapshot.root)
        for skill_md in sorted(snapshot.root.rglob("SKILL.md")):
            if len(candidates) >= MAX_GIT_CANDIDATES:
                break
            if (
                _unsafe_path(snapshot.root, skill_md)
                or skill_md.stat().st_size > MAX_PREVIEW_CHARS * 4
            ):
                continue
            try:
                name, description = _skill_metadata(skill_md)
            except (OSError, UnicodeError, ValueError):
                continue
            relative_dir = str(skill_md.parent.relative_to(snapshot.root)) or "."
            candidate_id = hashlib.sha256(
                f"{snapshot_id}\0skill\0{relative_dir}".encode()
            ).hexdigest()
            candidate = {
                "id": candidate_id,
                "type": "skill",
                "title": name,
                "description": description,
                "relative_dir": relative_dir,
                "repository_url": snapshot.repository_url,
                "commit": snapshot.commit,
                "snapshot_id": snapshot_id,
                "license": license_evidence,
                "preview_id": f"git:{candidate_id}",
                "manifest": None,
            }
            self._write_candidate(candidate)
            candidates.append(candidate)
        for manifest_path in sorted(snapshot.root.rglob("integration-package.json")):
            if len(candidates) >= MAX_GIT_CANDIDATES:
                break
            if (
                _unsafe_path(snapshot.root, manifest_path)
                or manifest_path.stat().st_size > 512_000
            ):
                continue
            try:
                manifest = integration_package_to_dict(
                    integration_package_from_dict(
                        json.loads(manifest_path.read_text(encoding="utf-8"))
                    )
                )
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                continue
            component_types = {item["type"] for item in manifest["components"]}
            candidate_type = (
                "mcp"
                if "mcp" in component_types
                else "plugin"
                if component_types.intersection({"plugin", "extension"})
                else "package"
            )
            relative_dir = str(manifest_path.parent.relative_to(snapshot.root)) or "."
            candidate_id = hashlib.sha256(
                f"{snapshot_id}\0manifest\0{relative_dir}".encode()
            ).hexdigest()
            candidate = {
                "id": candidate_id,
                "type": candidate_type,
                "title": manifest["id"],
                "description": "Immutable integration-package.json",
                "relative_dir": relative_dir,
                "repository_url": snapshot.repository_url,
                "commit": snapshot.commit,
                "snapshot_id": snapshot_id,
                "license": manifest["license"],
                "preview_id": None,
                "manifest": manifest,
            }
            self._write_candidate(candidate)
            candidates.append(candidate)
        return candidates

    def _scan_root_skills(self) -> tuple[_RootSkill, ...]:
        by_key: dict[tuple[str, str], _RootSkill] = {}
        for root, target_ids, origin in self._root_skill_roots:
            root = Path(root).expanduser()
            if not root.is_dir() or root.is_symlink():
                continue
            count = 0
            for skill_md in sorted(root.rglob("SKILL.md")):
                if count >= MAX_ROOT_SKILLS:
                    break
                if _unsafe_path(root, skill_md):
                    continue
                try:
                    name, description = _skill_metadata(skill_md)
                    digest = hashlib.sha256(skill_md.read_bytes()).hexdigest()
                except (OSError, UnicodeError, ValueError):
                    continue
                count += 1
                key = (name, digest)
                current = by_key.get(key)
                merged_targets = tuple(
                    sorted(set(target_ids).union(current.target_ids if current else ()))
                )
                by_key[key] = _RootSkill(
                    id=f"root:{digest}",
                    name=name,
                    description=description,
                    path=skill_md,
                    target_ids=merged_targets,
                    origin=current.origin if current is not None else origin,
                )
        return tuple(sorted(by_key.values(), key=lambda item: item.name.casefold()))

    def _candidate_path(self, candidate_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", candidate_id):
            raise ValueError("Git candidate id is invalid")
        return self.git_cache / "candidates" / f"{candidate_id}.json"

    def _write_candidate(self, candidate: Mapping[str, Any]) -> None:
        path = self._candidate_path(str(candidate["id"]))
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(
            json.dumps(candidate, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _load_candidate(self, candidate_id: str) -> dict[str, Any]:
        path = self._candidate_path(candidate_id)
        if not path.is_file() or path.is_symlink():
            raise KeyError(candidate_id)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("id") != candidate_id:
            raise ValueError("Git candidate state is invalid")
        return value

    def _snapshot_root(self, snapshot_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise ValueError("Git snapshot id is invalid")
        return self.git_cache / snapshot_id

    def _existing_snapshot_root(self, snapshot_id: str) -> Path:
        root = self._snapshot_root(snapshot_id)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Git snapshot is unavailable")
        return root


def _default_root_skill_roots() -> tuple[tuple[Path, tuple[str, ...], str], ...]:
    all_targets = (
        CODEX_SKILL_TARGET_ID,
        CLAUDE_SKILL_TARGET_ID,
        GEMINI_SKILL_TARGET_ID,
    )
    configured = os.environ.get("GIGA_ROOT_SKILLS_DIRS")
    shared = (
        tuple(Path(item) for item in configured.split(os.pathsep) if item)
        if configured
        else (Path.home() / ".agents" / "skills",)
    )
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    gemini_home = Path(os.environ.get("GEMINI_CLI_HOME", Path.home() / ".gemini"))
    roots = [(path, all_targets, "root") for path in shared]
    roots.extend(
        (
            (codex_home / "skills", (CODEX_SKILL_TARGET_ID,), "codex-root"),
            (claude_home / "skills", (CLAUDE_SKILL_TARGET_ID,), "claude-root"),
            (gemini_home / "skills", (GEMINI_SKILL_TARGET_ID,), "gemini-root"),
        )
    )
    return tuple(roots)


def _default_sources() -> tuple[FederatedCatalogSource, ...]:
    sources: list[FederatedCatalogSource] = [NeuralDeepFederatedCatalogSource()]
    proxy_origin = os.environ.get("GIGA_SKILLS_PROXY_ORIGIN")
    if proxy_origin:
        sources.insert(
            0,
            SkillsShFederatedCatalogSource(
                hosted_fetch=SkillsCatalogProxyFetcher(proxy_origin)
            ),
        )
    return tuple(sources)


def _root_projection(item: _RootSkill) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "target_ids": list(item.target_ids),
        "origin": item.origin,
        "scope": "root",
        "connected": True,
        "preview_id": item.id,
    }


def _federated_projection(item: FederatedCatalogCandidate) -> dict[str, Any]:
    return {
        "id": f"remote:{item.source_id}:{item.upstream_id}",
        "source_id": item.source_id,
        "upstream_id": item.upstream_id,
        "title": item.name,
        "component": item.component.value,
        "artifact_url": item.provenance.artifact_url,
        "detail_url": item.provenance.detail_url,
        "curated": item.trust.curated,
        "popularity": item.trust.popularity,
        "upstream_audit": item.trust.upstream_audit,
        "install_authorized": False,
    }


def _preview_projection(
    name: str,
    description: str,
    markdown: str,
    source: str,
    target_ids: Sequence[str],
) -> dict[str, Any]:
    truncated = len(markdown) > MAX_PREVIEW_CHARS
    return {
        "name": name,
        "description": description,
        "markdown": markdown[:MAX_PREVIEW_CHARS],
        "truncated": truncated,
        "source": source,
        "target_ids": list(target_ids),
    }


def _skill_metadata(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    metadata, _ = _skill_document(text)
    return str(metadata["name"]), str(metadata["description"])


def _skill_document(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("Skill frontmatter is required")
    end = text.index("\n---\n", 4)

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        pairs = loader.construct_pairs(node, deep=True)
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("duplicate Skill frontmatter key")
        return dict(pairs)

    UniqueLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping
    )
    try:
        value = yaml.load(text[4:end], Loader=UniqueLoader) or {}
    except ValueError:
        raise
    except yaml.YAMLError as exc:
        raise ValueError("Skill frontmatter is invalid") from exc
    if not isinstance(value, Mapping):
        raise ValueError("Skill frontmatter must be an object")
    name = value.get("name")
    description = value.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Skill name is required")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Skill description is required")
    return {"name": name.strip(), "description": description.strip()}, text[end + 5 :]


def _normalize_skill_markdown(text: str) -> str:
    metadata, instructions = _skill_document(text)
    header = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{header}\n---\n\n{instructions.lstrip()}"


def _portable_skill_markdown(skill: PortableSkill) -> str:
    header = yaml.safe_dump(
        {"name": skill.name, "description": skill.description},
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{header}\n---\n\n{skill.instructions}"


def _canonical_github_repository(value: str) -> tuple[str, str | None]:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Git inspection currently accepts public GitHub HTTPS URLs")
    parts = [item for item in parsed.path.split("/") if item]
    if len(parts) < 2:
        raise ValueError("GitHub repository URL is incomplete")
    owner, repository = parts[:2]
    repository = repository.removesuffix(".git")
    if not _GITHUB_PART_RE.fullmatch(owner) or not _GITHUB_PART_RE.fullmatch(
        repository
    ):
        raise ValueError("GitHub repository identity is invalid")
    embedded_ref = None
    if len(parts) > 2:
        if len(parts) < 4 or parts[2] != "tree":
            raise ValueError("GitHub URL must identify a repository or tree ref")
        embedded_ref = "/".join(parts[3:])
    return urlunsplit(
        ("https", "github.com", f"/{owner}/{repository}.git", "", "")
    ), embedded_ref


def _run_git(
    argv: tuple[str, ...], cwd: Path | None, timeout: float
) -> GitCommandResult:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH_COMMAND"}
    }
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitCommandResult(1, "", type(exc).__name__)
    return GitCommandResult(
        completed.returncode,
        completed.stdout[-8_000:],
        completed.stderr[-8_000:],
    )


def _unsafe_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return not path.is_file()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("Git candidate path is unsafe")
    return path


def _read_skill_files(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Git Skill directory is unavailable")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if ".git" in path.relative_to(root).parts:
            continue
        if _unsafe_path(root, path):
            raise ValueError("Git Skill contains an unsafe path")
        relative = str(path.relative_to(root))
        files[relative] = path.read_bytes()
    return files


def _artifact_hash(files: Mapping[str, bytes]) -> str:
    return hashlib.sha256(
        b"".join(name.encode() + b"\0" + files[name] for name in sorted(files))
    ).hexdigest()


def _license_evidence(root: Path) -> str:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        path = root / name
        if path.is_file() and not path.is_symlink():
            return name
    return "operator-review-required"


def _external_skill_package(
    candidate: Mapping[str, Any], skill: PortableSkill, artifact_sha256: str
) -> IntegrationPackage:
    commit = str(candidate["commit"])
    repository_url = str(candidate["repository_url"])
    package_id = "git." + ".".join(
        part.lower().replace("_", "-")
        for part in (
            *urlsplit(repository_url).path.strip("/").removesuffix(".git").split("/"),
            skill.name,
        )
    )
    target_ids = (
        CODEX_SKILL_TARGET_ID,
        CLAUDE_SKILL_TARGET_ID,
        GEMINI_SKILL_TARGET_ID,
    )
    license_name = "NOASSERTION"
    return IntegrationPackage(
        id=package_id,
        version=f"0.0.0+{commit[:12]}",
        publisher=urlsplit(repository_url).path.strip("/").split("/", 1)[0],
        license=license_name,
        source_type=IntegrationSourceType.GIT,
        source=repository_url,
        immutable_ref=commit,
        checksum=f"sha256:{artifact_sha256}",
        components=(
            IntegrationComponent(
                id=skill.component_id,
                type=IntegrationComponentType.SKILL,
                portable=True,
            ),
        ),
        requirements=(),
        overlays=tuple(
            IntegrationTargetOverlay(
                target_id=target_id,
                component_ids=(skill.component_id,),
            )
            for target_id in target_ids
        ),
        compatibility=tuple(
            IntegrationCompatibility(
                target_id=target_id,
                required_capabilities=("skill.discovery",),
            )
            for target_id in target_ids
        ),
        scopes=(InstallationScope.MANAGED_HOME, InstallationScope.PROJECT),
        update_policy=IntegrationUpdatePolicy.PINNED,
        verification_steps=("skill-discovery",),
        rollback_steps=("restore-snapshot",),
        trust_evidence=(
            IntegrationTrustEvidence(
                id="git-immutable-source",
                kind=IntegrationTrustKind.SOURCE,
                status=IntegrationTrustStatus.VERIFIED,
                authority="git",
                revision=commit,
            ),
            IntegrationTrustEvidence(
                id="git-publisher-identity",
                kind=IntegrationTrustKind.PUBLISHER,
                status=IntegrationTrustStatus.UNVERIFIED,
                authority="github",
                revision=commit,
            ),
            IntegrationTrustEvidence(
                id="git-license-review",
                kind=IntegrationTrustKind.LICENSE,
                status=IntegrationTrustStatus.UNVERIFIED,
                authority="operator",
                revision=artifact_sha256,
            ),
        ),
    )


__all__ = ["GitCommandResult", "SkillLibraryService"]
