# Примеры использования `gpt2giga`

В каталоге `examples/` лежат runnable-примеры для разных SDK и клиентских сценариев. Это лучший вход, если хочется быстро проверить конкретный API surface без чтения всего root README.

## Перед запуском

1. Поднимите `gpt2giga` локально или в Docker.
2. Проверьте, что proxy доступен по `http://localhost:8090`, либо обновите `base_url` в примере под свой адрес.
3. Если включен `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, передавайте API key так, как ожидает конкретный SDK.
4. Для examples в `examples/agents/` дополнительно выполните:

   ```bash
   uv sync --group integrations
   ```

## Быстрый выбор примера

| Если вам нужно | Каталог | Что внутри |
|---|---|---|
| Базовый OpenAI-compatible чат | [openai/chat/README.md](./openai/chat/README.md) | Chat Completions и streaming |
| Новый OpenAI Responses API | [openai/responses/README.md](./openai/responses/README.md) | `responses.create`, multi-turn, structured output |
| Работа с файлами | [openai/files/README.md](./openai/files/README.md) | Upload, list, read, delete |
| Batch-обработка | [openai/batches/README.md](./openai/batches/README.md) | OpenAI Batches API |
| Embeddings | [openai/embeddings/README.md](./openai/embeddings/README.md) | Векторизация через proxy |
| Список моделей | [openai/models/README.md](./openai/models/README.md) | OpenAI-compatible Models API |
| Anthropic Messages API | [anthropic/README.md](./anthropic/README.md) | Messages и message batches |
| Gemini Developer API | [gemini/README.md](./gemini/README.md) | generateContent, stream, files, batches, embeddings |
| Agent-style сценарии | [agents/README.md](./agents/README.md) | OpenAI Agents SDK и tool-based examples |
| Provider-to-provider translation | [translate/README.md](./translate/README.md) | Трансляция payload между API-форматами |

## Команды запуска

### OpenAI-compatible

```bash
uv run python examples/openai/chat/chat_completion.py
uv run python examples/openai/responses/single_prompt.py
uv run python examples/openai/files/files.py
uv run python examples/openai/batches/batches.py
uv run python examples/openai/embeddings/embeddings.py
uv run python examples/openai/models/models.py
```

### Anthropic-compatible

```bash
uv run python examples/anthropic/messages.py
uv run python examples/anthropic/message_batches.py
uv run python examples/anthropic/message_batches_from_jsonl.py
```

### Gemini-compatible

```bash
uv run python examples/gemini/generate_content.py
uv run python examples/gemini/files.py
uv run python examples/gemini/batches.py
uv run python examples/gemini/structured_output.py
uv run python examples/gemini/embeddings.py
```

### Translation и agents

```bash
uv run python examples/translate/openai_to_anthropic.py
uv run python examples/translate/openai_to_gemini.py
uv run python examples/translate/openai_to_gigachat.py
uv run python examples/translate/anthropic_to_openai.py
uv run python examples/translate/anthropic_to_gemini.py
uv run python examples/translate/anthropic_to_gigachat.py
uv run python examples/translate/gemini_to_openai.py
uv run python examples/translate/gemini_to_anthropic.py
uv run python examples/translate/gemini_to_gigachat.py
uv run python examples/agents/openai_agents.py
WEATHER_API_KEY=... uv run python examples/agents/weather_agent.py
```

## Несколько практических замечаний

- OpenAI examples покрывают chat, responses, files, batches, embeddings и models.
- Anthropic examples покрывают messages и message batches.
- Gemini examples показывают `google-genai` поверх `/v1beta`, включая files и batch flows.
- `weather_agent.py` требует `WEATHER_API_KEY`.
- Некоторые agent-style клиенты могут отправлять probe-запросы вроде `GET /responses` или `Upgrade: websocket`; это не мешает обычным `POST /responses`.
