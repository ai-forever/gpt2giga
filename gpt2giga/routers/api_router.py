import time
from typing import Optional

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import StreamingResponse
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_form import read_request_multipart
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import (
    stream_chat_completion_generator,
    stream_responses_generator,
)
from gpt2giga.common.tools import convert_tool_to_giga_functions
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_docs import (
    batches_openapi_extra,
    chat_completions_openapi_extra,
    embeddings_openapi_extra,
    files_openapi_extra,
    responses_openapi_extra,
)
from gpt2giga.protocol.batches import (
    build_openai_batch_object,
    get_batch_target,
    infer_openai_file_purpose,
    map_openai_file_purpose,
    transform_batch_input_file,
    transform_batch_output_file,
    transform_embedding_body,
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


def _model_info_entry(model_id: str) -> dict:
    return {
        "model_name": model_id,
        "litellm_params": {"model": model_id},
        "model_info": {"id": model_id},
    }


@router.get("/model/info")
@exceptions_handler
async def get_model_info(request: Request, model: Optional[str] = None):
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    if model:
        response = await giga_client.aget_model(model=model)
        return _model_info_entry(response.id_)
    response = await giga_client.aget_models()
    return {"data": [_model_info_entry(m.id_) for m in response.data]}


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
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    transformed = await transform_embedding_body(
        data, request.app.state.config.proxy_settings.embeddings
    )
    embeddings = await giga_client.aembeddings(
        texts=transformed["input"], model=transformed["model"]
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


def _get_batch_store(request: Request) -> dict:
    state = request.app.state
    if not hasattr(state, "batch_metadata_store"):
        state.batch_metadata_store = {}
    return state.batch_metadata_store


def _get_file_store(request: Request) -> dict:
    state = request.app.state
    if not hasattr(state, "file_metadata_store"):
        state.file_metadata_store = {}
    return state.file_metadata_store


def _serialize_file_object(file_obj, stored_metadata: Optional[dict] = None) -> dict:
    stored_metadata = stored_metadata or {}
    purpose = infer_openai_file_purpose(
        getattr(file_obj, "purpose", None), stored_metadata.get("purpose")
    )
    return {
        "id": getattr(file_obj, "id_", ""),
        "object": "file",
        "bytes": getattr(file_obj, "bytes_", 0),
        "created_at": getattr(file_obj, "created_at", None),
        "filename": getattr(file_obj, "filename", ""),
        "purpose": purpose,
        "status": stored_metadata.get("status", "processed"),
        "expires_at": stored_metadata.get("expires_at"),
        "status_details": stored_metadata.get("status_details"),
    }


def _paginate_items(
    items: list, after: Optional[str], limit: Optional[int]
) -> tuple[list, bool]:
    if after:
        for index, item in enumerate(items):
            if item.get("id") == after:
                items = items[index + 1 :]
                break
    if limit is None:
        return items, False
    return items[:limit], len(items) > limit


@router.post("/files", openapi_extra=files_openapi_extra())
@exceptions_handler
async def create_file(request: Request):
    multipart = await read_request_multipart(request)
    purpose = multipart["form"].get("purpose")
    upload = multipart["files"].get("file")
    if not purpose or upload is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Multipart upload requires both `file` and `purpose`.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_multipart",
                }
            },
        )

    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    uploaded = await giga_client.aupload_file(
        (upload["filename"], upload["content"], upload["content_type"]),
        purpose=map_openai_file_purpose(purpose),
    )

    file_store = _get_file_store(request)
    file_store[uploaded.id_] = {
        "purpose": purpose,
        "filename": upload["filename"],
        "status": "processed",
    }
    return _serialize_file_object(uploaded, file_store[uploaded.id_])


@router.get("/files")
@exceptions_handler
async def list_files(
    request: Request,
    after: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None),
    order: Optional[str] = Query(default=None),
    purpose: Optional[str] = Query(default=None),
):
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    files = await giga_client.aget_files()
    file_store = _get_file_store(request)
    data = [
        _serialize_file_object(file_obj, file_store.get(file_obj.id_))
        for file_obj in files.data
    ]
    if purpose:
        data = [item for item in data if item["purpose"] == purpose]
    if order == "desc":
        data = sorted(data, key=lambda item: item.get("created_at") or 0, reverse=True)
    elif order == "asc":
        data = sorted(data, key=lambda item: item.get("created_at") or 0)
    paged, has_more = _paginate_items(data, after, limit)
    return {"data": paged, "has_more": has_more, "object": "list"}


@router.get("/files/{file_id}")
@exceptions_handler
async def retrieve_file(file_id: str, request: Request):
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    file_store = _get_file_store(request)
    file_obj = await giga_client.aget_file(file=file_id)
    return _serialize_file_object(file_obj, file_store.get(file_id))


@router.delete("/files/{file_id}")
@exceptions_handler
async def delete_file(file_id: str, request: Request):
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    deleted = await giga_client.adelete_file(file=file_id)
    _get_file_store(request).pop(file_id, None)
    return {
        "id": deleted.id_,
        "deleted": deleted.deleted,
        "object": "file",
    }


@router.get("/files/{file_id}/content")
@exceptions_handler
async def get_file_content(file_id: str, request: Request):
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    file_response = await giga_client.aget_file_content(file_id=file_id)
    batch_store = _get_batch_store(request)
    matching_batch = next(
        (
            meta
            for meta in batch_store.values()
            if meta.get("output_file_id") == file_id
        ),
        None,
    )
    if matching_batch:
        input_file = await giga_client.aget_file_content(
            file_id=matching_batch["input_file_id"]
        )
        content = await transform_batch_output_file(
            file_response.content,
            batch_metadata=matching_batch,
            input_content_b64=input_file.content,
            response_processor=request.app.state.response_processor,
        )
    else:
        import base64

        content = base64.b64decode(file_response.content)
    return Response(content=content, media_type="application/octet-stream")


@router.post("/batches", openapi_extra=batches_openapi_extra())
@exceptions_handler
async def create_batch(request: Request):
    data = await read_request_json(request)
    completion_window = data.get("completion_window")
    input_file_id = data.get("input_file_id")
    if completion_window != "24h":
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": 'Only `completion_window="24h"` is supported.',
                    "type": "invalid_request_error",
                    "param": "completion_window",
                    "code": None,
                }
            },
        )
    if not input_file_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "`input_file_id` is required.",
                    "type": "invalid_request_error",
                    "param": "input_file_id",
                    "code": None,
                }
            },
        )

    target = get_batch_target(data.get("endpoint", ""))
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    file_content = await giga_client.aget_file_content(file_id=input_file_id)

    import base64

    transformed_content = await transform_batch_input_file(
        base64.b64decode(file_content.content),
        target=target,
        request_transformer=request.app.state.request_transformer,
        giga_client=giga_client,
        embeddings_model=request.app.state.config.proxy_settings.embeddings,
    )
    batch = await giga_client.acreate_batch(
        transformed_content,
        method=target.method,
    )

    metadata = {
        "endpoint": target.endpoint,
        "input_file_id": input_file_id,
        "completion_window": completion_window,
        "metadata": data.get("metadata"),
        "output_file_id": batch.output_file_id,
    }
    _get_batch_store(request)[batch.id_] = metadata
    if batch.output_file_id:
        _get_file_store(request)[batch.output_file_id] = {"purpose": "batch_output"}
    return build_openai_batch_object(batch, metadata)


@router.get("/batches")
@exceptions_handler
async def list_batches(
    request: Request,
    after: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None),
):
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    batch_store = _get_batch_store(request)
    file_store = _get_file_store(request)
    batches = await giga_client.aget_batches()
    data = []
    for batch in batches.batches:
        metadata = batch_store.get(batch.id_) or {
            "endpoint": "/v1/chat/completions",
            "input_file_id": "",
            "completion_window": "24h",
        }
        metadata["output_file_id"] = batch.output_file_id
        batch_store[batch.id_] = metadata
        if batch.output_file_id:
            file_store[batch.output_file_id] = {"purpose": "batch_output"}
        data.append(build_openai_batch_object(batch, metadata))
    paged, has_more = _paginate_items(data, after, limit)
    return {"data": paged, "has_more": has_more, "object": "list"}


@router.get("/batches/{batch_id}")
@exceptions_handler
async def retrieve_batch(batch_id: str, request: Request):
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    batch_store = _get_batch_store(request)
    file_store = _get_file_store(request)
    batches = await giga_client.aget_batches(batch_id=batch_id)
    if not batches.batches:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"Batch `{batch_id}` not found.",
                    "type": "not_found_error",
                    "param": "batch_id",
                    "code": None,
                }
            },
        )
    batch = batches.batches[0]
    metadata = batch_store.get(batch_id) or {
        "endpoint": "/v1/chat/completions",
        "input_file_id": "",
        "completion_window": "24h",
    }
    metadata["output_file_id"] = batch.output_file_id
    batch_store[batch_id] = metadata
    if batch.output_file_id:
        file_store[batch.output_file_id] = {"purpose": "batch_output"}
    return build_openai_batch_object(batch, metadata)
