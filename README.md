# Утилита для проксирования OpenAI-запросов в GigaChat

[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/ai-forever/gpt2giga/ci.yaml?&style=flat-square)](https://github.com/ai-forever/gpt2giga/actions/workflows/ci.yaml)
[![GitHub License](https://img.shields.io/github/license/ai-forever/gpt2giga?style=flat-square)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://img.shields.io/pypi/dm/gpt2giga?style=flat-square)](https://pypistats.org/packages/gpt2giga)
[![GitHub Repo stars](https://img.shields.io/github/stars/ai-forever/gpt2giga?style=flat-square)](https://star-history.com/#ai-forever/gpt2giga)
[![GitHub Open Issues](https://img.shields.io/github/issues-raw/ai-forever/gpt2giga?style=flat-square)](https://github.com/ai-forever/gpt2giga/issues)

![Coverage](./badges/coverage.svg)

## Содержание
1. [Описание](#описание)
2. [Возможности gpt2giga](#возможности-gpt2giga)
3. [Начало работы](#начало-работы)
   1. [Запуск в Docker](#запуск-в-docker)
   2. [Локальный запуск](#локальный-запуск)
4. [Параметры](#изменение-параметров-gpt2giga)
   1. [Аргументы командной строки](#аргументы-командной-строки)
   2. [Переменные окружения](#переменные-окружения)
5. [Авторизация с помощью заголовка](#авторизация-с-помощью-заголовка)
6. [Использование HTTPS](#использование-https)
7. [Использование API ключа](#использование-api-ключа)
8. [Системные эндпоинты](#системные-эндпоинты)
9. [Совместимые приложения](#совместимые-приложения)


## Описание
Утилита gpt2giga — это прокси-сервер, который перенаправляет запросы, отправленные в OpenAI API, в GigaChat API.

При старте утилиты запускается HTTP-сервер, адрес которого нужно использовать вместо адреса OpenAI API, заданного в вашем приложении (например, `https://api.openai.com/v1/`).
Утилита обработает запрос и перенаправит его заданной [модели GigaChat](https://developers.sber.ru/docs/ru/gigachat/models).
После получения ответа модели, она передаст его в приложение в формате OpenAI.

Утилита работает как с запросами на генерацию, так и с запросами на создание эмбеддингов (эндпоинты `/embeddings` или `/v1/embeddings`).

Общая схема работы gpt2giga:

```mermaid
sequenceDiagram
    participant YourApp as Приложение
    participant gpt2giga
    participant GigaChat as GigaChat API

    YourApp->>gpt2giga: OpenAI-запрос
    gpt2giga->>GigaChat: Запрос формата GigaChat API
    GigaChat->>gpt2giga: Ответ формата GigaChat API
    gpt2giga->>YourApp: OpenAI-ответ
```

## Возможности gpt2giga

С помощью gpt2giga вы можете:

- использовать возможности моделей OpenAI и полностью заменить ChatGPT на GigaChat;
- вызывать функции через API, включая передачу и выполнение функций с аргументами;
- обрабатывать ответ модели в режиме потоковой генерации токенов с помощью параметра `stream=true`;
- перенаправлять запросы на создание эмбеддингов (поддерживаются эндпоинты `/embeddings` и `/v1/embeddings`);
- работать в асинхронном режиме с множеством потоков запросов от нескольких клиентов;
- общение в openai-формате с файлом.
- отображать подробные сведения о запросах и ответах при включенном логирования `DEBUG`, `INFO` ...;
- задавать параметры работы как с помощью аргументов командной строки, так и с помощью переменных окружения (`.env`).

## Начало работы

Утилиту можно запустить как в контейнере, с помощью Docker, так и локально.

### Запуск в Docker

1. Переименуйте файл [`.env.example`](./.env.example) в `.env`.

   ```sh
   cp .env.example .env
   ```

2. В файле `.env` укажите данные для авторизации в GigaChat API.

   GigaChat API поддерживает различные способы авторизации, которые отличаются в зависимости от типа вашей учетной записи. Пример с `Authorization key`.

    ```dotenv
    GPT2GIGA_HOST=0.0.0.0
    GIGACHAT_CREDENTIALS="Authorization key GigaChat API"
    GIGACHAT_SCOPE=<your_api_scope>
    GIGACHAT_MODEL=GigaChat
    GIGACHAT_VERIFY_SSL_CERTS=False
    ```

3. Выберите образ с нужной версией Python (3.10-3.13).
```sh
PYTHON_VERSION=3.10
docker pull gigateam/gpt2giga:python${PYTHON_VERSION}
```
Доступные образы можно увидеть на https://hub.docker.com/r/gigateam/gpt2giga

4. Запустите контейнер с помощью Docker Compose: `docker compose up -d`

### Локальный запуск

Для локального запуска:

1. Установите пакет gpt2giga с помощью менеджера пакетов pip:

   ```sh
   pip install gpt2giga
   ```

   Вы также можете использовать исходники:

   ```sh
   pip install git+https://github.com/ai-forever/gpt2giga.git
   ```

   После установки пакета вы сможете использовать команду `gpt2giga`, которая позволяет запускать и настраивать прокси-сервер.

2. Переименуйте файл [`.env.example`](./.env.example) в `.env` и сохраните его в корне своего проекта:

   ```sh
   cp .env.example .env
   ```

3. В файле `.env` укажите данные для авторизации в GigaChat API.

   GigaChat API поддерживает различные способы авторизации, которые отличаются в зависимости от типа вашей учетной записи.

   > Кроме переменных gpt2giga в `.env` можно указать переменные окружения, которые поддерживает [python-библиотека GigaChat](https://github.com/ai-forever/gigachat#настройка-переменных-окружения).


1. В терминале выполните команду `gpt2giga`.

Запустится прокси-сервер, по умолчанию доступный по адресу `localhost:8090`.
Адрес и порт сервера, а также другие параметры, можно настроить с помощью аргументов командной строки или переменных окружения.

## Изменение параметров gpt2giga

Вы можете изменять параметры работы утилиты с помощью аргументов командной строки или переменных окружения.

### Аргументы командной строки

Утилита поддерживает аргументы 2 типов(настройки прокси и настройки GigaChat:
- `--env-path <PATH>` — путь до файла с переменными окружения `.env`. По умолчанию ищется `.env` в текущей директории.


- `--proxy-host <HOST>` — хост, на котором запускается прокси-сервер. По умолчанию `localhost`;
- `--proxy-port <PORT>` — порт, на котором запускается прокси-сервер. По умолчанию `8090`;
- `--proxy-use-https <True/False>` — Использовать ли https. По умолчанию `False`;
- `--proxy-https-key-file <PATH>` — Путь до key файла для https. По умолчанию `None`;
- `--proxy-https-cert-file <PATH>` — Путь до cert файла https. По умолчанию `None`;
- `--proxy-pass-model` — передавать в GigaChat API модель, которую указал клиент в поле `model` в режиме чата;
- `--proxy-pass-token` — передавать токен, полученный в заголовке `Authorization`, в GigaChat API. С помощью него можно настраивать передачу ключей в GigaChat через `OPENAI_API_KEY`;
- `--proxy-embeddings <EMBED_MODEL>` — модель, которая будет использоваться для создания эмбеддингов. По умолчанию `EmbeddingsGigaR`;
- `--proxy-enable-images` — флаг, который включает передачу изображений в формате OpenAI в GigaChat API
- `--proxy-log-level` — Уровень логов `{CRITICAL,ERROR,WARNING,INFO,DEBUG}`. По умолчанию `INFO`
- `--proxy-log-filename` — Имя лог файла. По умолчанию `gpt2giga.log`
- `--proxy-log-max-size` — Максимальный размер файла в байтах. По умолчанию `10 * 1024 * 1024` (10 MB)
- `--proxy-enable-api-key-auth` — Нужно ли закрыть доступ к эндпоинтам (требовать API-ключ). По умолчанию `False`
- `--proxy-api-key` — API ключ для защиты эндпоинтов (если enable_api_key_auth=True).

Далее идут стандартные настройки из библиотеки GigaChat:
- `--gigachat-base-url <BASE_URL>` — базовый URL для GigaChat API. По умолчанию берется значение переменной `GIGACHAT_BASE_URL` или поля `BASE_URL` внутри пакета;
- `--gigachat-auth-url <AUTH_URL>` — базовый URL для Auth GigaChat API. По умолчанию берется значение переменной `GIGACHAT_AUTH_URL` или поля `AUTH_URL` внутри пакета;
- `--gigachat-credentials <BASE_URL>` — Креды гигачат;
- `--gigachat-scope <GIGACHAT_SCOPE>` — Скоуп гигачат (API_CORP, API_PERS...);
- `--gigachat-user <GIGACHAT_USER>` — Вариант авторизации через user/password;
- `--gigachat-password <GIGACHAT_PASSWORD>` — Вариант авторизации через user/password;
- `--gigachat-access_token <ACCESS_TOKEN>` — JWE токен;
- `--gigachat-model <MODEL>` — модель для запросов в GigaChat. По умолчанию `GIGACHAT_MODEL`;
- `--gigachat-profanity-check <True/False>` — Параметр цензуры. По умолчанию `None`;
- `--gigachat-timeout <TIMEOUT>` — таймаут для запросов к GigaChat API. По умолчанию `30` секунд;
- `--gigachat-verify-ssl-certs <True/False>` — проверять сертификаты SSL (по умолчанию `True`)

#### Пример запуска утилиты с заданными параметрами

Для запуска прокси-сервера с заданным адресом и портом выполните команду:

```sh
gpt2giga \
    --proxy-host 127.0.0.1 \
    --proxy-port 8080 \
    --proxy-log-level \
    --proxy-pass-model \
    --proxy-pass-token \
    --gigachat-base-url https://gigachat.devices.sberbank.ru/api/v1 \
    --gigachat-model GigaChat-Max \
    --gigachat-timeout 300 \
    --gigachat-embeddings EmbeddingsGigaR
```

### Переменные окружения

Для настройки параметров утилиты также можно использовать переменные окружения, заданные в файле `.env`.

У настроек прокси префикс GPT2GIGA_, у настроек GigaChat: GIGACHAT_

Список доступных переменных:

- `GPT2GIGA_HOST="localhost"` — хост, на котором запускается прокси-сервер. По умолчанию `localhost`;
- `GPT2GIGA_PORT="8090"` — порт, на котором запускается прокси-сервер. По умолчанию `8090`;
- `GPT2GIGA_USE_HTTPS="False"` — Использовать ли https. По умолчанию `False`;
- `GPT2GIGA_HTTPS_KEY_FILE=<PATH>` — Путь до key файла для https. По умолчанию `None`;
- `GPT2GIGA_HTTPS_CERT_FILE=<PATH>` — Путь до cert файла https. По умолчанию `None`;
- `GPT2GIGA_PASS_MODEL="False"` — передавать ли модель, указанную в запросе, непосредственно в GigaChat;
- `GPT2GIGA_PASS_TOKEN="False"` — передавать токен, полученный в заголовке `Authorization`, в GigaChat API;
- `GPT2GIGA_TIMEOUT="600"` — таймаут для запросов к GigaChat API (в секундах);
- `GPT2GIGA_EMBEDDINGS="EmbeddingsGigaR"` — модель для создания эмбеддингов.
- `GPT2GIGA_ENABLE_IMAGES="True"` — флаг, который включает передачу изображений в формате OpenAI в GigaChat API;
- `GPT2GIGA_LOG_LEVEL="INFO"` — Уровень логов `{CRITICAL,ERROR,WARNING,INFO,DEBUG}`. По умолчанию `INFO`
- `GPT2GIGA_LOG_FILENAME="gpt2giga.log"` — Имя лог файла. По умолчанию `gpt2giga.log`
- `GPT2GIGA_LOG_MAX_SIZE="10*1024*1024"` Максимальный размер файла в байтах. По умолчанию `10 * 1024 * 1024` (10 MB)
- `GPT2GIGA_ENABLE_API_KEY_AUTH="False"` — Нужно ли закрыть доступ к эндпоинтам (требовать API-ключ). По умолчанию `False`
- `GPT2GIGA_API_KEY=""` — API ключ для защиты эндпоинтов (если enable_api_key_auth=True).

Также можно использовать переменные, которые поддерживает [библиотека GigaChat](https://github.com/ai-forever/gigachat#настройка-переменных-окружения):
- `GIGACHAT_BASE_URL="https://gigachat.devices.sberbank.ru/api/v1"` — базовый URL GigaChat;
- `GIGACHAT_MODEL="GigaChat"` — модель GigaChat API, которая будет обрабатывать запросы по умолчанию;
- `GIGACHAT_USER` и `GIGACHAT_PASSWORD` — для авторизации с помощью с помощью логина и пароля;
- `GIGACHAT_CREDENTIALS` и `GIGACHAT_SCOPE` — для авторизации с помощью ключа авторизации;
- `GIGACHAT_ACCESS_TOKEN` — для авторизации с помощью токена доступа, полученного в обмен на ключ;
- `GIGACHAT_CA_BUNDLE_FILE` - путь к файлу сертификата корневого центра сертификации;
- `GIGACHAT_MTLS_AUTH` — использовать аутентификацию по сертефикатам mTLS;
- `GIGACHAT_CERT_FILE` - путь к клиентскому сертификату;
- `GIGACHAT_KEY_FILE` - путь к закрытому ключу;
- `GIGACHAT_KEY_FILE_PASSWORD` - пароль от закрытого ключа;
- `GIGACHAT_VERIFY_SSL_CERTS` — для того, что бы проверять SSL сертификаты, по умолчанию `False`.

После запуска сервер будет перенаправлять все запросы, адресованные OpenAI API, в GigaChat API.

## Авторизация с помощью заголовка

Утилита может авторизовать запросы в GigaChat API с помощью данных, полученных в заголовке `Authorization`.

Для этого запустите gpt2giga с аргументом `--pass-token` или задайте переменную окружения `GPT2GIGA_PASS_TOKEN=True`.
Поддерживается авторизация с помощью ключа, токена доступа и логина и пароля.

Возможные варианты содержимого заголовка `Authorization`:

- `giga-cred-<credentials>:<scope>` — авторизация с помощью ключа. Вместо `<scope>` нужно указать версию API, к которой будут выполняться запросы. [Подробнее о ключе авторизации и версии API](https://github.com/ai-forever/gigachat?tab=readme-ov-file#параметры-объекта-gigachat).
- `giga-auth-<access_token>` — при авторизации с помощью токена доступа. Токен доступа получается в обмен на ключ авторизации и действителен в течение 30 минут.
- `giga-user-<user>:<password>` — при авторизации с помощью логина и пароля.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="giga-cred-<credentials>:<scope>")

completion = client.chat.completions.create(
    model="gpt-5",
    messages=[
        {"role": "user", "content": "Кто ты?"},
    ],
)
```

## Использование HTTPS

Утилита может использоваться с протоколом HTTPS, пример генерации сертификатов:
```bash
openssl req -x509 -nodes -days 365   -newkey rsa:4096   -keyout key.pem   -out cert.pem   -subj "/CN=localhost"   -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```
```dotenv
GPT2GIGA_USE_HTTPS=False
GPT2GIGA_HTTPS_KEY_FILE="Path to key.pem"
GPT2GIGA_HTTPS_CERT_FILE="Path to cert.pem"
```
После этого, в переменные окружения или в cli-args нужно добавить данные сертификаты.

## Использование API ключа
```dotenv
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=123
```

После этого, в сервисе будет добавлена авторизация по токену. Возможны разные варианты выполнения запросов, например:
Авторизация по запросу:
```bash
curl -L http://localhost:8090/models?x-api-key=123
```
Авторизация по заголовкам:
```bash
curl -H "x-api-key:123" -L http://localhost:8090/models
```
Авторизация через Bearer:
```bash
 curl -H "Authorization: Bearer 123" -L http://localhost:8090/models
```
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="123")

completion = client.chat.completions.create(
    model="gpt-5",
    messages=[
        {"role": "user", "content": "Кто ты?"},
    ],
)
```
## Системные эндпоинты
- `GET /health`
- `GET | POST /ping`
- `GET /logs/{last_n_lines}` - получение последних N строчек из логов;
- `GET /logs/stream` - SSE стриминг логов;
- `GET /logs/html` - HTML страница для удобства просмотра стрима логов

При использовании можно зайти на страницу: http://localhost:8090/logs/html и:
1. Если используется API ключ [Использование API ключа](#использование-api-ключа), то введите ваш `GPT2GIGA_API_KEY`
2. Иначе, введите любой символ

После этого, воспользуйтесь утилитой и будут выведены логи
## Совместимые приложения

Таблица содержит приложения, проверенные на совместную работу с gpt2giga.

| Приложение                                             | Описание                                                                                                                                   |
|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| [Aider](https://aider.chat/)                           | AI-ассистент для написания приложений.<br /> Подробнее о запуске и настройке Aider для работы с gpt2giga — в [README](/integrations/aider) |
| [n8n](https://n8n.io/)                                 | Платформа для создания nocode-агентов                                                                                                      |
| [Cline](https://github.com/cline/cline)                | AI-ассистент разработчика                                                                                                                  |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | AI-ассистент для разработки<br /> Подробнее о запуске и настройке OpenHands для работы с gpt2giga — в [README](/integrations/openhands)    |
| [KiloCode](https://kilocode.ai/) | AI-кодовый агент | AI-агент для написания кода, доступен в jetbrains/vscode |

## Лицензия

Проект распространяется под лицензией MIT.
Подробная информация — в файле [LICENSE](LICENSE).
