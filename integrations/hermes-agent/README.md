# Интеграция Hermes Agent с GigaChat

[Hermes Agent](https://hermes-agent.nousresearch.com/docs) — агент с поддержкой инструментария, работающий с любым LLM-провайдером. С помощью `gpt2giga` можно подключить Hermes к моделям GigaChat как к OpenAI-совместимому провайдеру.

## Предварительные требования

- Установленный [Hermes Agent](https://hermes-agent.nousresearch.com/install)
- Запущенный прокси-сервер `gpt2giga`
- Учётные данные GigaChat (`GIGACHAT_CREDENTIALS`)

---

## 1. Настройка gpt2giga

Настройте переменные окружения в файле `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS

GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_api_ключ>
GPT2GIGA_GIGACHAT_API_MODE=v2
GPT2GIGA_DISABLE_REASONING=True
```

Рекомендуемые параметры для Hermes:

- `GPT2GIGA_GIGACHAT_API_MODE=v2` - включает режим v2 с поддержкой встроенных инструментов GigaChat (web_search, image_generate).
- `GPT2GIGA_DISABLE_REASONING=True` - удаляет `reasoning` и `reasoning_effort` из запроса к GigaChat, чтобы клиентские поля не мешали обработке.
- `GPT2GIGA_API_KEY` - произвольный набор символов.

Запустите прокси-сервер:

```shell
gpt2giga
```

По умолчанию сервер будет доступен по адресу `http://localhost:8090`.

---

## 2. Настройка Hermes Agent

### Через CLI

```shell
hermes config set model.provider custom
hermes config set model.base_url "http://localhost:8090/v2"
hermes config set model.api_key "<ваш_GPT2GIGA_API_KEY>"
hermes config set model.default "GigaChat-2-Max"
hermes config set model.api_streaming "true"
```

### Через config.yaml

Отредактируйте `~/.hermes/config.yaml`:

```yaml
model:
  default: GigaChat-2-Max
  provider: custom
  base_url: http://localhost:8090/v2
  api_mode: chat_completions
  api_key: "<ваш_GPT2GIGA_API_KEY>"
  api_streaming: true
```

### Опционально: алиасы моделей

```shell
hermes config set model.aliases.giga-max "custom/GigaChat-2-Max"
hermes config set model.aliases.giga-ultra "custom/GigaChat-3-Ultra"
```

---

## 3. Проверка работы

### Базовый запрос

```shell
hermes chat --provider custom --model GigaChat-2-Max -q "Привет! Расскажи о себе."
```

### Вызов инструментов

```shell
hermes chat --provider custom --model GigaChat-2-Max -q "Найди текущую погоду в Москве" --toolsets "web"
```

---

## 4. Диагностика

- **Hermes получает 401/403** — проверьте, что `GPT2GIGA_API_KEY` в конфиге Hermes совпадает со значением на сервере `gpt2giga`.
- **Hermes не может подключиться** — проверьте, что gpt2giga запущен и слушает на `localhost:8090`.
- **Ошибки стриминга** — попробуйте `GPT2GIGA_DISABLE_REASONING=True` и `GPT2GIGA_PASS_MODEL=False`.
- **Модель не отвечает** — проверьте, что `GIGACHAT_CREDENTIALS` корректен и не истёк срок действия.

---
