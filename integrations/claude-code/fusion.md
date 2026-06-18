# Claude Code + GigaFusion

Этот guide дополняет основной [Claude Code README](README.md). Используйте его,
когда Claude Code должен отправлять Anthropic Messages requests в локальный
GigaFusion alias.

Fusion не требует OpenRouter plugin. Claude Code выбирает model id, а
`gpt2giga` распознает alias и выполняет локальный GigaChat panel + judge
pipeline.

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

## 2. Настройте Claude Code

```shell
export ANTHROPIC_BASE_URL=http://localhost:8090
export ANTHROPIC_API_KEY=<ваш_GPT2GIGA_API_KEY>
```

Если API-key auth на локальном прокси выключен, можно использовать:

```shell
export ANTHROPIC_API_KEY=0
```

## 3. Запуск

Interactive:

```shell
claude --model gpt2giga/fusion-code
```

Print mode:

```shell
claude -p \
  --model gpt2giga/fusion-code \
  --output-format json \
  "Проверь план миграции и укажи главный риск"
```

## 4. Smoke check

Проверьте Anthropic Messages route напрямую:

```shell
curl http://localhost:8090/v1/messages \
  -H "Authorization: Bearer $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt2giga/fusion-code",
    "max_tokens": 2048,
    "messages": [
      {"role": "user", "content": "Compare two implementation approaches."}
    ]
  }'
```

## Notes

- Fusion streaming is buffered. Claude Code may wait longer before receiving
  the final stream.
- `code-high` uses more panel calls; `code-budget` reduces cost and latency.
- Full Fusion behavior and env reference: [docs/fusion.md](../../docs/fusion.md).
