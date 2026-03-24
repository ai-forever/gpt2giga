---
name: Отчет об ошибке
about: Сообщите об ошибке, чтобы помочь нам улучшить gpt2giga
title: "[БАГ] "
labels: bug
assignees: ''
---

## Описание ошибки

<!-- Четко и кратко опишите ошибку -->

## Окружение

### Настройка gpt2giga

- **Версия gpt2giga**: <!-- например, 0.5.0 -->
- **Способ установки**:
  - [ ] pip (`pip install gpt2giga`)
  - [ ] uv (`uv tool install gpt2giga` / `uv add gpt2giga`)
  - [ ] Docker (`docker compose up`)
  - [ ] Из исходников (`pip install git+...`)

- **Версия Python**: <!-- например, 3.10 -->
- **ОС**: <!-- например, Ubuntu 22.04, macOS 14.0, Windows 11 -->

### Конфигурация GigaChat

- **Модель GigaChat**: <!-- например, GigaChat, GigaChat-2-Max -->
- **Настройки авторизации**: <!-- например, OAuth(scope+creds), Basic(user+password) -->

## Как воспроизвести

### Используемый метод

- [ ] OpenAI Python SDK
- [ ] curl
- [ ] Другое: <!-- укажите -->

### Тело запроса

<!--
Приведите полный запрос, который вы отправляете.
Удалите любые чувствительные данные (учетные данные, токены и т. д.)
-->

<details>
<summary>Запрос</summary>

**Для OpenAI SDK:**

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="your-key")

# Ваш запрос здесь
completion = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Ваше сообщение"}
    ],
    # ... другие параметры
)
```

**Для curl:**

```bash
curl -X POST http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-key" \
  -d '{
    "model": "gpt-4",
    "messages": [
      {"role": "user", "content": "Ваше сообщение"}
    ]
  }'
```

</details>

### Шаги для воспроизведения

1. Запустите gpt2giga командой: `...`
2. Отправьте запрос: `...`
3. Наблюдайте ошибку

## Ожидаемое поведение

<!-- Что, по вашему ожиданию, должно было произойти -->

## Фактическое поведение

<!-- Что произошло на самом деле -->

## Вывод ошибки

<details>
<summary>Сообщение об ошибке / Traceback</summary>

```
Вставьте сюда текст ошибки или traceback
```

</details>

## Логи

<!--
Установите GPT2GIGA_LOG_LEVEL=DEBUG и приложите релевантные логи.
Удалите любую чувствительную информацию!
-->

<details>
<summary>Логи gpt2giga (уровень DEBUG)</summary>

```
Вставьте сюда релевантные логи
```

</details>

## Конфигурация

<!-- Приведите содержимое вашего .env файла (удалите чувствительные значения!) -->

<details>
<summary>Конфигурация .env</summary>

```dotenv
GPT2GIGA_HOST=localhost
GPT2GIGA_PORT=8090
GPT2GIGA_LOG_LEVEL=DEBUG
# ... другие настройки
```

</details>

## Дополнительный контекст

<!-- Добавьте сюда любой дополнительный контекст по проблеме -->

## Возможное решение

<!-- Необязательно: если у вас есть идеи по исправлению, опишите их здесь -->
