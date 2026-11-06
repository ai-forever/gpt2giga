# Gemini Files и асинхронные batches

Используйте `google-genai` с `api_version="v1beta"` и base URL шлюза. Суффикс
`/v1` или `/v2` в base URL выбирает действующий API mode, сохраняя Gemini
wire format. Общий resource store должен находиться на persistent volume,
доступном всем workers и сохраняемом при restart. Namespace зависит от проверенной
identity и контекста credentials. Anonymous local mode использует один namespace;
ротация opaque pass-through token не гарантирует сохранение прежнего владельца.

## Files

`files.upload` начинает resumable session на `/upload/v1beta/files`, затем передаёт
настоящие bytes по `X-Goog-Upload-URL`. Upload/query/finalize проверяют offset и
объявленную длину. Незаконченные sessions истекают через 24 часа. Лимит blob
ограничивает буфер; дополнительно действуют MIME/размерные лимиты GigaChat.
POST одних metadata и multipart/form-data не подменяют Google upload protocol.

Get/list/delete сохраняют известные filename, displayName, MIME, размер и время
создания. `fileData.fileUri` разрешается только через owner-scoped mapping к native
attachment. Неизвестный ID, произвольный URI и локальный batch JSONL нельзя передать
как document attachment. Загруженные пользователем файлы не downloadable. Для
batch output возвращается `downloadUri`; настоящий SDK скачивает bytes через
`/v1beta/files/{id}:download?alt=media`.

JSONL хранится локально и передаётся native batch как raw bytes. Его загрузка как
документа GigaChat не требуется. Resource volume должен оставаться приватным.

## Batches

`batches.create` и `batches.create_embeddings` вызывают реальный native backend.
Поддержаны inline requests и собственный локальный JSONL. Один job использует одну
модель GigaChat и одно семейство chat/text embeddings. Streaming, stateful
continuation, webhooks, внешние output destinations и hosted tools отклоняются до
submission. Пользовательские функции используют существующие adapters.
Optional embedding options сохраняют accepted/ignored policy: векторы не усекаются
для имитации произвольных dimensions.

Create/get возвращают Operation с `name="batches/{id}"`, list — `operations` и
page tokens. `metadata.output` заполняет `BatchJob.dest` реального SDK. Порядок и
metadata строк сохраняются при перемешанном upstream output. Ошибки отдельных
элементов не превращаются в успех; file input получает downloadable JSONL output.
Повторный poll использует сохранённый результат.

Шлюз опрашивает backend по запросу клиента, без scheduler. Неопределённый timeout
submission не вызывает повторную отправку. Доступность batch зависит от аккаунта.
Cancel/delete возвращают 501 `UNIMPLEMENTED` и не имитируют остановку native job.
Для Gemini не вводится фиктивный completion window или SLA. Retention ресурсов
отделён от времени исполнения job.

## Авторизация resumable upload

`google-genai` 2.14 отправляет финальные raw bytes непосредственно через HTTP
transport и может не перенести `api_key` из обычного запроса. Если в шлюзе включена
авторизация, передайте `x-api-key` также в default headers собственного HTTPX client:
`httpx.Client(headers={"x-api-key": gateway_key})`, затем передайте его как
`types.HttpOptions(httpx_client=http_client)`. Для async используйте
`httpx.AsyncClient` и `httpx_async_client`. Pass-token Authorization также должен
присутствовать на обеих стадиях. Проверка авторизации не отключается; credentials
не сохраняются в upload session.
