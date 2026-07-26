from dataclasses import replace

import pytest

from gpt2giga_harness.session_titles import (
    SessionTitleGeneration,
    apply_provider_native_title,
    claim_fallback_title,
    complete_fallback_title,
    title_diagnostics,
)
from gpt2giga_harness.sessions import (
    FilesystemHarnessSessionStore,
    InMemoryHarnessSessionStore,
)


@pytest.mark.parametrize("store_kind", ["memory", "filesystem"])
def test_title_priority_is_manual_then_native_then_fallback(tmp_path, store_kind):
    store = (
        InMemoryHarnessSessionStore()
        if store_kind == "memory"
        else FilesystemHarnessSessionStore(tmp_path)
    )
    session = store.create_session()
    claim = claim_fallback_title(
        store,
        session.id,
        run_id="run-first",
        model="TitleModel",
        timeout_seconds=7.5,
    )

    assert claim is not None
    fallback = complete_fallback_title(
        store,
        claim,
        SessionTitleGeneration(
            title="Fallback title",
            status="succeeded",
            duration_ms=12.25,
            usage={"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
        ),
    )
    assert fallback is not None
    assert fallback.title == "Fallback title"
    assert title_diagnostics(fallback) == {
        "schema_version": 1,
        "provenance": "fallback",
        "status": "succeeded",
        "source": "bounded_fallback",
        "bound_run_id": "run-first",
        "model": "TitleModel",
        "timeout_seconds": 7.5,
        "duration_ms": 12.25,
        "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
        "cost": {"knowledge": "unknown"},
    }

    native = apply_provider_native_title(
        store,
        session.id,
        title="Provider title",
        run_id="run-first",
        provider="codex-cli",
        source_id="thread-1",
    )
    assert native is not None
    assert native.title == "Provider title"
    assert title_diagnostics(native)["provenance"] == "provider_native"

    assert (
        apply_provider_native_title(
            store,
            session.id,
            title="Reordered provider title",
            run_id="run-first",
            provider="codex-cli",
            source_id="thread-1",
        )
        is None
    )
    manual = store.update_session(session.id, title="Manual title")
    assert title_diagnostics(manual)["provenance"] == "manual"
    assert (
        apply_provider_native_title(
            store,
            session.id,
            title="Late provider title",
            run_id="run-first",
            provider="codex-cli",
            source_id="thread-1",
        )
        is None
    )
    assert store.get_session(session.id).title == "Manual title"


def test_legacy_session_is_diagnostic_only_and_never_claimed():
    store = InMemoryHarnessSessionStore()
    created = store.create_session()
    legacy = replace(created, metadata={})
    store._sessions[created.id] = legacy

    assert title_diagnostics(legacy) == {
        "schema_version": 1,
        "provenance": "legacy",
        "status": "settled",
        "source": "legacy_session",
    }
    assert (
        claim_fallback_title(
            store,
            legacy.id,
            run_id="run-new",
            model=None,
            timeout_seconds=5.0,
        )
        is None
    )
    assert store.get_session(legacy.id).title == "Untitled session"


def test_concurrent_first_turn_claim_is_single_writer():
    store = InMemoryHarnessSessionStore()
    session = store.create_session()

    first = claim_fallback_title(
        store,
        session.id,
        run_id="run-first",
        model=None,
        timeout_seconds=5.0,
    )
    second = claim_fallback_title(
        store,
        session.id,
        run_id="run-second",
        model=None,
        timeout_seconds=5.0,
    )

    assert first is not None
    assert second is None
    assert title_diagnostics(store.get_session(session.id))["bound_run_id"] == (
        "run-first"
    )
