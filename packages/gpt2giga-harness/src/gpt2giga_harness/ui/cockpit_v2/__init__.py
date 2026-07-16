"""Validated access to the packaged Cockpit V2 browser assets."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib import resources
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping


ASSET_FORMAT_VERSION = "gpt2giga-cockpit-v2-assets-v1"
ASSET_PACKAGE = "gpt2giga_harness.ui.cockpit_v2"
_DIGEST = re.compile(r"[0-9a-f]{64}")


class CockpitV2UnavailableError(RuntimeError):
    """Report missing, malformed, or integrity-invalid packaged V2 assets."""


class CockpitV2AssetNotFoundError(FileNotFoundError):
    """Report an asset path that is not declared by the packaged manifest."""


@dataclass(frozen=True)
class CockpitV2Asset:
    """One integrity-bound identity asset and its precompressed variants."""

    name: str
    media_type: str
    byte_count: int
    sha256: str
    gzip_name: str | None = None
    gzip_byte_count: int | None = None
    gzip_sha256: str | None = None
    brotli_name: str | None = None
    brotli_byte_count: int | None = None
    brotli_sha256: str | None = None


@dataclass(frozen=True)
class CockpitV2Manifest:
    """Validated deterministic asset graph embedded in the Harness wheel."""

    entry: str
    initial: tuple[str, ...]
    assets: Mapping[str, CockpitV2Asset]


def _asset_root() -> Any:
    return resources.files(ASSET_PACKAGE).joinpath("assets")


def _safe_asset_name(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CockpitV2UnavailableError("Cockpit V2 manifest contains an invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise CockpitV2UnavailableError("Cockpit V2 manifest contains an invalid path")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CockpitV2UnavailableError(
            f"Cockpit V2 manifest contains an invalid {field}"
        )
    return value


def _optional_variant(
    record: Mapping[str, object],
    *,
    name_field: str,
    bytes_field: str,
    digest_field: str,
) -> tuple[str | None, int | None, str | None]:
    variant_name = record.get(name_field)
    variant_bytes = record.get(bytes_field)
    variant_digest = record.get(digest_field)
    if variant_name is None and variant_bytes is None and variant_digest is None:
        return None, None, None
    if variant_name is None or variant_bytes is None or variant_digest is None:
        raise CockpitV2UnavailableError(
            "Cockpit V2 manifest contains an incomplete compressed variant"
        )
    if not isinstance(variant_digest, str) or _DIGEST.fullmatch(variant_digest) is None:
        raise CockpitV2UnavailableError(
            "Cockpit V2 manifest contains an invalid compressed digest"
        )
    return (
        _safe_asset_name(variant_name),
        _positive_int(variant_bytes, field=bytes_field),
        variant_digest,
    )


@lru_cache(maxsize=1)
def load_cockpit_v2_manifest() -> CockpitV2Manifest:
    """Load and validate the deterministic packaged asset manifest."""
    try:
        payload = json.loads(_asset_root().joinpath("manifest.json").read_text("utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError) as exc:
        raise CockpitV2UnavailableError(
            "Cockpit V2 packaged asset manifest is unavailable"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CockpitV2UnavailableError("Cockpit V2 manifest must be an object")
    if payload.get("format_version") != ASSET_FORMAT_VERSION:
        raise CockpitV2UnavailableError("Cockpit V2 manifest version is unsupported")

    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, Mapping) or not raw_assets:
        raise CockpitV2UnavailableError("Cockpit V2 manifest has no assets")
    assets: dict[str, CockpitV2Asset] = {}
    for raw_name, raw_record in raw_assets.items():
        name = _safe_asset_name(raw_name)
        if not isinstance(raw_record, Mapping):
            raise CockpitV2UnavailableError(
                "Cockpit V2 manifest contains an invalid asset record"
            )
        media_type = raw_record.get("media_type")
        digest = raw_record.get("sha256")
        if not isinstance(media_type, str) or not media_type:
            raise CockpitV2UnavailableError(
                "Cockpit V2 manifest contains an invalid media type"
            )
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise CockpitV2UnavailableError(
                "Cockpit V2 manifest contains an invalid digest"
            )
        gzip_name, gzip_bytes, gzip_sha256 = _optional_variant(
            raw_record,
            name_field="gzip",
            bytes_field="gzip_bytes",
            digest_field="gzip_sha256",
        )
        brotli_name, brotli_bytes, brotli_sha256 = _optional_variant(
            raw_record,
            name_field="brotli",
            bytes_field="brotli_bytes",
            digest_field="brotli_sha256",
        )
        if gzip_name is not None and gzip_name != f"{name}.gz":
            raise CockpitV2UnavailableError("Cockpit V2 gzip binding is invalid")
        if brotli_name is not None and brotli_name != f"{name}.br":
            raise CockpitV2UnavailableError("Cockpit V2 Brotli binding is invalid")
        assets[name] = CockpitV2Asset(
            name=name,
            media_type=media_type,
            byte_count=_positive_int(raw_record.get("bytes"), field="bytes"),
            sha256=digest,
            gzip_name=gzip_name,
            gzip_byte_count=gzip_bytes,
            gzip_sha256=gzip_sha256,
            brotli_name=brotli_name,
            brotli_byte_count=brotli_bytes,
            brotli_sha256=brotli_sha256,
        )

    entry = _safe_asset_name(payload.get("entry"))
    raw_initial = payload.get("initial")
    if entry not in assets or not isinstance(raw_initial, list):
        raise CockpitV2UnavailableError("Cockpit V2 entry graph is invalid")
    initial = tuple(_safe_asset_name(name) for name in raw_initial)
    if (
        not initial
        or len(set(initial)) != len(initial)
        or any(name not in assets for name in initial)
    ):
        raise CockpitV2UnavailableError("Cockpit V2 initial graph is invalid")
    return CockpitV2Manifest(entry=entry, initial=initial, assets=assets)


@lru_cache(maxsize=128)
def _read_packaged_file(name: str) -> bytes:
    try:
        return _asset_root().joinpath(name).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise CockpitV2UnavailableError(
            "Cockpit V2 packaged asset is unavailable"
        ) from exc


def _verified_identity(asset: CockpitV2Asset) -> bytes:
    content = _read_packaged_file(asset.name)
    if (
        len(content) != asset.byte_count
        or hashlib.sha256(content).hexdigest() != asset.sha256
    ):
        raise CockpitV2UnavailableError(
            "Cockpit V2 packaged asset failed integrity validation"
        )
    return content


def load_cockpit_v2_shell() -> str:
    """Return the integrity-verified UTF-8 V2 shell document."""
    manifest = load_cockpit_v2_manifest()
    asset = manifest.assets[manifest.entry]
    try:
        return _verified_identity(asset).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CockpitV2UnavailableError("Cockpit V2 shell is not valid UTF-8") from exc


def load_cockpit_v2_asset(
    name: str,
    *,
    encoding: str = "identity",
) -> tuple[bytes, CockpitV2Asset]:
    """Return one declared asset variant without accepting arbitrary paths."""
    manifest = load_cockpit_v2_manifest()
    asset = manifest.assets.get(name)
    if asset is None or asset.name == manifest.entry:
        raise CockpitV2AssetNotFoundError(name)
    if encoding == "identity":
        return _verified_identity(asset), asset
    if encoding == "br" and asset.brotli_name is None:
        return _verified_identity(asset), asset
    if encoding == "gzip" and asset.gzip_name is None:
        return _verified_identity(asset), asset
    if encoding == "br":
        content = _read_packaged_file(asset.brotli_name)
        expected = asset.brotli_byte_count
        expected_digest = asset.brotli_sha256
    elif encoding == "gzip":
        content = _read_packaged_file(asset.gzip_name)
        expected = asset.gzip_byte_count
        expected_digest = asset.gzip_sha256
    else:
        raise CockpitV2AssetNotFoundError(name)
    if (
        expected is None
        or expected_digest is None
        or len(content) != expected
        or hashlib.sha256(content).hexdigest() != expected_digest
    ):
        raise CockpitV2UnavailableError(
            "Cockpit V2 compressed asset failed integrity validation"
        )
    return content, asset
