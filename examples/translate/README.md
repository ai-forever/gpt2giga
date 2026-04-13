# Provider-to-Provider translation через `gpt2giga`

`gpt2giga` теперь умеет не только принимать provider-compatible запросы, но и отдельно переводить payload из одного формата в другой через `/translate` и `/v1/translate`.

Это полезно, если вы хотите:

- посмотреть, как прокси нормализует запрос;
- подготовить payload для другого SDK/provider без реального вызова модели;
- отладить несовпадения между OpenAI, Gemini, Anthropic и внутренним GigaChat backend payload.

## Запуск

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
```

## Что есть в папке

- `openai_to_anthropic.py`: переводит OpenAI Chat payload в Anthropic Messages
- `openai_to_gemini.py`: переводит OpenAI Chat payload в Gemini `generateContent`
- `openai_to_gigachat.py`: переводит OpenAI Chat payload во внутренний GigaChat backend payload
- `anthropic_to_openai.py`: переводит Anthropic Messages payload в OpenAI Chat payload
- `anthropic_to_gemini.py`: переводит Anthropic Messages payload в Gemini `generateContent`
- `anthropic_to_gigachat.py`: переводит Anthropic Messages payload во внутренний GigaChat backend payload
- `gemini_to_openai.py`: переводит Gemini `generateContent` payload в OpenAI Chat payload
- `gemini_to_anthropic.py`: переводит Gemini `generateContent` payload в Anthropic Messages
- `gemini_to_gigachat.py`: переводит Gemini `generateContent` payload во внутренний GigaChat backend payload

## Нюансы

- В первой версии ручка поддерживает `kind="chat"`.
- Для `to="gigachat"` возвращается внутренний backend payload, а не внешний HTTP endpoint.
- Для `to="gigachat"` offline translation не поддерживает image/file parts, потому что вложения требуют реального upload.
