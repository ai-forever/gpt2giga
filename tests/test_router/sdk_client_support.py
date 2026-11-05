"""Bridge SDK HTTPX clients to Starlette's in-process test client."""

import httpx
from fastapi.testclient import TestClient


def make_httpx_client(app) -> httpx.Client:
    """Keep HTTPX 0.x SDKs compatible with Starlette's optional HTTPX 2 transport."""

    def handle(request: httpx.Request) -> httpx.Response:
        with TestClient(app) as client:
            response = client.request(
                request.method,
                str(request.url),
                headers=request.headers.multi_items(),
                content=request.read(),
            )
        return httpx.Response(
            response.status_code,
            headers=response.headers.multi_items(),
            content=response.content,
        )

    return httpx.Client(
        base_url="http://testserver", transport=httpx.MockTransport(handle)
    )
