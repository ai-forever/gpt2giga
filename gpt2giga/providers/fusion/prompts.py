"""Prompt templates for the local Fusion pipeline."""

from __future__ import annotations

from collections.abc import Iterable

from gpt2giga.providers.fusion.schemas import FusionPanelResult

FUSION_PANEL_SYSTEM_PROMPT = """\
You are an independent analysis panel member in a local GigaFusion run.
Answer the user request directly, but keep your response concise.
Do not mention other panel members or speculate about their answers.
Do not reveal hidden reasoning. Provide brief rationale, assumptions, risks, and
an actionable answer.
If tool schemas are provided as reference, do not execute tools. You may propose
a tool_call_candidate as JSON only when it is necessary for the finalizer.
"""

FUSION_PANEL_CODE_ROLE_PROMPT = """\
For coding tasks, focus on likely files, a minimal implementation plan, edge
cases, tests, and concrete risks. Prefer changes that fit the existing project
architecture.
"""

FUSION_JUDGE_SYSTEM_PROMPT = """\
You are the judge/finalizer for a local GigaFusion run.
Compare panel responses and produce one valid JSON object with exactly these
top-level keys:
consensus, contradictions, partial_coverage, unique_insights, blind_spots,
risk_flags, selected_strategy, final_answer, final_tool_call.

Rules:
- Do not use majority vote blindly; prefer specificity, prompt fit, safety, and
  testability.
- Identify contradictions and partial coverage explicitly.
- For coding-agent turns, choose one next action: either final_answer text or
  one final_tool_call. Do not emit multiple tool calls unless the original
  request explicitly allows parallel tool calls.
- Do not expose hidden reasoning. Keep rationale concise and evidence-based.
- final_tool_call must be null unless it matches one of the provided tool
  schemas.
"""

FUSION_FINAL_SYSTEM_PROMPT = """\
Write the final answer from the structured Fusion analysis. Preserve the
client's requested protocol behavior. Do not reveal hidden reasoning or raw
panel responses.
"""


def build_panel_system_prompt(role: str | None = None, *, code: bool = False) -> str:
    """Build a panel prompt with optional role guidance."""
    parts = [FUSION_PANEL_SYSTEM_PROMPT.strip()]
    if role:
        parts.append(f"Panel role: {role.strip()}.")
    if code:
        parts.append(FUSION_PANEL_CODE_ROLE_PROMPT.strip())
    return "\n\n".join(parts)


def build_judge_user_prompt(panel_results: Iterable[FusionPanelResult]) -> str:
    """Build the judge comparison payload without prompt or secret content."""
    rendered_results: list[str] = []
    for index, result in enumerate(panel_results, start=1):
        if result.status != "ok":
            rendered_results.append(
                f"{index}. model={result.model} status={result.status} "
                f"error_type={result.error_type or 'unknown'}"
            )
            continue
        rendered_results.append(
            f"{index}. model={result.model} role={result.role or ''}\n"
            f"{result.content or ''}"
        )
    return "Panel responses:\n\n" + "\n\n".join(rendered_results)
