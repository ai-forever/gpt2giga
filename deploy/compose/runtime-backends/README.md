# Runtime Backend Extension Examples

Эта папка содержит scaffolding для подключения внешних runtime backend-ов поверх
`gpt2giga` runtime store abstraction.

Что уже есть в коде:

- built-in backend-ы `memory` и `sqlite`;
- scaffold class [`ConfigurableRuntimeStateBackend`](../../../gpt2giga/app/runtime_backends.py);
- registry через `register_runtime_backend(...)`.

## Как добавить новый backend

1. Создайте класс-наследник `ConfigurableRuntimeStateBackend`.
2. Реализуйте `mapping()` и `feed()`.
3. При необходимости реализуйте `open()` и `close()` для lifecycle внешнего клиента.
4. Зарегистрируйте backend через `register_runtime_backend(...)`.

Минимальный шаблон:

```python
from collections.abc import MutableMapping
from typing import Any

from gpt2giga.app.runtime_backends import (
    ConfigurableRuntimeStateBackend,
    EventFeed,
    register_runtime_backend,
)


class RedisRuntimeStateBackend(ConfigurableRuntimeStateBackend):
    name = "redis"

    async def open(self) -> None:
        # создать Redis client / pool
        ...

    async def close(self) -> None:
        # закрыть client / pool
        ...

    def mapping(self, name: str) -> MutableMapping[str, Any]:
        # вернуть Redis-backed mapping resource
        ...

    def feed(self, name: str, *, max_items: int) -> EventFeed:
        # вернуть Redis-backed recent-events feed
        ...


register_runtime_backend(
    RedisRuntimeStateBackend.descriptor(
        description="Redis-backed runtime stores and recent-event feeds.",
    )
)
```

`ConfigurableRuntimeStateBackend` уже прокидывает:

- `self.dsn` из `GPT2GIGA_RUNTIME_STORE_DSN`;
- `self.namespace` из `GPT2GIGA_RUNTIME_STORE_NAMESPACE`;
- `self.logger`.

## Примеры DSN

- Redis: `redis://redis:6379/0`
- Postgres: `postgresql://gpt2giga:gpt2giga@postgres:5432/gpt2giga`
- S3/MinIO: `s3://gpt2giga:gpt2giga-secret@minio:9000/gpt2giga-runtime?region=us-east-1&secure=false`

## Compose examples

Файлы в этой папке поднимают внешнюю инфраструктуру и прокидывают рекомендуемые
env-переменные в `gpt2giga`.

- [redis.yaml](./redis.yaml)
- [postgres.yaml](./postgres.yaml)
- [s3.yaml](./s3.yaml)

Важно:

- эти compose-стеки не добавляют backend implementation автоматически;
- значение `GPT2GIGA_RUNTIME_STORE_BACKEND` в примерах должно совпасть с именем,
  под которым вы зарегистрируете свой backend в коде/плагине;
- если вы хотите отключить sink telemetry и оставить только admin recent feeds,
  используйте `GPT2GIGA_ENABLE_TELEMETRY=false`.

## Быстрый старт

Пример для Redis:

```bash
docker compose -f deploy/compose/runtime-backends/redis.yaml up -d
```

После этого:

1. Убедитесь, что образ `gpt2giga` содержит ваш custom backend class.
2. Проверьте `/admin/api/runtime`:
   - `runtime_store_backend`
   - `runtime_store_namespace`
   - `telemetry_enabled`
