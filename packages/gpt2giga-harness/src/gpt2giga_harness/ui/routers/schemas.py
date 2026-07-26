"""Typed response contracts for routable Harness UI areas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UIHealthResponse(BaseModel):
    """Minimal public liveness response."""

    status: str = "ok"


class BrowserSessionResponse(BaseModel):
    """Result of exchanging a bootstrap token for a browser cookie."""

    authenticated: bool = True


class BrowserAccessStatusResponse(BaseModel):
    """Content-free state of the current browser access boundary."""

    local: bool
    authenticated: bool
    claimable: bool = False
    expires_at: str | None = None
    idle_expires_at: str | None = None
    actor_id: str | None = None
    role: str | None = None
    session_id: str | None = None
    authentication_time: str | None = None
    recovery: str


class RunBundleResponse(BaseModel):
    """Persisted session bundle selected by a stable run deep link."""

    selected_run_id: str
    session: dict[str, Any]
    messages: list[dict[str, Any]] = Field(default_factory=list)
    runs: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    raw_requests: list[dict[str, Any]] = Field(default_factory=list)
    raw_responses: list[dict[str, Any]] = Field(default_factory=list)
    native_links: list[dict[str, Any]] = Field(default_factory=list)
    storage: dict[str, Any] = Field(default_factory=dict)
