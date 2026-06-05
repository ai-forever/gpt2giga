"""Check per-model max connections with real async OpenAI SDK calls.

Start the proxy in another terminal with a visible fail-fast limit:

    GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2":1}' \
    GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=0 \
    uv run gpt2giga

Then run:

    uv run python examples/openai/chat_completions/per_model_max_connections_async.py

Expected result: the holder stream occupies the single model slot, and the
contender requests receive HTTP 429 with code=model_concurrency_limit.
"""

import asyncio
import os
from collections.abc import Sequence
from contextlib import suppress

from openai import APIStatusError, AsyncOpenAI


BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:8090")
API_KEY = os.getenv("OPENAI_API_KEY", "0")
MODEL = os.getenv("GPT2GIGA_EXAMPLE_MODEL", "GigaChat-2")
HOLD_SECONDS = float(os.getenv("GPT2GIGA_EXAMPLE_HOLD_SECONDS", "3"))
CONTENDERS = int(os.getenv("GPT2GIGA_EXAMPLE_CONTENDERS", "2"))
FIRST_CHUNK_TIMEOUT = float(os.getenv("GPT2GIGA_EXAMPLE_FIRST_CHUNK_TIMEOUT", "30"))


def _error_code(exc: APIStatusError) -> str | None:
    try:
        body = exc.response.json()
    except ValueError:
        return None

    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return code if isinstance(code, str) else None
    return None


async def _wait_until_stream_slot_is_held(
    holder: asyncio.Task[None],
    first_chunk_seen: asyncio.Event,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + FIRST_CHUNK_TIMEOUT

    while not first_chunk_seen.is_set():
        if holder.done():
            await holder
            raise RuntimeError("holder stream finished before the first chunk")
        if loop.time() >= deadline:
            holder.cancel()
            raise TimeoutError("timed out waiting for the first stream chunk")
        await asyncio.sleep(0.05)


async def hold_stream_slot(
    client: AsyncOpenAI,
    first_chunk_seen: asyncio.Event,
) -> None:
    print(f"holder: starting stream model={MODEL!r}")
    stream = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Отвечай развернуто."},
            {
                "role": "user",
                "content": "Напиши 5 коротких пунктов про асинхронность.",
            },
        ],
        stream=True,
    )

    first_chunk = True
    async for event in stream:
        if not event.choices:
            continue

        text = event.choices[0].delta.content or ""
        if first_chunk:
            first_chunk = False
            first_chunk_seen.set()
            print(
                "holder: got first chunk, keeping the model slot "
                f"for {HOLD_SECONDS:.1f}s"
            )
            if text:
                print(f"holder chunk: {text!r}")
            await asyncio.sleep(HOLD_SECONDS)
        elif text:
            print(f"holder chunk: {text!r}")

    print("holder: stream finished")


async def contender_request(client: AsyncOpenAI, index: int) -> str:
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": f"Коротко ответь: проверочный запрос {index}.",
                }
            ],
        )
    except APIStatusError as exc:
        return f"contender {index}: HTTP {exc.status_code}, code={_error_code(exc)!r}"

    content = response.choices[0].message.content
    return f"contender {index}: OK, content={content!r}"


def print_summary(results: Sequence[str]) -> None:
    print("\nresults:")
    for result in results:
        print(f"- {result}")

    limited = [result for result in results if "model_concurrency_limit" in result]
    if limited:
        print("\nper-model limiter is visible: at least one request was rate-limited.")
    else:
        print(
            "\nNo 429 was observed. Check that the proxy was started with "
            "GPT2GIGA_MODEL_MAX_CONNECTIONS for this model and "
            "GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=0."
        )


async def main() -> None:
    client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
    first_chunk_seen = asyncio.Event()
    holder = asyncio.create_task(hold_stream_slot(client, first_chunk_seen))

    try:
        await _wait_until_stream_slot_is_held(holder, first_chunk_seen)
        requests = [
            asyncio.create_task(contender_request(client, index))
            for index in range(1, CONTENDERS + 1)
        ]
        results = await asyncio.gather(*requests)
        print_summary(results)
        await holder
    finally:
        if not holder.done():
            holder.cancel()
            with suppress(asyncio.CancelledError):
                await holder
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
