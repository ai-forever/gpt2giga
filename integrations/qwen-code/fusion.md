# Qwen Code + GigaFusion

Этот guide дополняет основной [Qwen Code README](README.md). Используйте его,
когда Qwen Code должен работать с локальным GigaFusion alias через
OpenAI-compatible provider.

Fusion включается модельным alias. Qwen Code не должен поддерживать
OpenRouter-style plugins.

## 1. Включите Fusion на gpt2giga

Минимальный `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max

GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_api_ключ>
GPT2GIGA_GIGACHAT_API_MODE=v2

GPT2GIGA_FUSION_ENABLED=True
GPT2GIGA_FUSION_DEFAULT_PRESET=code-high
GPT2GIGA_FUSION_STREAMING_MODE=buffered
```

Запустите прокси:

```shell
gpt2giga
```

## 2. Настройте Qwen Code

`~/.qwen/settings.json`:

```json
{
  "modelProviders": {
    "openai": [{
      "id": "gpt2giga/fusion-code",
      "name": "GigaFusion Code",
      "description": "Local gpt2giga Fusion via GigaChat",
      "envKey": "GPT2GIGA_API_KEY",
      "baseUrl": "http://localhost:8090/v2",
      "generationConfig": {
        "timeout": 180000,
        "samplingParams": { "temperature": 0.2 }
      }
    }]
  }
}
```

Задайте API key для прокси:

```shell
export GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Если auth выключен:

```shell
export GPT2GIGA_API_KEY=0
```

## 3. Smoke check

Проверьте OpenAI-compatible Chat Completions напрямую:

```shell
curl http://localhost:8090/v2/chat/completions \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt2giga/fusion-code",
    "messages": [
      {"role": "user", "content": "Find edge cases in this CLI integration."}
    ]
  }'
```

Потом выберите provider/model `gpt2giga/fusion-code` в Qwen Code.

## Notes

- Fusion requests have higher latency because panel and judge calls run before
  the final answer is streamed back.
- For lower cost, set `GPT2GIGA_FUSION_DEFAULT_PRESET=code-budget` or use
  request-level plugin/metadata config from [docs/fusion.md](../../docs/fusion.md).
