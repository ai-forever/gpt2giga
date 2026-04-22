from types import SimpleNamespace

from gpt2giga.app._runtime_backends import (
    ConfigurableRuntimeStateBackend,
    InMemoryRuntimeStateBackend,
    RuntimeBackendDescriptor,
    RuntimeStateBackend,
    SqliteRuntimeStateBackend,
    register_runtime_backend,
)
from gpt2giga.app.dependencies import (
    configure_runtime_stores,
    ensure_runtime_dependencies,
)
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


class _FakeFeed:
    def __init__(self):
        self.items = []

    def append(self, item):
        self.items.append(item)

    def recent(self, *, limit=None):
        return self.items if limit is None else self.items[-limit:]

    def query(self, *, limit=None, filters=None):
        items = self.recent(limit=limit)
        if not filters:
            return items
        return [
            item
            for item in items
            if all(item.get(key) == value for key, value in filters.items())
        ]

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


class _ScaffoldBackend(ConfigurableRuntimeStateBackend):
    name = "scaffold-test"

    def mapping(self, name):
        return {}

    def feed(self, name, *, max_items):
        return _FakeFeed()


def test_runtime_backend_exports_come_from_internal_package():
    assert RuntimeStateBackend.__module__ == "gpt2giga.app._runtime_backends.contracts"
    assert (
        ConfigurableRuntimeStateBackend.__module__
        == "gpt2giga.app._runtime_backends.contracts"
    )
    assert (
        InMemoryRuntimeStateBackend.__module__
        == "gpt2giga.app._runtime_backends.memory"
    )
    assert (
        SqliteRuntimeStateBackend.__module__ == "gpt2giga.app._runtime_backends.sqlite"
    )


def test_ensure_runtime_dependencies_configures_memory_backend_resources():
    state = SimpleNamespace()

    ensure_runtime_dependencies(state, config=ProxyConfig())

    assert state.stores.backend is not None
    assert state.stores.backend.name == "memory"
    assert state.stores.files == {}
    assert state.stores.batches == {}
    assert state.stores.responses == {}
    assert state.stores.usage_by_api_key == {}
    assert state.stores.usage_by_provider == {}
    assert state.stores.governance_counters == {}
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
    assert stores.backend.mapping_names == [
        "files",
        "batches",
        "responses",
        "usage_by_api_key",
        "usage_by_provider",
        "governance_counters",
    ]
    assert stores.backend.feed_names == [
        ("recent_requests", 7),
        ("recent_errors", 3),
    ]


def test_sqlite_runtime_backend_persists_mappings_and_feeds(tmp_path):
    database_path = tmp_path / "runtime.sqlite3"
    config = ProxyConfig(
        proxy=ProxySettings(
            runtime_store_backend="sqlite",
            runtime_store_dsn=str(database_path),
            runtime_store_namespace="tests",
            recent_requests_max_items=3,
        )
    )
    first_state = SimpleNamespace()
    first_stores = configure_runtime_stores(first_state, config=config)

    first_stores.files["file-1"] = {"id": "file-1", "purpose": "batch"}
    first_stores.usage_by_api_key["global"] = {
        "name": "global",
        "request_count": 2,
        "total_tokens": 15,
    }
    first_stores.governance_counters["governance:0:openai:1712810400"] = {
        "request_count": 1,
        "total_tokens": 15,
        "window_started_at": 1712810400,
        "window_ends_at": 1712810460,
    }
    first_stores.recent_requests.append(
        {
            "request_id": "req-1",
            "provider": "openai",
            "endpoint": "/chat/completions",
            "method": "POST",
            "status_code": 200,
            "model": "gpt-4.1-mini",
            "error_type": None,
        }
    )
    first_stores.recent_requests.append(
        {
            "request_id": "req-2",
            "provider": "gemini",
            "endpoint": "/v1beta/models/gemini:generateContent",
            "method": "POST",
            "status_code": 429,
            "model": "gemini-2.5-pro",
            "error_type": "RateLimitError",
        }
    )

    second_state = SimpleNamespace()
    second_stores = configure_runtime_stores(second_state, config=config)

    assert second_stores.backend is not None
    assert second_stores.backend.name == "sqlite"
    assert second_stores.files["file-1"] == {"id": "file-1", "purpose": "batch"}
    assert second_stores.usage_by_api_key["global"] == {
        "name": "global",
        "request_count": 2,
        "total_tokens": 15,
    }
    assert second_stores.governance_counters["governance:0:openai:1712810400"] == {
        "request_count": 1,
        "total_tokens": 15,
        "window_started_at": 1712810400,
        "window_ends_at": 1712810460,
    }
    assert second_stores.recent_requests.recent() == [
        {
            "request_id": "req-1",
            "provider": "openai",
            "endpoint": "/chat/completions",
            "method": "POST",
            "status_code": 200,
            "model": "gpt-4.1-mini",
            "error_type": None,
        },
        {
            "request_id": "req-2",
            "provider": "gemini",
            "endpoint": "/v1beta/models/gemini:generateContent",
            "method": "POST",
            "status_code": 429,
            "model": "gemini-2.5-pro",
            "error_type": "RateLimitError",
        },
    ]
    assert second_stores.recent_requests.query(
        limit=10,
        filters={
            "provider": "gemini",
            "status_code": 429,
            "error_type": "RateLimitError",
        },
    ) == [
        {
            "request_id": "req-2",
            "provider": "gemini",
            "endpoint": "/v1beta/models/gemini:generateContent",
            "method": "POST",
            "status_code": 429,
            "model": "gemini-2.5-pro",
            "error_type": "RateLimitError",
        }
    ]


def test_sqlite_runtime_backend_prunes_feed_capacity(tmp_path):
    config = ProxyConfig(
        proxy=ProxySettings(
            runtime_store_backend="sqlite",
            runtime_store_dsn=str(tmp_path / "runtime.sqlite3"),
            runtime_store_namespace="tests",
            recent_requests_max_items=2,
        )
    )
    state = SimpleNamespace()
    stores = configure_runtime_stores(state, config=config)

    stores.recent_requests.append({"request_id": "req-1", "status_code": 200})
    stores.recent_requests.append({"request_id": "req-2", "status_code": 200})
    stores.recent_requests.append({"request_id": "req-3", "status_code": 200})

    assert stores.recent_requests.recent() == [
        {"request_id": "req-2", "status_code": 200},
        {"request_id": "req-3", "status_code": 200},
    ]


def test_configurable_runtime_backend_descriptor_uses_shared_proxy_config():
    config = ProxyConfig(
        proxy=ProxySettings(
            runtime_store_dsn="redis://redis:6379/0",
            runtime_store_namespace="backend-tests",
        )
    )

    descriptor = _ScaffoldBackend.descriptor(description="Scaffold backend")
    backend = descriptor.factory(config=config, logger="logger")

    assert isinstance(backend, _ScaffoldBackend)
    assert backend.dsn == "redis://redis:6379/0"
    assert backend.namespace == "backend-tests"
    assert backend.logger == "logger"
