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
    "unknown_model_alias",
]


class ProviderProfileError(ValueError):
    """Bounded configuration failure that never embeds input or credentials."""

    def __init__(self, code: ProviderProfileErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"ProviderProfileError(code={self.code!r}, message={self.message!r})"


class ProviderAliasError(ProviderProfileError):
    """Stable lookup failure without echoing the client-supplied alias."""

    def __init__(self, reason_id: str) -> None:
        self.reason_id = reason_id
        super().__init__(
            "unknown_model_alias",
            "The requested public model alias is not available.",
        )

    def __repr__(self) -> str:
        return (
            "ProviderAliasError("
            f"code={self.code!r}, reason_id={self.reason_id!r}, "
            f"message={self.message!r})"
        )
