"""Fail-closed import and storage of reviewed external Agent Skills."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath

import yaml

from gpt2giga_harness.portable_skills import (
    MAX_SKILL_FILE_BYTES,
    MAX_SKILL_TOTAL_BYTES,
    PortableSkill,
    PortableSkillFile,
)


@dataclass(frozen=True)
class ExternalSkillArtifact:
    """Content-addressed bytes and immutable upstream identity for a Skill."""

    source_id: str
    immutable_ref: str
    license_evidence: str
    files: Mapping[str, bytes]
    sha256: str


class ExternalSkillStore:
    """Persist reviewed Skill artifacts under private, content-addressed paths."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def import_artifact(
        self,
        *,
        source_id: str,
        immutable_ref: str,
        license_evidence: str,
        files: Mapping[str, bytes],
        expected_sha256: str,
    ) -> ExternalSkillArtifact:
        artifact = _validate_artifact(
            source_id, immutable_ref, license_evidence, files, expected_sha256
        )
        destination = self.root / artifact.sha256
        destination.mkdir(parents=True, exist_ok=True)
        for name, content in artifact.files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o600)
        return artifact

    def resolve(self, sha256: str) -> ExternalSkillArtifact:
        """Resolve only an already stored artifact; never fetches upstream bytes."""
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("artifact hash is invalid")
        directory = self.root / sha256
        files = {
            str(path.relative_to(directory)): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }
        return _validate_artifact("local", "stored", "stored", files, sha256)


def parse_external_skill(artifact: ExternalSkillArtifact) -> PortableSkill:
    """Parse a stored external Skill with strict frontmatter and path rules."""
    raw = artifact.files.get("SKILL.md")
    if raw is None:
        raise ValueError("external Skill must contain SKILL.md")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SKILL.md must be UTF-8") from exc
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("SKILL.md frontmatter is required")
    end = text.index("\n---\n", 4)

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        pairs = loader.construct_pairs(node, deep=True)
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("duplicate SKILL.md frontmatter key")
        return dict(pairs)

    UniqueLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping
    )
    try:
        metadata = yaml.load(text[4:end], Loader=UniqueLoader) or {}
    except ValueError:
        raise
    except yaml.YAMLError as exc:
        raise ValueError("invalid SKILL.md frontmatter") from exc
    if set(metadata) - {"name", "description"}:
        raise ValueError("unsupported external Skill frontmatter")
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError("Skill name and description are required")
    supporting = []
    for path, content in artifact.files.items():
        if path == "SKILL.md":
            continue
        supporting.append(PortableSkillFile(path, content, _safe_mode(path)))
    return PortableSkill(name, name, description, text[end + 5 :], tuple(supporting))


def _validate_artifact(source_id, immutable_ref, license_evidence, files, expected):
    if not source_id or not immutable_ref or not license_evidence:
        raise ValueError("artifact provenance and license evidence are required")
    normalized = {}
    total = 0
    for name, content in files.items():
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or name != str(path):
            raise ValueError("artifact path is unsafe")
        if name == "SKILL.md" and path.parts != ("SKILL.md",):
            raise ValueError("SKILL.md path is invalid")
        if not isinstance(content, bytes) or len(content) > MAX_SKILL_FILE_BYTES:
            raise ValueError("artifact file is invalid or too large")
        total += len(content)
        if total > MAX_SKILL_TOTAL_BYTES:
            raise ValueError("artifact is too large")
        normalized[name] = content
    digest = hashlib.sha256(
        b"".join(
            name.encode() + b"\0" + normalized[name] for name in sorted(normalized)
        )
    ).hexdigest()
    if digest != expected:
        raise ValueError("artifact hash does not match immutable content")
    return ExternalSkillArtifact(
        source_id, immutable_ref, license_evidence, normalized, digest
    )


def _safe_mode(path: str) -> int:
    return 0o755 if path.startswith("scripts/") else 0o644
