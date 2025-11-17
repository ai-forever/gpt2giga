import time

import tiktoken
from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import StreamingResponse
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel
from gpt2giga.logger import rquid_context
from gpt2giga.utils import (
    exceptions_handler,
    stream_responses_generator,
    stream_chat_completion_generator,
    convert_tool_to_giga_functions,
)

router = APIRouter(tags=["API"])


@router.get("/models")
@exceptions_handler
async def show_available_models(request: Request):
    state = request.app.state
    response = await state.gigachat_client.aget_models()
    models = [i.dict(by_alias=True) for i in response.data]
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
    response = await state.gigachat_client.aget_model(model=model)
    model = response.dict(by_alias=True)
    model["created"] = int(time.time())
    return OpenAIModel(**model)


@router.post("/chat/completions")
@exceptions_handler
async def chat_completions(request: Request):
    data = await request.json()
    stream = data.get("stream", False)
    tools = "tools" in data or "functions" in data
    is_response_api = "input" in data
    current_rquid = rquid_context.get()
    state = request.app.state
    if tools:
        data["functions"] = convert_tool_to_giga_functions(data)
        state.logger.debug(f"Functions count: {len(data['functions'])}")
    chat_messages = await state.request_transformer.send_to_gigachat(data)
    if not stream:
        response = await state.gigachat_client.achat(chat_messages)
        if is_response_api:
            processed = state.response_processor.process_response_api(
                data, response, chat_messages.model, current_rquid
            )
        else:
            processed = state.response_processor.process_response(
                response, chat_messages.model, current_rquid
            )
        return processed
    else:
        if is_response_api:
            return StreamingResponse(
                stream_responses_generator(request, chat_messages, current_rquid),
                media_type="text/event-stream",
            )
        else:
            return StreamingResponse(
                stream_chat_completion_generator(request, chat_messages, current_rquid),
                media_type="text/event-stream",
            )


@router.post("/embeddings")
@exceptions_handler
async def embeddings(request: Request):
    data = await request.json()
    inputs = data.get("input", [])
    gpt_model = data.get("model", None)

    if isinstance(inputs, list):
        new_inputs = []
        if isinstance(inputs[0], int):  # List[int]:
            encoder = tiktoken.encoding_for_model(gpt_model)
            new_inputs = encoder.decode(inputs)
        else:
            encoder = None
            for row in inputs:
                if isinstance(row, list):  # List[List[int]]
                    if encoder is None:
                        encoder = tiktoken.encoding_for_model(gpt_model)
                    new_inputs.append(encoder.decode(row))
                else:
                    new_inputs.append(row)
    else:
        new_inputs = [inputs]

    embeddings = await request.app.state.gigachat_client.aembeddings(
        texts=new_inputs, model=request.app.state.config.proxy_settings.embeddings
    )

    return embeddings


@router.post("/responses")
@exceptions_handler
async def responses(request: Request):
    return await chat_completions(request)
