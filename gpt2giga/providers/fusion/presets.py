"""Built-in Fusion presets used when env presets are not supplied."""

from __future__ import annotations

from gpt2giga.models.config import FusionPresetSettings


def built_in_fusion_presets() -> dict[str, FusionPresetSettings]:
    """Return fresh built-in Fusion preset objects."""
    return {
        "general": FusionPresetSettings(
            analysis_models=["GigaChat-2-Max", "GigaChat-2-Pro"],
            judge_model="GigaChat-2-Max",
            panel_roles=["planner", "critic"],
            temperature=0.2,
            max_completion_tokens=3072,
            min_successful_panels=1,
            timeout_seconds=120.0,
            tools_mode="off",
        ),
        "code-budget": FusionPresetSettings(
            analysis_models=["GigaChat-2-Pro", "GigaChat-2-Max"],
            judge_model="GigaChat-2-Max",
            panel_roles=["implementer", "reviewer"],
            temperature=0.2,
            max_completion_tokens=3072,
            min_successful_panels=1,
            timeout_seconds=120.0,
            tools_mode="schema_only",
        ),
        "code-high": FusionPresetSettings(
            analysis_models=[
                "GigaChat-3-Ultra",
                "GigaChat-2-Max",
                "GigaChat-2-Pro",
            ],
            judge_model="GigaChat-3-Ultra",
            panel_roles=["architect", "implementer", "reviewer"],
            temperature=0.2,
            max_completion_tokens=4096,
            min_successful_panels=1,
            timeout_seconds=180.0,
            tools_mode="schema_only",
        ),
        "accuracy-ultra-selector": FusionPresetSettings(
            analysis_models=["GigaChat-3-Ultra"],
            judge_model="GigaChat-3-Ultra",
            panel_roles=["solver"],
            temperature=0,
            max_completion_tokens=None,
            include_direct_candidate=True,
            return_selected_candidate=True,
            decision_mode="selector",
            prompt_mode="minimal",
            max_panel_output_chars=6000,
            max_total_panel_output_chars=12000,
            min_successful_panels=1,
            timeout_seconds=120.0,
            tools_mode="off",
        ),
        "accuracy-ultra-verifier": FusionPresetSettings(
            analysis_models=["GigaChat-3-Ultra"],
            judge_model="GigaChat-3-Ultra",
            final_model="GigaChat-3-Ultra",
            panel_roles=["verifier"],
            temperature=0,
            max_completion_tokens=None,
            include_direct_candidate=True,
            return_selected_candidate=True,
            decision_mode="selector",
            prompt_mode="minimal",
            max_panel_output_chars=4000,
            max_total_panel_output_chars=8000,
            min_successful_panels=1,
            timeout_seconds=120.0,
            tools_mode="off",
        ),
        "code-agent-safe": FusionPresetSettings(
            analysis_models=["GigaChat-3-Ultra", "GigaChat-2-Max"],
            judge_model="GigaChat-3-Ultra",
            final_model="GigaChat-3-Ultra",
            panel_roles=["solver", "reviewer"],
            temperature=0,
            max_completion_tokens=8192,
            include_direct_candidate=True,
            return_selected_candidate=False,
            decision_mode="selector",
            prompt_mode="full",
            max_panel_output_chars=6000,
            max_total_panel_output_chars=16000,
            min_successful_panels=1,
            timeout_seconds=180.0,
            tools_mode="schema_only",
        ),
    }


def get_fusion_presets(
    custom_presets: dict[str, FusionPresetSettings],
) -> dict[str, FusionPresetSettings]:
    """Merge built-in presets with user presets."""
    presets = built_in_fusion_presets()
    presets.update(custom_presets)
    return presets
