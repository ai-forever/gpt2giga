"""Bounded startup loading for immutable provider-profile sets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from gpt2giga.providers.profiles.errors import ProviderProfileError
from gpt2giga.providers.profiles.models import (
    ProviderModelInventory,
    ProviderProfile,
    ProviderProfileConfig,
)


CONFIG_ENV_NAME = "GPT2GIGA_CONFIG"
MAX_PROFILE_CONFIG_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ProviderPolicyCatalog:
    """Reviewed policy identifiers supplied by the application owner."""

    network_policy_refs: frozenset[str]
    tls_policy_refs: frozenset[str]


@dataclass(frozen=True, repr=False)
class LoadedProviderProfileSet:
    """Validated process-lifetime config with privately held credentials."""

    config: ProviderProfileConfig
    _credentials: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "_credentials", MappingProxyType(dict(self._credentials))
        )

    def __repr__(self) -> str:
        return (
            "LoadedProviderProfileSet("
            f"schema_version={self.schema_version!r}, revision={self.revision!r}, "
            f"profiles={len(self.config.profiles)}, immutable=True)"
        )

    @property
    def schema_version(self) -> str:
        """Return the loaded profile schema revision."""
        return self.config.schema_version

    @property
    def revision(self) -> str:
        """Return the exact secret-free configuration revision."""
        return self.config.revision

    @property
    def immutable(self) -> bool:
        """Expose the process-lifetime immutability contract."""
        return True

    def credential_for(self, profile_id: str) -> str | None:
        """Return a credential only to exact adapter composition code."""
        profile = next(
            (
                profile
                for profile in self.config.profiles
                if profile.profile_id == profile_id
            ),
            None,
        )
        if profile is None:
            raise ProviderProfileError(
                "credential_unavailable",
                "Credential reference is unavailable for the selected profile.",
            )
        if profile.credential_env is None:
            return None
        try:
            return self._credentials[profile_id]
        except KeyError as exc:
            raise ProviderProfileError(
                "credential_unavailable",
                "Credential reference is unavailable for the selected profile.",
            ) from exc

    def redacted(self) -> dict[str, object]:
        """Return bounded startup evidence without credential names or values."""
        return {
            "schema_version": self.schema_version,
            "config_revision": self.revision,
            "immutable": True,
            "profile_count": len(self.config.profiles),
        }


def select_provider_config_path(
    cli_path: str | os.PathLike[str] | None,
    *,
    environ: Mapping[str, str],
) -> Path | None:
    """Apply the frozen CLI-over-environment config path contract."""
    env_path = environ.get(CONFIG_ENV_NAME)
    explicit = _normalized_path(cli_path) if cli_path is not None else None
    configured = _normalized_path(env_path) if env_path else None
    if explicit is not None and configured is not None and explicit != configured:
        raise ProviderProfileError(
            "invalid_profile_schema",
            "CLI and environment provider config paths disagree.",
        )
    return explicit or configured


def load_provider_profiles(
    path: str | os.PathLike[str],
    *,
    environ: Mapping[str, str],
    policies: ProviderPolicyCatalog,
) -> LoadedProviderProfileSet:
    """Load and fully preflight one authoritative provider config file."""
    payload = _read_profile_document(Path(path))
    try:
        config = ProviderProfileConfig.model_validate(payload)
    except ValidationError as exc:
        raise _validation_error(exc) from None

    credentials: dict[str, str] = {}
    for profile in config.profiles:
        _validate_destination(profile)
        _validate_policy_references(profile, policies)
        if profile.model_inventory is ProviderModelInventory.DYNAMIC or any(
            model.enabled for model in profile.models
        ):
            if profile.credential_env is not None:
                credential = environ.get(profile.credential_env)
                if not credential:
                    raise ProviderProfileError(
                        "credential_unavailable",
                        "Credential reference is unavailable for an enabled profile.",
                    )
                credentials[profile.profile_id] = credential
    return LoadedProviderProfileSet(config=config, _credentials=credentials)


def _read_profile_document(path: Path) -> Any:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ProviderProfileError(
            "invalid_profile_schema",
            "Provider profile config cannot be read.",
        ) from exc
    if size > MAX_PROFILE_CONFIG_BYTES:
        raise ProviderProfileError(
            "invalid_profile_schema",
            "Provider profile config exceeds the size limit.",
        )
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProviderProfileError(
            "invalid_profile_schema",
            "Provider profile config must be readable UTF-8.",
        ) from exc

    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(source, object_pairs_hook=_unique_json_object)
        if suffix in {".yaml", ".yml"}:
            return _safe_yaml_load(source)
    except (ValueError, TypeError) as exc:
        raise ProviderProfileError(
            "invalid_profile_schema",
            "Provider profile config is malformed.",
        ) from exc
    raise ProviderProfileError(
        "invalid_profile_schema",
        "Provider profile config must use a .json, .yaml, or .yml suffix.",
    )


def _safe_yaml_load(source: str) -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ProviderProfileError(
            "invalid_profile_schema",
            "YAML profile support is unavailable in this installation.",
        ) from exc

    class UniqueKeySafeLoader(yaml.SafeLoader):
        pass

    def construct_unique_mapping(loader: Any, node: Any, deep: bool = False) -> Any:
        loader.flatten_mapping(node)
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError("duplicate YAML mapping key")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueKeySafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_unique_mapping,
    )
    try:
        return yaml.load(source, Loader=UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise ValueError("malformed safe YAML") from exc


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON mapping key")
        result[key] = value
    return result


def _validate_destination(profile: ProviderProfile) -> None:
    parsed = urlsplit(profile.base_url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if "%" in host:
        raise ProviderProfileError(
            "invalid_destination",
            "Provider profile destination is invalid.",
        )
    is_loopback = host == "localhost"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        is_loopback = address.is_loopback
        if not address.is_global and not address.is_loopback:
            raise ProviderProfileError(
                "invalid_destination",
                "Provider profile destination is not public.",
            )

    if profile.allow_loopback:
        if parsed.scheme != "http" or not is_loopback:
            raise ProviderProfileError(
                "invalid_destination",
                "Loopback development profiles require an HTTP loopback destination.",
            )
        return
    if parsed.scheme != "https" or is_loopback:
        raise ProviderProfileError(
            "invalid_destination",
            "Provider profile destination must use public HTTPS.",
        )


def _validate_policy_references(
    profile: ProviderProfile,
    policies: ProviderPolicyCatalog,
) -> None:
    if (
        profile.network_policy_ref not in policies.network_policy_refs
        or profile.tls_policy_ref not in policies.tls_policy_refs
    ):
        raise ProviderProfileError(
            "invalid_policy_reference",
            "Provider profile references an unknown reviewed policy.",
        )


def _validation_error(exc: ValidationError) -> ProviderProfileError:
    messages = " ".join(str(error.get("msg", "")) for error in exc.errors())
    if "duplicate profile ids" in messages:
        code = "duplicate_profile_id"
        message = "Provider profile ids must be globally unique."
    elif "duplicate model aliases" in messages:
        code = "duplicate_model_alias"
        message = "Public model aliases must be globally unique."
    else:
        code = "invalid_profile_schema"
        message = "Provider profile config does not match the required schema."
    return ProviderProfileError(code, message)


def _normalized_path(value: str | os.PathLike[str]) -> Path:
    raw = os.fspath(value)
    if not raw or raw != raw.strip():
        raise ProviderProfileError(
            "invalid_profile_schema",
            "Provider config path is invalid.",
        )
    return Path(raw).expanduser().resolve(strict=False)
