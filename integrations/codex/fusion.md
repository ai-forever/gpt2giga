# Codex + GigaFusion

Этот guide дополняет основной [Codex README](README.md). Используйте его, когда
нужно подключить OpenAI Codex к локальному GigaFusion alias вместо одной модели
GigaChat.

Fusion работает через OpenAI Responses API, поэтому Codex не требует отдельного
plugin: достаточно указать virtual model id.

## 1. Включите Fusion на gpt2giga

Минимальный `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max

GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_api_ключ>
GPT2GIGA_GIGACHAT_API_MODE=v2
GPT2GIGA_DISABLE_REASONING=True

GPT2GIGA_FUSION_ENABLED=True
GPT2GIGA_FUSION_DEFAULT_PRESET=code-high
GPT2GIGA_FUSION_STREAMING_MODE=buffered
```

Для более дешевого режима используйте:

```ini
GPT2GIGA_FUSION_DEFAULT_PRESET=code-budget
```

`GPT2GIGA_PASS_MODEL=False` можно оставить из обычной Codex-настройки:
Fusion alias будет распознан до подмены модели, а panel/judge models будут
переданы во внутренние GigaChat calls явно.

Запустите прокси:

```shell
gpt2giga
```

## 2. Настройте Codex

`~/.codex/config.toml`:

```toml
model = "gpt2giga/fusion-code"
model_provider = "gpt2giga"
model_reasoning_effort = "none"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "http://localhost:8090/v2"
env_key = "GPT2GIGA_API_KEY"
wire_api = "responses"
supports_websockets = false
```

Переменная окружения должна совпадать с `GPT2GIGA_API_KEY` на сервере:

```shell
export GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Если локальная авторизация на прокси отключена, подойдет любое непустое значение:

```shell
export GPT2GIGA_API_KEY=0
```

## 3. Smoke check

Проверьте, что alias появился в model discovery:

```shell
curl http://localhost:8090/v2/models \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY"
```

Проверьте Responses API напрямую:

```shell
curl http://localhost:8090/v2/responses \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt2giga/fusion-code",
    "input": "Review this repository and propose one safe next step."
  }'
```

Запустите Codex:

```shell
codex exec -m gpt2giga/fusion-code "Суммируй текущий проект и найди риски"
```

## Notes

- Fusion streaming is buffered: Codex receives a valid stream only after panel
  and judge calls finish.
- A Fusion request costs several GigaChat calls. Use `code-budget` when latency
  and token usage matter more than deeper comparison.
- Full Fusion behavior and env reference: [docs/fusion.md](../../docs/fusion.md).
