# AGENTS.md — tests/

## Package Identity

- **What:** pytest suite for the `gpt2giga` proxy server
- **Framework:** `pytest`, `pytest-asyncio`, `pytest-mock`, `pytest-cov`
- **Coverage target:** `>= 80%`

## Run Commands

```bash
# Full suite
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80

# Useful focused runs
uv run pytest tests/test_api_server/test_api_server.py
uv run pytest tests/test_router/test_router_batches.py
uv run pytest tests/test_router/test_anthropic_router.py
uv run pytest tests/test_protocol/test_protocol.py

# Marker-based runs
uv run pytest -m unit
uv run pytest -m integration
```

## Test Layout

| Path | What It Covers |
|---|---|
| `tests/test_api_server/` | App factory, lifespan, middleware/router wiring |
| `tests/test_cli/` | CLI config loading and secret-warning behavior |
| `tests/test_config/` | `ProxySettings` and `ProxyConfig` parsing/validation |
| `tests/test_protocol/` | Request/response transforms, attachments, schema handling, edge cases |
| `tests/test_router/` | OpenAI, Anthropic, system, and batch endpoint behavior |
| `tests/test_utils/` | Shared helpers in `gpt2giga.common.*` |
| `tests/test_auth.py` | API-key auth dependency |
| `tests/test_logger.py` | Logger setup and redaction |
| `tests/test_middleware.py` | Path normalization and token middleware |
| `tests/test_embeddings_variants.py` | Embeddings input-shape variants |

## Patterns & Conventions

- Mirror the source behavior being tested; keep router, protocol, and helper coverage separated when practical.
- Prefer standalone `test_*` functions over test classes.
- Mock all upstream GigaChat interactions; tests should stay hermetic.
- Build small `FastAPI()` apps in router tests and mount only the routers under test.
- Reuse existing dummy-client and mocked-response patterns instead of introducing live API calls.

## Example Patterns

### Endpoint Tests

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.api.openai import router as openai_router
from gpt2giga.api.system import system_router

app = FastAPI()
app.include_router(openai_router)
app.include_router(system_router)


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
```

### Async Protocol Tests

```python
import pytest
from loguru import logger

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer


@pytest.mark.asyncio
async def test_transformer_merges_messages():
    config = ProxyConfig()
    attachments = AttachmentProcessor(logger)
    transformer = RequestTransformer(config, logger, attachments)
    data = {
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "world"},
        ]
    }

    chat = await transformer.prepare_chat_completion(data)
    assert len(chat.messages) == 1
```

## Markers

Defined in `pytest.ini`:

- `unit`
- `integration`
- `slow`

## Quick Find Commands

```bash
# Find async tests
rg -n "@pytest.mark.asyncio|async def test_" tests

# Find router tests for a route family
rg -n "batches|anthropic|responses|embeddings" tests/test_router

# Find tests touching common helpers
rg -n "gpt2giga.common" tests/test_utils

# Find mock usage
rg -n "mocker|MagicMock|AsyncMock|patch" tests
```

## Common Gotchas

- Async auto-mode is enabled in `pytest.ini`, but explicit `@pytest.mark.asyncio` is still preferred for clarity.
- There is no shared `conftest.py`; most fixtures live close to the tests that use them.
- Coverage excludes `tests/`, `scripts/`, `docs/`, and `examples/`.
- Batch and file behavior rely on in-memory stores in app state; tests should initialize or mock that state explicitly when needed.

## Pre-PR Check

```bash
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```
