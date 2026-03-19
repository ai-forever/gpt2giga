# Интеграция Qwen Code с GigaChat

[Qwen Code](https://github.com/QwenLM/qwen-code) — CLI-агент для написания кода. С помощью `gpt2giga` можно использовать модели GigaChat в Qwen Code через OpenAI-совместимый провайдер.

## Подключение Qwen Code к GigaChat

Для работы Qwen Code с GigaChat используется утилита `gpt2giga`, которая преобразует запросы в формате OpenAI API в вызовы GigaChat API.

### Предварительные требования

- Установленный [Qwen Code](https://github.com/QwenLM/qwen-code)
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

## 2. Настройка Qwen Code

Qwen Code использует конфигурацию провайдеров моделей в JSON (`~/.qwen/settings.json`). В репозитории есть готовый пример: [`settings.json`](../../qwen_settings.json).

Добавьте в ваш файл настроек Qwen Code следующий блок:

```json
{
  "modelProviders": {
    "openai": [{
      "id": "GigaChat-2-Max",
      "name": "GigaChat-Max",
      "description": "GigaChat-2-Max via Qwen Code CLI",
      "envKey": "GPT2GIGA_API_KEY",
      "baseUrl": "http://localhost:8090",
      "generationConfig": {
        "timeout": 60000,
        "samplingParams": { "temperature": 0.2 }
      }
    }]
  }
}
```

- `id` — имя модели, которое будет видно в Qwen Code.
- `envKey` — имя переменной окружения, из которой Qwen Code берёт API-ключ для `gpt2giga`.
- `baseUrl` — адрес прокси-сервера `gpt2giga`.

> `gpt2giga` поддерживает как корневые OpenAI-совместимые маршруты, так и маршруты с префиксом `/v1`, поэтому `http://localhost:8090` достаточно.

### Переменная окружения

Задайте API-ключ, соответствующий значению `GPT2GIGA_API_KEY` на сервере:

```shell
export GPT2GIGA_API_KEY=<ваш_api_ключ>
```

### Запуск Qwen Code

Запустите Qwen Code и выберите модель `GigaChat-2-Max`.

---

## 3. Использование удалённого сервера

Если `gpt2giga` развёрнут на удалённом сервере (например, за nginx с TLS), укажите адрес сервера в настройках Qwen Code:

```json
{
  "modelProviders": {
    "openai": [{
      "id": "GigaChat-2-Max",
      "name": "GigaChat-Max",
      "description": "GigaChat-2-Max via Qwen Code CLI",
      "envKey": "GPT2GIGA_API_KEY",
      "baseUrl": "https://ваш-сервер.example.com/",
      "generationConfig": {
        "timeout": 60000,
        "samplingParams": { "temperature": 0.2 }
      }
    }]
  }
}
```

Подробнее о развёртывании с nginx и TLS — в [integrations/nginx/README.md](../nginx/README.md).

---

## 4. Использование другой модели GigaChat

Если вы хотите использовать другую модель, измените:

- `GIGACHAT_MODEL` в `.env` или параметрах запуска `gpt2giga`
- `id` в конфигурации Qwen Code

Например:

```ini
GIGACHAT_MODEL=GigaChat-2-Pro
```

```json
{
  "modelProviders": {
    "openai": [{
      "id": "GigaChat-2-Pro",
      "name": "GigaChat-Pro",
      "description": "GigaChat-2-Pro via Qwen Code CLI",
      "envKey": "GPT2GIGA_API_KEY",
      "baseUrl": "http://localhost:8090"
    }]
  }
}
```

---

## Доступные модели

| Модель GigaChat  | Описание                                        |
|------------------|-------------------------------------------------|
| `GigaChat-2-Max` | Максимальная версия — рекомендована для агентов |
| `GigaChat-2-Pro` | Промежуточная версия                            |
| `GigaChat-2`     | Базовая версия                                  |

---

## Полезные ссылки

- [Документация Qwen Code](https://github.com/QwenLM/qwen-code)
- [Документация GigaChat API](https://developers.sber.ru/docs/ru/gigachat/overview)
