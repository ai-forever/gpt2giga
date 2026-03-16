from mitmproxy import http


def responseheaders(flow: http.HTTPFlow) -> None:

    ct = flow.response.headers.get("content-type", "")
    if "text/event-stream" in ct.lower():
        flow.response.stream = True
        flow.response.headers["Cache-Control"] = "no-cache"
