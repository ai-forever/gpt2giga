# AGENTS.md — tests/

## Package Identity

- **What:** Test suite for the gpt2giga proxy server
- **Framework:** pytest + pytest-asyncio + pytest-mock + pytest-cov
- **Coverage target:** ≥ 80% (enforced in CI)

## Run Commands

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80

# Run a single test file
uv run pytest tests/test_router/test_router.py

# Run a single test function
uv run pytest tests/test_router/test_router.py::test_health_endpoint

# Run only unit tests
uv run pytest -m unit

# Run only integration tests
uv run pytest -m integration

# Verbose output with short traceback
uv run pytest -v --tb=short
```

## Test Organization

Tests mirror the source structure:

| Test Directory/File | Source Module | What It Tests |
|---|---|---|
| `test_api_server/test_api_server.py` | `api_server.py` | App creation, factory, CORS, router registration |
| `test_api_server/test_api_server_lifespan.py` | `api_server.py` | Startup/shutdown lifecycle, state init |
| `test_cli/test_cli.py` | `cli.py` | CLI argument parsing, env file loading, boolean flags |
| `test_config/test_config.py` | `config.py` | Configuration loading, env var parsing, defaults |
| `test_protocol/test_protocol.py` | `protocol/` | Core request/response transformation, message collapsing, tools→functions |
| `test_protocol/test_protocol_attachments.py` | `protocol/attachments.py` | Image upload, caching (TTL, LRU), error handling |
| `test_protocol/test_protocol_attachments_success.py` | `protocol/attachments.py` | Attachment success paths |
| `test_protocol/test_protocol_messages_attachments.py` | `protocol/` | Message attachment handling |
| `test_protocol/test_protocol_response_format.py` | `protocol/response_mapper.py` | Response format transformation |
| `test_protocol/test_protocol_transform_params.py` | `protocol/request_mapper.py` | Parameter transformation |
| `test_protocol/test_request_mapper_extra.py` | `protocol/request_mapper.py` | Request mapping edge cases |
| `test_protocol/test_responseprocessor_exceptions.py` | `protocol/response_mapper.py` | Response processor error handling |
| `test_router/test_router.py` | `routers/` | Endpoint basics (health, ping), 404/405 |
| `test_router/test_router_chat_nonstream.py` | `routers/api_router.py` | Non-streaming chat completions |
| `test_router/test_router_stream_chat.py` | `routers/api_router.py` | Streaming chat completions |
| `test_router/test_router_models.py` | `routers/api_router.py` | Model listing endpoint |
| `test_router/test_router_endpoints.py` | `routers/api_router.py` | Endpoint integration (embeddings, responses) |
| `test_router/test_system_router_extra.py` | `routers/system_router.py` | System router edge cases |
| `test_router/test_anthropic_router.py` | `routers/anthropic_router.py` | Anthropic Messages API (tools, streaming, thinking) |
| `test_utils/test_utils.py` | `utils.py` | Utility functions, exception handler |
| `test_utils/test_convert_tools.py` | `utils.py` | Tool conversion, JSON schema normalization |
| `test_utils/test_stream_generators.py` | `utils.py` | Stream generators (chat, responses), SSE events |
| `test_utils/test_utils_exceptions_branch.py` | `utils.py` | Exception handling branches |
| `test_utils/test_utils_extra.py` | `utils.py` | Additional utility edge cases |
| `test_auth.py` | `auth.py` | API key verification (Bearer, X-API-Key) |
| `test_middleware.py` | `middlewares/` | Path normalization, token passing |
| `test_logger.py` | `logger.py` | Logger setup, log levels |
| `test_embeddings_variants.py` | `routers/api_router.py` | Embeddings (string, token IDs, list of lists) |

## Patterns & Conventions

### Test File Naming

- Files: `test_<module_name>.py` or `test_<module>_<aspect>.py`
- Classes: `Test<Feature>` (rarely used — prefer standalone functions)
- Functions: `test_<what_is_tested>`

### Writing a New Test

```
✅ DO: Copy pattern from `test_router/test_router.py` for endpoint tests
✅ DO: Copy pattern from `test_protocol/test_protocol.py` for transformation tests
✅ DO: Copy pattern from `test_utils/test_utils.py` for utility function tests
```

### Endpoint Test Pattern

Use `FastAPI` + `TestClient` for synchronous endpoint tests:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gpt2giga.routers import api_router, system_router

app = FastAPI()
app.include_router(api_router)
app.include_router(system_router)

def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
```

### Async Test Pattern

Use `@pytest.mark.asyncio` for async tests (auto-mode is enabled in `pytest.ini`):

```python
import pytest
from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer
from loguru import logger

@pytest.mark.asyncio
async def test_request_transformer_collapse_messages():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "world"},
    ]
    data = {"messages": messages}
    chat = await rt.send_to_gigachat(data)
    assert len(chat["messages"]) == 1
```

### Mocking

- Use `pytest-mock` fixtures (`mocker`) for patching.
- Mock `GigaChat` client methods (`achat`, `astream`, `aembeddings`) — never call real API in tests.
- Use `DummyClient` pattern (see `test_protocol/test_protocol.py`) for lightweight stubs.

```
❌ DON'T: Put “tests” under `local/` (e.g. `local/concurrency_test.py`) — CI only runs `tests/`
❌ DON'T: Turn the unit test suite into live API experiments (keep experiments in `local/gigachat_so_testing.py`, mock in `tests/`)
```

### Markers

Defined in `pytest.ini`:

- `@pytest.mark.unit` — fast, isolated unit tests
- `@pytest.mark.integration` — tests requiring more setup
- `@pytest.mark.slow` — long-running tests

## JIT Search Hints

```bash
# Find all test functions
rg -n "^def test_|^async def test_" tests/

# Find tests for a specific module
rg -rn "from gpt2giga.protocol" tests/

# Find tests using mock
rg -n "mocker|mock|patch|MagicMock" tests/

# Find async tests
rg -n "@pytest.mark.asyncio|async def test_" tests/

# Find tests by marker
rg -n "@pytest.mark.unit|@pytest.mark.integration" tests/
```

## Common Gotchas

- `--asyncio-mode=auto` is set in `pytest.ini` — async tests are auto-detected, but `@pytest.mark.asyncio` is still recommended for clarity.
- No shared `conftest.py` — each test file sets up its own fixtures inline.
- Coverage omits `tests/`, `scripts/`, `examples/` (configured in `pyproject.toml`).
- When testing router endpoints, create a fresh `FastAPI()` app and include only needed routers.

## Pre-PR Check

```bash
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```
