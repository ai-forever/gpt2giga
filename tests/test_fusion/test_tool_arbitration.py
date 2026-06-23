import json

from gpt2giga.protocols.normalized import NormalizedTool, NormalizedToolCall
from gpt2giga.providers.fusion.schemas import FusionPanelResult
from gpt2giga.providers.fusion.tool_arbitration import (
    build_judge_tool_arbitration_prompt,
    build_panel_tool_reference,
    first_allowed_tool_call,
    looks_like_tool_candidate_json,
    panel_tool_candidates,
    panel_tool_candidates_by_result,
    resolve_tool_call_policy,
    tool_call_allowed,
    tool_choice_requires_tool,
    validate_tool_call_arguments,
)


def _tool(name="lookup") -> NormalizedTool:
    return NormalizedTool(
        name=name,
        description="Lookup data",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    )


def test_panel_tool_reference_is_schema_only_and_disabled_in_off_mode():
    assert build_panel_tool_reference([_tool()], "off") is None

    reference = build_panel_tool_reference([_tool()], "schema_only")

    assert reference is not None
    assert "reference-only" in reference
    assert '"name": "lookup"' in reference
    assert "Do not execute tools" in reference


def test_tool_policy_respects_none_required_and_forced_function_choice():
    tool = _tool()

    none_policy = resolve_tool_call_policy(
        tools=[tool],
        tools_mode="schema_only",
        tool_choice="none",
    )
    required_policy = resolve_tool_call_policy(
        tools=[tool],
        tools_mode="schema_only",
        tool_choice="required",
    )
    forced_policy = resolve_tool_call_policy(
        tools=[tool],
        tools_mode="schema_only",
        tool_choice={"type": "function", "function": {"name": "lookup"}},
    )

    assert not none_policy.allow_tool_calls
    assert required_policy.require_tool_call
    assert forced_policy.require_tool_call
    assert forced_policy.forced_tool_name == "lookup"


def test_tool_call_validation_rejects_wrong_or_disabled_tool_choice():
    lookup = _tool("lookup")
    wrong_call = NormalizedToolCall(name="other", arguments={})
    lookup_call = NormalizedToolCall(name="lookup", arguments={"q": "hello"})

    assert not tool_call_allowed(
        lookup_call,
        request_tools=[lookup],
        tools_mode="schema_only",
        tool_choice="none",
    )
    assert not tool_call_allowed(
        wrong_call,
        request_tools=[lookup],
        tools_mode="schema_only",
        tool_choice={"type": "function", "function": {"name": "lookup"}},
    )
    assert tool_call_allowed(
        lookup_call,
        request_tools=[lookup],
        tools_mode="schema_only",
        tool_choice={"type": "function", "function": {"name": "lookup"}},
    )


def test_first_allowed_tool_call_selects_only_valid_final_call():
    calls = [
        NormalizedToolCall(name="other", arguments={}),
        NormalizedToolCall(name="lookup", arguments={"q": "hello"}),
    ]

    selected = first_allowed_tool_call(
        calls,
        request_tools=[_tool("lookup")],
        tools_mode="final_arbitration",
        tool_choice="auto",
    )

    assert selected == calls[1]


def test_tool_call_validation_parses_string_arguments_and_checks_schema():
    result = validate_tool_call_arguments(
        NormalizedToolCall(name="lookup", arguments='{"q": "hello"}'),
        request_tools=[_tool("lookup")],
        tools_mode="schema_only",
        tool_choice="auto",
    )

    assert result.valid
    assert result.tool_call is not None
    assert result.tool_call.arguments == {"q": "hello"}


def test_tool_call_validation_rejects_malformed_and_missing_arguments():
    malformed = validate_tool_call_arguments(
        NormalizedToolCall(name="lookup", arguments="{not-json"),
        request_tools=[_tool("lookup")],
        tools_mode="schema_only",
        tool_choice="auto",
    )
    missing_required = validate_tool_call_arguments(
        NormalizedToolCall(name="lookup", arguments={}),
        request_tools=[_tool("lookup")],
        tools_mode="schema_only",
        tool_choice="auto",
    )
    wrong_type = validate_tool_call_arguments(
        NormalizedToolCall(name="lookup", arguments={"q": 123}),
        request_tools=[_tool("lookup")],
        tools_mode="schema_only",
        tool_choice="auto",
    )

    assert not malformed.valid
    assert malformed.reason == "arguments_malformed_json"
    assert not missing_required.valid
    assert missing_required.reason == "arguments.q.required"
    assert not wrong_type.valid
    assert wrong_type.reason == "arguments.q.type"


def test_tool_call_validation_uses_original_json_schema_constraints():
    tool = NormalizedTool(
        name="submit",
        description="Submit structured data",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "pattern": "^[A-Z]+$"},
                "count": {
                    "type": "integer",
                    "exclusiveMinimum": 0,
                    "multipleOf": 2,
                },
                "mode": {"oneOf": [{"const": "fast"}, {"const": "safe"}]},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                },
                "note": {"type": ["string", "null"]},
            },
            "required": ["code", "count", "mode", "tags"],
            "additionalProperties": False,
        },
    )
    valid = validate_tool_call_arguments(
        NormalizedToolCall(
            name="submit",
            arguments={
                "code": "ABC",
                "count": 2,
                "mode": "safe",
                "tags": ["a", "b"],
                "note": None,
            },
        ),
        request_tools=[tool],
        tools_mode="schema_only",
        tool_choice="auto",
    )
    bad_pattern = validate_tool_call_arguments(
        NormalizedToolCall(
            name="submit",
            arguments={"code": "abc", "count": 2, "mode": "fast", "tags": ["a"]},
        ),
        request_tools=[tool],
        tools_mode="schema_only",
        tool_choice="auto",
    )
    duplicate_tags = validate_tool_call_arguments(
        NormalizedToolCall(
            name="submit",
            arguments={
                "code": "ABC",
                "count": 2,
                "mode": "fast",
                "tags": ["a", "a"],
            },
        ),
        request_tools=[tool],
        tools_mode="schema_only",
        tool_choice="auto",
    )
    extra_property = validate_tool_call_arguments(
        NormalizedToolCall(
            name="submit",
            arguments={
                "code": "ABC",
                "count": 2,
                "mode": "fast",
                "tags": ["a"],
                "extra": True,
            },
        ),
        request_tools=[tool],
        tools_mode="schema_only",
        tool_choice="auto",
    )
    bad_one_of = validate_tool_call_arguments(
        NormalizedToolCall(
            name="submit",
            arguments={"code": "ABC", "count": 2, "mode": "slow", "tags": ["a"]},
        ),
        request_tools=[tool],
        tools_mode="schema_only",
        tool_choice="auto",
    )

    assert valid.valid
    assert valid.tool_call is not None
    assert valid.tool_call.arguments["note"] is None
    assert not bad_pattern.valid
    assert bad_pattern.reason == "arguments.code.pattern"
    assert not duplicate_tags.valid
    assert duplicate_tags.reason == "arguments.tags.uniqueItems"
    assert not extra_property.valid
    assert extra_property.reason == "arguments.extra.additionalProperties"
    assert not bad_one_of.valid
    assert bad_one_of.reason == "arguments.mode.oneOf"


def test_panel_tool_candidates_parse_actual_calls_and_json_candidate_text():
    panel_results = [
        FusionPanelResult(
            model="PanelA",
            role="implementer",
            status="ok",
            content=json.dumps(
                {
                    "tool_call_candidate": {
                        "id": "candidate-1",
                        "name": "lookup",
                        "arguments": {"q": "from text"},
                    }
                }
            ),
            tool_calls=[
                NormalizedToolCall(
                    id="call-1",
                    name="lookup",
                    arguments={"q": "from call"},
                )
            ],
        )
    ]

    candidates = panel_tool_candidates(panel_results)

    assert [candidate.id for candidate in candidates] == ["call-1", "candidate-1"]
    assert all(
        candidate.raw_extensions["fusion_panel_model"] == "PanelA"
        for candidate in candidates
    )


def test_panel_tool_candidate_accepts_parameters_alias():
    result = FusionPanelResult(
        model="GigaChat-3-Ultra",
        role="solver",
        status="ok",
        content=(
            "```json\n"
            '{"name":"write_file","parameters":'
            '{"file_path":"hello.py","content":"print(1)"}}'
            "\n```"
        ),
    )

    calls = panel_tool_candidates([result])

    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {
        "file_path": "hello.py",
        "content": "print(1)",
    }


def test_panel_tool_candidate_accepts_function_parameters_alias():
    result = FusionPanelResult(
        model="GigaChat-3-Ultra",
        role="solver",
        status="ok",
        content=json.dumps(
            {
                "function": {
                    "name": "write_file",
                    "parameters": {
                        "file_path": "hello.py",
                        "content": "print(1)",
                    },
                }
            }
        ),
    )

    calls = panel_tool_candidates([result])

    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {
        "file_path": "hello.py",
        "content": "print(1)",
    }


def test_panel_tool_candidate_accepts_canonical_advisory_shape():
    result = FusionPanelResult(
        model="GigaChat-3-Ultra",
        role="solver",
        status="ok",
        content=json.dumps(
            {
                "tool_call_candidate": {
                    "name": "write_file",
                    "arguments": {
                        "file_path": "hello.py",
                        "content": "print(1)",
                    },
                }
            }
        ),
    )

    calls = panel_tool_candidates([result])

    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {
        "file_path": "hello.py",
        "content": "print(1)",
    }


def test_panel_tool_candidates_by_result_preserves_panel_index_mapping():
    first = FusionPanelResult(
        model="PanelA",
        role="solver",
        status="ok",
        content='{"name":"lookup","arguments":{"q":"first"}}',
    )
    failed = FusionPanelResult(model="PanelB", role="critic", status="error")
    third = FusionPanelResult(
        model="PanelC",
        role="solver",
        status="ok",
        content='{"name":"lookup","arguments":{"q":"third"}}',
    )

    calls_by_result = panel_tool_candidates_by_result([first, failed, third])

    assert sorted(calls_by_result) == [0, 2]
    assert calls_by_result[0][0].arguments == {"q": "first"}
    assert calls_by_result[2][0].arguments == {"q": "third"}
    assert calls_by_result[2][0].raw_extensions["fusion_panel_model"] == "PanelC"


def test_tool_candidate_json_detector_handles_invalid_candidate_shapes():
    assert looks_like_tool_candidate_json(
        '{"tool_call_candidate":{"name":"unknown","parameters":{"q":1}}}'
    )


def test_judge_tool_prompt_includes_schemas_candidates_and_choice_policy():
    prompt = build_judge_tool_arbitration_prompt(
        tools=[_tool()],
        panel_results=[
            FusionPanelResult(
                model="PanelA",
                status="ok",
                content='{"tool_call_candidate": {"name": "lookup"}}',
            )
        ],
        tool_choice="required",
        tools_mode="schema_only",
        max_tool_calls=1,
    )

    assert prompt is not None
    assert "Tool arbitration instructions" in prompt
    assert '"require_tool_call": true' in prompt
    assert '"tool_schemas"' in prompt
    assert '"panel_tool_candidates"' in prompt


def test_required_tool_choice_is_reported_even_when_tools_are_unavailable():
    assert tool_choice_requires_tool(
        request_tools=[],
        tools_mode="schema_only",
        tool_choice="required",
    )
