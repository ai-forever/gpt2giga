import base64
import hashlib
import re
import time
import uuid
from typing import Optional, NamedTuple

import httpx
from gigachat import GigaChat


class CacheEntry(NamedTuple):
    """Запись кэша с TTL"""

    file_id: str
    expires_at: float


class AttachmentProcessor:
    """Обработчик изображений с кэшированием и async HTTP"""

    DEFAULT_MAX_CACHE_SIZE = 1000
    DEFAULT_CACHE_TTL_SECONDS = 3600

    def __init__(
        self,
        logger,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ):
        self.logger = logger
        self._cache: dict[str, CacheEntry] = {}
        self._max_cache_size = max_cache_size
        self._cache_ttl = cache_ttl_seconds
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Получает или создаёт async HTTP клиент с connection pooling"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        """Закрывает HTTP клиент. Вызывать при shutdown приложения."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _get_cached(self, key: str) -> Optional[str]:
        """Получает значение из кэша с проверкой TTL"""
        entry = self._cache.get(key)
        if entry is None:
            return None

        # Проверяем TTL
        if time.time() > entry.expires_at:
            del self._cache[key]
            return None

        return entry.file_id

    def _set_cached(self, key: str, file_id: str) -> None:
        """Добавляет значение в кэш с LRU-eviction"""
        # LRU eviction: удаляем старые записи если кэш переполнен
        if len(self._cache) >= self._max_cache_size:
            # Удаляем просроченные записи
            now = time.time()
            expired_keys = [k for k, v in self._cache.items() if v.expires_at < now]
            for k in expired_keys:
                del self._cache[k]

            # Если всё ещё переполнен, удаляем самые старые (FIFO как приближение LRU)
            if len(self._cache) >= self._max_cache_size:
                # Удаляем 10% самых старых записей
                items_to_remove = max(1, self._max_cache_size // 10)
                sorted_keys = sorted(
                    self._cache.keys(), key=lambda k: self._cache[k].expires_at
                )
                for k in sorted_keys[:items_to_remove]:
                    del self._cache[k]

        self._cache[key] = CacheEntry(
            file_id=file_id, expires_at=time.time() + self._cache_ttl
        )

    def clear_cache(self) -> int:
        """Очищает кэш и возвращает количество удалённых записей"""
        count = len(self._cache)
        self._cache.clear()
        return count

    def get_cache_stats(self) -> dict:
        """Возвращает статистику кэша"""
        now = time.time()
        expired = sum(1 for v in self._cache.values() if v.expires_at < now)
        return {
            "size": len(self._cache),
            "max_size": self._max_cache_size,
            "ttl_seconds": self._cache_ttl,
            "expired_entries": expired,
        }

    async def upload_file(
        self, giga_client: GigaChat, image_url: str, filename: str | None = None
    ) -> Optional[str]:
        """Загружает файл в GigaChat и возвращает file_id"""

        # Fast regex match, single search, avoids repeated parsing
        base64_matches = re.search(r"data:(.+);base64,(.+)", image_url)
        hashed = hashlib.sha256(image_url.encode()).hexdigest()

        # Проверяем кэш с TTL
        cached_id = self._get_cached(hashed)
        if cached_id is not None:
            self.logger.debug(f"Image found in cache: {hashed[:16]}...")
            return cached_id

        try:
            if base64_matches:
                content_type = base64_matches.group(1)
                image_str = base64_matches.group(2)
                content_bytes = base64.b64decode(image_str)
                self.logger.info("Decoded base64 image")
            else:
                self.logger.info(f"Downloading image from URL: {image_url[:100]}...")
                # Используем async HTTP клиент
                client = await self._get_http_client()
                response = await client.get(image_url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                content_bytes = response.content

            ext = content_type.split("/")[-1] or "jpg"
            filename = filename or f"{uuid.uuid4()}.{ext}"
            self.logger.info(f"Uploading file to GigaChat... with extension {ext}")
            file = await giga_client.aupload_file((filename, content_bytes))

            # Сохраняем в кэш с TTL
            self._set_cached(hashed, file.id_)
            self.logger.info(f"File uploaded successfully, file_id: {file.id_}")
            return file.id_

        except httpx.HTTPStatusError as e:
            self.logger.error(
                f"HTTP error downloading file: {e.response.status_code} {e.request.url}"
            )
            return None
        except httpx.RequestError as e:
            self.logger.error(
                f"Network error downloading file: {type(e).__name__}: {e}"
            )
            return None
        except Exception as e:
            self.logger.error(f"Error processing file: {type(e).__name__}: {e}")
            return None
