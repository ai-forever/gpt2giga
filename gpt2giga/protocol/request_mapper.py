import json
from typing import List, Dict, Tuple, Optional, Any

from gigachat.models import (
    Messages,
    MessagesRole,
    FunctionCall,
)

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol.attachments import AttachmentProcessor


class RequestTransformer:
    """Трансформер запросов из OpenAI в GigaChat формат"""

    def __init__(
        self,
        config: ProxyConfig,
        logger,
        attachment_processor: Optional[AttachmentProcessor] = None,
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
        """Трансформирует параметры чата (Chat Completions API)"""
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
        if response_format:
            if response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                schema_name = json_schema.get("name", "structured_output")
                schema = json_schema.get("schema")

                function_def = {
                    "name": schema_name,
                    "description": f"Output response in structured format: {schema_name}",
                    "parameters": schema,
                }

                if "functions" not in transformed:
                    transformed["functions"] = []

                transformed["functions"].append(function_def)
                transformed["function_call"] = {"name": schema_name}

            else:
                transformed["response_format"] = {
                    "type": response_format.get("type"),
                    **response_format.get("json_schema", {}),
                }

        return transformed

    def transform_responses_parameters(self, data: Dict) -> Dict:
        """Трансформирует параметры responses (Responses API)"""
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

        response_format_responses: dict | None = transformed.pop("text", None)
        if response_format_responses:
            response_format = response_format_responses.get("format", {})
            if response_format.get("type") == "json_schema":
                if "json_schema" in response_format:
                    json_schema = response_format.get("json_schema", {})
                    schema_name = json_schema.get("name", "structured_output")
                    schema = json_schema.get("schema")
                else:
                    schema_name = response_format.get("name", "structured_output")
                    schema = response_format.get("schema")

                function_def = {
                    "name": schema_name,
                    "description": f"Output response in structured format: {schema_name}",
                    "parameters": schema,
                }

                if "functions" not in transformed:
                    transformed["functions"] = []

                transformed["functions"].append(function_def)
                transformed["function_call"] = {"name": schema_name}
            else:
                transformed["response_format"] = response_format

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
        ).model_dump()

    async def _finalize_transformation(self, transformed_data: dict) -> Dict[str, Any]:
        """Общая логика трансформации сообщений и логгирования"""
        transformed_data["messages"] = await self.transform_messages(
            transformed_data.get("messages", [])
        )

        # Collapse messages
        messages_objs = [
            Messages.model_validate(m) for m in transformed_data["messages"]
        ]
        collapsed_objs = self._collapse_messages(messages_objs)
        transformed_data["messages"] = [
            m.model_dump(exclude_none=True) for m in collapsed_objs
        ]

        self.logger.debug("Sending request to GigaChat API")
        self.logger.debug(f"Request: {transformed_data}")

        return transformed_data

    async def prepare_chat_completion(self, data: dict) -> Dict[str, Any]:
        """Подготовка запроса для Chat Completions API"""
        transformed_data = self.transform_chat_parameters(data)
        return await self._finalize_transformation(transformed_data)

    async def prepare_response(self, data: dict) -> Dict[str, Any]:
        """Подготовка запроса для Responses API"""
        transformed_data = self.transform_responses_parameters(data)
        transformed_data["messages"] = self.transform_response_format(transformed_data)
        return await self._finalize_transformation(transformed_data)

    # Backward-compatible API (used by older tests / integrations)
    async def send_to_gigachat(self, data: dict) -> Dict[str, Any]:
        """
        Совместимый алиас: исторически метод возвращал подготовленный payload для GigaChat.
        Сейчас это делает `prepare_chat_completion`.
        """
        return await self.prepare_chat_completion(data)

    async def send_to_gigachat_responses(self, data: dict) -> Dict[str, Any]:
        """
        Совместимый алиас для Responses API.
        Сейчас это делает `prepare_response`.
        """
        return await self.prepare_response(data)

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
