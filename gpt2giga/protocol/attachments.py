import base64
import hashlib
import re
import uuid
from typing import Optional

import httpx
from gigachat import GigaChat


class AttachmentProcessor:
    """Обработчик изображений с кэшированием"""

    def __init__(self, giga_client: GigaChat, logger):
        self.giga = giga_client
        self.logger = logger
        self.cache: dict[str, str] = {}

    async def upload_file(
        self, image_url: str, filename: str | None = None
    ) -> Optional[str]:
        """Загружает файл в GigaChat и возвращает file_id"""

        # Fast regex match, single search, avoids repeated parsing
        base64_matches = re.search(r"data:(.+);base64,(.+)", image_url)
        hashed = hashlib.sha256(image_url.encode()).hexdigest()

        cached_id = self.cache.get(hashed)
        if cached_id is not None:
            self.logger.debug(f"Image found in cache: {hashed}")
            return cached_id

        try:
            if base64_matches:
                content_type = base64_matches.group(1)
                image_str = base64_matches.group(2)
                content_bytes = base64.b64decode(image_str)
                self.logger.info("Decoded base64 image")
            else:
                self.logger.info(f"Downloading image from URL: {image_url[:100]}...")
                response = httpx.get(image_url, timeout=30)
                content_type = response.headers.get("content-type", "")
                content_bytes = response.content
            ext = content_type.split("/")[-1] or "jpg"
            filename = filename or f"{uuid.uuid4()}.{ext}"
            self.logger.info(f"Uploading file to GigaChat... with extension {ext}")
            file = await self.giga.aupload_file((filename, content_bytes))

            self.cache[hashed] = file.id_
            self.logger.info(f"File uploaded successfully, file_id: {file.id_}")
            return file.id_

        except Exception as e:
            self.logger.error(f"Error processing file: {e}")
            return None
