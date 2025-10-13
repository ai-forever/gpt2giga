import json
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import gigachat
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from gigachat import GigaChat
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel

from gpt2giga import ImageProcessor, RequestTransformer, ResponseProcessor
from gpt2giga.cli import load_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    app.state.gigachat_client = GigaChat(**config.gigachat_settings.dict())
    image_processor = ImageProcessor(app.state.gigachat_client)
    app.state.request_transformer = RequestTransformer(config, image_processor)
    app.state.response_processor = ResponseProcessor()
    yield

router = APIRouter()
app = FastAPI(lifespan=lifespan)

@router.get("/health", response_class=Response)
async def health() -> Response:
    """Health check."""
    try:
        return Response(status_code=200)
    except:
        return Response(status_code=503)

@router.get("/ping", response_class=Response)
@router.post("/ping", response_class=Response)
async def ping() -> Response:
    return await health()

@router.get("/models")
@router.get("/v1/models")
async def show_available_models(raw_request: Request):
    response = await raw_request.app.state.gigachat_client.aget_models()
    models = [i.dict(by_alias=True) for i in response.data]
    current_timestamp = int(time.time())
    for model in models:
        model['created'] = current_timestamp
    models = [OpenAIModel(**model) for model in models]
    model_page = AsyncPage(data=models, object=response.object_)
    return model_page

@router.get("/models/{model}")
@router.get("/v1/models/{model}")
async def get_model(model: str, request: Request):

    try:
        response = await request.app.state.gigachat_client.aget_model(model=model)
        model = response.dict(by_alias=True)
        model['created'] = int(time.time())

    except gigachat.exceptions.ResponseError as e:
        url, status_code, message, _ = e.args
        error_detail = json.loads(message)
        raise HTTPException(status_code=status_code,
                            detail=error_detail)
    return OpenAIModel(**model)


@router.post("/v1/chat/completions")
@router.post("/chat/completions")
async def chat_completions(request: Request):
    data = await request.json()
    stream = data.get("stream", False)
    chat_messages = app.state.request_transformer.send_to_gigachat(data)
    if not stream:
        response = await request.app.state.gigachat_client.achat(chat_messages)
        return response
    else:
        async def stream_generator() -> AsyncGenerator[str, None]:
            """
            Yields formatted SSE (Server-Sent Events) chunks
            as they arrive from the model.
            """
            async for chunk in request.app.state.gigachat_client.astream(chat_messages):
                # Process and format the chunk
                processed = request.app.state.response_processor.process_stream_chunk(
                    chunk,
                    chat_messages.model,
                    is_tool_call="tools" in chat_messages
                )
                # Convert to proper SSE format
                yield f"data: {json.dumps(processed)}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")




@router.post("/v1/embeddings")
@router.post("/embeddings")
async def embeddings(request: Request):
    data = await request.json()

app.include_router(router)



