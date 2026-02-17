import base64
import hashlib
import ipaddress
import re
import socket
import time
import uuid
from urllib.parse import urlsplit, urlunsplit, urljoin
from typing import Optional, NamedTuple, Literal

import anyio
import httpx
from fastapi import HTTPException
from gigachat import GigaChat

from gpt2giga.constants import (
    DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES as CONST_DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
    DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES as CONST_DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
    DEFAULT_MAX_TEXT_FILE_SIZE_BYTES as CONST_DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
    SUPPORTED_AUDIO_EXTENSIONS as CONST_SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_AUDIO_MIME_TYPES as CONST_SUPPORTED_AUDIO_MIME_TYPES,
    SUPPORTED_IMAGE_EXTENSIONS as CONST_SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_IMAGE_MIME_TYPES as CONST_SUPPORTED_IMAGE_MIME_TYPES,
    SUPPORTED_TEXT_EXTENSIONS as CONST_SUPPORTED_TEXT_EXTENSIONS,
    SUPPORTED_TEXT_MIME_TYPES as CONST_SUPPORTED_TEXT_MIME_TYPES,
)


class CacheEntry(NamedTuple):
    """Запись кэша с TTL"""

    file_id: str
    expires_at: float


class UploadResult(NamedTuple):
    """Результат загрузки файла с метаданными."""

    file_id: str
    file_size_bytes: int
    file_kind: Literal["audio", "image", "text", "unknown"]


class AttachmentProcessor:
    """Обработчик изображений с кэшированием и async HTTP"""

    DEFAULT_MAX_CACHE_SIZE = 1000
    DEFAULT_CACHE_TTL_SECONDS = 3600
    DEFAULT_MAX_REDIRECTS = 5
    DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES = CONST_DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES
    DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES = CONST_DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES
    DEFAULT_MAX_TEXT_FILE_SIZE_BYTES = CONST_DEFAULT_MAX_TEXT_FILE_SIZE_BYTES
    SUPPORTED_TEXT_MIME_TYPES = CONST_SUPPORTED_TEXT_MIME_TYPES
    SUPPORTED_IMAGE_MIME_TYPES = CONST_SUPPORTED_IMAGE_MIME_TYPES
    SUPPORTED_AUDIO_MIME_TYPES = CONST_SUPPORTED_AUDIO_MIME_TYPES
    SUPPORTED_TEXT_EXTENSIONS = CONST_SUPPORTED_TEXT_EXTENSIONS
    SUPPORTED_IMAGE_EXTENSIONS = CONST_SUPPORTED_IMAGE_EXTENSIONS
    SUPPORTED_AUDIO_EXTENSIONS = CONST_SUPPORTED_AUDIO_EXTENSIONS

    def __init__(
        self,
        logger,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        max_audio_file_size_bytes: int = DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
        max_image_file_size_bytes: int = DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
        max_text_file_size_bytes: int = DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
    ):
        self.logger = logger
        self._cache: dict[str, CacheEntry] = {}
        self._max_cache_size = max_cache_size
        self._cache_ttl = cache_ttl_seconds
        self._max_audio_file_size_bytes = max_audio_file_size_bytes
        self._max_image_file_size_bytes = max_image_file_size_bytes
        self._max_text_file_size_bytes = max_text_file_size_bytes
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Получает или создаёт async HTTP клиент с connection pooling"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                # Redirects are handled manually to validate every hop (SSRF hardening).
                follow_redirects=False,
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

    @staticmethod
    def _extract_main_content_type(content_type: str) -> str:
        return (content_type or "").split(";")[0].strip().lower()

    @staticmethod
    def _estimate_base64_size(encoded: str) -> int:
        value = encoded.strip()
        if not value:
            return 0
        padding = len(value) - len(value.rstrip("="))
        return (len(value) * 3) // 4 - padding

    @staticmethod
    def _parse_content_length(content_length: str | None) -> int | None:
        if not content_length:
            return None
        try:
            parsed = int(content_length)
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None

    def _classify_file_kind(
        self, content_type: str, filename: str | None = None
    ) -> Literal["audio", "image", "text", "unknown"]:
        normalized_type = self._extract_main_content_type(content_type)
        if normalized_type in self.SUPPORTED_AUDIO_MIME_TYPES:
            return "audio"
        if normalized_type in self.SUPPORTED_IMAGE_MIME_TYPES:
            return "image"
        if normalized_type in self.SUPPORTED_TEXT_MIME_TYPES:
            return "text"

        if filename:
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext in self.SUPPORTED_AUDIO_EXTENSIONS:
                return "audio"
            if ext in self.SUPPORTED_IMAGE_EXTENSIONS:
                return "image"
            if ext in self.SUPPORTED_TEXT_EXTENSIONS:
                return "text"

        return "unknown"

    def _get_file_size_limit(self, file_kind: str) -> int:
        if file_kind == "audio":
            return self._max_audio_file_size_bytes
        if file_kind == "image":
            return self._max_image_file_size_bytes
        if file_kind == "text":
            return self._max_text_file_size_bytes
        return self._max_text_file_size_bytes

    @staticmethod
    def _raise_size_limit_exceeded(
        actual_size: int, limit_size: int, source: str, file_kind: str
    ) -> None:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "message": (
                        f"Attachment size limit exceeded for {file_kind} ({source}): "
                        f"{actual_size} bytes > {limit_size} bytes"
                    ),
                    "type": "invalid_request_error",
                    "param": "attachments",
                    "code": "request_entity_too_large",
                }
            },
        )

    @staticmethod
    def _raise_unsupported_media_type(content_type: str, filename: str | None) -> None:
        raise HTTPException(
            status_code=415,
            detail={
                "error": {
                    "message": (
                        "Unsupported attachment format. "
                        f"content_type={content_type or 'unknown'}, filename={filename or 'unknown'}"
                    ),
                    "type": "invalid_request_error",
                    "param": "attachments",
                    "code": "unsupported_media_type",
                }
            },
        )

    @staticmethod
    def _raise_disallowed_url(message: str) -> None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": f"Disallowed attachment URL: {message}",
                    "type": "invalid_request_error",
                    "param": "attachments",
                    "code": "invalid_url",
                }
            },
        )

    @staticmethod
    def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        # Block common SSRF targets and non-global ranges.
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    async def _resolve_host_ips(
        self, host: str, port: int
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """Resolve host to IP addresses in a thread (avoid blocking event loop)."""

        def _resolve() -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
            for family, _socktype, _proto, _canonname, sockaddr in infos:
                if family == socket.AF_INET:
                    ips.append(ipaddress.ip_address(sockaddr[0]))
                elif family == socket.AF_INET6:
                    ips.append(ipaddress.ip_address(sockaddr[0]))
            return ips

        return await anyio.to_thread.run_sync(_resolve)

    async def _validate_remote_url(self, raw_url: str) -> str:
        """Validate a remote URL to mitigate SSRF."""
        try:
            parts = urlsplit(raw_url)
        except Exception as exc:  # pragma: no cover (defensive)
            self._raise_disallowed_url(f"invalid URL: {type(exc).__name__}")
            raise

        scheme = (parts.scheme or "").lower()
        if scheme not in {"http", "https"}:
            self._raise_disallowed_url(f"unsupported scheme: {parts.scheme or 'empty'}")

        # Reject credentials in URL (userinfo).
        if parts.username is not None or parts.password is not None:
            self._raise_disallowed_url("userinfo is not allowed")

        host = parts.hostname
        if not host:
            self._raise_disallowed_url("missing hostname")

        normalized_host = host.strip().lower()
        if normalized_host in {"localhost"}:
            self._raise_disallowed_url("hostname is localhost")

        port = parts.port or (443 if scheme == "https" else 80)

        # If host is an IP-literal, validate it directly. Otherwise resolve and validate all A/AAAA.
        try:
            ip = ipaddress.ip_address(normalized_host)
        except ValueError:
            try:
                resolved_ips = await self._resolve_host_ips(normalized_host, port)
            except OSError as exc:
                # Let downstream HTTP client error out, but make it explicit for the caller.
                self._raise_disallowed_url(f"cannot resolve host: {type(exc).__name__}")
            if not resolved_ips:
                self._raise_disallowed_url("host resolved to no IPs")
            for resolved_ip in resolved_ips:
                if self._is_disallowed_ip(resolved_ip):
                    self._raise_disallowed_url(
                        f"host resolves to disallowed IP: {resolved_ip}"
                    )
        else:
            if self._is_disallowed_ip(ip):
                self._raise_disallowed_url(f"disallowed IP: {ip}")

        # Normalize URL (drop fragment).
        normalized = urlunsplit(
            (scheme, parts.netloc, parts.path or "/", parts.query or "", "")
        )
        return normalized

    async def upload_file_with_meta(
        self,
        giga_client: GigaChat,
        image_url: str,
        filename: str | None = None,
        max_audio_image_total_remaining: int | None = None,
    ) -> Optional[UploadResult]:
        """Загружает файл в GigaChat и возвращает file_id и метаданные."""

        base64_matches = re.search(r"data:(.+);base64,(.+)", image_url)
        hashed = hashlib.sha256(image_url.encode()).hexdigest()

        cached_id = self._get_cached(hashed)
        if cached_id is not None:
            self.logger.debug(f"Image found in cache: {hashed[:16]}...")
            return UploadResult(cached_id, 0, "unknown")

        try:
            if base64_matches:
                content_type = self._extract_main_content_type(base64_matches.group(1))
                image_str = base64_matches.group(2)
                file_kind = self._classify_file_kind(content_type, filename)
                if file_kind == "unknown":
                    self._raise_unsupported_media_type(content_type, filename)
                file_limit = self._get_file_size_limit(file_kind)
                effective_limit = file_limit
                if (
                    file_kind in {"audio", "image"}
                    and max_audio_image_total_remaining is not None
                ):
                    effective_limit = min(
                        effective_limit, max(0, max_audio_image_total_remaining)
                    )

                estimated_size = self._estimate_base64_size(image_str)
                if estimated_size > effective_limit:
                    self.logger.warning(
                        f"File too large (base64 pre-check): {estimated_size} bytes > {effective_limit} bytes"
                    )
                    self._raise_size_limit_exceeded(
                        estimated_size, effective_limit, "base64 pre-check", file_kind
                    )

                content_bytes = base64.b64decode(image_str)
                if len(content_bytes) > effective_limit:
                    self.logger.warning(
                        f"File too large: {len(content_bytes)} bytes > {effective_limit} bytes"
                    )
                    self._raise_size_limit_exceeded(
                        len(content_bytes), effective_limit, "base64 decode", file_kind
                    )
                self.logger.info("Decoded base64 file")
            else:
                validated_url = await self._validate_remote_url(image_url)
                self.logger.info(
                    f"Downloading image from URL: {validated_url[:100]}..."
                )
                client = await self._get_http_client()
                current_url = validated_url
                response = None
                stream_cm = None
                for _redirect_i in range(self.DEFAULT_MAX_REDIRECTS + 1):
                    stream_cm = client.stream("GET", current_url)
                    response = await stream_cm.__aenter__()
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        await stream_cm.__aexit__(None, None, None)
                        stream_cm = None
                        response = None
                        if not location:
                            self._raise_disallowed_url(
                                "redirect without Location header"
                            )
                        next_url = urljoin(current_url, location)
                        current_url = await self._validate_remote_url(next_url)
                        continue
                    response.raise_for_status()
                    break
                else:
                    self._raise_disallowed_url("too many redirects")

                try:
                    content_type = self._extract_main_content_type(
                        response.headers.get("content-type", "")
                    )
                    file_kind = self._classify_file_kind(content_type, filename)
                    if file_kind == "unknown":
                        self._raise_unsupported_media_type(content_type, filename)
                    file_limit = self._get_file_size_limit(file_kind)
                    effective_limit = file_limit
                    if (
                        file_kind in {"audio", "image"}
                        and max_audio_image_total_remaining is not None
                    ):
                        effective_limit = min(
                            effective_limit, max(0, max_audio_image_total_remaining)
                        )

                    content_length = self._parse_content_length(
                        response.headers.get("content-length")
                    )
                    if content_length is not None and content_length > effective_limit:
                        self.logger.warning(
                            f"File too large (Content-Length): {content_length} bytes > {effective_limit} bytes"
                        )
                        self._raise_size_limit_exceeded(
                            content_length,
                            effective_limit,
                            "content-length",
                            file_kind,
                        )

                    chunks = []
                    total_downloaded = 0
                    async for chunk in response.aiter_bytes():
                        total_downloaded += len(chunk)
                        if total_downloaded > effective_limit:
                            self.logger.warning(
                                f"File too large while downloading: {total_downloaded} bytes > {effective_limit} bytes"
                            )
                            self._raise_size_limit_exceeded(
                                total_downloaded,
                                effective_limit,
                                "stream download",
                                file_kind,
                            )
                        chunks.append(chunk)
                    content_bytes = b"".join(chunks)
                finally:
                    if stream_cm is not None:
                        await stream_cm.__aexit__(None, None, None)

            ext = content_type.split("/")[-1] or "jpg"
            filename = filename or f"{uuid.uuid4()}.{ext}"
            self.logger.info(f"Uploading file to GigaChat... with extension {ext}")
            file = await giga_client.aupload_file((filename, content_bytes))

            self._set_cached(hashed, file.id_)
            self.logger.info(f"File uploaded successfully, file_id: {file.id_}")
            return UploadResult(file.id_, len(content_bytes), file_kind)

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
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error processing file: {type(e).__name__}: {e}")
            return None

    async def upload_file(
        self, giga_client: GigaChat, image_url: str, filename: str | None = None
    ) -> Optional[str]:
        """Загружает файл в GigaChat и возвращает file_id."""
        result = await self.upload_file_with_meta(giga_client, image_url, filename)
        return result.file_id if result else None
