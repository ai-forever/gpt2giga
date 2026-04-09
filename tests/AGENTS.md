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
uv run pytest tests/integration/app/test_api_server.py
uv run pytest tests/integration/openai/test_router_batches.py
uv run pytest tests/integration/anthropic/test_anthropic_router.py
uv run pytest tests/unit/providers/gigachat/test_protocol_compat.py

# Marker-based runs
uv run pytest -m unit
uv run pytest -m integration
```

## Test Layout

| Path | What It Covers |
|---|---|
| `tests/unit/core/` | Config, logging, CLI parsing, and other core runtime helpers |
| `tests/unit/api/` | Shared API dependencies, middleware, exception handling |
| `tests/unit/api/openai/` | OpenAI transport helpers such as streaming and batch-format mapping |
| `tests/unit/features/` | Capability services and store/accessor behavior for chat, responses, files, batches, embeddings, models |
| `tests/unit/providers/gigachat/` | GigaChat request/response mapping, attachments, tool/schema helpers, compatibility facades |
| `tests/integration/app/` | App factory, lifespan, and system-route wiring |
| `tests/integration/openai/` | OpenAI-compatible endpoint behavior |
| `tests/integration/anthropic/` | Anthropic-compatible endpoint behavior |
| `tests/integration/gemini/` | Gemini-compatible endpoint behavior |
| `tests/smoke/` | App-boot and Starlette baseline smoke suites |

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

### Async Mapping Tests

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
    assert len(chat["messages"]) == 1
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

# Find integration tests for a route family
rg -n "batches|anthropic|responses|embeddings" tests/integration

# Find provider-mapper tests
rg -n "RequestTransformer|ResponseProcessor|AttachmentProcessor" tests/unit/providers/gigachat

# Find mock usage
rg -n "mocker|MagicMock|AsyncMock|patch" tests
```

## Common Gotchas

- Async auto-mode is enabled in `pytest.ini`, but explicit `@pytest.mark.asyncio` is still preferred for clarity.
- `tests/conftest.py` auto-applies `unit` to `tests/unit/**` and `integration` to both `tests/integration/**` and `tests/smoke/**`.
- Coverage excludes `tests/`, `scripts/`, `docs/`, and `examples/`.
- Batch and file behavior rely on in-memory stores in app state; tests should initialize or mock that state explicitly when needed.

## Pre-PR Check

```bash
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```
