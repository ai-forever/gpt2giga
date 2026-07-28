# Интеграция с gateway

GigaLoom устанавливается самостоятельно. Базовый дистрибутив не импортирует
gateway и не требует checkout его репозитория.

Установите необязательную релизную интеграцию только для Direct Chat или legacy
preset локального gateway:

```sh
uv tool install --prerelease allow 'gpt2giga-harness[gpt2giga]==0.5.1a1'
```

Extra закрепляет проверенный публичный дистрибутив `gpt2giga`. Candidate testing
использует явный wheel URL/path и SHA-256, без editable sibling dependency.

## Канонические контракты gateway

Отдельный gateway project владеет этими reference:

- [Нормализованные сообщения](https://github.com/ai-forever/gpt2giga/blob/main/docs/architecture/normalized-messages.md)
- [Совместимость API](https://github.com/ai-forever/gpt2giga/blob/main/docs/api-compatibility.md)
- [Совместимость параметров клиента](https://github.com/ai-forever/gpt2giga/blob/main/docs/client-parameter-compatibility.md)
- [Маппинг встроенных инструментов](https://github.com/ai-forever/gpt2giga/blob/main/docs/builtin-tools.md)

Это актуальные canonical gateway links, а не ссылки разработки GigaLoom.
Изменения GigaLoom относятся к
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom).
