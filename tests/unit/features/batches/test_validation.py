import pytest

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches.validation import (
    detect_batch_input_format,
    parse_jsonl_with_diagnostics,
    validate_batch_input_bytes,
    validate_batch_input_rows,
)
from gpt2giga.features.batches.validation_contracts import BatchValidationSeverity


def test_parse_jsonl_with_diagnostics_collects_blank_line_json_and_shape_issues():
    content = (
        b'{"url":"/v1/chat/completions","body":{"messages":[]}}\n'
        b"\n"
        b'{"broken": }\n'
        b'["not-an-object"]\n'
        b'{"custom_id":"row-2","params":{"model":"claude"}}\n'
    )

    rows, issues = parse_jsonl_with_diagnostics(content)

    assert rows == [
        {"url": "/v1/chat/completions", "body": {"messages": []}},
        {"custom_id": "row-2", "params": {"model": "claude"}},
    ]
    assert [(issue.code, issue.line) for issue in issues] == [
        ("blank_line", 2),
        ("invalid_json", 3),
        ("row_not_object", 4),
    ]
    assert [issue.severity for issue in issues] == [
        BatchValidationSeverity.WARNING,
        BatchValidationSeverity.ERROR,
        BatchValidationSeverity.ERROR,
    ]


def test_parse_jsonl_with_diagnostics_reports_invalid_encoding():
    rows, issues = parse_jsonl_with_diagnostics(b"\xff\xfe\xfd")

    assert rows == []
    assert len(issues) == 1
    assert issues[0].code == "invalid_encoding"
    assert issues[0].severity is BatchValidationSeverity.ERROR
    assert issues[0].line == 1


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [{"custom_id": "o-1", "url": "/v1/chat/completions", "body": {}}],
            NormalizedArtifactFormat.OPENAI,
        ),
        (
            [{"custom_id": "a-1", "params": {"messages": []}}],
            NormalizedArtifactFormat.ANTHROPIC,
        ),
        (
            [{"key": "g-1", "request": {"contents": []}}],
            NormalizedArtifactFormat.GEMINI,
        ),
        (
            [
                {"custom_id": "o-1", "url": "/v1/chat/completions", "body": {}},
                {"custom_id": "a-1", "params": {"messages": []}},
            ],
            None,
        ),
    ],
)
def test_detect_batch_input_format_uses_row_shapes(rows, expected):
    assert detect_batch_input_format(rows) == expected


def test_validate_batch_input_bytes_warns_when_selected_format_mismatches_shape():
    report = validate_batch_input_bytes(
        b'{"custom_id":"row-1","url":"/v1/chat/completions","body":{"messages":[]}}\n',
        api_format="anthropic",
    )

    assert report.valid is True
    assert report.api_format is NormalizedArtifactFormat.ANTHROPIC
    assert report.detected_format is NormalizedArtifactFormat.OPENAI
    assert report.summary.total_rows == 1
    assert report.summary.error_count == 0
    assert report.summary.warning_count == 1
    assert report.issues[0].code == "format_mismatch"


def test_validate_batch_input_rows_marks_empty_payload_invalid():
    report = validate_batch_input_rows([], api_format="openai")

    assert report.valid is False
    assert report.summary.total_rows == 0
    assert report.summary.error_count == 1
    assert report.issues[0].code == "empty_rows"
