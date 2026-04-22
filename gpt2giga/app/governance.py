"""Fixed-window governance helpers for request rate limits and token quotas."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from time import time
from typing import Any

from gpt2giga.app.dependencies import get_config_from_state, get_runtime_stores
from gpt2giga.core.config.settings import GovernanceLimitSettings


@dataclass(frozen=True, slots=True)
class GovernanceContext:
    """Normalized request/event context used for governance matching."""

    provider: str | None
    endpoint: str | None
    model: str | None
    api_key_name: str | None


@dataclass(frozen=True, slots=True)
class MatchedGovernanceLimit:
    """Concrete governance rule matched against a request/event context."""

    index: int
    rule: GovernanceLimitSettings
    subject: str

    @property
    def key_prefix(self) -> str:
        """Return the stable key prefix for the matched rule subject."""
        return f"governance:{self.index}:{self.subject}:"

    def key_for_window(self, window_started_at: int) -> str:
        """Return the storage key for a fixed-window counter bucket."""
        return f"{self.key_prefix}{window_started_at}"


def list_matched_governance_limits(
    state: Any,
    context: GovernanceContext,
) -> list[MatchedGovernanceLimit]:
    """Return governance rules applicable to the current request/event context."""
    config = get_config_from_state(state)
    proxy = config.proxy_settings
    matched: list[MatchedGovernanceLimit] = []
    for index, raw_rule in enumerate(getattr(proxy, "governance_limits", [])):
        rule = (
            raw_rule
            if isinstance(raw_rule, GovernanceLimitSettings)
            else GovernanceLimitSettings.model_validate(raw_rule)
        )
        if rule.providers is not None:
            if context.provider is None or context.provider not in rule.providers:
                continue
        if rule.endpoints is not None:
            if context.endpoint is None or context.endpoint not in rule.endpoints:
                continue
        if rule.models is not None:
            if context.model is None or context.model not in rule.models:
                continue

        subject = _resolve_governance_subject(rule, context)
        if subject is None:
            continue
        matched.append(MatchedGovernanceLimit(index=index, rule=rule, subject=subject))
    return matched


def reserve_governance_request_window(
    state: Any,
    context: GovernanceContext,
    *,
    now: int | None = None,
) -> list[dict[str, object]]:
    """Reserve request-count slots for matching governance rules."""
    current_time = int(now if now is not None else time())
    store = get_runtime_stores(state).governance_counters
    reservations: list[
        tuple[MatchedGovernanceLimit, str, dict[str, object], int, int]
    ] = []
    exceeded: list[dict[str, object]] = []

    for matched in list_matched_governance_limits(state, context):
        _prune_expired_governance_counters(
            store,
            key_prefix=matched.key_prefix,
            now=current_time,
        )
        window_started_at = current_time - (current_time % matched.rule.window_seconds)
        window_ends_at = window_started_at + matched.rule.window_seconds
        key = matched.key_for_window(window_started_at)
        counter = _coerce_counter_record(store.get(key))

        if (
            matched.rule.max_requests is not None
            and _coerce_int_value(counter.get("request_count"))
            >= matched.rule.max_requests
        ):
            exceeded.append(
                _build_limit_status(
                    matched,
                    dimension="requests",
                    window_ends_at=window_ends_at,
                    current_value=_coerce_int_value(counter.get("request_count")),
                    limit_value=matched.rule.max_requests,
                    current_time=current_time,
                )
            )
            continue

        if (
            matched.rule.max_total_tokens is not None
            and _coerce_int_value(counter.get("total_tokens"))
            >= matched.rule.max_total_tokens
        ):
            exceeded.append(
                _build_limit_status(
                    matched,
                    dimension="total_tokens",
                    window_ends_at=window_ends_at,
                    current_value=_coerce_int_value(counter.get("total_tokens")),
                    limit_value=matched.rule.max_total_tokens,
                    current_time=current_time,
                )
            )
            continue

        reservations.append((matched, key, counter, window_started_at, window_ends_at))

    if exceeded:
        return exceeded

    for matched, key, counter, window_started_at, window_ends_at in reservations:
        if matched.rule.max_requests is None:
            continue
        counter["request_count"] = _coerce_int_value(counter.get("request_count")) + 1
        counter["window_started_at"] = window_started_at
        counter["window_ends_at"] = window_ends_at
        counter["scope"] = matched.rule.scope
        counter["subject"] = matched.subject
        counter["rule_name"] = matched.rule.name or f"governance-{matched.index}"
        store[key] = counter

    return []


def record_governance_event(state: Any, event: Mapping[str, object]) -> None:
    """Update token-quota counters from a finalized request audit event."""
    provider = event.get("provider")
    if provider in (None, "admin", "system"):
        return

    context = GovernanceContext(
        provider=str(provider),
        endpoint=_normalize_event_endpoint(event.get("endpoint")),
        model=_coerce_optional_text(event.get("model")),
        api_key_name=_coerce_optional_text(event.get("api_key_name")),
    )
    token_usage = event.get("token_usage")
    token_usage_mapping = token_usage if isinstance(token_usage, Mapping) else {}
    total_tokens = _coerce_int_value(token_usage_mapping.get("total_tokens"))
    if total_tokens <= 0:
        return

    current_time = _coerce_event_timestamp(event) or int(time())
    store = get_runtime_stores(state).governance_counters
    for matched in list_matched_governance_limits(state, context):
        if matched.rule.max_total_tokens is None:
            continue
        _prune_expired_governance_counters(
            store,
            key_prefix=matched.key_prefix,
            now=current_time,
        )
        window_started_at = current_time - (current_time % matched.rule.window_seconds)
        window_ends_at = window_started_at + matched.rule.window_seconds
        key = matched.key_for_window(window_started_at)
        counter = _coerce_counter_record(store.get(key))
        counter["window_started_at"] = window_started_at
        counter["window_ends_at"] = window_ends_at
        counter["scope"] = matched.rule.scope
        counter["subject"] = matched.subject
        counter["rule_name"] = matched.rule.name or f"governance-{matched.index}"
        counter["total_tokens"] = (
            _coerce_int_value(counter.get("total_tokens")) + total_tokens
        )
        store[key] = counter


def _resolve_governance_subject(
    rule: GovernanceLimitSettings,
    context: GovernanceContext,
) -> str | None:
    if rule.scope == "provider":
        return context.provider
    if rule.scope == "api_key":
        return context.api_key_name
    return None


def _coerce_counter_record(value: object) -> dict[str, object]:
    """Return a mutable governance counter record."""
    if isinstance(value, Mapping):
        record = dict(value)
    else:
        record = {}
    record.setdefault("request_count", 0)
    record.setdefault("total_tokens", 0)
    return record


def _coerce_int_value(value: object, default: int = 0) -> int:
    """Safely coerce loosely-typed values into integers."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return default
        try:
            return int(normalized)
        except ValueError:
            return default
    return default


def _prune_expired_governance_counters(
    store: MutableMapping[str, Any],
    *,
    key_prefix: str,
    now: int,
) -> None:
    """Delete expired counters for the matched rule subject."""
    expired_keys: list[str] = []
    for key in list(store):
        if not isinstance(key, str) or not key.startswith(key_prefix):
            continue
        counter = store.get(key)
        if not isinstance(counter, Mapping):
            expired_keys.append(key)
            continue
        if _coerce_int_value(counter.get("window_ends_at")) <= now:
            expired_keys.append(key)
    for key in expired_keys:
        del store[key]


def _build_limit_status(
    matched: MatchedGovernanceLimit,
    *,
    dimension: str,
    window_ends_at: int,
    current_value: int,
    limit_value: int,
    current_time: int,
) -> dict[str, object]:
    """Build a normalized over-limit status payload."""
    retry_after_seconds = max(1, window_ends_at - current_time)
    return {
        "rule_name": matched.rule.name or f"governance-{matched.index}",
        "scope": matched.rule.scope,
        "subject": matched.subject,
        "dimension": dimension,
        "current_value": current_value,
        "limit_value": limit_value,
        "retry_after_seconds": retry_after_seconds,
    }


def _coerce_optional_text(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _normalize_event_endpoint(value: object) -> str | None:
    endpoint = _coerce_optional_text(value)
    if endpoint is None:
        return None
    normalized = endpoint.strip("/")
    for prefix in ("v1/", "v1beta/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized or None


def _coerce_event_timestamp(event: Mapping[str, object]) -> int | None:
    created_at = event.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    normalized = created_at.strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        return None
