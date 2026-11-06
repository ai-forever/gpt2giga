# Files и пакетные ресурсы

Три протокола используют [единое устойчивое хранилище](configuration.md): SQLite metadata и ограниченные blobs. Для restart/multiworker нужен общий persistent volume. Namespace включает доверенную identity, provider/profile и credentials; смена opaque pass-token меняет namespace. Anonymous mode означает одного общего владельца.

## Files

OpenAI upload/list/retrieve/content/delete доступны на root, /v1, /v2. Исходные purpose, filename и MIME сохраняются после restart. Native документы сохраняют upstream ID; content возвращается как bytes. Старые неизвестные upstream IDs обслуживаются под credentials запроса, а утраченные ранее metadata не восстанавливаются выдуманными значениями. Batch JSONL хранится локально с ID file_g2g_..., не отправляется в document upload и не может стать attachment.

Общий /files выбирает Anthropic только по anthropic-version/anthropic-beta; x-api-key не является признаком протокола. Upload требует только file. Metadata содержит size_bytes, MIME и RFC3339 created_at. Пользовательские uploads не объявляются downloadable; generated batch output допускает download. Custom scope/expiry отклоняются. Messages принимает user document/image с source.type=file и file_id; ownership/MIME проверяются до native attachment. Прочие document source forms отклоняются.

Default/2023-06-01 Files использует after_id/limit; явная 2026-10-21 — page/next_page с limit. Models pagination не меняется. Gemini описан в [Gemini resources](gemini-resources.md).

## Batches

Native batch требует pay-as-you-go account. Поддерживаются OpenAI chat/completions, stateless responses, embeddings; Anthropic Messages; Gemini GenerateContent и embeddings. В job один endpoint family и native model. Streaming, hosted tools и stateful Responses отклоняются до submission; custom functions разрешены. OpenAI/Anthropic custom_id обязателен и уникален; Gemini без key получает стабильный key. Shuffled results связываются по key, не по позиции.

SDK acreate_batch получает raw JSONL, aget_batches выполняет poll. Результаты и mappings переживают restart. Poll не создаёт jobs и не повторяет конвертацию сохранённого результата. Неопределённый timeout submission не приводит к retry. Background scheduler отсутствует. Cancel/delete возвращает протокольную unsupported ошибку, не меняя native job локально.

**24h означает срок принятия результатов шлюзом, а не native SLA.** Poll до deadline может сохранить подтверждённые результаты. Первый poll после deadline фиксирует unresolved rows как expired, даже если native job завершилась раньше: SDK не предоставляет подтверждённый completion timestamp. Native job может продолжиться и тарифицироваться после gateway expiry; отмены нет. Retention metadata/results задаётся отдельно и не стирает готовые результаты в момент deadline.

Примеры: examples/openai/batches/ и examples/anthropic/message_batches/. Они требуют настроенного gateway и аккаунта с batch-доступом. Offline SDK tests не подтверждают live entitlement.

## Оценка токенов и cache key

POST /responses/input_tokens возвращает object=response.input_tokens и input_tokens. Подсчитывается текст, instructions, function names/arguments/schemas и response schema через tokens/count, без chat и uploads. Files/images/stateful input/hosted tools отклоняются. Это текстовая оценка, не точный OpenAI tokenizer и не полная стоимость мультимодального запроса.

Явный prompt_cache_key преобразуется в hashed X-Session-ID с разделением owner/profile/model даже при выключенном автоматическом prefix cache. Приоритет: пользовательский session header, глобальный GIGACHAT session, prompt_cache_key, затем включённый automatic prefix cache. В session ID нет raw prompt/API key. OpenAI retention TTL не обещается; usage берётся только из upstream.


### Отказы и владение ресурсами

До batch POST сохраняется durable intent. Если хранилище недоступно, POST не выполняется.
Неопределённый результат отправки или ошибка сохранения native ID оставляет failed intent
с `submission_outcome_unknown`; polling не отправляет job заново. Перед новым submit
оператор должен сверить запись с провайдером. Общей транзакции SQLite и провайдера нет.
Каждый terminal batch учитывает все input ID ровно один раз, сохраняя подтверждённые
частичные результаты и явные ошибки отсутствующих строк. После restart используется
сохранённый profile и соответствующий credential namespace пользователя.

Перед генерацией проверяется владение registered ID в native `attachments`, headers
и protocol-specific ссылках. Ошибка обязательного download/upload останавливает запрос.
Cache вложений разделён по provider/profile/credentials и хранит размер и тип.
Anthropic `expires_in_seconds` отклоняется до upload, пока native expiry не поддержан.
Гонка resumable-записей на одном offset даёт один success и один HTTP 409.
Finalize локального JSONL переносит blob без повторного расходования квоты.
