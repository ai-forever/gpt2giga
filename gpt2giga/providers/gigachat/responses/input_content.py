"""Responses API v2 content normalization helpers."""

import base64
from typing import Any, Dict, List, Optional

from gigachat import GigaChat

from gpt2giga.core.constants import DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_to_gigachat


class ResponsesV2ContentPartsMixin:
    """Normalize Responses API content parts into GigaChat message payloads."""

    async def _upload_response_file_part(
        self,
        giga_client: Optional[GigaChat],
        source: Any,
        *,
        filename: Optional[str] = None,
        size_totals: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        if source is None or self.attachment_processor is None:
            return None
        if giga_client is None:
            self.logger.warning("giga_client not provided for file upload")
            return None

        max_audio_image_total = getattr(
            self.config.proxy_settings,
            "max_audio_image_total_size_bytes",
            DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
        )
        remaining = max_audio_image_total
        if size_totals is not None:
            remaining = max(
                0,
                max_audio_image_total - size_totals.get("audio_image_total", 0),
            )

        upload_result = await self.attachment_processor.upload_file_with_meta(
            giga_client,
            source,
            filename,
            max_audio_image_total_remaining=remaining,
        )
        if not upload_result:
            return None
        if upload_result.file_kind in {"audio", "image"} and size_totals is not None:
            size_totals["audio_image_total"] = (
                size_totals.get("audio_image_total", 0) + upload_result.file_size_bytes
            )
        return {"files": [{"id": upload_result.file_id}]}

    async def _build_response_v2_content_parts(
        self,
        content: Any,
        giga_client: Optional[GigaChat] = None,
        *,
        size_totals: Optional[Dict[str, int]] = None,
        fallback_function_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if content is None:
            return []
        if isinstance(content, str):
            return [{"text": content}]
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        result: List[Dict[str, Any]] = []
        pending_multimodal_part: Dict[str, Any] = {}

        def flush_pending_multimodal_part() -> None:
            nonlocal pending_multimodal_part
            if pending_multimodal_part:
                result.append(pending_multimodal_part)
                pending_multimodal_part = {}

        def append_text_to_pending_part(text: str) -> None:
            existing_text = pending_multimodal_part.get("text")
            if isinstance(existing_text, str) and existing_text:
                pending_multimodal_part["text"] = f"{existing_text}\n{text}"
            else:
                pending_multimodal_part["text"] = text

        def append_files_to_pending_part(files_part: Dict[str, Any]) -> None:
            files = files_part.get("files")
            if not isinstance(files, list) or not files:
                return
            pending_multimodal_part.setdefault("files", []).extend(files)

        for content_part in content:
            if not isinstance(content_part, dict):
                continue
            ctype = content_part.get("type")

            if ctype in {"input_text", "output_text", "text"}:
                text = content_part.get("text")
                if text is not None:
                    append_text_to_pending_part(str(text))
                continue

            if ctype in {"input_image", "image_url"}:
                file_id = content_part.get("file_id")
                if isinstance(file_id, str) and file_id:
                    append_files_to_pending_part({"files": [{"id": file_id}]})
                    continue
                image_url = content_part.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                uploaded = await self._upload_response_file_part(
                    giga_client,
                    image_url,
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype in {"input_file", "file"}:
                if ctype == "input_file":
                    file_id = content_part.get("file_id")
                    if isinstance(file_id, str) and file_id:
                        append_files_to_pending_part({"files": [{"id": file_id}]})
                        continue
                    source = content_part.get("file_data") or content_part.get(
                        "file_url"
                    )
                    filename = content_part.get("filename")
                else:
                    file_payload = content_part.get("file") or {}
                    file_id = file_payload.get("file_id")
                    if isinstance(file_id, str) and file_id:
                        result.append({"files": [{"id": file_id}]})
                        continue
                    source = file_payload.get("file_data") or file_payload.get(
                        "file_url"
                    )
                    filename = file_payload.get("filename")

                uploaded = await self._upload_response_file_part(
                    giga_client,
                    source,
                    filename=filename,
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype == "input_audio":
                input_audio = content_part.get("input_audio") or {}
                audio_data = input_audio.get("data")
                audio_format = input_audio.get("format", "mp3")
                decoded_audio = audio_data
                if isinstance(audio_data, str):
                    try:
                        decoded_audio = base64.b64decode(audio_data)
                    except Exception:
                        decoded_audio = audio_data
                uploaded = await self._upload_response_file_part(
                    giga_client,
                    decoded_audio,
                    filename=f"input.{audio_format}",
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype == "function_call":
                flush_pending_multimodal_part()
                name = content_part.get("name")
                if not isinstance(name, str) or not name:
                    continue
                result.append(
                    {
                        "function_call": {
                            "name": map_tool_name_to_gigachat(name),
                            "arguments": self._decode_json_value(
                                content_part.get("arguments"),
                            ),
                        }
                    }
                )
                continue

            if ctype == "function_call_output":
                flush_pending_multimodal_part()
                name = content_part.get("name") or fallback_function_name
                if not isinstance(name, str) or not name:
                    continue
                result.append(
                    {
                        "function_result": {
                            "name": map_tool_name_to_gigachat(name),
                            "result": self._normalize_function_result_value(
                                content_part.get("output"),
                            ),
                        }
                    }
                )
                continue

            if ctype == "refusal":
                text = content_part.get("refusal") or content_part.get("text")
                if text is not None:
                    append_text_to_pending_part(str(text))

        flush_pending_multimodal_part()
        return result
