from types import SimpleNamespace

from gpt2giga.app.dependencies import (
    configure_runtime_stores,
    ensure_runtime_dependencies,
)
from gpt2giga.app.runtime_backends import (
    RuntimeBackendDescriptor,
    RuntimeStateBackend,
    register_runtime_backend,
)
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


class _FakeFeed:
    def __init__(self):
        self.items = []

    def append(self, item):
        self.items.append(item)

    def recent(self, *, limit=None):
        return self.items if limit is None else self.items[-limit:]

    def clear(self):
        self.items.clear()

    def __len__(self):
        return len(self.items)


class _CustomBackend(RuntimeStateBackend):
    name = "custom-test"

    def __init__(self):
        self.mapping_names = []
        self.feed_names = []

    def mapping(self, name):
        self.mapping_names.append(name)
        return {}

    def feed(self, name, *, max_items):
        self.feed_names.append((name, max_items))
        return _FakeFeed()


def test_ensure_runtime_dependencies_configures_memory_backend_resources():
    state = SimpleNamespace()

    ensure_runtime_dependencies(state, config=ProxyConfig())

    assert state.stores.backend is not None
    assert state.stores.backend.name == "memory"
    assert state.stores.files == {}
    assert state.stores.batches == {}
    assert state.stores.responses == {}
    assert len(state.stores.recent_requests) == 0
    assert len(state.stores.recent_errors) == 0


def test_runtime_store_backend_can_be_registered_and_selected():
    register_runtime_backend(
        RuntimeBackendDescriptor(
            name="custom-test",
            description="Test backend",
            factory=lambda **_: _CustomBackend(),
        )
    )
    state = SimpleNamespace()
    config = ProxyConfig(
        proxy=ProxySettings(
            runtime_store_backend="custom-test",
            recent_requests_max_items=7,
            recent_errors_max_items=3,
        )
    )

    stores = configure_runtime_stores(state, config=config)

    assert stores.backend is not None
    assert stores.backend.name == "custom-test"
    assert stores.backend.mapping_names == ["files", "batches", "responses"]
    assert stores.backend.feed_names == [
        ("recent_requests", 7),
        ("recent_errors", 3),
    ]
