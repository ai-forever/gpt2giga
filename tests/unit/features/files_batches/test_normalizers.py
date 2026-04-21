from types import SimpleNamespace

from gpt2giga.core.contracts import NormalizedArtifactFormat
from gpt2giga.features.files_batches.normalizers import (
    normalize_anthropic_file,
    normalize_anthropic_batch,
    normalize_anthropic_output_file,
    normalize_gemini_batch,
    normalize_gemini_file,
    normalize_openai_batch,
    normalize_openai_file,
)


class FakeRequestCounts:
    def __init__(self, *, total: int, completed: int | None, failed: int | None):
        self._payload = {
            "total": total,
            "completed": completed,
            "failed": failed,
        }

    def model_dump(self):
        return dict(self._payload)


def test_normalize_openai_file_builds_canonical_paths():
    record = normalize_openai_file(
        {
            "id": "file-1",
            "filename": "input.jsonl",
            "purpose": "batch",
            "bytes": 12,
            "status": "processed",
            "created_at": 123,
        }
    )

    assert record.api_format is NormalizedArtifactFormat.OPENAI
    assert record.content_path == "/admin/api/files-batches/files/file-1/content"
    assert record.delete_path == "/v1/files/file-1"
    assert record.content_kind == "jsonl"


def test_normalize_openai_batch_preserves_output_file_linkage():
    record = normalize_openai_batch(
        {
            "id": "batch-1",
            "endpoint": "/v1/chat/completions",
            "status": "completed",
            "created_at": 123,
            "input_file_id": "file-input-1",
            "output_file_id": "file-output-1",
            "request_counts": {"total": 2, "completed": 2, "failed": 0},
            "model": "gpt-test",
        }
    )

    assert record.api_format is NormalizedArtifactFormat.OPENAI
    assert record.output_kind == "file"
    assert record.output_path == "/admin/api/files-batches/batches/batch-1/output"
    assert record.request_counts.total == 2
    assert record.request_counts.succeeded == 2


def test_normalize_anthropic_batch_recovers_results_endpoint():
    batch = SimpleNamespace(
        id_="batch-1",
        status="completed",
        created_at=123,
        updated_at=124,
        output_file_id="file-output-1",
        request_counts=FakeRequestCounts(total=2, completed=1, failed=1),
    )

    record = normalize_anthropic_batch(
        batch,
        {
            "api_format": "anthropic_messages",
            "endpoint": "/v1/chat/completions",
            "input_file_id": "file-input-1",
            "requests": [{"custom_id": "req-1"}, {"custom_id": "req-2"}],
        },
    )

    assert record.api_format is NormalizedArtifactFormat.ANTHROPIC
    assert record.output_kind == "results"
    assert record.output_path == "/admin/api/files-batches/batches/batch-1/output"
    assert record.request_counts.errored == 1
    assert record.request_counts.succeeded == 1


def test_normalize_gemini_file_uses_gemini_paths_and_display_name():
    record = normalize_gemini_file(
        {
            "id": "file-1",
            "filename": "internal.bin",
            "purpose": "user_data",
            "bytes": 7,
            "created_at": 123,
        },
        metadata={
            "display_name": "Poem",
            "mime_type": "text/plain",
            "source": "UPLOADED",
        },
    )

    assert record.api_format is NormalizedArtifactFormat.GEMINI
    assert record.filename == "Poem"
    assert record.content_path == "/admin/api/files-batches/files/file-1/content"
    assert record.delete_path == "/v1beta/files/file-1"


def test_normalize_gemini_batch_builds_download_path():
    batch = SimpleNamespace(
        id_="batch-1",
        status="completed",
        created_at=123,
        updated_at=124,
        output_file_id="file-output-1",
        request_counts=FakeRequestCounts(total=3, completed=2, failed=1),
    )

    record = normalize_gemini_batch(
        batch,
        {
            "api_format": "gemini_generate_content",
            "display_name": "Gemini batch",
            "model": "gemini-test",
            "input_file_id": "file-input-1",
            "requests": [{}, {}, {}],
        },
    )

    assert record.api_format is NormalizedArtifactFormat.GEMINI
    assert record.output_path == "/admin/api/files-batches/batches/batch-1/output"
    assert record.request_counts.pending == 0
    assert record.display_name == "Gemini batch"


def test_normalize_gemini_batch_maps_enum_style_completed_status():
    batch = SimpleNamespace(
        id_="batch-1",
        status="BatchStatus.COMPLETED",
        created_at=123,
        updated_at=124,
        output_file_id="file-output-1",
        request_counts=FakeRequestCounts(total=2, completed=2, failed=0),
    )

    record = normalize_gemini_batch(
        batch,
        {
            "api_format": "gemini_generate_content",
            "display_name": "Gemini batch",
            "model": "gemini-test",
            "input_file_id": "file-input-1",
            "requests": [{}, {}],
        },
    )

    assert record.status == "completed"
    assert record.request_counts.pending == 0
    assert record.request_counts.succeeded == 2


def test_normalize_anthropic_output_file_points_to_results_path():
    record = normalize_anthropic_output_file(
        {
            "id": "file-output-1",
            "filename": "batch-output.jsonl",
            "purpose": "batch_output",
            "bytes": 14,
            "created_at": 123,
        },
        metadata={"batch_id": "batch-1"},
        batch_id="batch-1",
        batch_metadata={"api_format": "anthropic_messages"},
    )

    assert record.api_format is NormalizedArtifactFormat.ANTHROPIC
    assert record.content_kind == "batch_results"
    assert record.content_path == "/admin/api/files-batches/files/file-output-1/content"
    assert record.delete_path is None


def test_normalize_anthropic_input_file_uses_staged_file_shape():
    record = normalize_anthropic_file(
        {
            "id": "file-input-1",
            "filename": "anthropic-input.jsonl",
            "purpose": "batch",
            "bytes": 14,
            "created_at": 123,
        },
        metadata={"api_format": "anthropic", "purpose": "batch"},
    )

    assert record.api_format is NormalizedArtifactFormat.ANTHROPIC
    assert record.content_kind == "jsonl"
    assert record.content_path == "/admin/api/files-batches/files/file-input-1/content"
    assert record.delete_path == "/v1/files/file-input-1"
