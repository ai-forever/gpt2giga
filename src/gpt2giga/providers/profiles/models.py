"""Immutable, secret-free configuration models for reviewed providers."""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROVIDER_PROFILE_SCHEMA_VERSION = "gpt2giga.provider-profiles.v1"
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_IDENTIFIER = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,254}[a-z0-9])?$")


class ProviderKind(str, Enum):
    """Provider implementations admitted by the reviewed bridge registry."""

    GIGACHAT = "gigachat"
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class ProviderSupportStatus(str, Enum):
    """Machine-readable maturity of one public alias route."""

    STABLE = "stable"
    TECHNICAL_PREVIEW = "technical_preview"
    BLOCKED = "blocked"


PROVIDER_KINDS = frozenset(kind.value for kind in ProviderKind)


class _ProfileModel(BaseModel):
    """Strict immutable base for process-lifetime profile configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderModelAlias(_ProfileModel):
    """Bind one public model name to an exact upstream model and capability."""

    public_alias: str = Field(min_length=1, max_length=256)
    upstream_model: str = Field(min_length=1, max_length=256)
    capability_profile: str = Field(min_length=1, max_length=256)
    support_status: ProviderSupportStatus
    enabled: bool = True
    deprecated: bool = False

    @field_validator("public_alias", "upstream_model", "capability_profile")
    @classmethod
    def _normalize_names(cls, value: str) -> str:
        return _normalized_name(value)


class ProviderProfile(_ProfileModel):
    """Describe one reviewed destination without resolving its credential."""

    profile_id: str = Field(min_length=1, max_length=256)
    provider_kind: ProviderKind
    base_url: str
    credential_env: str = Field(min_length=1, max_length=256)
    network_policy_ref: str = Field(min_length=1, max_length=256)
    tls_policy_ref: str = Field(min_length=1, max_length=256)
    allow_loopback: bool = False
    models: tuple[ProviderModelAlias, ...] = ()

    @field_validator("profile_id", "network_policy_ref", "tls_policy_ref")
    @classmethod
    def _normalize_identifiers(cls, value: str) -> str:
        normalized = _normalized_name(value)
        if not _IDENTIFIER.fullmatch(normalized):
            raise ValueError("must be a lowercase reviewed identifier")
        return normalized

    @field_validator("credential_env")
    @classmethod
    def _validate_credential_env(cls, value: str) -> str:
        if value != value.strip() or not _ENV_NAME.fullmatch(value):
            raise ValueError("must be an uppercase environment variable name")
        return value

    @field_validator("base_url")
    @classmethod
    def _canonicalize_base_url(cls, value: str) -> str:
        return canonical_base_url(value)

    @model_validator(mode="after")
    def _validate_model_aliases(self) -> ProviderProfile:
        if not self.models and self.provider_kind is not ProviderKind.GIGACHAT:
            raise ValueError("only GigaChat profiles may use dynamic model inventory")
        aliases = [model.public_alias for model in self.models]
        if len(aliases) != len(set(aliases)):
            raise ValueError("profile contains duplicate public model aliases")
        return self

    @property
    def revision(self) -> str:
        """Return the deterministic digest of this secret-free profile."""
        return canonical_revision(self)


class ProviderProfileConfig(_ProfileModel):
    """Versioned, immutable provider configuration loaded once at startup."""

    schema_version: str = PROVIDER_PROFILE_SCHEMA_VERSION
    profiles: tuple[ProviderProfile, ...] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != PROVIDER_PROFILE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {PROVIDER_PROFILE_SCHEMA_VERSION!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_global_identity(self) -> ProviderProfileConfig:
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("provider configuration contains duplicate profile ids")

        aliases = [
            model.public_alias for profile in self.profiles for model in profile.models
        ]
        if len(aliases) != len(set(aliases)):
            raise ValueError("provider configuration contains duplicate model aliases")
        return self

    @property
    def revision(self) -> str:
        """Return the deterministic digest of the complete loaded config."""
        return canonical_revision(self)

    def canonical_json(self) -> str:
        """Serialize as canonical UTF-8 JSON while preserving array order."""
        return canonical_json(self)


def canonical_json(model: BaseModel) -> str:
    """Serialize a strict profile model using the ADR canonical JSON rules."""
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_revision(model: BaseModel) -> str:
    """Hash a canonical secret-free profile model."""
    payload = canonical_json(model).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_base_url(value: str) -> str:
    """Validate and canonicalize a provider base URL without network access."""
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("base_url must not contain surrounding whitespace")
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("base_url scheme must be http or https")
    if not parsed.hostname:
        raise ValueError("base_url must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not contain userinfo")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain query or fragment")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("base_url contains an invalid port") from exc

    host = parsed.hostname.encode("idna").decode("ascii").lower()
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    )
    netloc = (
        rendered_host if port is None or default_port else f"{rendered_host}:{port}"
    )
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _normalized_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("must be a string")
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized or any(character.isspace() for character in normalized):
        raise ValueError("must be a non-empty name without whitespace")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("must not contain control or formatting characters")
    return normalized
