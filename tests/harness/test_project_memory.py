from gpt2giga.harness.project import resolve_project
from gpt2giga.harness.project_memory import (
    FilesystemProjectMemoryStore,
    memory_entries_to_prompt,
)


def test_project_memory_store_crud_and_prompt_order(tmp_path):
    project = resolve_project(tmp_path, data_dir=tmp_path / "data")
    store = FilesystemProjectMemoryStore()

    first = store.add(project, text="Use Alembic migrations", tags=("db",))
    second = store.add(project, text="Never edit generated clients", tags=("codegen",))

    prompt = memory_entries_to_prompt(store.enabled_for_prompt(project))
    assert "Use Alembic migrations" in prompt
    assert prompt.index("Use Alembic") < prompt.index("Never edit")

    disabled = store.update(project, first.id, enabled=False)
    assert disabled.enabled is False
    assert [entry.id for entry in store.list(project)] == [second.id]
    assert {entry.id for entry in store.list(project, include_disabled=True)} == {
        first.id,
        second.id,
    }

    store.delete(project, first.id)
    assert [entry.id for entry in store.list(project, include_disabled=True)] == [
        second.id
    ]


def test_project_memory_store_redacts_secret_like_values(tmp_path):
    project = resolve_project(tmp_path, data_dir=tmp_path / "data")
    store = FilesystemProjectMemoryStore()

    entry = store.add(
        project,
        text="token sk-memory-secret-1234567890 should not persist",
        metadata={"api_key": "secret"},
    )

    assert "<redacted>" in entry.text
    assert "sk-memory-secret" not in entry.text
    memory_file = tmp_path / "data" / "projects" / project.id / "memory.jsonl"
    content = memory_file.read_text(encoding="utf-8")
    assert "sk-memory-secret" not in content
    assert '"api_key": "<redacted>"' in content
