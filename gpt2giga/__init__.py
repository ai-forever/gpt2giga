import argparse
import array
import base64
import hashlib
import http.server
import importlib.resources
import io
import json
import logging
import os
import re
import socketserver
import time
import uuid
import warnings
from functools import lru_cache
from typing import Optional, Tuple, List, Iterator, Dict

import httpx
import tiktoken
from PIL import Image
from dotenv import find_dotenv, load_dotenv
from gigachat import GigaChat
from gigachat.models import Chat, ChatCompletion, ChatCompletionChunk, Messages
from gigachat.settings import Settings as GigachatSettings
from pydantic.v1 import Field
from gigachat.pydantic_v1 import BaseSettings

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ProxySettings(BaseSettings):
    host: str = Field(default="localhost", description="Хост для запуска сервера")
    port: int = Field(default=8090, description="Порт для запуска сервера")
    pass_model: bool = Field(default=False, description="Передавать модель из запроса в API")
    pass_token: bool = Field(default=False, description="Передавать токен из запроса в API")
    embeddings: str = Field(default="EmbeddingsGigaR", description="Модель для эмбеддингов")
    verify_ssl_certs: bool = Field(default=False, description="Проверять SSL сертификаты")
    enable_images: bool = Field(default=False, description="Включить загрузку изображений")
    verbose: bool = Field(default=False, description="verbose of logs")
    env_path: Optional[str] = Field(None, description="Путь к .env файлу")

    class Config:
        env_prefix = "gpt2giga_"
        case_sensitive = False

class ProxyConfig(BaseSettings):
    """Конфигурация прокси-сервера"""
    proxy_settings: ProxySettings = Field(default_factory=ProxySettings)
    gigachat_settings: GigachatSettings = Field(default_factory=GigachatSettings)

class ImageProcessor:
    """Обработчик изображений с кэшированием"""

    def __init__(self, giga_client: GigaChat):
        self.giga = giga_client
        self.cache: Dict[str, str] = {}
        self.logger = logging.getLogger(f"{__name__}.ImageProcessor")

    def upload_image(self, image_url: str) -> Optional[str]:
        """Загружает изображение в GigaChat и возвращает file_id"""
        base64_matches = re.search(r"data:(.+);(.+),(.+)", image_url)
        hashed = hashlib.sha256(image_url.encode()).hexdigest()

        if hashed in self.cache:
            self.logger.debug(f"Image found in cache: {hashed}")
            return self.cache[hashed]

        try:
            if not base64_matches:
                self.logger.info(f"Downloading image from URL: {image_url[:100]}...")
                response = httpx.get(image_url, timeout=30)
                content_type = response.headers.get('content-type', "")
                content_bytes = response.content

                if not content_type.startswith("image/"):
                    self.logger.warning(f"Invalid content type for image: {content_type}")
                    return None
            else:
                content_type, type_, image_str = base64_matches.groups()
                if type_ != "base64":
                    self.logger.warning(f"Unsupported encoding type: {type_}")
                    return None
                content_bytes = base64.b64decode(image_str)
                self.logger.debug("Decoded base64 image")

            # Конвертируем и сжимаем изображение
            image = Image.open(io.BytesIO(content_bytes)).convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format='JPEG', quality=85)
            buf.seek(0)

            self.logger.info("Uploading image to GigaChat...")
            file = self.giga.upload_file((f"{uuid.uuid4()}.jpg", buf))

            self.cache[hashed] = file.id_
            self.logger.info(f"Image uploaded successfully, file_id: {file.id_}")
            return file.id_

        except Exception as e:
            self.logger.error(f"Error processing image: {e}")
            return None


class RequestTransformer:
    """Трансформер запросов из OpenAI в GigaChat формат"""

    def __init__(self, config: ProxyConfig, image_processor: Optional[ImageProcessor] = None):
        self.config = config
        self.image_processor = image_processor
        self.logger = logging.getLogger(f"{__name__}.RequestTransformer")

    def transform_messages(self, messages: List[Dict]) -> List[Dict]:
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
                try:
                    json.loads(message.get("content", ""))
                except json.JSONDecodeError:
                    message["content"] = json.dumps(message.get("content", ""), ensure_ascii=False)

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
                texts, attachments = self._process_content_parts(message["content"])
                message["content"] = "\n".join(texts)
                message["attachments"] = attachments
                attachment_count += len(attachments)

            transformed_messages.append(message)

        # Проверяем лимиты вложений
        if attachment_count > 10:
            self._limit_attachments(transformed_messages)

        return transformed_messages

    def _process_content_parts(self, content_parts: List[Dict]) -> Tuple[List[str], List[str]]:
        """Обрабатывает части контента (текст и изображения)"""
        texts = []
        attachments = []

        for content_part in content_parts:
            if content_part.get("type") == "text":
                texts.append(content_part.get("text", ""))
            elif (content_part.get("type") == "image_url" and
                  content_part.get("image_url") and
                  self.image_processor and
                  self.config.proxy_settings.enable_images):

                file_id = self.image_processor.upload_image(content_part["image_url"]["url"])
                if file_id:
                    attachments.append(file_id)
                    self.logger.info(f"Added attachment: {file_id}")

        # Ограничиваем количество изображений
        if len(attachments) > 2:
            self.logger.warning("GigaChat can only handle 2 images per message. Cutting off excess.")
            attachments = attachments[:2]

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

        # Преобразуем tools в functions
        if "functions" not in transformed and "tools" in transformed:
            functions = []
            for tool in transformed["tools"]:
                if tool["type"] == "function":
                    functions.append(tool.get("function", tool))
            transformed["functions"] = functions
            self.logger.debug(f"Transformed {len(functions)} tools to functions")

        return transformed


class ResponseProcessor:
    """Обработчик ответов от GigaChat в формат OpenAI"""

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.ResponseProcessor")

    def process_response(self, giga_resp: ChatCompletion, gpt_model: str, is_tool_call: bool = False) -> dict:
        """Обрабатывает обычный ответ от GigaChat"""
        giga_dict = giga_resp.dict()

        for choice in giga_dict["choices"]:
            self._process_choice(choice, is_tool_call)

        result = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time() * 1000),
            "model": gpt_model,
            "choices": giga_dict["choices"],
            "usage": self._build_usage(giga_dict["usage"]),
            "system_fingerprint": f"fp_{uuid.uuid4()}",
        }

        self.logger.debug("Processed chat completion response")
        return result

    def process_stream_chunk(self, giga_resp: ChatCompletionChunk, gpt_model: str, is_tool_call: bool = False) -> dict:
        """Обрабатывает стриминговый чанк от GigaChat"""
        giga_dict = giga_resp.dict()

        for choice in giga_dict["choices"]:
            self._process_choice(choice, is_tool_call, is_stream=True)

        result = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion.chunk",
            "created": int(time.time() * 1000),
            "model": gpt_model,
            "choices": giga_dict["choices"],
            "usage": self._build_usage(giga_dict.get("usage")),
            "system_fingerprint": f"fp_{uuid.uuid4()}",
        }

        self.logger.debug("Processed stream chunk")
        return result

    def _process_choice(self, choice: Dict, is_tool_call: bool, is_stream: bool = False):
        """Обрабатывает отдельный choice"""
        message_key = "delta" if is_stream else "message"

        choice["index"] = 0
        choice["logprobs"] = None

        if message_key in choice:
            message = choice[message_key]
            message["refusal"] = None

            if message.get("role") == "assistant" and message.get("function_call"):
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
                message["tool_calls"] = [{
                    "id": f"call_{uuid.uuid4()}",
                    "type": "function",
                    "function": function_call
                }]
                if message.get("finish_reason") == "function_call":
                    message["finish_reason"] = "tool_calls"
            else:
                message["function_call"] = function_call

            if message.get("content") == "":
                message["content"] = None

            message.pop("functions_state_id", None)

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
            "completion_tokens_details": {
                "reasoning_tokens": 0
            },
        }


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """Обработчик HTTP запросов прокси-сервера"""

    config: Optional[ProxyConfig] = None
    giga: Optional[GigaChat] = None
    request_transformer: Optional[RequestTransformer] = None
    response_processor: Optional[ResponseProcessor] = None
    image_processor: Optional[ImageProcessor] = None

    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(f"{__name__}.ProxyHandler")
        super().__init__(*args, **kwargs)

    @classmethod
    def initialize(cls, config: ProxyConfig, giga_client: GigaChat):
        """Инициализирует классовые переменные"""
        cls.config = config
        cls.giga = giga_client
        cls.response_processor = ResponseProcessor()

        if config.proxy_settings.enable_images:
            cls.image_processor = ImageProcessor(giga_client)

        cls.request_transformer = RequestTransformer(config, cls.image_processor)

    def log_message(self, fmt: str, *args):
        """Переопределяет стандартное логирование HTTP запросов"""
        self.logger.info(f"{self.address_string()} - {fmt % args}")

    def _send_cors_headers(self):
        """Отправляет CORS заголовки"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _handle_error(self, message: str, status_code: int = 500):
        """Обрабатывает ошибки"""
        self.logger.error(message)
        self.send_error(status_code, message)

    def _parse_request_body(self) -> Optional[Dict]:
        """Парсит тело запроса"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                return {}

            request_body = self.rfile.read(content_length)
            request_body_text = request_body.decode("utf-8", errors="replace")
            return json.loads(request_body_text)

        except Exception as e:
            self.logger.error(f"Error parsing request body: {e}")
            self._handle_error(f"Invalid JSON: {e}", 400)
            return None

    def _setup_gigachat_auth(self):
        """Настраивает аутентификацию GigaChat из заголовков"""
        if not self.config.proxy_settings.pass_token:
            return

        token = self.headers.get("Authorization", "").replace("Bearer ", "", 1)
        if not token:
            return

        self.logger.info("Setting up GigaChat auth from headers")

        if token.startswith("giga-user-"):
            user, password = token.replace("giga-user-", "", 1).split(":", 1)
            self.giga._settings.user = user
            self.giga._settings.password = password
            self.logger.debug("Using user/password auth")
        elif token.startswith("giga-cred-"):
            parts = token.replace("giga-cred-", "", 1).split(":", 1)
            self.giga._settings.credentials = parts[0]
            self.giga._settings.scope = parts[1] if len(parts) > 1 else self.config.gigachat_settings.scope
            self.logger.debug("Using credentials auth")
        elif token.startswith("giga-auth-"):
            self.giga._settings.access_token = token.replace("giga-auth-", "", 1)
            self.logger.debug("Using access token auth")

    def do_OPTIONS(self):
        """Обрабатывает OPTIONS запросы для CORS"""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        """Обрабатывает GET запросы"""
        if self.path in ("/models", "/v1/models"):
            self.handle_models_request()
        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        """Обрабатывает POST запросы"""
        if self.path in ("/chat/completions", "/v1/chat/completions"):
            self.handle_proxy_chat()
        elif self.path in ("/embeddings", "/v1/embeddings"):
            self.handle_proxy_embeddings()
        else:
            self.send_error(404, "Endpoint not found")

    def handle_proxy_chat(self):
        """Обрабатывает запросы к chat/completions"""
        try:
            json_body = self._parse_request_body()
            if json_body is None:
                return

            self.logger.info(f"Processing chat request with model: {json_body.get('model', 'default')}")

            if self.config.proxy_settings.verbose:
                self.logger.debug(f"Request headers: {dict(self.headers)}")
                self.logger.debug(f"Request body: {json.dumps(json_body, ensure_ascii=False, indent=2)}")

            self._setup_gigachat_auth()

            stream = json_body.get("stream", False)
            self.send_response(200)
            self._send_cors_headers()

            if stream:
                self._handle_streaming_chat(json_body)
            else:
                self._handle_normal_chat(json_body)

        except Exception as e:
            self._handle_error(f"Error processing chat request: {e}")

    def _handle_normal_chat(self, json_body: Dict):
        """Обрабатывает обычный (не-стриминговый) чат запрос"""
        try:
            chat_completion = self._send_to_gigachat(json_body)
            response_data = self.response_processor.process_response(
                chat_completion,
                json_body.get("model", self.config.gigachat_settings.model),
                is_tool_call="tools" in json_body
            )

            response_body = json.dumps(response_data, ensure_ascii=False, indent=2).encode("utf-8")

            if self.config.proxy_settings.verbose:
                self.logger.debug(f"Response: {response_body}")

            self._send_json_response(response_body)

        except Exception as e:
            self._handle_error(f"Error in normal chat: {e}")

    def _handle_streaming_chat(self, json_body: Dict):
        """Обрабатывает стриминговый чат запрос"""
        try:
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            for chunk in self._send_to_gigachat_stream(json_body):
                chunk_data = self.response_processor.process_stream_chunk(
                    chunk,
                    json_body.get("model", self.config.gigachat_settings.model),
                    is_tool_call="tools" in json_body
                )

                chunk_str = f"data: {json.dumps(chunk_data, ensure_ascii=False)}\r\n\r\n"
                self.wfile.write(chunk_str.encode("utf-8"))

                if self.config.proxy_settings.verbose:
                    self.logger.debug(f"Stream chunk: {chunk_str}")

            self.wfile.write(b"data: [DONE]\r\n\r\n")
            self.logger.info("Stream completed successfully")

        except Exception as e:
            self.logger.error(f"Error in streaming chat: {e}")

    def _send_json_response(self, response_body: bytes):
        """Отправляет JSON ответ с стандартными заголовками"""
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_body)))
        self.send_header('Connection', 'keep-alive')
        self._add_openai_headers()
        self.end_headers()
        self.wfile.write(response_body)
        print("ALL GOOD")

    def _add_openai_headers(self):
        """Добавляет стандартные заголовки OpenAI"""
        headers = {
            "Access-Control-Expose-Headers": "X-Request-ID",
            "OpenAI-Organization": "user-1234567890",
            "OpenAI-Processing-Ms": "100",
            "OpenAI-Version": "2020-10-01",
            "X-RateLimit-Limit-Requests": "10000",
            "X-RateLimit-Limit-Tokens": "50000000",
            "X-RateLimit-Remaining-Requests": "9999",
            "X-RateLimit-Remaining-Tokens": "49999945",
            "X-RateLimit-Reset-Requests": "6ms",
            "X-RateLimit-Reset-Tokens": "0s",
            "X-Request-ID": f"req_{uuid.uuid4()}",
        }

        for key, value in headers.items():
            self.send_header(key, value)

    def _send_to_gigachat(self, data: dict) -> ChatCompletion:
        """Отправляет запрос в GigaChat API"""
        transformed_data = self.request_transformer.transform_chat_parameters(data)
        transformed_data["messages"] = self.request_transformer.transform_messages(
            transformed_data.get("messages", [])
        )

        chat = Chat.parse_obj(transformed_data)
        chat.messages = self._collapse_messages(chat.messages)

        self.logger.info("Sending request to GigaChat API")
        return self.giga.chat(chat)

    def _send_to_gigachat_stream(self, data: dict) -> Iterator[ChatCompletionChunk]:
        """Отправляет стриминговый запрос в GigaChat API"""
        transformed_data = self.request_transformer.transform_chat_parameters(data)
        transformed_data["messages"] = self.request_transformer.transform_messages(
            transformed_data.get("messages", [])
        )

        chat = Chat.parse_obj(transformed_data)
        chat.messages = self._collapse_messages(chat.messages)

        self.logger.info("Sending streaming request to GigaChat API")
        return self.giga.stream(chat)

    @staticmethod
    def _collapse_messages(messages: List[Messages]) -> List[Messages]:
        """Объединяет последовательные пользовательские сообщения"""
        collapsed_messages = []
        for message in messages:
            if (collapsed_messages and
                    message.role == "user" and
                    collapsed_messages[-1].role == "user"):
                collapsed_messages[-1].content += "\n" + message.content
            else:
                collapsed_messages.append(message)
        return collapsed_messages

    def handle_proxy_embeddings(self):
        """Обрабатывает запросы к embeddings"""
        try:
            json_body = self._parse_request_body()
            if json_body is None:
                return

            self.logger.info("Processing embeddings request")

            if self.config.proxy_settings.verbose:
                self.logger.debug(f"Request headers: {dict(self.headers)}")
                self.logger.debug(f"Request body: {json.dumps(json_body, ensure_ascii=False, indent=2)}")

            self._setup_gigachat_auth()

            response_data = self._process_embeddings_request(json_body)
            response_body = json.dumps(response_data, ensure_ascii=False, indent=2).encode("utf-8")
            print(response_body)
            self._send_json_response(response_body)
            self.logger.info("Embeddings request completed successfully")

        except Exception as e:
            self._handle_error(f"Error processing embeddings request: {e}")

    def _process_embeddings_request(self, json_body: Dict) -> Dict:
        """Обрабатывает запрос embeddings"""
        encoding_format = json_body.pop("encoding_format", "float")
        dimensions = json_body.pop("dimensions", None)
        gpt_model = json_body.pop("model", self.config.proxy_settings.embeddings)

        if dimensions:
            self.logger.warning("Dimension parameter not supported in GigaChat")
            warnings.warn("Dimension parameter not supported!")

        input_data = json_body.get("input", [])
        processed_input = self._preprocess_embedding_input(input_data, gpt_model)

        self.logger.info(f"Getting embeddings for {len(processed_input)} texts")
        giga_resp = self.giga.embeddings(texts=processed_input, model=self.config.proxy_settings.embeddings)
        giga_dict = giga_resp.dict()

        usage_tokens = 0
        for embedding in giga_dict["data"]:
            if encoding_format == "base64":
                embedding["embedding"] = self._list_to_base64(embedding["embedding"])
            usage_tokens += embedding.pop("usage", {}).get("prompt_tokens", 0)

        giga_dict["model"] = gpt_model
        giga_dict["usage_tokens"] = {
            "prompt_tokens": usage_tokens,
            "total_tokens": usage_tokens
        }

        return giga_dict

    def _preprocess_embedding_input(self, input_data, gpt_model: str):
        """Предобрабатывает входные данные для embeddings"""
        if not input_data:
            return []

        if isinstance(input_data, list):
            if not input_data:
                return []

            if isinstance(input_data[0], int):
                return tiktoken.encoding_for_model(gpt_model).decode(input_data)
            else:
                processed = []
                for row in input_data:
                    if isinstance(row, list):
                        processed.append(tiktoken.encoding_for_model(gpt_model).decode(row))
                    else:
                        processed.append(row)
                return processed
        else:
            return [input_data]

    @staticmethod
    @lru_cache
    def _has_numpy() -> bool:
        try:
            import numpy
            return True
        except ImportError:
            return False

    def _list_to_base64(self, l: list[float]) -> str:
        """Конвертирует список float в base64 строку"""
        if self._has_numpy():
            import numpy as np
            arr = np.array(l, dtype=np.float32)
        else:
            arr = array.array("f", l)
        return base64.b64encode(arr).decode("utf-8")

    def handle_models_request(self):
        """Обрабатывает запросы к /models"""
        try:
            models_data = json.load(
                importlib.resources.open_text("gpt2giga", "gpt2giga_models.json")
            )

            response_data = json.dumps(models_data, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(response_data)

            self.logger.info("Models request handled successfully")

        except FileNotFoundError:
            self._handle_error("gpt2giga_models.json not found", 404)
        except Exception as e:
            self._handle_error(f"Error handling models request: {e}")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Многопоточный HTTP сервер"""
    daemon_threads = True


def run_proxy_server(config: ProxyConfig):
    """Запускает прокси-сервер"""
    logger.info(f"Starting proxy server on {config.proxy_settings.host}:{config.proxy_settings.port}")
    logger.info(f"Configuration: {config.dict()}")

    # Инициализируем GigaChat клиент
    giga_client = GigaChat(**config.gigachat_settings.dict())

    # Инициализируем обработчик
    ProxyHandler.initialize(config, giga_client)

    # Настраиваем логирование
    logging_level = logging.DEBUG if config.proxy_settings.verbose else logging.INFO
    logging.getLogger().setLevel(logging_level)

    # Запускаем сервер
    server_address = (config.proxy_settings.host, config.proxy_settings.port)
    httpd = ThreadingHTTPServer(server_address, ProxyHandler)

    logger.info(f"Proxy server is running on http://{config.proxy_settings.host}:{config.proxy_settings.port}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    finally:
        httpd.server_close()
        logger.info("Server shut down gracefully")


def add_nested_arguments(parser, model_class, prefix=""):
    """Рекурсивно добавляет аргументы для вложенных моделей"""
    for field_name, field in model_class.__fields__.items():
        if hasattr(field.type_, '__fields__'):  # Если поле само является моделью
            add_nested_arguments(parser, field.type_, f"{prefix}{field_name}-")
        else:
            arg_name = f"--{prefix}{field_name.replace('_', '-')}"
            help_text = field.field_info.description or field_name

            if field.type_ == bool:
                parser.add_argument(arg_name, action="store_true", default=None, help=help_text)
            else:
                parser.add_argument(arg_name, type=field.type_, default=None, help=help_text)


def load_config() -> ProxyConfig:
    """Загружает конфигурацию из аргументов командной строки и переменных окружения"""
    parser = argparse.ArgumentParser(
        description="Gpt2Giga converter proxy. Use GigaChat instead of OpenAI GPT models"
    )

    # Добавляем аргументы для proxy_settings
    for field_name, field in ProxySettings.__fields__.items():
        if field_name == "env_path":
            continue
        arg_name = f"--proxy-{field_name.replace('_', '-')}"
        help_text = field.field_info.description or field_name

        if field.type_ == bool:
            parser.add_argument(arg_name, action="store_true", default=None, help=help_text)
        else:
            parser.add_argument(arg_name, type=field.type_, default=None, help=help_text)

    # Добавляем аргументы для gigachat_settings
    for field_name, field in GigachatSettings.__fields__.items():
        arg_name = f"--gigachat-{field_name.replace('_', '-')}"
        help_text = field.field_info.description or field_name

        if field.type_ == bool:
            parser.add_argument(arg_name, action="store_true", default=None, help=help_text)
        else:
            parser.add_argument(arg_name, type=field.type_, default=None, help=help_text)

    parser.add_argument("--env-path", type=str, default=None, help="Path to .env file")

    args = parser.parse_args()

    # Загружаем переменные окружения
    env_path = find_dotenv(args.env_path if args.env_path else f"{os.getcwd()}/.env")
    load_dotenv(env_path)

    if env_path:
        logger.info(f"Loaded environment from: {env_path}")

    # Собираем конфигурацию из CLI аргументов
    proxy_settings_dict = {}
    gigachat_settings_dict = {}

    for arg_name, arg_value in vars(args).items():
        if arg_value is not None:
            if arg_name.startswith('proxy_'):
                field_name = arg_name.replace('proxy_', '').replace('-', '_')
                proxy_settings_dict[field_name] = arg_value
            elif arg_name.startswith('gigachat_'):
                field_name = arg_name.replace('gigachat_', '').replace('-', '_')
                gigachat_settings_dict[field_name] = arg_value

    # Создаем конфиг
    config = ProxyConfig(
        proxy_settings=ProxySettings(**proxy_settings_dict) if proxy_settings_dict else ProxySettings(),
        gigachat_settings=GigachatSettings(**gigachat_settings_dict) if gigachat_settings_dict else GigachatSettings()
    )

    return config


def main():
    """Основная функция"""
    try:
        config = load_config()
        run_proxy_server(config)
    except Exception as e:
        logger.error(f"Failed to start proxy server: {e}")
        raise


if __name__ == "__main__":
    main()