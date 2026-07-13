"""Deterministic harness recommendations for the Project Cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.native.models import HarnessInvocationMode
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.types import Availability, AvailabilityStatus, HarnessSpec


PROMPT_EDIT_MARKERS = (
    "fix",
    "implement",
    "modify",
    "patch",
    "refactor",
    "rename",
    "update",
    "write tests",
    "исправ",
    "почини",
    "поменяй",
    "реализ",
    "рефактор",
    "тест",
)
PROMPT_CODE_MARKERS = (
    "branch",
    "bug",
    "code",
    "diff",
    "module",
    "repo",
    "src/",
    "stack trace",
    "test",
    "workspace",
    "ветк",
    "код",
    "модул",
    "проект",
    "репозит",
    "стек",
    "файл",
)
PROMPT_IMAGE_MARKERS = (
    "diagram",
    "image",
    "photo",
    "picture",
    "screenshot",
    "screen shot",
    "картин",
    "изображ",
    "скрин",
    "фото",
)
PROMPT_REVIEW_MARKERS = (
    "analyze",
    "diagnose",
    "explain",
    "inspect",
    "review",
    "summarize",
    "анализ",
    "объясн",
    "проверь",
    "ревью",
)
HARNESS_TIE_BREAK = {
    "codex-cli": 50,
    "direct-chat": 40,
    "claude-code": 30,
    "gemini-cli": 20,
    "echo": 10,
}


@dataclass(frozen=True)
class HarnessRouteRecommendation:
    """One deterministic recommendation for a harness run."""

    harness_id: str
    mode: str
    invocation_mode: HarnessInvocationMode
    confidence: float
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RouteFeatures:
    prompt: str
    mode: str
    workspace_present: bool
    selected_file_count: int
    attachment_kinds: tuple[str, ...]
    has_image_context: bool
    has_code_context: bool
    edit_intent: bool
    review_intent: bool


@dataclass(frozen=True)
class _Candidate:
    spec: HarnessSpec
    availability: Availability
    score: float
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def recommend_harness_route(
    registry: HarnessRegistry,
    *,
    prompt: str = "",
    mode: str | None = None,
    workspace: str | None = None,
    attachments: Iterable[Mapping[str, Any]] = (),
    selected_files: Iterable[str] = (),
) -> HarnessRouteRecommendation:
    """Recommend one harness without calling an LLM or external service."""
    features = _features(
        prompt=prompt,
        mode=mode,
        workspace=workspace,
        attachments=tuple(attachments),
        selected_files=tuple(selected_files),
    )
    candidates = [_score_candidate(harness, features) for harness in registry.list()]
    if not candidates:
        raise ValueError("No harnesses are registered")
    selectable_candidates = [
        candidate
        for candidate in candidates
        if candidate.availability.status == AvailabilityStatus.AVAILABLE
    ] or candidates
    best = max(
        selectable_candidates,
        key=lambda candidate: (
            candidate.score,
            HARNESS_TIE_BREAK.get(candidate.spec.id, 0),
            candidate.spec.id,
        ),
    )
    confidence = _confidence(best)
    warnings = _global_warnings(features, candidates, best)
    return HarnessRouteRecommendation(
        harness_id=best.spec.id,
        mode=features.mode,
        invocation_mode=HarnessInvocationMode.HEADLESS,
        confidence=confidence,
        reasons=best.reasons,
        warnings=(*warnings, *best.warnings),
    )


def route_recommendation_to_dict(
    recommendation: HarnessRouteRecommendation,
) -> dict[str, Any]:
    """Serialize a route recommendation for API/UI responses."""
    return {
        "harness_id": recommendation.harness_id,
        "mode": recommendation.mode,
        "invocation_mode": recommendation.invocation_mode.value,
        "confidence": recommendation.confidence,
        "reasons": list(recommendation.reasons),
        "warnings": list(recommendation.warnings),
    }


def _features(
    *,
    prompt: str,
    mode: str | None,
    workspace: str | None,
    attachments: tuple[Mapping[str, Any], ...],
    selected_files: tuple[str, ...],
) -> _RouteFeatures:
    prompt_text = str(prompt or "")
    prompt_lower = prompt_text.lower()
    selected_file_count = len(
        [item for item in selected_files if str(item or "").strip()]
    )
    attachment_kinds = tuple(_attachment_kind(attachment) for attachment in attachments)
    workspace_refs = [
        str(attachment.get("workspace_path") or "").strip()
        for attachment in attachments
        if isinstance(attachment, Mapping)
    ]
    selected_file_count += len([item for item in workspace_refs if item])
    has_image_context = "image" in attachment_kinds or _contains_any(
        prompt_lower, PROMPT_IMAGE_MARKERS
    )
    edit_intent = _contains_any(prompt_lower, PROMPT_EDIT_MARKERS)
    code_context = (
        bool(str(workspace or "").strip())
        or selected_file_count > 0
        or _contains_any(prompt_lower, PROMPT_CODE_MARKERS)
    )
    return _RouteFeatures(
        prompt=prompt_text,
        mode=_recommended_mode(mode),
        workspace_present=bool(str(workspace or "").strip()),
        selected_file_count=selected_file_count,
        attachment_kinds=attachment_kinds,
        has_image_context=has_image_context,
        has_code_context=code_context,
        edit_intent=edit_intent,
        review_intent=_contains_any(prompt_lower, PROMPT_REVIEW_MARKERS),
    )


def _recommended_mode(mode: str | None) -> str:
    value = str(mode or "").strip().lower()
    if value == "edit":
        return "edit"
    if value in {"ask", "read", "review"}:
        return "read"
    if value and value not in {"auto", "plan"}:
        return value
    return "plan"


def _score_candidate(harness: BaseHarness, features: _RouteFeatures) -> _Candidate:
    spec = harness.spec()
    availability = harness.availability()
    score = 0.0
    reasons: list[str] = []
    warnings: list[str] = []

    if availability.status == AvailabilityStatus.AVAILABLE:
        score += 20
    else:
        score -= 60
        warnings.append(f"{spec.title} is unavailable: {availability.reason}.")

    if spec.id == "direct-chat":
        score += 12
    if spec.id == "echo":
        score += 2
    if spec.kind == "agent-cli":
        score += 8

    if features.attachment_kinds:
        if spec.supports_attachments:
            score += 8
            _append_unique(
                reasons, "The selected attachments can be routed through this harness."
            )
        else:
            score -= 30
            warnings.append(f"{spec.title} does not support attachments.")
        unsupported = _unsupported_attachment_kinds(spec, features.attachment_kinds)
        if unsupported:
            score -= 20 * len(unsupported)
            warnings.append(
                f"{spec.title} does not accept {', '.join(sorted(unsupported))} attachments."
            )
        elif features.attachment_kinds and spec.supports_attachments:
            score += 10

    if features.has_image_context:
        if "image" in spec.accepted_attachment_kinds:
            score += 24
            _append_unique(
                reasons, "Image context is present and this harness accepts images."
            )
            if spec.id == "direct-chat":
                score += 12
                _append_unique(
                    reasons, "Direct chat can send images through content parts."
                )
        else:
            score -= 14

    if features.workspace_present or features.selected_file_count:
        if spec.supports_workspace:
            score += 20
            _append_unique(
                reasons,
                "Workspace context is present and this harness can run in a project.",
            )
        else:
            score -= 18
            warnings.append(f"{spec.title} cannot use the selected workspace directly.")

    if features.has_code_context:
        if spec.kind == "agent-cli":
            score += 22
            _append_unique(reasons, "The prompt looks like project code work.")
        elif spec.supports_workspace:
            score += 10
        else:
            score -= 6

    if features.mode == "edit":
        if spec.kind == "agent-cli" and spec.supports_workspace:
            score += 30
            _append_unique(
                reasons,
                "Edit mode was explicitly selected, so a workspace-capable agent is preferred.",
            )
        else:
            score -= 30
            warnings.append(
                f"{spec.title} is not a safe default for edit-mode project work."
            )
    elif features.edit_intent:
        if spec.kind == "agent-cli":
            score += 18
            _append_unique(
                reasons,
                "The prompt sounds like an edit task, but mode stays non-edit until selected.",
            )
        elif spec.id == "direct-chat":
            score -= 8

    if features.mode == "read" or features.review_intent:
        if spec.kind == "agent-cli" and features.has_code_context:
            score += 12
            _append_unique(
                reasons,
                "Review-style project work benefits from repository-aware context.",
            )
        elif spec.id == "direct-chat" and not features.has_code_context:
            score += 12
            _append_unique(
                reasons, "Prompt-only analysis is a good fit for direct chat."
            )

    if not features.attachment_kinds and not features.has_code_context:
        if spec.id == "direct-chat":
            score += 25
            _append_unique(
                reasons, "Prompt-only proxy requests are fastest through direct chat."
            )
        elif spec.id == "echo":
            score += 5

    if spec.id == "codex-cli" and (
        features.has_code_context or features.mode == "edit"
    ):
        score += 10
        _append_unique(
            reasons, "Codex CLI is the default project agent for code tasks."
        )
    if (
        spec.id == "claude-code"
        and features.review_intent
        and features.has_code_context
    ):
        score += 6
    if spec.id == "gemini-cli" and features.selected_file_count:
        score += 4

    if not reasons:
        _append_unique(
            reasons, "This is the best available fallback for the current request."
        )
    return _Candidate(
        spec=spec,
        availability=availability,
        score=score,
        reasons=tuple(reasons[:4]),
        warnings=tuple(warnings),
    )


def _global_warnings(
    features: _RouteFeatures,
    candidates: list[_Candidate],
    best: _Candidate,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if features.edit_intent and features.mode != "edit":
        warnings.append(
            f"Prompt looks like an edit task; keeping mode {features.mode} until edit is selected explicitly."
        )
    if best.availability.status != AvailabilityStatus.AVAILABLE:
        warnings.append(
            "No available harness matched this request; recommendation is a fallback."
        )
    if (
        features.workspace_present
        or features.selected_file_count
        or features.mode == "edit"
    ) and not any(
        candidate.availability.status == AvailabilityStatus.AVAILABLE
        and candidate.spec.kind == "agent-cli"
        and candidate.spec.supports_workspace
        for candidate in candidates
    ):
        warnings.append("No available workspace-capable agent harness was found.")
    return tuple(warnings)


def _confidence(candidate: _Candidate) -> float:
    value = 0.45 + max(0.0, min(candidate.score, 80.0)) / 160
    if candidate.warnings:
        value -= 0.08
    if candidate.availability.status != AvailabilityStatus.AVAILABLE:
        value -= 0.15
    return round(max(0.2, min(value, 0.95)), 2)


def _attachment_kind(attachment: Mapping[str, Any]) -> str:
    metadata = attachment.get("metadata")
    if str(attachment.get("kind") or "") == "workspace_file" and isinstance(
        metadata, Mapping
    ):
        detected = str(metadata.get("detected_kind") or "").strip()
        if detected:
            return detected
    return str(attachment.get("kind") or "binary").strip() or "binary"


def _unsupported_attachment_kinds(
    spec: HarnessSpec,
    kinds: tuple[str, ...],
) -> set[str]:
    if not kinds:
        return set()
    accepted = set(spec.accepted_attachment_kinds)
    if not accepted:
        return set(kinds)
    return {kind for kind in kinds if kind not in accepted}


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
