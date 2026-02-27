# Интеграция OpenAI Codex с GigaChat

[OpenAI Codex](https://github.com/openai/codex) — CLI-агент от OpenAI для написания кода. С помощью `gpt2giga` можно использовать модели GigaChat в Codex в качестве кастомного провайдера.

## Подключение Codex к GigaChat

Для работы Codex с GigaChat используется утилита `gpt2giga`, которая преобразует запросы в формате OpenAI API в вызовы GigaChat API.

### Предварительные требования

- Установленный [OpenAI Codex](https://github.com/openai/codex)
- Запущенный прокси-сервер `gpt2giga`
- Учётные данные GigaChat (`GIGACHAT_CREDENTIALS`)

---

## 1. Запуск gpt2giga

Настройте переменные окружения в файле `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Запустите прокси-сервер:

```shell
gpt2giga
```

По умолчанию сервер будет доступен по адресу `http://localhost:8090`.

---

## 2. Настройка Codex

### Конфигурация `config.toml`

Отредактируйте файл конфигурации Codex:

- **macOS / Linux:** `~/.codex/config.toml`
- **Windows:** `%USERPROFILE%\.codex\config.toml`

Добавьте следующее содержимое:

```toml
model = "GigaChat-2-Max"

model_provider = "gpt2giga"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "http://localhost:8090"
env_key = "GPT2GIGA_API_KEY"
```

### Переменная окружения

Задайте API-ключ, соответствующий значению `GPT2GIGA_API_KEY` на сервере:

```shell
export GPT2GIGA_API_KEY=<ваш_api_ключ>
```

### Запуск Codex

```shell
codex
```

Codex будет отправлять запросы через `gpt2giga` в GigaChat API.

---

## 3. Использование удалённого сервера

Если `gpt2giga` развёрнут на удалённом сервере (например, за nginx с TLS), укажите адрес сервера в `config.toml`:

```toml
model = "GigaChat-2-Max"

model_provider = "gpt2giga"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "https://ваш-сервер.example.com/"
env_key = "GPT2GIGA_API_KEY"
```

Подробнее о развёртывании с nginx и TLS — в [integrations/nginx/README.md](../nginx/README.md).

---

## 4. Доверенные проекты

Codex требует явного указания доверенных проектов. Добавьте ваш проект в `config.toml`:

```toml
[projects."/path/to/your/project"]
trust_level = "trusted"
```

---

## 5. Пример полного `config.toml`

```toml
model = "GigaChat-2-Max"

model_provider = "gpt2giga"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "https://ваш-сервер.example.com/"
#base_url = "http://localhost:8090"
env_key = "GPT2GIGA_API_KEY"

[projects."/Users/USER/code_projects/MY_PROJECT"]
trust_level = "trusted"
```

---

## Доступные модели

| Модель в Codex | Модель GigaChat |
|---|---|
| `GigaChat-2-Max` | GigaChat-2-Max |
| `GigaChat-2-Pro` | GigaChat-2-Pro |
| `GigaChat-2` | GigaChat-2 |

---

## Полезные ссылки

- [Документация OpenAI Codex](https://github.com/openai/codex)
- [Документация GigaChat API](https://developers.sber.ru/docs/ru/gigachat/overview)
