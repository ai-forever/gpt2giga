# ADR: статусы protocol/provider и loss matrix

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владельцы решения: направления bridge-matrix и integration
- Схема матрицы: `gpt2giga.bridge-loss-matrix.v1`
- Схема route manifest: `gpt2giga.route-support-matrix.v1`
- Схема effective capabilities: `gpt2giga.effective-capabilities.v1`

## Контекст

Нормализованная v1-матрица описывает проекцию features в downstream wire
protocols. Релизу также нужна матрица «public protocol × upstream provider».
Эта route matrix является coarse maturity view, а не model inventory или
effective capability answer выбранной model.

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

`unknown` недопустим для route maturity cells, которые должны быть
классифицированы до релиза. Но model-level capability без evidence обязана
оставаться явным tri-state `unknown`. Пропущенные cells, implicit defaults и
общие заявления об эквивалентности недопустимы.

Матрица описывает зрелость normalized routes. Native GigaChat Responses —
stable compatibility owner вне normalized matrix. Ячейка normalized OpenAI
Responses → GigaChat остаётся `technical_preview`, пока attachments и остаток
accepted native corpus не получат end-to-end normalized parity.

### Ячейки и semantic rows

Ячейка хранит `status`, `reasons`, `evidence_ids`, окна client/provider versions
и полную semantic table. Обязательны rows для roles, multimodal, tools/call ids,
tool results, parallel calls, JSON Schema, stream lifecycle, usage/cache/
reasoning tokens, stop/refusal/safety, reasoning, previous-response state,
files/images, hosted tools, cancellation, timeout, malformed stream и disconnect.

Каждая coarse row имеет `exact`, `conditional` или `unsupported`.
`conditional` делегирует решение effective capability resolver для selected
model и API mode. Resolver объединяет public protocol, provider adapter, model
evidence, API mode и route policy. Effective decision имеет состояние
`supported`, `unsupported` или `unknown` и сохраняет reason/source/evidence/
revision identifiers.

### Ревизия и admission

Secret-free matrix канонизируется как provider profiles; `matrix_revision` —
`sha256:<lowercase-hex>`. Semantic status/reasons/version windows/evidence ids
входят в digest, runtime health и редакционное форматирование — нет.

До credentials и network выполняется:

1. разрешение immutable provider route;
2. разрешение selected model из общего catalog;
3. выбор protocol/provider cell и отклонение `blocked` route;
4. разрешение effective model/API-mode capabilities;
5. вывод requested semantic rows без потери recognized intent;
6. применение явной policy для `unknown` и отклонение unsupported semantics;
7. content-free admission record с config/profile/inventory/matrix revisions;
8. dispatch ровно одного provider adapter.

Lossy downgrade и provider/model fallback запрещены. Отказ —
`unsupported_semantic` с public field path и bounded reason id.

### Machine projection

`GET /bridge/capabilities` без model query отдаёт 16-cell route manifest. Query
с model/protocol/API-mode отдаёт effective tri-state projection с inventory и
capability revisions. Проекции не содержат prompts, response bodies,
credentials, userinfo или raw provider data.

## Миграция и откат

- `PROTOCOL_LOSS_MATRIX_V1` остаётся внутренним input до замены projection.
- Ячейки без evidence начинаются как `blocked`.
- Откат 0.2.x удаляет endpoint/admission layer; matrix files остаются inert.
