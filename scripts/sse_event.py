import json
from mitmproxy import http, ctx


class SSECapture:
    def responseheaders(self, flow: http.HTTPFlow) -> None:
        ct = flow.response.headers.get("content-type", "").lower()

        if "text/event-stream" in ct:
            flow.response.headers["Cache-Control"] = "no-cache"
            flow.metadata["sse_chunks"] = []
            flow.metadata["llm_tokens"] = []
            flow.metadata["sse_buf"] = ""

            def capture(chunk: bytes) -> bytes:
                # keep raw body for mitmweb later
                flow.metadata["sse_chunks"].append(chunk)

                # incremental parser buffer
                text = chunk.decode("utf-8", errors="ignore")
                flow.metadata["sse_buf"] += text

                buf = flow.metadata["sse_buf"]
                lines = buf.splitlines(keepends=True)

                # keep incomplete trailing line in buffer
                if lines and not (lines[-1].endswith("\n") or lines[-1].endswith("\r")):
                    flow.metadata["sse_buf"] = lines[-1]
                    lines = lines[:-1]
                else:
                    flow.metadata["sse_buf"] = ""

                for line in lines:
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue

                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        flow.metadata["llm_full_response"] = "".join(flow.metadata["llm_tokens"])
                        continue

                    try:
                        data = json.loads(payload)

                        # OpenAI-style streaming
                        delta = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        )
                        if delta:
                            flow.metadata["llm_tokens"].append(delta)
                            continue

                        # Some providers stream final-style chunks
                        msg = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content")
                        )
                        if msg:
                            flow.metadata["llm_tokens"].append(msg)
                    except Exception:
                        pass

                return chunk

            flow.response.stream = capture

    def response(self, flow: http.HTTPFlow) -> None:
        if "sse_chunks" in flow.metadata:
            try:
                flow.response.content = b"".join(flow.metadata["sse_chunks"])
            except Exception as e:
                ctx.log.warn(f"failed to rebuild SSE body: {e}")


addons = [SSECapture()]