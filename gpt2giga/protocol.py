import base64
import hashlib
import json
import re
import time
import uuid
from typing import Optional, List, Dict, Tuple, Literal

import httpx
from gigachat import GigaChat
from gigachat.models import (
    ChatCompletionChunk,
    ChatCompletion,
    Chat,
    Messages,
    MessagesRole,
    FunctionCall,
)
from openai.types.responses import ResponseFunctionToolCall, ResponseTextDeltaEvent

from gpt2giga.config import ProxyConfig


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


class RequestTransformer:
    """Трансформер запросов из OpenAI в GigaChat формат"""

    def __init__(
        self,
        config: ProxyConfig,
        logger,
        attachment_processor: Optional["AttachmentProcessor"] = None,
    ):
        self.config = config
        self.logger = logger
        self.attachment_processor = attachment_processor

    async def transform_messages(self, messages: List[Dict]) -> List[Dict]:
        """Трансформирует сообщения в формат GigaChat"""
        transformed_messages = []
        attachment_count = 0

        for i, message in enumerate(messages):
            self.logger.debug(f"Processing message {i}: role={message.get('role')}")

            # Удаляем неиспользуемые поля
            message.pop("name", None)

            # Преобразуем роли
            if message["role"] == "developer":
                message["role"] = "system"
            elif message["role"] == "system" and i > 0:
                message["role"] = "user"
            elif message["role"] == "tool":
                message["role"] = "function"
                message["content"] = json.dumps(
                    message.get("content", ""), ensure_ascii=False
                )

            # Обрабатываем контент
            if message.get("content") is None:
                message["content"] = ""

            # Обрабатываем tool_calls
            if "tool_calls" in message and message["tool_calls"]:
                message["function_call"] = message["tool_calls"][0]["function"]
                try:
                    message["function_call"]["arguments"] = json.loads(
                        message["function_call"]["arguments"]
                    )
                except json.JSONDecodeError as e:
                    self.logger.warning(f"Failed to parse function call arguments: {e}")

            # Обрабатываем составной контент (текст + изображения)
            if isinstance(message["content"], list):
                texts, attachments = await self._process_content_parts(
                    message["content"]
                )
                message["content"] = "\n".join(texts)
                message["attachments"] = attachments
                attachment_count += len(attachments)

            transformed_messages.append(message)

        # Проверяем лимиты вложений
        if attachment_count > 10:
            self._limit_attachments(transformed_messages)

        return transformed_messages

    async def _process_content_parts(
        self, content_parts: List[Dict]
    ) -> Tuple[List[str], List[str]]:
        """Обрабатывает части контента (текст и изображения)"""
        texts = []
        attachments: List[str] = []
        max_attachments = 2

        # Cache references used in loop to minimize attribute lookups
        processor = self.attachment_processor
        enable_images = getattr(self.config.proxy_settings, "enable_images", False)
        logger = self.logger

        for content_part in content_parts:
            ctype = content_part.get("type")
            if ctype == "text":
                texts.append(content_part.get("text", ""))
            elif (
                ctype == "image_url"
                and processor is not None
                and enable_images
                and content_part.get("image_url")
                and len(attachments)
                < max_attachments  # Early cutoff to avoid extra work/logging/excess uploads
            ):
                url = content_part["image_url"].get("url")
                if url is not None:
                    file_id = await processor.upload_file(url)
                    if file_id:
                        attachments.append(file_id)
                        logger.info(f"Added attachment: {file_id}")
            elif ctype == "file" and processor is not None and content_part.get("file"):
                filename = content_part["file"].get("filename")
                file_data = content_part["file"].get("file_data")
                file_id = await processor.upload_file(file_data, filename)
                if file_id:
                    attachments.append(file_id)
                    logger.info(f"Added attachment: {file_id}")
        if len(attachments) > max_attachments:
            logger.warning(
                "GigaChat can only handle 2 images per message. Cutting off excess."
            )
            attachments = attachments[:max_attachments]

        return texts, attachments

    def _limit_attachments(self, messages: List[Dict]):
        """Ограничивает количество вложений в сообщениях"""
        cur_attachment_count = 0
        for message in reversed(messages):
            message_attachments = len(message.get("attachments", []))
            if cur_attachment_count + message_attachments > 10:
                allowed = 10 - cur_attachment_count
                message["attachments"] = message["attachments"][:allowed]
                self.logger.warning(f"Limited attachments in message to {allowed}")
                break
            cur_attachment_count += message_attachments

    def transform_chat_parameters(self, data: Dict) -> Dict:
        """Трансформирует параметры чата"""
        transformed = data.copy()

        # Обрабатываем температуру
        gpt_model = data.get("model", None)
        if not self.config.proxy_settings.pass_model and gpt_model:
            del transformed["model"]
        temperature = transformed.pop("temperature", 0)
        if temperature == 0:
            transformed["top_p"] = 0
        elif temperature > 0:
            transformed["temperature"] = temperature
        max_tokens = transformed.pop("max_output_tokens", None)
        if max_tokens:
            transformed["max_tokens"] = max_tokens
        # Преобразуем tools в functions
        if "functions" not in transformed and "tools" in transformed:
            functions = []
            for tool in transformed["tools"]:
                if tool["type"] == "function":
                    functions.append(tool.get("function", tool))
            transformed["functions"] = functions
            self.logger.debug(f"Transformed {len(functions)} tools to functions")

        response_format: dict | None = transformed.pop("response_format", None)
        response_format_responses: dict | None = transformed.pop("text", None)
        if response_format:
            transformed["response_format"] = {
                "type": response_format.get("type"),
                **response_format.get("json_schema", {}),
            }
        if response_format_responses:
            fmt = response_format_responses.get("format", {})
            transformed["response_format"] = fmt
        return transformed

    def transform_response_format(self, data: Dict) -> List:
        message_payload = []
        if "instructions" in data:
            message_payload.append({"role": "system", "content": data["instructions"]})
        input_ = data["input"]
        if isinstance(input_, str):
            message_payload.append({"role": "user", "content": input_})

        elif isinstance(input_, list):
            for message in input_:
                message_type = message.get("type")
                if message_type == "function_call_output":
                    message_payload.append(
                        {
                            "role": "function",
                            "content": json.dumps(message.get("output")),
                        }
                    )
                    continue
                elif message_type == "function_call":
                    message_payload.append(self.mock_completion(message))
                    continue

                role = message.get("role")
                if role:
                    content = message.get("content")
                    if isinstance(content, list):
                        # Use a local list to avoid accumulating contents across messages
                        contents = []
                        append = (
                            contents.append
                        )  # Micro-optimization for attribute access
                        for content_part in content:
                            ctype = content_part.get("type")
                            if ctype == "input_text":
                                append(
                                    {
                                        "type": "text",
                                        "text": content_part.get("text"),
                                    }
                                )
                            elif ctype == "input_image":
                                append(
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": content_part.get("image_url")
                                        },
                                    }
                                )

                        message_payload.append({"role": role, "content": contents})
                    else:
                        message_payload.append({"role": role, "content": content})
        return message_payload

    @staticmethod
    def mock_completion(message: dict) -> dict:
        arguments = json.loads(message.get("arguments"))
        name = message.get("name")
        return Messages(
            role=MessagesRole.ASSISTANT,
            function_call=FunctionCall(name=name, arguments=arguments),
        ).dict()

    async def send_to_gigachat(self, data: dict) -> Chat:
        """Отправляет запрос в GigaChat API"""
        transformed_data = self.transform_chat_parameters(data)
        if not transformed_data.get("messages") and transformed_data.get("input"):
            transformed_data["messages"] = self.transform_response_format(
                transformed_data
            )

        transformed_data["messages"] = await self.transform_messages(
            transformed_data.get("messages", [])
        )

        chat = Chat.parse_obj(transformed_data)
        chat.messages = self._collapse_messages(chat.messages)

        self.logger.debug("Sending request to GigaChat API")
        self.logger.debug(f"Request: {chat}")

        return chat

    @staticmethod
    def _collapse_messages(messages: List[Messages]) -> List[Messages]:
        """Объединяет последовательные пользовательские сообщения"""
        collapsed_messages: List[Messages] = []
        prev_user_message = None
        content_parts = []

        for message in messages:
            if message.role == "user" and prev_user_message is not None:
                content_parts.append(message.content)
            else:
                if content_parts:
                    prev_user_message.content = "\n".join(
                        [prev_user_message.content] + content_parts
                    )
                    content_parts = []
                collapsed_messages.append(message)
                prev_user_message = message if message.role == "user" else None

        if content_parts:
            prev_user_message.content = "\n".join(
                [prev_user_message.content] + content_parts
            )

        return collapsed_messages


class ResponseProcessor:
    """Обработчик ответов от GigaChat в формат OpenAI"""

    def __init__(self, logger):
        self.logger = logger

    def process_response(
        self, giga_resp: ChatCompletion, gpt_model: str, response_id: str
    ) -> dict:
        """Обрабатывает обычный ответ от GigaChat"""
        giga_dict = giga_resp.dict()
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"
        for choice in giga_dict["choices"]:
            self._process_choice(choice, is_tool_call)
        result = {
            "id": f"chatcmpl-{response_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": gpt_model,
            "choices": giga_dict["choices"],
            "usage": self._build_usage(giga_dict["usage"]),
            "system_fingerprint": f"fp_{response_id}",
        }

        self.logger.debug("Processed chat completion response")
        self.logger.debug(f"Response: {result}")
        return result

    def process_response_api(
        self,
        data: dict,
        giga_resp: ChatCompletion,
        gpt_model: str,
        response_id: str,
    ) -> dict:
        giga_dict = giga_resp.dict()
        is_tool_call = giga_dict["choices"][0]["finish_reason"] == "function_call"
        for choice in giga_dict["choices"]:
            self._process_choice_responses(choice, response_id)

        result = {
            "id": f"resp_{response_id}",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "instructions": data.get("instructions"),
            "model": gpt_model,
            "output": self._create_output_responses(
                giga_dict, is_tool_call, response_id
            ),
            "text": {"format": {"type": "text"}},
            "usage": self._build_response_usage(giga_dict.get("usage")),
        }
        self.logger.debug("Processed responses API response")
        self.logger.debug(f"Response: {result}")

        return result

    @staticmethod
    def _create_output_responses(
        data: dict,
        is_tool_call: bool = False,
        response_id: Optional[str] = None,
        message_key: Literal["message", "delta"] = "message",
    ) -> list:
        response_id = str(uuid.uuid4()) if response_id is None else response_id
        try:
            if is_tool_call:
                return [data["choices"][0][message_key]["output"]]
            else:
                return [
                    {
                        "type": "message",
                        "id": f"msg_{response_id}",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": data["choices"][0][message_key]["content"],
                            }
                        ],
                    }
                ]
        except Exception:
            return [
                {
                    "type": "message",
                    "id": f"msg_{response_id}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": data["choices"][0][message_key]["content"],
                        }
                    ],
                }
            ]

    def process_stream_chunk(
        self, giga_resp: ChatCompletionChunk, gpt_model: str, response_id: str
    ) -> dict:
        """Обрабатывает стриминговый чанк от GigaChat"""
        giga_dict = giga_resp.dict()
        is_tool_call = giga_dict["choices"][0].get("finish_reason") == "function_call"
        for choice in giga_dict["choices"]:
            self._process_choice(choice, is_tool_call, is_stream=True)

        result = {
            "id": f"chatcmpl-{response_id}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": gpt_model,
            "choices": giga_dict["choices"],
            "usage": self._build_usage(giga_dict.get("usage")),
            "system_fingerprint": f"fp_{response_id}",
        }

        self.logger.debug(f"Processed stream chunk: {result}")
        return result

    def process_stream_chunk_response(
        self,
        giga_resp: ChatCompletionChunk,
        sequence_number: int = 0,
        response_id: Optional[str] = None,
    ) -> dict:
        giga_dict = giga_resp.dict()
        response_id = str(uuid.uuid4()) if response_id is None else response_id
        for choice in giga_dict["choices"]:
            self._process_choice_responses(choice, response_id, is_stream=True)
        delta = giga_dict["choices"][0]["delta"]
        if delta["content"]:
            result = ResponseTextDeltaEvent(
                content_index=0,
                delta=delta["content"],
                item_id=f"msg_{response_id}",
                output_index=0,
                logprobs=[],
                type="response.output_text.delta",
                sequence_number=sequence_number,
            ).dict()
        else:
            result = self._create_output_responses(
                giga_dict,
                is_tool_call=True,
                message_key="delta",
                response_id=response_id,
            )

        return result

    def _process_choice(
        self, choice: Dict, is_tool_call: bool, is_stream: bool = False
    ):
        """Обрабатывает отдельный choice"""
        message_key = "delta" if is_stream else "message"

        choice["index"] = 0
        choice["logprobs"] = None
        if is_tool_call:
            choice["finish_reason"] = "tool_calls"
        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None
            if message.get("function_call"):
                self._process_function_call(message, is_tool_call)

    def _process_function_call(self, message: Dict, is_tool_call: bool):
        """Обрабатывает function call"""
        try:
            arguments = json.dumps(
                message["function_call"]["arguments"],
                ensure_ascii=False,
            )
            function_call = {
                "name": message["function_call"]["name"],
                "arguments": arguments,
            }
            if is_tool_call:
                message["tool_calls"] = [
                    {
                        "id": f"call_{uuid.uuid4()}",
                        "type": "function",
                        "function": function_call,
                    }
                ]
            else:
                message["function_call"] = function_call
            message.pop("functions_state_id", None)
        except Exception as e:
            self.logger.error(f"Error processing function call: {e}")

    def _process_choice_responses(
        self, choice: Dict, response_id: str, is_stream: bool = False
    ):
        """Обрабатывает отдельный choice"""
        message_key = "delta" if is_stream else "message"

        choice["index"] = 0
        choice["logprobs"] = None

        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None

            if message.get("role") == "assistant" and message.get("function_call"):
                self._process_function_call_responses(message, response_id)

    def _process_function_call_responses(self, message: Dict, response_id: str):
        """Обрабатывает function call"""
        try:
            arguments = json.dumps(
                message["function_call"]["arguments"],
                ensure_ascii=False,
            )
            message["output"] = ResponseFunctionToolCall(
                arguments=arguments,
                call_id=f"call_{response_id}",
                name=message["function_call"]["name"],
                id=f"fc_{message['functions_state_id']}",
                status="completed",
                type="function_call",
            ).dict()

        except Exception as e:
            self.logger.error(f"Error processing function call: {e}")

    @staticmethod
    def _build_usage(usage_data: Optional[Dict]) -> Optional[Dict]:
        """Строит объект usage"""
        if not usage_data:
            return None

        return {
            "prompt_tokens": usage_data["prompt_tokens"],
            "completion_tokens": usage_data["completion_tokens"],
            "total_tokens": usage_data["total_tokens"],
            "prompt_tokens_details": {
                "cached_tokens": usage_data.get("precached_prompt_tokens", 0)
            },
            "completion_tokens_details": {"reasoning_tokens": 0},
        }

    @staticmethod
    def _build_response_usage(usage_data: Optional[Dict]) -> Optional[Dict]:
        if not usage_data:
            return None
        return {
            "input_tokens": usage_data.get("prompt_tokens", 0),
            "output_tokens": usage_data.get("completion_tokens", 0),
            "total_tokens": usage_data["total_tokens"],
            "prompt_tokens_details": {
                "cached_tokens": usage_data.get("precached_prompt_tokens", 0)
            },
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
