"""Stable, redacted errors for provider-profile admission."""

from __future__ import annotations

from typing import Literal


ProviderProfileErrorCode = Literal[
    "credential_unavailable",
    "duplicate_model_alias",
    "duplicate_profile_id",
    "invalid_destination",
    "invalid_policy_reference",
    "invalid_profile_schema",
]


class ProviderProfileError(ValueError):
    """Bounded configuration failure that never embeds input or credentials."""

    def __init__(self, code: ProviderProfileErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"ProviderProfileError(code={self.code!r}, message={self.message!r})"
