"""Fail-closed verification for injected Cockpit build assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Mapping, Sequence


ASSET_FORMAT_VERSION = "gpt2giga-cockpit-v2-assets-v1"
PROVENANCE_FORMAT_VERSION = "gpt2giga-cockpit-assets-provenance-v1"
SBOM_FORMAT_VERSION = "gpt2giga-cockpit-sbom-v1"
LICENSE_FORMAT_VERSION = "gpt2giga-cockpit-licenses-v1"
RECOVERY_COMMAND = "npm --prefix packages/gpt2giga-harness/frontend run build"
ASSET_RELATIVE_ROOT = Path("src/gpt2giga_harness/ui/cockpit_v2/assets")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40,64}")
_MAX_FILES = 512
_MAX_BYTES = 32 * 1024 * 1024


class AssetContractError(RuntimeError):
    """Report an unsafe, missing, stale, or malformed injected asset tree."""


def _fail(message: str) -> None:
    raise AssetContractError(f"{message}. Recover with: {RECOVERY_COMMAND}")


def _json_object(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        _fail(f"Cockpit {label} is missing or malformed")
        raise AssertionError from exc
    if not isinstance(payload, Mapping):
        _fail(f"Cockpit {label} must be a JSON object")
    return payload


def _digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest_file(path: Path) -> str:
    return _digest_bytes(path.read_bytes())


def _safe_name(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        _fail(f"Cockpit {label} contains an invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        _fail(f"Cockpit {label} contains an unsafe path")
    return value


def _regular_files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        _fail("Cockpit injected asset directory is unavailable")
    files: list[Path] = []
    total_bytes = 0
    pending = [root]
    while pending:
        current = pending.pop()
        for path in sorted(current.iterdir(), key=lambda item: item.name, reverse=True):
            if path.is_symlink():
                _fail(
                    "Cockpit injected asset tree contains a symlink "
                    f"{path.relative_to(root).as_posix()}"
                )
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                files.append(path)
                total_bytes += path.stat().st_size
            else:
                _fail(
                    "Cockpit injected asset tree contains a non-regular entry "
                    f"{path.relative_to(root).as_posix()}"
                )
            if len(files) > _MAX_FILES or total_bytes > _MAX_BYTES:
                _fail("Cockpit injected asset tree exceeds its package bound")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _named_digest(root: Path, files: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _frontend_inputs(project_root: Path) -> list[Path]:
    frontend = project_root / "frontend"
    fixed = [
        frontend / "eslint.config.js",
        frontend / "index.html",
        frontend / "package-lock.json",
        frontend / "package.json",
        frontend / "tsconfig.json",
        frontend / "vite.config.ts",
        project_root / "branding/generate-assets.mjs",
        project_root / "branding/gigaloom-mark.svg",
    ]
    dynamic = [
        *sorted((frontend / "scripts").rglob("*")),
        *sorted((frontend / "src").rglob("*")),
        *sorted((frontend / "public").rglob("*")),
    ]
    files = [
        path
        for path in [*fixed, *dynamic]
        if path.is_file()
        and not path.is_symlink()
        and not path.is_relative_to(frontend / "public/brand")
    ]
    if any(not path.is_file() for path in fixed):
        _fail("Cockpit authored frontend inputs are incomplete")
    return sorted(files, key=lambda path: path.relative_to(project_root).as_posix())


def _current_revision(project_root: Path) -> str | None:
    environment_revision = os.environ.get("GIGALOOM_SOURCE_REVISION") or os.environ.get(
        "GITHUB_SHA"
    )
    if environment_revision:
        return environment_revision.casefold()
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip().casefold()


def _evidence_record(
    manifest: Mapping[str, Any],
    *,
    key: str,
    relative_name: str,
    asset_root: Path,
) -> Path:
    build = manifest.get("build")
    if not isinstance(build, Mapping):
        _fail("Cockpit manifest has no build evidence")
    record = build.get(key)
    if not isinstance(record, Mapping) or record.get("path") != relative_name:
        _fail(f"Cockpit manifest has invalid {key} evidence")
    path = asset_root / relative_name
    try:
        size = path.stat().st_size
        digest = _digest_file(path)
    except FileNotFoundError as exc:
        _fail(f"Cockpit {key} evidence is missing")
        raise AssertionError from exc
    if record.get("bytes") != size or record.get("sha256") != digest:
        _fail(f"Cockpit {key} evidence failed integrity validation")
    return path


def verify_asset_tree(project_root: Path) -> Mapping[str, Any]:
    """Verify one complete injected tree and return content-free build evidence."""
    project_root = Path(project_root).resolve()
    asset_root = project_root / ASSET_RELATIVE_ROOT
    if not asset_root.is_dir() or asset_root.is_symlink():
        _fail("Cockpit injected asset directory is unavailable")
    manifest_path = asset_root / "manifest.json"
    manifest = _json_object(manifest_path, label="asset manifest")
    if manifest.get("format_version") != ASSET_FORMAT_VERSION:
        _fail("Cockpit asset manifest version is unsupported")

    raw_assets = manifest.get("assets")
    raw_initial = manifest.get("initial")
    entry = _safe_name(manifest.get("entry"), label="asset manifest")
    if not isinstance(raw_assets, Mapping) or not raw_assets:
        _fail("Cockpit asset manifest has no files")
    if not isinstance(raw_initial, list) or not raw_initial:
        _fail("Cockpit asset manifest has no initial graph")

    expected = {
        "manifest.json",
        "_build/provenance.json",
        "_build/sbom.cdx.json",
        "_build/licenses.json",
    }
    runtime_files: list[Path] = []
    for raw_name, raw_record in raw_assets.items():
        name = _safe_name(raw_name, label="asset manifest")
        if not isinstance(raw_record, Mapping):
            _fail(f"Cockpit asset record is invalid for {name}")
        path = asset_root / name
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            _fail(f"Cockpit asset is missing: {name}")
            raise AssertionError from exc
        if (
            raw_record.get("bytes") != len(content)
            or not isinstance(raw_record.get("sha256"), str)
            or _DIGEST.fullmatch(raw_record["sha256"]) is None
            or raw_record["sha256"] != _digest_bytes(content)
        ):
            _fail(f"Cockpit asset failed integrity validation: {name}")
        expected.add(name)
        runtime_files.append(path)

    if entry not in raw_assets:
        _fail("Cockpit entry is absent from the asset manifest")
    initial = [_safe_name(value, label="initial graph") for value in raw_initial]
    if len(initial) != len(set(initial)) or any(
        name not in raw_assets for name in initial
    ):
        _fail("Cockpit initial graph is invalid")

    actual = {
        path.relative_to(asset_root).as_posix() for path in _regular_files(asset_root)
    }
    if actual != expected:
        unexpected = sorted(actual - expected)
        missing = sorted(expected - actual)
        _fail(
            "Cockpit injected asset tree is not allowlisted "
            f"(unexpected={unexpected}, missing={missing})"
        )

    build = manifest["build"]
    output_digest = _named_digest(
        asset_root,
        sorted(runtime_files, key=lambda path: path.relative_to(asset_root).as_posix()),
    )
    if build.get("output_sha256") != output_digest:
        _fail("Cockpit output tree digest is invalid")

    provenance_path = _evidence_record(
        manifest,
        key="provenance",
        relative_name="_build/provenance.json",
        asset_root=asset_root,
    )
    sbom_path = _evidence_record(
        manifest,
        key="sbom",
        relative_name="_build/sbom.cdx.json",
        asset_root=asset_root,
    )
    licenses_path = _evidence_record(
        manifest,
        key="licenses",
        relative_name="_build/licenses.json",
        asset_root=asset_root,
    )
    provenance = _json_object(provenance_path, label="provenance")
    sbom = _json_object(sbom_path, label="SBOM")
    licenses = _json_object(licenses_path, label="license evidence")

    if provenance.get("format_version") != PROVENANCE_FORMAT_VERSION:
        _fail("Cockpit provenance version is unsupported")
    source_revision = provenance.get("source_revision")
    digest_fields = (
        "frontend_input_sha256",
        "lockfile_sha256",
        "brand_sha256",
        "output_sha256",
        "sbom_sha256",
        "licenses_sha256",
    )
    if (
        not isinstance(source_revision, str)
        or _REVISION.fullmatch(source_revision) is None
        or not isinstance(provenance.get("source_dirty"), bool)
        or any(
            not isinstance(provenance.get(field), str)
            or _DIGEST.fullmatch(provenance[field]) is None
            for field in digest_fields
        )
    ):
        _fail("Cockpit provenance fields are invalid")
    if (
        provenance["output_sha256"] != output_digest
        or provenance["sbom_sha256"] != _digest_file(sbom_path)
        or provenance["licenses_sha256"] != _digest_file(licenses_path)
    ):
        _fail("Cockpit provenance evidence binding is invalid")
    sbom_metadata = sbom.get("metadata")
    sbom_properties = (
        sbom_metadata.get("properties") if isinstance(sbom_metadata, Mapping) else None
    )
    if (
        sbom.get("bomFormat") != "CycloneDX"
        or sbom.get("specVersion") != "1.6"
        or not isinstance(sbom_properties, list)
        or {
            item.get("value")
            for item in sbom_properties
            if isinstance(item, Mapping)
            and item.get("name") == "gpt2giga:format-version"
        }
        != {SBOM_FORMAT_VERSION}
    ):
        _fail("Cockpit SBOM version is unsupported")
    if licenses.get("format_version") != LICENSE_FORMAT_VERSION:
        _fail("Cockpit license evidence version is unsupported")
    if (
        not isinstance(sbom.get("components"), list)
        or not isinstance(licenses.get("packages"), list)
        or licenses.get("package_count") != len(licenses["packages"])
        or len(sbom["components"]) != licenses["package_count"]
    ):
        _fail("Cockpit supply-chain evidence is inconsistent")

    frontend_root = project_root / "frontend"
    if frontend_root.is_dir():
        inputs = _frontend_inputs(project_root)
        if (
            provenance.get("frontend_input_files") != len(inputs)
            or provenance["frontend_input_sha256"]
            != _named_digest(project_root, inputs)
            or provenance["lockfile_sha256"]
            != _digest_file(frontend_root / "package-lock.json")
            or provenance["brand_sha256"]
            != _digest_file(project_root / "branding/gigaloom-mark.svg")
        ):
            _fail("Cockpit injected assets are stale for the authored frontend")
        current_revision = _current_revision(project_root)
        if current_revision is not None and current_revision != source_revision:
            _fail("Cockpit injected assets belong to a different source revision")

    return {
        "asset_count": len(raw_assets),
        "frontend_input_sha256": provenance["frontend_input_sha256"],
        "licenses_sha256": provenance["licenses_sha256"],
        "output_sha256": output_digest,
        "sbom_sha256": provenance["sbom_sha256"],
        "source_dirty": provenance["source_dirty"],
        "source_revision": source_revision,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Verify assets for local, CI, release, and rollback automation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    parser.add_argument("--require-clean", action="store_true")
    arguments = parser.parse_args(argv)
    evidence = verify_asset_tree(arguments.project_root)
    if arguments.require_clean and evidence["source_dirty"]:
        _fail("Cockpit release provenance records dirty authored inputs")
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
