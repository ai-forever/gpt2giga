"""Access-control helper models for proxy settings."""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import NoDecode

from gpt2giga.core.config._settings.common import (
    GovernanceLimitScope,
    ProviderName,
    normalize_optional_string,
    normalize_optional_string_list,
    normalize_provider_allowlist,
)


class ScopedAPIKeySettings(BaseModel):
    """Optional API key with narrowed access scopes."""

    name: str | None = Field(
        default=None,
        description="Человеко-читаемое имя scoped API key для admin/runtime surfaces.",
    )
    key: str = Field(
        min_length=1,
        description="Значение scoped API key.",
        repr=False,
    )
    providers: Annotated[list[ProviderName], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist внешних provider-ов: openai, anthropic, gemini. "
            "Пусто = без ограничения по provider."
        ),
    )
    endpoints: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist normalized endpoint ids без /v1 или /v1beta "
            "(например chat/completions, responses, models/{model}:generateContent)."
        ),
    )
    models: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist model aliases/ids. Пусто = без ограничения по "
            "модели."
        ),
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        """Normalize blank names to ``None``."""
        return normalize_optional_string(value)

    @field_validator("providers", mode="before")
    @classmethod
    def normalize_providers(cls, value):
        """Normalize provider allowlists from ENV/CLI friendly forms."""
        return normalize_provider_allowlist(value)

    @field_validator("endpoints", "models", mode="before")
    @classmethod
    def normalize_optional_lists(cls, value):
        """Normalize endpoint/model allowlists from ENV/CLI friendly forms."""
        return normalize_optional_string_list(value)


class GovernanceLimitSettings(BaseModel):
    """Fixed-window governance rule for request rate and token quotas."""

    name: str | None = Field(
        default=None,
        description="Опциональное имя governance rule для admin/runtime surfaces.",
    )
    scope: GovernanceLimitScope = Field(
        description="Группа subject-ов, по которой считать окно: api_key или provider.",
    )
    providers: Annotated[list[ProviderName], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist внешних provider-ов. "
            "Пусто = rule применяется ко всем provider-ам."
        ),
    )
    endpoints: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description=(
            "Опциональный allowlist normalized endpoint ids без /v1 или /v1beta."
        ),
    )
    models: Annotated[list[str], NoDecode] | None = Field(
        default=None,
        description="Опциональный allowlist model aliases/ids.",
    )
    window_seconds: int = Field(
        default=60,
        ge=1,
        le=86_400,
        description="Размер fixed window в секундах.",
    )
    max_requests: int | None = Field(
        default=None,
        ge=1,
        description="Максимум HTTP requests в одном окне.",
    )
    max_total_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Максимум total_tokens в одном окне.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        """Normalize blank names to ``None``."""
        return normalize_optional_string(value)

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, value):
        """Normalize governance scope names from ENV/CLI friendly forms."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("providers", mode="before")
    @classmethod
    def normalize_providers(cls, value):
        """Normalize provider allowlists from ENV/CLI friendly forms."""
        return normalize_provider_allowlist(value)

    @field_validator("endpoints", "models", mode="before")
    @classmethod
    def normalize_optional_lists(cls, value):
        """Normalize endpoint/model allowlists from ENV/CLI friendly forms."""
        return normalize_optional_string_list(value)

    @model_validator(mode="after")
    def validate_thresholds(self):
        """Require at least one request- or token-based threshold."""
        if self.max_requests is None and self.max_total_tokens is None:
            raise ValueError(
                "governance limit must define max_requests or max_total_tokens"
            )
        return self
