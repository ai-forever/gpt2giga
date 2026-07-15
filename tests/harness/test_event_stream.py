import asyncio

import pytest

from gpt2giga_harness.sessions import (
    FilesystemHarnessSessionStore,
    InMemoryHarnessSessionStore,
)
from gpt2giga_harness.sessions.event_stream import RunEventBroker, StreamSignal
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import utc_now


def _event(event_id: str, *, run_id: str = "run-one") -> HarnessStoredEvent:
    return HarnessStoredEvent(
        id=event_id,
        session_id="session-one",
        run_id=run_id,
        type="message_delta",
        message=event_id,
        payload={"delta": event_id},
        created_at=utc_now(),
    )


async def test_run_event_broker_wakes_only_exact_run_and_resnapshots_overflow():
    broker = RunEventBroker(queue_size=2)
    first = broker.subscribe("run-one")
    second = broker.subscribe("run-two")
    try:
        broker.publish(_event("evt-1"))
        broker.publish(_event("evt-2"))
        broker.publish(_event("evt-3"))
        await asyncio.sleep(0)

        assert await first.wait(0.1) is StreamSignal.RESNAPSHOT_REQUIRED
        assert await second.wait(0.01) is None
        assert broker.subscriber_count("run-one") == 1
        assert broker.subscriber_count() == 2
    finally:
        first.close()
        second.close()

    assert broker.subscriber_count() == 0


@pytest.mark.parametrize("store_kind", ["memory", "filesystem"])
def test_event_tail_pages_are_offset_bounded_and_run_filtered(tmp_path, store_kind):
    store = (
        InMemoryHarnessSessionStore()
        if store_kind == "memory"
        else FilesystemHarnessSessionStore(tmp_path)
    )
    session = store.create_session(title="Tail")
    first = _event("evt-1")
    other = _event("evt-other", run_id="run-two")
    second = _event("evt-2")
    for event in (first, other, second):
        store.append_event(
            HarnessStoredEvent(
                **{
                    **event.__dict__,
                    "session_id": session.id,
                }
            )
        )

    page = store.list_event_tail_page(
        session.id,
        run_id="run-one",
        limit=1,
        max_bytes=1024,
    )
    continued = store.list_event_tail_page(
        session.id,
        run_id="run-one",
        offset=page.next_offset,
        limit=100,
        max_bytes=1024,
    )

    assert [item.event.id for item in page.items] == ["evt-1"]
    assert page.has_more is True
    assert [item.event.id for item in continued.items] == ["evt-2"]
    assert continued.has_more is False
    resolved = store.resolve_event_cursor(
        session.id,
        run_id="run-one",
        event_id="evt-1",
    )
    assert resolved is not None
    assert resolved.offset == page.items[0].next_offset
