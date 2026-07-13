from pathlib import Path

from gpt2giga_harness.attachments.models import HarnessAttachment
from gpt2giga_harness.preflight import (
    ACTION_CONTINUE,
    ACTION_EXCLUDE_ATTACHMENT,
    build_preflight_report,
    preflight_report_to_dict,
)
from gpt2giga_harness.sessions.models import HarnessMessage


def test_preflight_blocks_private_key_prompt_without_echoing_secret():
    prompt = "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----"

    report = build_preflight_report(prompt=prompt, workspace=None)

    assert report.hard_block is True
    assert {finding.code for finding in report.findings} == {"private_key_material"}
    payload = preflight_report_to_dict(report)
    assert "not-real-secret" not in str(payload)


def test_preflight_blocks_incomplete_private_key_header_without_backtracking():
    prompt = "-----BEGIN RSA PRIVATE KEY-----" + ("-----BEGIN PRIVATE KEY-----" * 2_000)

    report = build_preflight_report(prompt=prompt, workspace=None)

    assert report.hard_block is True
    assert {finding.code for finding in report.findings} == {"private_key_material"}


def test_preflight_blocks_credential_assignment_without_false_positive_noise():
    report = build_preflight_report(
        prompt="TOKEN=abcdefghijklmnopqrstuvwxyz123456",
        workspace=None,
    )

    assert report.hard_block is True
    assert {finding.code for finding in report.findings} == {"credential_value"}

    safe = build_preflight_report(
        prompt="Explain tokenization, password rotation, and secret management.",
        workspace=None,
    )
    assert safe.hard_block is False
    assert safe.findings == ()


def test_preflight_blocks_private_key_attachment_sample(tmp_path):
    data_dir = tmp_path / "data"
    blob = data_dir / "projects" / "proj" / "attachments" / "sha" / "original"
    blob.parent.mkdir(parents=True)
    blob.write_text(
        "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----",
        encoding="utf-8",
    )
    attachment = _attachment(storage_path=blob, size_bytes=blob.stat().st_size)

    report = build_preflight_report(
        prompt="review attachment",
        workspace=None,
        attachments=(attachment,),
        data_dir=data_dir,
    )

    assert report.hard_block is True
    assert "private_key_material" in {finding.code for finding in report.findings}
    assert "not-real-secret" not in str(preflight_report_to_dict(report))


def test_preflight_warns_for_large_attachment_with_remediation_actions():
    attachment = _attachment(size_bytes=1_000_001)

    report = build_preflight_report(
        prompt="review large file",
        workspace=None,
        attachments=(attachment,),
    )

    assert report.hard_block is False
    finding = next(item for item in report.findings if item.code == "large_attachment")
    assert finding.severity == "warning"
    assert ACTION_EXCLUDE_ATTACHMENT in finding.actions
    assert ACTION_CONTINUE in finding.actions
    assert report.context_budget.attached_file_bytes == 1_000_001


def test_preflight_estimates_history_truncation():
    messages = tuple(
        HarnessMessage(
            id=f"msg_{index}",
            session_id="sess",
            run_id=None,
            role="user",
            content=f"message {index}",
            created_at="2026-07-09T00:00:00Z",
        )
        for index in range(25)
    )

    report = build_preflight_report(
        prompt="next",
        workspace=None,
        previous_messages=messages,
    )

    assert report.hard_block is False
    assert report.context_budget.previous_message_count == 25
    assert report.context_budget.included_previous_message_count == 19
    assert "history_truncation" in {finding.code for finding in report.findings}


def _attachment(
    *,
    storage_path: Path | None = None,
    size_bytes: int = 10,
) -> HarnessAttachment:
    return HarnessAttachment(
        id="att_test",
        session_id="sess",
        project_id="proj",
        kind="text",
        filename="note.txt",
        mime_type="text/plain",
        size_bytes=size_bytes,
        sha256="sha",
        source="upload",
        storage_path=str(storage_path) if storage_path is not None else None,
        created_at="2026-07-09T00:00:00Z",
    )
