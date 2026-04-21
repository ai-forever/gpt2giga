# Standalone batch validation через `gpt2giga`

`gpt2giga` поддерживает отдельную ручку `POST /batches/validate` и `POST /v1/batches/validate`.

Она полезна, если вы хотите:

- проверить batch payload до создания реального batch job;
- увидеть ошибки формата и provider-specific warnings;
- валидировать OpenAI-, Anthropic- и Gemini-style rows через один endpoint.

## Запуск

```bash
uv run python examples/batch_validation/openai_validate.py
uv run python examples/batch_validation/anthropic_validate.py
uv run python examples/batch_validation/gemini_validate.py
```

## Что есть в папке

- `openai_validate.py`: валидирует OpenAI batch rows с `api_format="openai"`
- `anthropic_validate.py`: валидирует Anthropic message batch rows с `api_format="anthropic"`
- `gemini_validate.py`: валидирует Gemini batch rows с `api_format="gemini"`

## Нюансы

- endpoint принимает либо `input_file_id`, либо inline `requests`;
- `model` нужен только как fallback model для форматов, где это применимо;
- validation ничего не создаёт upstream и не запускает batch execution.
