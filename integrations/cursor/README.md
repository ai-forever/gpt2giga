# Интеграция Cursor с GigaChat

[Cursor](https://cursor.com/) — редактор кода на основе искусственного интеллекта и агент для программирования. С помощью `gpt2giga` можно использовать модели GigaChat в Cursor в качестве кастомной модели.

## Подключение Cursor к GigaChat

Для работы Cursor с GigaChat используется утилита `gpt2giga`, которая преобразует запросы в формате OpenAI API в вызовы GigaChat API.

### Предварительные требования

- Установленный [Cursor](https://cursor.com/)
- Подписка на Cursor уровня Pro и выше
- Запущенный прокси-сервер `gpt2giga` на сервере (смотри [nginx](../nginx/README.md))

---
## 1. Настройка Cursor

### Добавление кастомной модели

1. Откройте **Cursor Settings** → **Models**.
2. Нажмите **+ Add Model** и введите имя модели, например `GigaChat-2-Max`.
3. Включите переключатель рядом с добавленной моделью.

### Настройка OpenAI API

1. В разделе **Models** нажмите на кнопку **OpenAI API Key**.
2. Введите значение API-ключа (например, `0`). Ключ OpenAI не используется — все запросы проксируются через `gpt2giga`.
3. Включите переключатель **Override OpenAI Base URL**.
4. Введите адрес прокси-сервера.

Когда `gpt2giga` развёрнут на удалённом сервере (например, за nginx с TLS), укажите в **Override OpenAI Base URL** адрес сервера:

```
https://ваш-сервер.example.com/
```

Подробнее о развёртывании с nginx и TLS — в [integrations/nginx/README.md](../nginx/README.md).
> **Примечание:** Cursor добавляет `/v1` автоматически к некоторым запросам.

### Проверка подключения

После настройки откройте чат в Cursor (Ctrl+L / Cmd+L), выберите добавленную модель `GigaChat-2-Max` и отправьте тестовое сообщение.

---

## 2. Использование с API-ключом gpt2giga

Если на прокси-сервере включена авторизация по API-ключу (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), введите значение `GPT2GIGA_API_KEY` в поле **OpenAI API Key** в настройках Cursor.

---

## 3. Передача авторизации через заголовок

Если вы хотите передавать учётные данные GigaChat напрямую через Cursor (без конфигурации `.env`), запустите `gpt2giga` с флагом `--proxy.pass-token true` и укажите в поле **OpenAI API Key** в Cursor один из вариантов:

- `giga-cred-<credentials>:<scope>` — авторизация по ключу
- `giga-user-<user>:<password>` — авторизация по логину и паролю
- `giga-auth-<access_token>` — авторизация по токену доступа

---

## Доступные модели

| Модель в Cursor  | Модель GigaChat |
|------------------|-----------------|
| `GigaChat-2-Max` | GigaChat-2-Max  |
| `GigaChat-2-Pro` | GigaChat-2-Pro  |
| `GigaChat-2`     | GigaChat-2      |

При включённом `--proxy.pass-model true` имя модели, указанное в Cursor, передаётся напрямую в GigaChat API.

---

## Полезные ссылки

- [Документация Cursor](https://docs.cursor.com/)
- [Настройка моделей в Cursor](https://docs.cursor.com/settings/models)
- [Документация GigaChat API](https://developers.sber.ru/docs/ru/gigachat/overview)
