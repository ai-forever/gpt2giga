# Agents SDK примеры через `gpt2giga`

Эта папка содержит runnable-примеры для agent-style сценариев поверх OpenAI-compatible proxy.

## Подготовка

1. Установите интеграционные зависимости:

```bash
uv sync --group integrations
```

2. Запустите прокси `gpt2giga`.

## Запуск

```bash
# Handoffs и tool use через OpenAI Agents SDK
uv run python examples/agents/openai_agents.py

# Weather agent с внешним погодным API
WEATHER_API_KEY=... uv run python examples/agents/weather_agent.py
```

## Что внутри

- `openai_agents.py`: handoffs между агентами и function tools через OpenAI Agents SDK.
- `weather_agent.py`: погодный агент с tool call и внешним `WEATHER_API_KEY`.
