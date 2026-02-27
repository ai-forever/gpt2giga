import functools
import time

import anyio
import tiktoken
from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import StreamingResponse
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import (
    stream_chat_completion_generator,
    stream_responses_generator,
)
from gpt2giga.common.tools import convert_tool_to_giga_functions
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_docs import (
    chat_completions_openapi_extra,
    embeddings_openapi_extra,
    responses_openapi_extra,
)

router = APIRouter(tags=["API"])


@router.get("/models")
@exceptions_handler
async def show_available_models(request: Request):
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)
    response = await giga_client.aget_models()
    models = [i.model_dump(by_alias=True) for i in response.data]
    current_timestamp = int(time.time())
    for model in models:
        model["created"] = current_timestamp
    models = [OpenAIModel(**model) for model in models]
    model_page = AsyncPage(data=models, object=response.object_)
    return model_page


@router.get("/models/{model}")
@exceptions_handler
async def get_model(model: str, request: Request):
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)
    response = await giga_client.aget_model(model=model)
    model = response.model_dump(by_alias=True)
    model["created"] = int(time.time())
    return OpenAIModel(**model)


@router.post("/chat/completions", openapi_extra=chat_completions_openapi_extra())
@exceptions_handler
async def chat_completions(request: Request):
    data = await read_request_json(request)
    stream = data.get("stream", False)
    tools = "tools" in data or "functions" in data
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)
    if tools:
        data["functions"] = convert_tool_to_giga_functions(data)
        state.logger.debug(f"Functions count: {len(data['functions'])}")
    chat_messages = await state.request_transformer.prepare_chat_completion(
        data, giga_client
    )
    if not stream:
        response = await giga_client.achat(chat_messages)
        processed = state.response_processor.process_response(
            response, data["model"], current_rquid, request_data=data
        )
        return processed
    else:
        return StreamingResponse(
            stream_chat_completion_generator(
                request, data["model"], chat_messages, current_rquid, giga_client
            ),
            media_type="text/event-stream",
        )


@router.post("/embeddings", openapi_extra=embeddings_openapi_extra())
@exceptions_handler
async def embeddings(request: Request):
    data = await read_request_json(request)
    inputs = data.get("input", [])
    gpt_model = data.get("model", None)

    if isinstance(inputs, list):
        new_inputs = []
        if len(inputs) > 0 and isinstance(inputs[0], int):  # List[int]
            encoder = await anyio.to_thread.run_sync(
                functools.partial(tiktoken.encoding_for_model, gpt_model)
            )
            new_inputs = encoder.decode(inputs)
        else:
            encoder = None
            for row in inputs:
                if isinstance(row, list):  # List[List[int]]
                    if encoder is None:
                        encoder = await anyio.to_thread.run_sync(
                            functools.partial(tiktoken.encoding_for_model, gpt_model)
                        )
                    new_inputs.append(encoder.decode(row))
                else:
                    new_inputs.append(row)
    else:
        new_inputs = [inputs]

    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    embeddings = await giga_client.aembeddings(
        texts=new_inputs, model=request.app.state.config.proxy_settings.embeddings
    )

    return embeddings


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    data = await read_request_json(request)
    stream = data.get("stream", False)
    tools = "tools" in data or "functions" in data
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)
    if tools:
        data["functions"] = convert_tool_to_giga_functions(data)
        state.logger.debug(f"Functions count: {len(data['functions'])}")
    chat_messages = await state.request_transformer.prepare_response(data, giga_client)
    if not stream:
        response = await giga_client.achat(chat_messages)
        processed = state.response_processor.process_response_api(
            data, response, data["model"], current_rquid
        )
        return processed
    else:
        return StreamingResponse(
            stream_responses_generator(
                request, chat_messages, current_rquid, giga_client, request_data=data
            ),
            media_type="text/event-stream",
        )
