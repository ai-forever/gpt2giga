"""Immutable, secret-free configuration models for reviewed providers."""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from gpt2giga.protocols.normalized.loss_matrix import BridgeFeature


PROVIDER_PROFILE_SCHEMA_V1 = "gpt2giga.provider-profiles.v1"
PROVIDER_PROFILE_SCHEMA_V2 = "gpt2giga.provider-profiles.v2"
PROVIDER_PROFILE_SCHEMA_V3 = "gpt2giga.provider-profiles.v3"
PROVIDER_PROFILE_SCHEMA_VERSION = PROVIDER_PROFILE_SCHEMA_V3
SUPPORTED_PROVIDER_PROFILE_SCHEMA_VERSIONS = frozenset(
    {
        PROVIDER_PROFILE_SCHEMA_V1,
        PROVIDER_PROFILE_SCHEMA_V2,
        PROVIDER_PROFILE_SCHEMA_V3,
    }
)
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


class ProviderModelInventory(str, Enum):
    """Declare whether one profile owns static aliases or provider discovery."""

    STATIC = "static"
    DYNAMIC = "dynamic"


PROVIDER_KINDS = frozenset(kind.value for kind in ProviderKind)


class _ProfileModel(BaseModel):
    """Strict immutable base for process-lifetime profile configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderTokenLimits(_ProfileModel):
    """Declare reviewed token limits for one exact upstream model."""

    context_window: int = Field(gt=0)
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_bounds(self) -> ProviderTokenLimits:
        for field_name in ("max_input_tokens", "max_output_tokens"):
            value = getattr(self, field_name)
            if value is not None and value > self.context_window:
                raise ValueError(f"{field_name} cannot exceed context_window")
        return self


class ProviderModelCapabilities(_ProfileModel):
    """Bind reviewed normalized features and limits to one model alias."""

    features: frozenset[BridgeFeature] = Field(min_length=1)
    limits: ProviderTokenLimits

    @field_serializer("features")
    def _serialize_features(
        self,
        value: frozenset[BridgeFeature],
    ) -> list[str]:
        return sorted(feature.value for feature in value)


class ProviderModelAlias(_ProfileModel):
    """Bind one public model name to an exact upstream model and capability."""

    public_alias: str = Field(min_length=1, max_length=256)
    upstream_model: str = Field(min_length=1, max_length=256)
    capability_profile: str = Field(min_length=1, max_length=256)
    capabilities: ProviderModelCapabilities | None = None
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
    credential_env: str | None = Field(default=None, min_length=1, max_length=256)
    network_policy_ref: str = Field(min_length=1, max_length=256)
    tls_policy_ref: str = Field(min_length=1, max_length=256)
    allow_loopback: bool = False
    model_inventory: ProviderModelInventory | None = None
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
    def _validate_credential_env(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or not _ENV_NAME.fullmatch(value):
            raise ValueError("must be an uppercase environment variable name")
        return value

    @field_validator("base_url")
    @classmethod
    def _canonicalize_base_url(cls, value: str) -> str:
        return canonical_base_url(value)

    @model_validator(mode="after")
    def _validate_model_aliases(self) -> ProviderProfile:
        inventory = self.model_inventory or ProviderModelInventory.STATIC
        if (
            inventory is ProviderModelInventory.DYNAMIC
            and self.provider_kind is not ProviderKind.GIGACHAT
        ):
            raise ValueError("only GigaChat profiles may use dynamic model inventory")
        if inventory is ProviderModelInventory.STATIC and not self.models:
            raise ValueError("static model inventory requires at least one model alias")
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

    # Keep omitted versions on the last implicit schema for compatibility.
    # New executable OpenAI-compatible profiles must opt into v3 explicitly.
    schema_version: str = PROVIDER_PROFILE_SCHEMA_V2
    profiles: tuple[ProviderProfile, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _validate_versioned_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        schema_version = value.get("schema_version", PROVIDER_PROFILE_SCHEMA_V2)
        profiles = value.get("profiles")
        if isinstance(profiles, (list, tuple)):
            if schema_version == PROVIDER_PROFILE_SCHEMA_V1 and any(
                isinstance(profile, dict) and "model_inventory" in profile
                for profile in profiles
            ):
                raise ValueError("model_inventory requires provider-profiles.v2")
            if schema_version in {
                PROVIDER_PROFILE_SCHEMA_V1,
                PROVIDER_PROFILE_SCHEMA_V2,
            } and any(
                isinstance(model, dict) and "capabilities" in model
                for profile in profiles
                if isinstance(profile, dict)
                for model in profile.get("models", ())
            ):
                raise ValueError("model capabilities require provider-profiles.v3")
        return value

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value not in SUPPORTED_PROVIDER_PROFILE_SCHEMA_VERSIONS:
            raise ValueError(
                "schema_version must be a supported provider-profile revision"
            )
        return value

    @model_validator(mode="after")
    def _validate_global_identity(self) -> ProviderProfileConfig:
        if self.schema_version == PROVIDER_PROFILE_SCHEMA_V1 and any(
            profile.model_inventory is not None for profile in self.profiles
        ):
            raise ValueError("model_inventory requires provider-profiles.v2")
        if self.schema_version in {
            PROVIDER_PROFILE_SCHEMA_V1,
            PROVIDER_PROFILE_SCHEMA_V2,
        }:
            if any(
                model.capabilities is not None
                for profile in self.profiles
                for model in profile.models
            ):
                raise ValueError("model capabilities require provider-profiles.v3")
            if any(profile.credential_env is None for profile in self.profiles):
                raise ValueError(
                    "credential_env is required before provider-profiles.v3"
                )
        if self.schema_version == PROVIDER_PROFILE_SCHEMA_V3:
            for profile in self.profiles:
                if profile.provider_kind is not ProviderKind.OPENAI_COMPATIBLE:
                    continue
                for model in profile.models:
                    if model.enabled and model.capabilities is None:
                        raise ValueError(
                            "enabled OpenAI-compatible aliases require reviewed "
                            "capabilities"
                        )
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("provider configuration contains duplicate profile ids")

        aliases = [
            model.public_alias for profile in self.profiles for model in profile.models
        ]
        if len(aliases) != len(set(aliases)):
            raise ValueError("provider configuration contains duplicate model aliases")
        dynamic_profiles = [
            profile
            for profile in self.profiles
            if profile.model_inventory is ProviderModelInventory.DYNAMIC
        ]
        if len(dynamic_profiles) > 1:
            raise ValueError(
                "provider configuration contains multiple dynamic model inventories"
            )
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
        model.model_dump(mode="json", exclude_none=True),
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
