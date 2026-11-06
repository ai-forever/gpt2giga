# Снимки Responses и Conversations

GPT2GIGA_RESPONSES_STORAGE_MODE=native остаётся default. Native v2 IDs обозначают продолжение GigaChat thread, могут повторяться и не являются immutable Response objects. Старые native IDs сохраняют прежний continuation path.

В opt-in режиме GPT2GIGA_RESPONSES_STORAGE_MODE=gateway общий [resource store](configuration.md) хранит уникальные resp_g2g_... снимки и conv_g2g_... Conversations. Поддержаны текстовые message items, custom function_call/function_call_output при исполнении через GigaChat. Внешние provider routes отклоняются до dispatch; режим native сохраняет их прежнее поведение. Namespace снимка включает выбранный GigaChat-профиль; чтение ищет только среди разрешённых текущей конфигурацией профилей с текущей credential identity. Multimodal, hosted tools, reasoning и provider artifacts отклоняются, если их нельзя сохранить и воспроизвести. Background/cancel/compact/connect не реализованы.

Snapshot и новый turn Conversations публикуются в одной SQLite-транзакции. Ошибка хранения после начала SSE возвращает terminal error вместо успешного завершения.

Root, /v1 и /v2 предоставляют Responses create/GET/DELETE/input_items и Conversations create/retrieve/update/delete/items. previous_response_id восстанавливает input+output конкретного snapshot в новом stateless upstream запросе; ветки от раннего turn не получают более позднюю историю. conversation использует сохранённые items и пополняется только успешным ответом. Конкурентные изменения приводят к conflict, а не перезаписи истории. conversation и previous_response_id несовместимы.

Неизвестный, удалённый, истёкший или чужой snapshot даёт 404 и никогда не становится произвольным GigaChat thread ID. store=false не сохраняет response object. Ошибка, incomplete stream и замеченный disconnect не записывают успешное завершение. Streaming использует один snapshot ID. Удаление snapshot не удаляет независимые дочерние снимки; удаление conversation не удаляет snapshots.

TTL берётся из resource retention, а не batch deadline. Input/output сохраняются намеренно для replay в приватном каталоге; log content capture остаётся opt-in. Сохраняйте persistent volume и namespace secret между workers/restarts. Пример: examples/openai/responses/storage/snapshots.py.
