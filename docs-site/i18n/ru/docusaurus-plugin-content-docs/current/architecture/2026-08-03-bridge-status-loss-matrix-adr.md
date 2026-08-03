# ADR: статусы protocol/provider и loss matrix

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владельцы решения: направления bridge-matrix и integration
- Схема матрицы: `gpt2giga.bridge-loss-matrix.v1`
- Схема manifest: `gpt2giga.bridge-capabilities.v1`

## Контекст

Нормализованная v1-матрица описывает проекцию features в downstream wire
protocols. Релизу также нужна матрица «public protocol × upstream provider».
Каждая ячейка обязана точно описывать безопасный поднабор; отсутствие или
`unknown` не является релизным состоянием.

## Решение

### Identity матрицы

Матрица содержит ровно четыре публичных протокола:
`openai_responses`, `openai_chat_completions`, `anthropic_messages`,
`gemini_generate_content`; и четыре upstream provider kind: `gigachat`,
`openai_compatible`, `anthropic`, `gemini`.

Каждая из 16 ячеек имеет один статус:

- `stable` — version-windowed corpus и hermetic release E2E доказывают subset;
- `technical_preview` — subset протестирован, но имеет документированную
  semantic loss или повышенный риск upstream drift;
- `blocked` — безопасного пути нет, admission отклоняет до I/O.

`unknown`, пропущенные ячейки, implicit defaults и общие заявления об
эквивалентности недопустимы.

### Ячейки и semantic rows

Ячейка хранит `status`, `reasons`, `evidence_ids`, окна client/provider versions
и полную semantic table. Обязательны rows для roles, multimodal, tools/call ids,
tool results, parallel calls, JSON Schema, stream lifecycle, usage/cache/
reasoning tokens, stop/refusal/safety, reasoning, previous-response state,
files/images, hosted tools, cancellation, timeout, malformed stream и disconnect.

Каждая row имеет `exact`, `conditional` или `unsupported`. `conditional`
указывает точный predicate capability profile. `blocked` ячейка может объяснять
потери, но не может исполняться.

### Ревизия и admission

Secret-free matrix канонизируется как provider profiles; `matrix_revision` —
`sha256:<lowercase-hex>`. Semantic status/reasons/version windows/evidence ids
входят в digest, runtime health и редакционное форматирование — нет.

До credentials и network выполняется:

1. точное разрешение публичного alias;
2. выбор protocol/provider cell;
3. отклонение `blocked` cell;
4. вывод requested semantic rows из normalized request;
5. проверка `exact` либо named capability predicate;
6. content-free admission record с config/profile/matrix revisions;
7. dispatch ровно одного provider adapter.

Lossy downgrade и provider/model fallback запрещены. Отказ —
`unsupported_semantic` с public field path и bounded reason id.

### Machine projection

`GET /bridge/capabilities` отдаёт все 16 ячеек в стабильном лексическом порядке
без prompts, response bodies, credentials, userinfo и live provider data. Этот
endpoint не обращается к upstream.

## Миграция и откат

- `PROTOCOL_LOSS_MATRIX_V1` остаётся внутренним input до замены projection.
- Ячейки без evidence начинаются как `blocked`.
- Откат 0.2.x удаляет endpoint/admission layer; matrix files остаются inert.
