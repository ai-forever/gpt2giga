# Совместимость API

Этот документ описывает, какие route-группы OpenAI, Anthropic и Gemini действительно поддерживаются в `gpt2giga`, а какие пока не входят в scope проекта.

## Базовые правила маршрутизации

- OpenAI-compatible маршруты доступны и без префикса, и с префиксом `/v1`, например `/chat/completions` и `/v1/chat/completions`.
- Anthropic-compatible маршруты публикуются под путями `/messages*`.
- Gemini Developer API-compatible маршруты публикуются под префиксом `/v1beta`.

## Короткая сводка

- OpenAI: `Stable` для основного proxy-набора `models`, `chat/completions`, `embeddings`, `files`, `batches`; `Partial` для частей `responses`; legacy и non-proxy surface остаются `Unsupported`.
- Anthropic: `Stable` для `Messages API`, `count_tokens` и create/read batch flows; `Partial` для batch cancel/delete.
- Gemini: `Stable` для core `models`, `generateContent`, `streamGenerateContent`, `countTokens`, embeddings, files и batch read/create flows; `Partial` для metadata-only file create и batch cancel/delete.
- Не цель проекта: полная реализация всех route официальных OpenAI, Anthropic и Gemini API, включая fine-tuning, images, audio, vector stores, assistants и realtime.

## Как читать support levels

- `Stable` — route или surface входит в основной 1.0 contract для proxy-use-cases.
- `Partial` — route опубликован, но часть официального поведения отсутствует, ограничена или может возвращать `501`.
- `Unsupported` — route не реализован и не входит в promise релизной линии `1.0`.

## OpenAI-compatible API

| Route / группа | Support level | Официальный OpenAI API | В gpt2giga | Что поддерживается |
|---|---|---|---|---|
| `POST /chat/completions` | `Stable` | Да | Да | Основной чатовый endpoint, включая `stream=true`, tools/function calling, structured outputs и вложения |
| `GET /models` | `Stable` | Да | Да | Список доступных моделей GigaChat в OpenAI-совместимом виде |
| `GET /models/{model}` | `Stable` | Да | Да | Информация по конкретной модели |
| `POST /embeddings` | `Stable` | Да | Да | Создание embeddings через модель из настроек proxy |
| `POST /responses` | `Partial` | Да | Да | OpenAI Responses API, включая `previous_response_id`, `conversation.id`, structured outputs и best-effort built-in tools |
| `POST /files` | `Stable` | Да | Да | Загрузка файлов |
| `GET /files` | `Stable` | Да | Да | Список файлов |
| `GET /files/{file_id}` | `Stable` | Да | Да | Метаданные файла |
| `DELETE /files/{file_id}` | `Stable` | Да | Да | Удаление файла |
| `GET /files/{file_id}/content` | `Stable` | Да | Да | Получение содержимого файла |
| `POST /batches` | `Stable` | Да | Да | Создание batch-задачи |
| `GET /batches` | `Stable` | Да | Да | Список batch-задач |
| `GET /batches/{batch_id}` | `Stable` | Да | Да | Получение batch-задачи |
| `GET /model/info` | `Stable` | Нет | Да | LiteLLM-compatible endpoint для model metadata и автодополнения моделей |
| `GET/POST /chat/completions` stored-completions routes | `Unsupported` | Да | Нет | Маршруты для хранения, выборки и обновления сохранённых chat completions не реализованы |
| `POST /completions` | `Unsupported` | Да | Нет | Legacy Completions API не реализован |
| `POST /images*` | `Unsupported` | Да | Нет | Генерация и редактирование изображений не реализованы |
| `POST /audio*` | `Unsupported` | Да | Нет | Speech, transcription и translation не реализованы |
| `POST /moderations` | `Unsupported` | Да | Нет | Moderations API не реализован |
| `POST /uploads*` | `Unsupported` | Да | Нет | Uploads API не реализован |
| `POST /fine_tuning*` | `Unsupported` | Да | Нет | Fine-tuning API не реализован |
| `POST /assistants*`, `POST /threads*`, `POST /runs*` | `Unsupported` | Да | Нет | Assistants, Threads и Runs API не реализованы |
| `POST /vector_stores*` | `Unsupported` | Да | Нет | Vector Stores API не реализован |
| `Realtime API` | `Unsupported` | Да | Нет | Realtime/WebSocket API не реализован |

## Anthropic-compatible API

| Route / группа | Support level | Официальный Anthropic API | В gpt2giga | Что поддерживается |
|---|---|---|---|---|
| `POST /messages` | `Stable` | Да | Да | Основной Messages API, включая стриминг, tool use и extended thinking |
| `POST /messages/count_tokens` | `Stable` | Да | Да | Подсчёт токенов для Messages API |
| `POST /messages/batches` | `Stable` | Да | Да | Создание message batch |
| `GET /messages/batches` | `Stable` | Да | Да | Список message batches |
| `GET /messages/batches/{message_batch_id}` | `Stable` | Да | Да | Получение message batch |
| `GET /messages/batches/{message_batch_id}/results` | `Stable` | Да | Да | Получение результатов batch |
| `POST /messages/batches/{message_batch_id}/cancel` | `Partial` | Да | Частично | Route есть, но сейчас возвращает `501`, потому что backend GigaChat не поддерживает отмену batch |
| `DELETE /messages/batches/{message_batch_id}` | `Partial` | Да | Частично | Route есть, но сейчас возвращает `501`, потому что backend GigaChat не поддерживает удаление batch |
| Другие route Anthropic API | `Unsupported` | Частично | Нет | Отдельной реализации вне Messages API и Message Batches API нет |

## Gemini Developer API-compatible API

| Route / группа | Support level | Официальный Gemini API | В gpt2giga | Что поддерживается |
|---|---|---|---|---|
| `GET /v1beta/models` | `Stable` | Да | Да | Список доступных моделей GigaChat в Gemini-совместимом виде |
| `GET /v1beta/models/{model}` | `Stable` | Да | Да | Информация по конкретной модели |
| `POST /v1beta/models/{model}:generateContent` | `Stable` | Да | Да | Генерация текста, multi-turn contents, function calling и structured output |
| `POST /v1beta/models/{model}:streamGenerateContent` | `Stable` | Да | Да | Data-only SSE streaming в Gemini-совместимом формате |
| `POST /v1beta/models/{model}:countTokens` | `Stable` | Да | Да | Подсчёт токенов для `contents` и `generateContentRequest` |
| `POST /v1beta/files` | `Partial` | Да | Да | Multipart file upload. Metadata-only JSON create сейчас не поддерживается и возвращает `501` |
| `POST /upload/v1beta/files` | `Stable` | Да | Да | Resumable upload flow для Gemini Files API |
| `GET /v1beta/files` | `Stable` | Да | Да | Список файлов |
| `GET /v1beta/files/{file}` | `Stable` | Да | Да | Метаданные файла |
| `GET /v1beta/files/{file}:download` | `Stable` | Да | Да | Скачивание содержимого файла |
| `DELETE /v1beta/files/{file}` | `Stable` | Да | Да | Удаление файла |
| `POST /v1beta/models/{model}:batchGenerateContent` | `Stable` | Да | Да | Создание Gemini batch job поверх GigaChat |
| `GET /v1beta/batches` | `Stable` | Да | Да | Список batch jobs |
| `GET /v1beta/batches/{batch}` | `Stable` | Да | Да | Получение batch job |
| `GET /v1beta/batches/{batch}:download` | `Stable` | Да | Да | Выгрузка результатов batch job в JSONL для local testing/debugging |
| `POST /v1beta/batches/{batch}:cancel` | `Partial` | Да | Частично | Route есть, но сейчас возвращает `501`, потому что backend GigaChat не поддерживает отмену batch |
| `DELETE /v1beta/batches/{batch}` | `Partial` | Да | Частично | Route есть, но сейчас возвращает `501`, потому что backend GigaChat не поддерживает удаление batch |
| `POST /v1beta/models/{model}:batchEmbedContents` | `Stable` | Да | Да | Embeddings через модель, настроенную на стороне proxy |
| `POST /v1beta/models/{model}:embedContent` | `Stable` | Да | Да | Single-input alias для embeddings |
| built-in Google tools и часть file-backed сценариев | `Unsupported` | Частично | Нет | Built-in Google tools и не-реализованные части Gemini surface остаются вне scope |
| Другие route Gemini API | `Unsupported` | Частично | Нет | Отдельной реализации вне перечисленных выше route нет |

## Практические ограничения

- Поддержка строится вокруг реальных proxy-use-cases, а не вокруг полного зеркала upstream API.
- Некоторые route доступны, но часть операций может возвращать `501`, если самого backend-эквивалента в GigaChat нет. Такие случаи помечены как `Partial`, а не как полноценный `Stable` contract.
- Поддерживаемый surface лучше проверять по capability, а не по бренду API: например, у OpenAI-compatible части есть `responses`, `files` и `batches`, а у Anthropic-compatible части сейчас основной акцент на `messages`.

## Смежные документы

- Общий обзор проекта: [../README.md](../README.md)
- Конфигурация и auth: [configuration.md](./configuration.md)
- Operator-сценарии: [operator-guide.md](./operator-guide.md)
- SDK-примеры: [../examples/README.md](../examples/README.md)
