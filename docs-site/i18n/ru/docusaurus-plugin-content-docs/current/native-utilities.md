# Изображения и native-операции GigaChat

Операции используют настроенный SDK-клиент GigaChat, общую авторизацию шлюза
и request-scoped identity режима pass-token. Доступность native-операции зависит
от выбранной модели и учётной записи upstream.

## Генерация изображений OpenAI

`POST /v2/images/generations` вызывает инструмент GigaChat v2 `image_generate`,
скачивает реальные bytes файла и возвращает OpenAI `b64_json`. Корневой маршрут
работает при `GPT2GIGA_GIGACHAT_API_MODE=v2`; `/v1` явно отклоняет операцию.
Запрос генерации отправляется один раз, без повтора при неопределённом исходе.
Отсутствие изображения или пустой файл — ошибка.

```python
import base64
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090/v2", api_key="0")
result = client.images.generate(
    model="gpt-image-1",
    prompt="Маяк на тихом побережье, акварель",
    n=1,
    response_format="b64_json",
)
image_bytes = base64.b64decode(result.data[0].b64_json)
```

В `GIGACHAT_MODEL` нужна модель с доступом к генерации изображений. Известные
клиентские aliases `gpt-image-1`, `gpt-image-1-mini`, `dall-e-2`, `dall-e-3`
выбирают эту настроенную модель, а не OpenAI backend. Явные aliases проверенного
GigaChat-профиля разрешаются в указанную в профиле upstream-модель. Профили
внешних провайдеров не могут вызывать native-операцию.

Поддержаны только `n=1`, `response_format=b64_json`, отсутствие `size` либо
`size=auto`. Формат файла и размеры выбирает GigaChat. Edits, masks, variations,
streaming, несколько кандидатов, явные размеры, quality и URL-ответы отклоняются
до генерации. `user` принимается без OpenAI billing semantics. ID сгенерированного
файла не выдаётся за публичный URL.

Пример: [generate.py](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/images/generate.py).

## Native utilities

Это расширения GigaChat, а не endpoints OpenAI, Anthropic или Gemini. Они не
вызывают chat generation и не исполняют пользовательские функции.

| Маршрут | JSON input | Результат и ограничения |
|---|---|---|
| `POST /bridge/gigachat/tokens/count` | `{"input":["привет"],"model":"GigaChat-3-Ultra"}` | Native подсчёт токенов текста, не полная стоимость файлов, изображений или ответа. |
| `POST /bridge/gigachat/functions/validate` | Native JSON-схема функции | Результаты валидации, включая ошибки в ответе HTTP 200. Только JSON input. |
| `GET /bridge/gigachat/balance` | Нет | Native баланс аккаунта; доступ зависит от аккаунта, в частности prepaid. |
| `POST /bridge/gigachat/ai/check` | `{"input":"Русский текст","model":"GigaChat-3-Ultra"}` | Вероятность генерации русского текста ИИ. Это не Moderations и не классификатор опасного контента. |

Текстовые операции используют существующий resolver модели; без `model`
используется настроенная модель. Безопасные headers/options и credentials
текущего запроса доходят до SDK. Транспортные headers ответа SDK и credentials
не включаются в JSON. Защита API-ключом шлюза действует и на эти `/bridge`
маршруты. Ограничения аккаунта возвращаются как upstream-ошибки.

Пример: [utilities.py](https://github.com/ai-forever/gpt2giga/blob/main/examples/native/utilities.py).

Для logprobs сохранена прежняя политика accepted/ignored. Наличие поля в SDK
не доказывает доступность для модели и аккаунта; это расширение не включает
профиль logprobs без подтверждённой поддержки. Вероятности не выдумываются,
глобальная поддержка logprobs не объявляется.
