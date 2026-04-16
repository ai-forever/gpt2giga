# Refactor Worklog

Этот файл ведётся как отдельный журнал выполненной работы по текущей волне рефакторинга.

## Правила ведения

- После каждого завершённого slice или milestone записывать, что изменено, чем проверено и каким коммитом это зафиксировано.
- Не считать работу завершённой, пока изменения не отражены и здесь, и в [PLANS.md](/Users/riyakupov/code_projects/gpt2giga/docs/PLANS.md).

## Entries

- 2026-04-16 — `Milestone 2`
  - `gpt2giga/features/responses/stream.py` превращён в thin compatibility facade с сохранением public import path.
  - Внутренняя реализация Responses streaming разложена по `gpt2giga/features/responses/_streaming/{events,state,v1,v2,failures}.py`.
  - `ResponsesStreamEventSequencer` вынесен отдельно; legacy v1 flow и v2 orchestration разнесены по разным internal modules.
  - V2 mutable stream state оформлен через typed state objects для text/function/tool веток, включая tool progress и image-generation hydration.
  - Добавлен targeted test на re-export `gpt2giga.features.responses.stream` поверх internal implementation.
  - Проверка: `uv run ruff check gpt2giga/features/responses tests/unit/api/openai/test_stream_generators.py`; `uv run ruff format --check gpt2giga/features/responses tests/unit/api/openai/test_stream_generators.py`; `uv run pytest tests/unit/api/openai/test_stream_generators.py -q`; `uv run pytest tests/integration/openai/test_router_endpoints.py -q`; `uv run pytest tests/unit/providers/gigachat/test_responses_v2.py -q`.
  - Commit: `refactor: split responses streaming implementation`.

- 2026-04-16 — `Milestone 1`
  - Вынесены общие SSE formatter helpers в `gpt2giga/core/http/sse.py`.
  - `gpt2giga/api/openai/streaming.py` оставлен как compatibility facade.
  - `gpt2giga/features/chat/stream.py` и `gpt2giga/features/responses/stream.py` переведены на нейтральный import path.
  - Добавлен targeted test на реэкспорт и сохранение старого import path.
  - Проверка: `uv run ruff check .github/workflows tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`; `uv run ruff format --check tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`; `uv run pytest tests/unit/api/openai/test_stream_generators.py tests/integration/openai/test_router_endpoints.py -q`; `uv run pytest tests/unit -q`.
  - Commit: `refactor: move openai sse formatting out of transport layer`.

- 2026-04-16 — `Milestone 0`
  - Добавлен отдельный CI job для сборки admin frontend через `npm ci` и `npm run build:admin`.
  - Исправлена публикация Docker tags: plain version и `latest` теперь публикуются только canonical matrix job.
  - Canonical Python для plain version и `latest` tags зафиксирован как `3.13` для Docker Hub и GHCR.
  - Расширены workflow `paths:` для UI package и frontend build-конфигов.
  - Добавлен AST-based architecture guardrail test против зависимости `features/**` и `providers/**` от `gpt2giga.api.openai.streaming`.
  - Удалены локальные директории `.ipynb_checkpoints/`.
  - В `AGENTS.md` и `docs/PLANS.md` закреплено обязательное правило отдельного commit после каждого завершённого зелёного slice.
  - Создан этот отдельный журнал и добавлены записи о выполненной работе.
  - Проверка: `npm ci`; `npm run build:admin`; `uv run ruff check .github/workflows tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`; `uv run ruff format --check tests gpt2giga/core/http gpt2giga/api/openai/streaming.py gpt2giga/features/chat/stream.py gpt2giga/features/responses/stream.py`; `uv run pytest tests/unit -q`; `git diff --check`.
  - Commit: `ci: add frontend build and docker publish guardrails`.

- 2026-04-16 — follow-up slice
  - В `.github/workflows/docker_image.yaml` canonical Docker Hub job для plain version и `latest` tags перенесён с Python `3.12` на Python `3.13`.
  - Проверка: `git diff --check`.
  - Commit: `ci: align docker latest tags with python 3.13`.
