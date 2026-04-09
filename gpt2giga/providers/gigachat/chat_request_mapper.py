"""GigaChat chat message mapping helpers."""

import json
from typing import Any, Dict, List, Optional, Tuple

from gigachat import GigaChat

from gpt2giga.common.content_utils import ensure_json_object_str
from gpt2giga.common.message_utils import ensure_system_first
from gpt2giga.common.tools import map_tool_name_to_gigachat
from gpt2giga.core.constants import DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES


class RequestTransformerMessagesMixin:
    """Helpers for message and attachment normalization."""

    async def transform_messages(
        self, messages: List[Dict], giga_client: Optional[GigaChat] = None
    ) -> List[Dict]:
        """Transform messages to GigaChat format."""
        transformed_messages = []
        attachment_count = 0
        system_message = None
        size_totals = {"audio_image_total": 0}

        for index, message in enumerate(messages):
            self.logger.debug(f"Processing message {index}: role={message.get('role')}")

            original_role = message.get("role", "user")
            is_first_for_system = system_message is None
            message["role"] = self._map_role(original_role, is_first_for_system)

            if message["role"] == "system" and system_message is None:
                system_message = message

            if original_role == "tool":
                message["content"] = ensure_json_object_str(message.get("content"))
                if message.get("name"):
                    message["name"] = map_tool_name_to_gigachat(message["name"])
            else:
                message.pop("name", None)

            if message.get("content") is None:
                message["content"] = ""

            if "tool_calls" in message and message["tool_calls"]:
                message["function_call"] = message["tool_calls"][0]["function"]
                if isinstance(message.get("function_call"), dict) and message[
                    "function_call"
                ].get("name"):
                    message["function_call"]["name"] = map_tool_name_to_gigachat(
                        message["function_call"]["name"]
                    )
                try:
                    message["function_call"]["arguments"] = json.loads(
                        message["function_call"]["arguments"]
                    )
                except json.JSONDecodeError as exc:
                    self.logger.warning(
                        f"Failed to parse function call arguments: {exc}"
                    )
            elif (
                message.get("function_call")
                and isinstance(message["function_call"], dict)
                and message["function_call"].get("name")
            ):
                message["function_call"]["name"] = map_tool_name_to_gigachat(
                    message["function_call"]["name"]
                )

            if isinstance(message["content"], list):
                texts, attachments = await self._process_content_parts(
                    message["content"], giga_client, size_totals
                )
                message["content"] = "\n".join(texts)
                message["attachments"] = attachments
                attachment_count += len(attachments)

            transformed_messages.append(message)

        transformed_messages = self._merge_consecutive_messages(transformed_messages)
        transformed_messages = ensure_system_first(transformed_messages)

        if attachment_count > 10:
            self._limit_attachments(transformed_messages)

        return transformed_messages

    async def _process_content_parts(
        self,
        content_parts: List[Dict],
        giga_client: Optional[GigaChat] = None,
        size_totals: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Process text and file/image content parts."""
        texts = []
        attachments: List[str] = []
        max_attachments = 2

        processor = self.attachment_processor
        enable_images = getattr(self.config.proxy_settings, "enable_images", False)
        max_audio_image_total = getattr(
            self.config.proxy_settings,
            "max_audio_image_total_size_bytes",
            DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
        )

        async def append_uploaded_attachment(
            source: Any,
            *,
            filename: Optional[str] = None,
        ) -> None:
            if giga_client is None:
                self.logger.warning("giga_client not provided for file upload")
                return
            remaining = max_audio_image_total
            if size_totals is not None:
                remaining = max(
                    0,
                    max_audio_image_total - size_totals.get("audio_image_total", 0),
                )
            upload_result = await processor.upload_file_with_meta(
                giga_client,
                source,
                filename,
                max_audio_image_total_remaining=remaining,
            )
            if not upload_result:
                return
            attachments.append(upload_result.file_id)
            if (
                upload_result.file_kind in {"audio", "image"}
                and size_totals is not None
            ):
                size_totals["audio_image_total"] = (
                    size_totals.get("audio_image_total", 0)
                    + upload_result.file_size_bytes
                )
            self.logger.info(f"Added attachment: {upload_result.file_id}")

        for content_part in content_parts:
            ctype = content_part.get("type")
            if ctype == "text":
                texts.append(content_part.get("text", ""))
                continue

            if (
                ctype == "image_url"
                and processor is not None
                and enable_images
                and content_part.get("image_url")
                and len(attachments) < max_attachments
            ):
                url = content_part["image_url"].get("url")
                if url is not None:
                    await append_uploaded_attachment(url)
                continue

            if ctype == "file" and processor is not None and content_part.get("file"):
                file_payload = content_part["file"]
                filename = file_payload.get("filename")
                file_data = file_payload.get("file_data")
                if file_data is not None:
                    await append_uploaded_attachment(file_data, filename=filename)

        if len(attachments) > max_attachments:
            self.logger.warning(
                "GigaChat can only handle 2 images per message. Cutting off excess."
            )
            attachments = attachments[:max_attachments]

        return texts, attachments
