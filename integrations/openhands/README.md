# Интеграция OpenHands с GigaChat

[OpenHands](https://github.com/All-Hands-AI/OpenHands) — платформа для разработки с помощью AI-ассистентов.

## Подключение OpenHands к GigaChat

Для работы OpenHands с GigaChat используется утилита `gpt2giga`, которая преобразует запросы в формате OpenAI API в вызовы GigaChat API.

### Базовая настройка

1. **Настройте переменные окружения**
```ini
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
```

2. **Запустите gpt2giga**:
```shell
gpt2giga
```

## Запустите OpenHands
### CLI 
Поставьте openhands
```
pip install openhands-ai
```

Запустите openhands
```
openhands
```

**Настройте через /settings**
- Введите ```/settings```
- Выберете ```Advanced```
- Укажите параметры:
  - **Custom Model**: `openai/gpt4o-mini` (или любая openai модель в формате `openai/<имя>`)
  - **Base URL**: `http://localhost:8090` (та ссылка, по которой запущена gpt2giga)
  - **API Key**: Любая строка (например, `xxx`)

**Если запускаете GUI, то необходимо прописать те же параметры через Advanced Settings в соответствующей вкладке в интерфейсе**

## Полезные ссылки
- [Документация OpenHands](https://docs.all-hands.dev)
