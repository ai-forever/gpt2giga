import ast
import json
from typing import List, Dict, Tuple, Optional, Any

from gigachat import GigaChat
from gigachat.models import (
    Messages,
    MessagesRole,
    FunctionCall,
)

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol.attachments import AttachmentProcessor
from gpt2giga.utils import normalize_json_schema


class RequestTransformer:
    """Трансформер запросов из OpenAI в GigaChat формат"""

    @staticmethod
    def _resolve_schema_refs(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Разрешает $ref ссылки и anyOf/oneOf в JSON schema.
        GigaChat не поддерживает $ref/$defs и anyOf/oneOf, поэтому нужно
        развернуть схему и упростить Optional типы.
        """

        def resolve(obj: Any, defs: Dict[str, Any]) -> Any:
            if isinstance(obj, dict):
                # Handle $ref
                if "$ref" in obj:
                    ref_path = obj["$ref"]
                    # Parse reference like '#/$defs/Step'
                    if ref_path.startswith("#/$defs/"):
                        ref_name = ref_path.split("/")[-1]
                        if ref_name in defs:
                            # Return resolved definition (recursively resolve)
                            resolved = defs[ref_name].copy()
                            return resolve(resolved, defs)
                    return obj

                # Handle anyOf/oneOf (typically from Optional types)
                # Pydantic generates: anyOf: [{actual_type}, {type: "null"}]
                for union_key in ("anyOf", "oneOf"):
                    if union_key in obj:
                        variants = obj[union_key]
                        # Find non-null variant
                        non_null_variants = [
                            v for v in variants if v.get("type") != "null"
                        ]
                        if non_null_variants:
                            # Take the first non-null variant and merge with other props
                            result = resolve(non_null_variants[0], defs)
                            # Preserve other properties like 'default', 'title', 'description'
                            for key, value in obj.items():
                                if (
                                    key not in (union_key, "$defs")
                                    and key not in result
                                ):
                                    result[key] = resolve(value, defs)
                            return result
                        # If all are null, just return null type
                        return {"type": "null"}

                # Recursively process dict, skipping $defs
                return {
                    key: resolve(value, defs)
                    for key, value in obj.items()
                    if key != "$defs"
                }

            elif isinstance(obj, list):
                return [resolve(item, defs) for item in obj]

            return obj

        defs = schema.get("$defs", {})
        return resolve(schema, defs)

    @staticmethod
    def _ensure_json_object_str(value: Any) -> str:
        """
        GigaChat требует, чтобы результат function/tool был валидным JSON object.
        При этом SDK `gigachat.models.Messages` ожидает `content: str`.

        OpenAI-совместимые клиенты часто присылают:
        - dict (ок)
        - JSON-строку (нужно json.loads)
        - двойную JSON-строку (нужно json.loads несколько раз)
        - python-подобную строку (single quotes) — пробуем ast.literal_eval
        """
        if value is None:
            return "{}"

        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", errors="ignore")
            except Exception:
                return json.dumps({"result": str(value)}, ensure_ascii=False)

        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)

        if isinstance(value, str):
            s: Any = value.strip()
            for _ in range(3):
                if not isinstance(s, str):
                    break
                if s == "":
                    return "{}"
                try:
                    s = json.loads(s)
                    continue
                except json.JSONDecodeError:
                    break

            if isinstance(s, dict):
                return json.dumps(s, ensure_ascii=False)
            if isinstance(s, (list, int, float, bool)) or s is None:
                return json.dumps({"result": s}, ensure_ascii=False)

            if isinstance(s, str):
                try:
                    lit = ast.literal_eval(s)
                    if isinstance(lit, dict):
                        return json.dumps(lit, ensure_ascii=False)
                    return json.dumps({"result": lit}, ensure_ascii=False)
                except Exception:
                    return json.dumps({"result": s}, ensure_ascii=False)

        return json.dumps({"result": value}, ensure_ascii=False)

    def __init__(
        self,
        config: ProxyConfig,
        logger,
        attachment_processor: Optional[AttachmentProcessor] = None,
    ):
        self.config = config
        self.logger = logger
        self.attachment_processor = attachment_processor

    async def transform_messages(
        self, messages: List[Dict], giga_client: Optional[GigaChat] = None
    ) -> List[Dict]:
        """Трансформирует сообщения в формат GigaChat"""
        transformed_messages = []
        attachment_count = 0

        for i, message in enumerate(messages):
            self.logger.debug(f"Processing message {i}: role={message.get('role')}")

            # Преобразуем роли
            if message["role"] == "developer":
                message["role"] = "system"
                # Удаляем неиспользуемые поля
                message.pop("name", None)
            elif message["role"] == "system" and i > 0:
                message["role"] = "user"
                # Удаляем неиспользуемые поля
                message.pop("name", None)
            elif message["role"] == "tool":
                message["role"] = "function"
                # Для function role желательно сохранять name (если пришел от клиента)
                message["content"] = self._ensure_json_object_str(
                    message.get("content")
                )
            else:
                # Удаляем неиспользуемые поля
                message.pop("name", None)

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
                    message["content"], giga_client
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
        self, content_parts: List[Dict], giga_client: Optional[GigaChat] = None
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
                    # If giga_client is not provided (e.g. tests), upload might fail if processor needs it
                    # But we assume caller provides it now.
                    # If giga_client is None, we might want to fallback or error?
                    # Given AttachmentProcessor refactor, it MUST receive a client.
                    if giga_client:
                        file_id = await processor.upload_file(giga_client, url)
                        if file_id:
                            attachments.append(file_id)
                            logger.info(f"Added attachment: {file_id}")
                    else:
                        logger.warning("giga_client not provided for image upload")

            elif ctype == "file" and processor is not None and content_part.get("file"):
                filename = content_part["file"].get("filename")
                file_data = content_part["file"].get("file_data")
                if giga_client:
                    file_id = await processor.upload_file(
                        giga_client, file_data, filename
                    )
                    if file_id:
                        attachments.append(file_id)
                        logger.info(f"Added attachment: {file_id}")
                else:
                    logger.warning("giga_client not provided for file upload")
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

    def _transform_common_parameters(self, data: Dict) -> Dict:
        """Общая логика трансформации параметров для Chat Completions и Responses API"""
        transformed = data.copy()

        # Обрабатываем модель
        gpt_model = data.get("model", None)
        if not self.config.proxy_settings.pass_model and gpt_model:
            del transformed["model"]

        # Обрабатываем температуру
        temperature = transformed.pop("temperature", 0)
        if temperature == 0:
            transformed["top_p"] = 0
        elif temperature > 0:
            transformed["temperature"] = temperature

        # Обрабатываем max_tokens
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

        return transformed

    @staticmethod
    def _apply_json_schema_as_function(
        transformed: Dict, schema_name: str, schema: Dict
    ) -> None:
        """Применяет JSON schema как function call для structured output"""
        # Разрешаем $ref/$defs ссылки, т.к. GigaChat их не поддерживает
        resolved_schema = RequestTransformer._resolve_schema_refs(schema)
        # Нормализуем схему: добавляем properties к объектам без properties
        resolved_schema = normalize_json_schema(resolved_schema)

        function_def = {
            "name": schema_name,
            "description": f"Output response in structured format: {schema_name}",
            "parameters": resolved_schema,
        }

        if "functions" not in transformed:
            transformed["functions"] = []

        transformed["functions"].append(function_def)
        transformed["function_call"] = {"name": schema_name}

    def transform_chat_parameters(self, data: Dict) -> Dict:
        """Трансформирует параметры чата (Chat Completions API)"""
        transformed = self._transform_common_parameters(data)

        response_format: dict | None = transformed.pop("response_format", None)
        if response_format:
            if response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                schema_name = json_schema.get("name", "structured_output")
                schema = json_schema.get("schema")
                self._apply_json_schema_as_function(transformed, schema_name, schema)
            else:
                print(response_format)
                transformed["response_format"] = {
                    "type": response_format.get("type"),
                    **response_format.get("json_schema", {}),
                }

        return transformed

    def transform_responses_parameters(self, data: Dict) -> Dict:
        """Трансформирует параметры responses (Responses API)"""
        transformed = self._transform_common_parameters(data)

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
                self._apply_json_schema_as_function(transformed, schema_name, schema)
            else:
                transformed["response_format"] = response_format

        return transformed

    def transform_response_format(self, data: Dict) -> List:
        message_payload = []
        if "instructions" in data:
            message_payload.append({"role": "system", "content": data["instructions"]})
            del data["instructions"]
        input_ = data["input"]
        del data["input"]
        if isinstance(input_, str):
            message_payload.append({"role": "user", "content": input_})

        elif isinstance(input_, list):
            last_function_name: Optional[str] = None
            for message in input_:
                message_type = message.get("type")
                if message_type == "function_call_output":
                    # Best effort: attach name from last function_call so GigaChat sees function name
                    fn_name = message.get("name") or last_function_name
                    message_payload.append(
                        {
                            "role": "function",
                            "name": fn_name,
                            "content": self._ensure_json_object_str(
                                message.get("output")
                            ),
                        }
                    )
                    continue
                elif message_type == "function_call":
                    last_function_name = message.get("name") or last_function_name
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

    async def _finalize_transformation(
        self, transformed_data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Общая логика трансформации сообщений и логгирования"""
        transformed_data["messages"] = await self.transform_messages(
            transformed_data.get("messages", []), giga_client
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

    async def prepare_chat_completion(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Подготовка запроса для Chat Completions API"""
        transformed_data = self.transform_chat_parameters(data)
        return await self._finalize_transformation(transformed_data, giga_client)

    async def prepare_response(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Подготовка запроса для Responses API"""
        transformed_data = self.transform_responses_parameters(data)
        transformed_data["messages"] = self.transform_response_format(transformed_data)
        return await self._finalize_transformation(transformed_data, giga_client)

    # Backward-compatible API (used by older tests / integrations)
    async def send_to_gigachat(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """
        Совместимый алиас: исторически метод возвращал подготовленный payload для GigaChat.
        Сейчас это делает `prepare_chat_completion`.
        """
        return await self.prepare_chat_completion(data, giga_client)

    async def send_to_gigachat_responses(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """
        Совместимый алиас для Responses API.
        Сейчас это делает `prepare_response`.
        """
        return await self.prepare_response(data, giga_client)

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
