import argparse
import array
import base64
import http.server
import json
import logging
import os
import socketserver
import time
import uuid
import warnings
from functools import lru_cache
from typing import Optional, Tuple, List, Iterator

import tiktoken
from dotenv import find_dotenv, load_dotenv
from gigachat import GigaChat
from gigachat.client import GIGACHAT_MODEL
from gigachat.models import Chat, ChatCompletion, ChatCompletionChunk, Messages
from gigachat.settings import SCOPE, BASE_URL


def process_gigachat_response(giga_resp: ChatCompletion, gpt_model: str) -> dict:
    """
    Processes the response from GigaChat API and transforms it to the format expected by the client.

    Args:
        giga_resp: The response from GigaChat API.
        gpt_model: The GPT model name.

    Returns:
        A dictionary formatted as the client's expected response.
    """
    giga_dict = giga_resp.dict()

    for choice in giga_dict["choices"]:
        choice["index"] = 0
        choice["logprobs"] = None
        choice["message"]["refusal"] = None
        if choice["message"]["role"] == "assistant":
            if choice["message"].get("function_call"):
                arguments = json.dumps(
                    choice["message"]["function_call"]["arguments"],
                    ensure_ascii=False,
                )
                choice["message"]["function_call"] = {
                    "name": choice["message"]["function_call"]["name"],
                    "arguments": arguments,
                }
                if choice["message"].get("content") == "":
                    choice["message"]["content"] = None
                choice["message"].pop("functions_state_id", None)
                choice["message"]["refusal"] = None

    result = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time() * 1000),
        "model": gpt_model,
        "choices": giga_dict["choices"],
        "usage": {
            "prompt_tokens": giga_dict["usage"]["prompt_tokens"],
            "completion_tokens": giga_dict["usage"]["completion_tokens"],
            "total_tokens": giga_dict["usage"]["total_tokens"],
            "prompt_tokens_details": {"cached_tokens": giga_dict["usage"].get("precached_prompt_tokens", 0)},
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
        "system_fingerprint": f"fp_{uuid.uuid4()}",
    }
    return result


def process_gigachat_stream(giga_resp: ChatCompletionChunk, gpt_model: str) -> dict:
    """
    Processes the response from GigaChat API stream and transforms it to the format expected by the client.

    Args:
        giga_resp: The response from GigaChat API stream.
        gpt_model: The GPT model name.

    Returns:
        A dictionary formatted as the client's expected response.
    """
    giga_dict = giga_resp.dict()

    for choice in giga_dict["choices"]:
        choice["index"] = 0
        choice["logprobs"] = None
        if choice["delta"].get("function_call"):
            arguments = json.dumps(
                choice["message"]["function_call"]["arguments"],
                ensure_ascii=False,
            )
            choice["message"]["function_call"] = {
                "name": choice["message"]["function_call"]["name"],
                "arguments": arguments,
            }
            if choice["delta"].get("content") == "":
                choice["delta"]["content"] = None
            choice["delta"].pop("functions_state_id", None)
    usage = None
    if giga_dict.get("usage", None) is not None:
        usage = {
            "prompt_tokens": giga_dict["usage"]["prompt_tokens"],
            "completion_tokens": giga_dict["usage"]["completion_tokens"],
            "total_tokens": giga_dict["usage"]["total_tokens"],
            "prompt_tokens_details": {"cached_tokens": giga_dict["usage"].get("precached_prompt_tokens", 0)},
            "completion_tokens_details": {"reasoning_tokens": 0},
        }

    result = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time() * 1000),
        "model": gpt_model,
        "choices": giga_dict["choices"],
        "usage": usage,
        "system_fingerprint": f"fp_{uuid.uuid4()}",
    }
    return result


@lru_cache
def has_numpy() -> bool:
    try:
        import numpy
    except ImportError:
        return False

    return True

def list_to_base64(l: list[float]) -> str:
    if has_numpy():
        import numpy as np
        arr = np.array(l, dtype=np.float32)
    else:
        arr = array.array("f", l)
    return base64.b64encode(arr).decode("utf-8")


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """
    Handles HTTP requests and proxies them to the GigaChat API after transforming the data.
    """
    giga: Optional[GigaChat] = None
    verbose: bool = False
    pass_token: bool = False
    pass_model: bool = False
    embeddings: str = "EmbeddingsGigaR"

    def __init__(self, *args, **kwargs):
        self.giga = self.__class__.giga
        self.verbose = self.__class__.verbose
        self.pass_token = self.__class__.pass_token
        self.pass_model = self.__class__.pass_model
        self.embeddings = self.__class__.embeddings
        super().__init__(*args, **kwargs)

    def transform_input_data(self, data: dict) -> Tuple[Chat, Optional[str]]:
        """
        Transforms the input data from the client to the format expected by GigaChat API.

        Args:
            data: The input data dictionary.

        Returns:
            A tuple containing the Chat object and the GPT model name.
        """
        gpt_model = data.get("model", None)
        if not self.pass_model and gpt_model:
            del data["model"]
        temperature = data.pop("temperature", 0)
        if temperature == 0:
            data["top_p"] = 0
        elif temperature and temperature > 0:
            data["temperature"] = temperature

        if "functions" not in data and data.get("tools"):
            data["functions"] = [
                tool["function"] for tool in data.get("tools", []) if tool["type"] == "function"
            ]

        for i, message in enumerate(data["messages"]):
            message.pop("name", None)
            # No non-first system messages available.
            if message["role"] == "system" and i > 0:
                message["role"] = "user"
            if message["role"] == "tool":
                message["role"] = "function"
                message["content"] = json.dumps(message.get("content", ""), ensure_ascii=False)
            if message["content"] is None:
                message["content"] = ""

        chat = Chat.parse_obj(data)
        return chat, gpt_model

    def pass_token_to_gigachat(self, token: str) -> None:
        self.giga._settings.credentials = None
        self.giga._settings.user = None
        self.giga._settings.password = None
        if token.startswith("giga-user-"):
            user, password = token.replace("giga-user-", "", 1).split(":")
            self.giga._settings.user = user
            self.giga._settings.password = password
        elif token.startswith("giga-cred-"):
            parts = token.replace("giga-cred-", "", 1).split(":")
            self.giga._settings.credentials = parts[0]
            self.giga._settings.scope = parts[1] if len(parts) > 1 else SCOPE
        elif token.startswith("giga-auth-"):
            self.giga._settings.access_token = token.replace("giga-auth-", "", 1)

    @staticmethod
    def collapse_messages(messages: List[Messages]):
        # Collapse consecutive user role messages into one
        collapsed_messages = []
        for message in messages:
            if collapsed_messages and message.role == "user" and collapsed_messages[-1].role == "user":
                collapsed_messages[-1].content += "\n" + message.content
            else:
                collapsed_messages.append(message)
        return collapsed_messages

    def send_to_gigachat(self, data: dict) -> dict:
        """
        Sends the transformed data to GigaChat API and processes the response.

        Args:
            data: The input data dictionary.

        Returns:
            The processed response dictionary.
        """

        chat, gpt_model = self.transform_input_data(data)
        chat.messages = self.collapse_messages(chat.messages)
        giga_resp = self.giga.chat(chat)
        result = process_gigachat_response(giga_resp, gpt_model)
        return result

    def send_to_gigachat_stream(self, data: dict) -> Iterator[dict]:
        """
        Sends the transformed data to GigaChat API and processes the response.

        Args:
            data: The input data dictionary.

        Returns:
            The processed response dictionary.
        """

        chat, gpt_model = self.transform_input_data(data)
        chat.messages = self.collapse_messages(chat.messages)
        for chunk in self.giga.stream(chat):
            yield process_gigachat_stream(chunk, gpt_model)

    def do_GET(self):
        if self.path in ("/models", "/v1/models"):
            self.handle_models_request()
        else:
            self.handle_proxy_chat()

    def do_POST(self):
        if self.path in ("/embeddings", "/v1/embeddings"):
            self.handle_proxy_embeddings()
        else:
            self.handle_proxy_chat()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self._send_CORS_headers()
        self.end_headers()

    def _send_CORS_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def handle_proxy_chat(self):
        """
        Handles proxy requests by forwarding them to GigaChat Chat API
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            request_body = self.rfile.read(content_length) if content_length else b''
            request_body_text = request_body.decode("utf-8", errors="replace")
            json_body = json.loads(request_body_text)
            stream = json_body.pop("stream", False)

            if self.verbose:
                logging.info(f"Request Headers: {self.headers}")
                logging.info("Request Body:")
                logging.info(json.dumps(json_body, ensure_ascii=False, indent=2))

            if self.pass_token:
                token = self.headers.get("Authorization", "").replace("Bearer ", "", 1)
                self.pass_token_to_gigachat(token)

            self.send_response(200)
            self._send_CORS_headers()

            if stream:
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                if self.verbose:
                    logging.info("Response:")
                for chunk in self.send_to_gigachat_stream(json_body):
                    chunk_send = f"data: {json.dumps(chunk, ensure_ascii=False)}\r\n\r\n"
                    self.wfile.write(chunk_send.encode("utf-8"))
                    if self.verbose:
                        logging.info(chunk)
                self.wfile.write(b"data: [DONE]\r\n\r\n")
                self.wfile.write(b"\r\n\r\n")
            else:
                giga_resp = self.send_to_gigachat(json_body)
                response_body = json.dumps(giga_resp, ensure_ascii=False, indent=2).encode("utf-8")

                if self.verbose:
                    logging.info("Response:")
                    logging.info(response_body)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response_body)))
                self.send_header('Connection', 'keep-alive')
                self.send_header("Access-Control-Expose-Headers", "X-Request-ID")
                self.send_header("OpenAI-Organization", "user-1234567890")
                self.send_header("OpenAI-Processing-Ms", "100")
                self.send_header("OpenAI-Version", "2020-10-01")
                self.send_header("X-RateLimit-Limit-Requests", "10000")
                self.send_header("X-RateLimit-Limit-Tokens", "50000000")
                self.send_header("X-RateLimit-Remaining-Requests", "9999")
                self.send_header("X-RateLimit-Remaining-Tokens", "49999945")
                self.send_header("X-RateLimit-Reset-Requests", "6ms")
                self.send_header("X-RateLimit-Reset-Tokens", "0s")
                self.send_header("X-Request-ID", "req_" + str(uuid.uuid4()))
                self.end_headers()
                self.wfile.write(response_body)
        except Exception as e:
            logging.error(f"Error processing the request: {e}", exc_info=True)
            self.send_error(500, f"Error processing the request: {e}")

    def handle_proxy_embeddings(self):
        """
        Handles proxy requests by forwarding them to GigaChat Embeddings API
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            request_body = self.rfile.read(content_length) if content_length else b''
            request_body_text = request_body.decode("utf-8", errors="replace")
            json_body = json.loads(request_body_text)
            encoding_format = json_body.pop("encoding_format", "float")
            dimensions = json_body.pop("dimensions", None)
            gpt_model = json_body.pop("model", None)
            if dimensions:
                warnings.warn("Dimension parameter not supported!")

            if self.verbose:
                logging.info(f"Request Headers: {self.headers}")
                logging.info("Request Body:")
                logging.info(json.dumps(json_body, ensure_ascii=False, indent=2))

            if self.pass_token:
                token = self.headers.get("Authorization", "").replace("Bearer ", "", 1)
                self.pass_token_to_gigachat(token)

            self.send_response(200)
            self._send_CORS_headers()

            input_ = json_body.get("input", [])
            if isinstance(input_, list):
                new_input = []
                if len(input_) > 0:
                    if isinstance(input_[0], int):
                        new_input = tiktoken.encoding_for_model(gpt_model).decode(input_)
                    else:
                        for row in input_:
                            if isinstance(row, list):
                                new_input.append(tiktoken.encoding_for_model(gpt_model).decode(row))
                            else:
                                new_input.append(row)
            else:
                new_input = input_

            giga_resp = self.giga.embeddings(texts=new_input, model=self.embeddings).dict()
            usage_tokens = 0
            for embedding in giga_resp["data"]:
                if encoding_format == "base64":
                    embedding["embedding"] = list_to_base64(embedding["embedding"])
                usage_tokens += embedding.pop("usage", {}).get("prompt_tokens", 0)
            giga_resp["model"] = gpt_model
            giga_resp["usage_tokens"] = {
                "prompt_tokens": usage_tokens,
                "total_tokens": usage_tokens
            }

            response_body = json.dumps(giga_resp, ensure_ascii=False, indent=2).encode("utf-8")

            if self.verbose:
                logging.info("Response:")
                logging.info(response_body)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response_body)))
            self.send_header('Connection', 'keep-alive')
            self.send_header("Access-Control-Expose-Headers", "X-Request-ID")
            self.send_header("OpenAI-Organization", "user-1234567890")
            self.send_header("OpenAI-Processing-Ms", "100")
            self.send_header("OpenAI-Version", "2020-10-01")
            self.send_header("X-RateLimit-Limit-Requests", "10000")
            self.send_header("X-RateLimit-Limit-Tokens", "50000000")
            self.send_header("X-RateLimit-Remaining-Requests", "9999")
            self.send_header("X-RateLimit-Remaining-Tokens", "49999945")
            self.send_header("X-RateLimit-Reset-Requests", "6ms")
            self.send_header("X-RateLimit-Reset-Tokens", "0s")
            self.send_header("X-Request-ID", "req_" + str(uuid.uuid4()))
            self.end_headers()
            self.wfile.write(response_body)
        except Exception as e:
            logging.error(f"Error processing the request: {e}", exc_info=True)
            self.send_error(500, f"Error processing the request: {e}")

    def handle_models_request(self):
        """
        Handles requests to /models or /v1/models by returning the models.json content.
        """
        try:
            with open("models.json", "r", encoding="utf-8") as f:
                models_data = json.load(f)

            response_data = json.dumps(models_data, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_data)))
            self._send_CORS_headers()
            self.end_headers()
            self.wfile.write(response_data)
        except FileNotFoundError:
            self.send_error(404, "models.json not found")
        except Exception as e:
            logging.error(f"Error handling /v1/models request: {e}", exc_info=True)
            self.send_error(500, "Internal Server Error")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """This class allows to handle requests in separate threads."""


def run_proxy_server(host: str, port: int,
                     verbose: bool = False,
                     pass_model: bool = False,
                     pass_token: bool = False,
                     base_url: str = BASE_URL,
                     model: str = GIGACHAT_MODEL,
                     timeout: int = 600,
                     embeddings: str = "EmbeddingsGigaR"):
    """
    Runs the proxy server.

    Args:
        host: The host to listen on.
        port: The port to listen on.
        verbose: Enables verbose logging if True.
        pass_model: Pass model from request to GigaChat API
        pass_token: Pass token from request to GigaChat API
        base_url: The base url of API
        model: Model for requests
        timeout: Timeout
        embeddings: Embeddings model
    """
    server_address = (host, port)
    ProxyHandler.verbose = verbose
    ProxyHandler.giga = GigaChat(base_url=base_url, model=model, timeout=timeout, profanity_check=False)
    ProxyHandler.pass_token = pass_token
    ProxyHandler.pass_model = pass_model
    ProxyHandler.embeddings = embeddings

    logging_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=logging_level)

    httpd = ThreadingHTTPServer(server_address, ProxyHandler)
    print(f"Serving HTTP proxy on {host} port {port}...")
    httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser(
        description="Gpt2Giga converter proxy. Use GigaChat instead of OpenAI GPT models"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host to listen on",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to listen on",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=None,
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--pass-model",
        action="store_true",
        default=None,
        help="Pass chat model from request to API"
    )
    parser.add_argument(
        "--pass-token",
        action="store_true",
        default=None,
        help="Pass token from request to API"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Base url for GigaChat API",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model of GigaChat API",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Timeout for GigaChat API",
    )
    parser.add_argument(
        "--embeddings",
        type=str,
        default=None,
        help="Embeddings model for GigaChat API",
    )
    parser.add_argument(
        "--env-path",
        type=str,
        default=None,
        help="Path to .env file (including .env file name)",
    )

    args = parser.parse_args()

    # Load environment variables
    env_path = find_dotenv(args.env_path if args.env_path else f"{os.getcwd()}/.env")
    load_dotenv(env_path)
    defaults = {
        "host": os.getenv("PROXY_HOST", "localhost"),
        "port": int(os.getenv("PROXY_PORT", "8090")),
        "verbose": os.getenv("GPT2GIGA_VERBOSE", "False") != "False",
        "pass_model": os.getenv("GPT2GIGA_PASS_MODEL", "False") != "False",
        "pass_token": os.getenv("GPT2GIGA_PASS_TOKEN", "False") != "False",
        "base_url": os.getenv("GIGACHAT_BASE_URL", BASE_URL),
        "model": os.getenv("GIGACHAT_MODEL", GIGACHAT_MODEL),
        "timeout": os.getenv("GPT2GIGA_TIMEOUT", 600),
        "embeddings": os.getenv("GPT2GIGA_EMBEDDINGS", "EmbeddingsGigaR"),
    }
    for key, value in defaults.items():
        if getattr(args, key) is None:
            setattr(args, key, value)

    run_proxy_server(
        args.host, args.port, args.verbose,
        args.pass_model, args.pass_token,
        args.base_url, args.model, args.timeout,
        args.embeddings
    )


if __name__ == "__main__":
    main()
