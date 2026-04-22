import pytest

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.batches.validation import (
    BatchInputValidator,
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


def test_validate_batch_input_rows_reports_gigachat_row_limit():
    report = validate_batch_input_rows(
        [
            {
                "custom_id": f"row-{index}",
                "url": "/v1/chat/completions",
                "body": {},
            }
            for index in range(101)
        ],
        api_format="openai",
    )

    assert report.valid is False
    assert report.summary.total_rows == 101
    assert report.summary.error_count == 1
    assert report.issues[0].code == "row_limit_exceeded"
    assert report.issues[0].severity is BatchValidationSeverity.ERROR


class FakeValidationTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        if data.get("messages") == "explode":
            raise ValueError("Chat normalization failed.")
        return data


@pytest.mark.asyncio
async def test_batch_input_validator_openai_collects_errors_and_warnings():
    validator = BatchInputValidator(
        request_transformer=FakeValidationTransformer(),
        embeddings_model="EmbeddingsGigaR",
        gigachat_api_mode="v2",
        default_model="GigaChat-2-Max",
    )

    report = await validator.validate_rows(
        [
            {"url": "/v1/chat/completions", "body": {"messages": []}},
            {
                "custom_id": "dup",
                "url": "/v1/embeddings",
                "body": {"input": "hello"},
            },
            {
                "custom_id": "dup",
                "method": "GET",
                "url": "/v1/chat/completions",
                "body": {"messages": "explode"},
            },
        ],
        api_format="openai",
    )

    codes = [issue.code for issue in report.issues]
    assert report.valid is False
    assert "missing_identifier" in codes
    assert "default_model_applied" in codes
    assert "compatibility_warning" in codes
    assert "mixed_endpoint_family" in codes
    assert "duplicate_identifier" in codes
    assert "invalid_field" in codes
    assert "missing_field" in codes


@pytest.mark.asyncio
async def test_batch_input_validator_anthropic_reports_schema_and_duplicate_issues():
    validator = BatchInputValidator()

    report = await validator.validate_rows(
        [
            {"custom_id": "dup", "params": {"model": "claude"}},
            {
                "custom_id": "dup",
                "params": {"messages": [], "stream": True},
                "metadata": {"source": "ignored"},
            },
            {"params": {"messages": []}},
        ],
        api_format="anthropic",
    )

    codes = [issue.code for issue in report.issues]
    assert report.valid is False
    assert "missing_field" in codes
    assert "duplicate_identifier" in codes
    assert "invalid_field" in codes
    assert "ignored_fields" in codes


@pytest.mark.asyncio
async def test_batch_input_validator_gemini_uses_fallback_model_and_flags_metadata():
    validator = BatchInputValidator(gemini_fallback_model="models/gemini-2.5-flash")

    report = await validator.validate_rows(
        [
            {
                "request": {
                    "contents": [{"role": "user", "parts": [{"text": "hello"}]}]
                },
                "metadata": {"source": "test"},
            },
            {
                "key": "dup",
                "request": {
                    "model": "models/gemini-2.5-flash",
                    "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
                },
            },
            {"key": "dup", "request": {"model": "models/gemini-2.5-flash"}},
        ],
        api_format="gemini",
    )

    codes = [issue.code for issue in report.issues]
    assert report.valid is False
    assert "default_model_applied" in codes
    assert "metadata_ignored" in codes
    assert "duplicate_identifier" in codes
    assert "request_normalization_failed" in codes
