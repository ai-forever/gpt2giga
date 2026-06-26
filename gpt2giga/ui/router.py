"""Protected built-in UI routes."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import HTMLResponse, RedirectResponse, Response

router = APIRouter(prefix="/ui", include_in_schema=False)

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        "base-uri 'none'; "
        "connect-src 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'; "
        "img-src 'self' data:; "
        "script-src 'none'; "
        "style-src 'unsafe-inline'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_PLAYGROUND_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga playground</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --surface: #ffffff;
      --surface-soft: #f3f6f8;
      --text: #101828;
      --muted: #5f6c7b;
      --border: #d7dde5;
      --teal: #0f766e;
      --blue: #1d4ed8;
      --amber: #b45309;
      --ink: #111827;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }

    main {
      width: min(1120px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 40px;
    }

    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }

    h1,
    h2,
    p {
      margin: 0;
    }

    h1 {
      font-size: 28px;
      line-height: 1.2;
      font-weight: 800;
      letter-spacing: 0;
    }

    h2 {
      font-size: 15px;
      line-height: 1.3;
      font-weight: 780;
    }

    .brand {
      display: grid;
      gap: 4px;
    }

    .brand-mark {
      color: var(--teal);
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      padding: 0 12px;
      color: var(--teal);
      border: 1px solid rgb(15 118 110 / 28%);
      border-radius: 999px;
      background: rgb(15 118 110 / 8%);
      font-size: 13px;
      font-weight: 760;
      white-space: nowrap;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--teal);
    }

    .workspace {
      display: grid;
      grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }

    .panel {
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 14px 34px rgb(17 24 39 / 7%);
    }

    .nav,
    .stage {
      padding: 18px;
    }

    .nav {
      display: grid;
      gap: 10px;
    }

    .nav-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 44px;
      padding: 0 12px;
      color: var(--ink);
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface);
      font-size: 14px;
      font-weight: 760;
      text-decoration: none;
    }

    .nav-item[aria-current="page"] {
      color: var(--blue);
      border-color: rgb(29 78 216 / 35%);
      background: rgb(29 78 216 / 7%);
    }

    .badge {
      min-height: 24px;
      padding: 0 8px;
      color: var(--amber);
      border: 1px solid rgb(180 83 9 / 30%);
      border-radius: 999px;
      background: rgb(180 83 9 / 8%);
      font-size: 12px;
      line-height: 22px;
      font-weight: 780;
      white-space: nowrap;
    }

    .stage {
      display: grid;
      gap: 16px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .metric {
      display: grid;
      gap: 6px;
      min-height: 92px;
      padding: 14px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface-soft);
    }

    .metric-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
      line-height: 1.25;
    }

    .metric-value {
      color: var(--ink);
      font-size: 15px;
      line-height: 1.35;
      font-weight: 800;
      overflow-wrap: anywhere;
    }

    .terminal {
      min-height: 218px;
      margin: 0;
      overflow: auto;
      padding: 14px;
      color: #e5e7eb;
      border-radius: 8px;
      background: #111827;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }

    @media (max-width: 820px) {
      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .workspace,
      .grid {
        grid-template-columns: 1fr;
      }

      .status {
        white-space: normal;
      }
    }

    @media (max-width: 560px) {
      main {
        width: min(100vw - 20px, 1120px);
        padding: 18px 0 28px;
      }

      .nav,
      .stage {
        padding: 14px;
      }

      h1 {
        font-size: 24px;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div class="brand">
        <div class="brand-mark">gpt2giga</div>
        <h1>Playground</h1>
      </div>
      <div class="status">
        <span class="dot"></span>
        <span>Local admin UI</span>
      </div>
    </header>

    <div class="workspace">
      <nav class="panel nav" aria-label="UI navigation">
        <a class="nav-item" aria-current="page" href="/ui/playground">
          <span>Playground</span>
          <span class="badge">baseline</span>
        </a>
        <a class="nav-item" href="/_admin/compat/analyze">
          <span>Compatibility</span>
          <span class="badge">API</span>
        </a>
      </nav>

      <section class="panel stage" aria-label="Playground shell">
        <div class="grid">
          <div class="metric">
            <div class="metric-label">Route</div>
            <div class="metric-value">/ui/playground</div>
          </div>
          <div class="metric">
            <div class="metric-label">Auth</div>
            <div class="metric-value">Admin key</div>
          </div>
          <div class="metric">
            <div class="metric-label">Network</div>
            <div class="metric-value">No upstream calls</div>
          </div>
        </div>
        <pre class="terminal">POST /_admin/compat/analyze
GET  /models
POST /chat/completions
POST /v1/messages
POST /v1beta/models/{model}:generateContent</pre>
      </section>
    </div>
  </main>
</body>
</html>"""


def _html_response(content: str) -> HTMLResponse:
    return HTMLResponse(content, headers=_SECURITY_HEADERS)


def _redirect_response(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, headers=_SECURITY_HEADERS)


@router.get("", response_class=HTMLResponse)
async def ui_root() -> Response:
    """Redirect the UI root to the playground shell."""
    return _redirect_response("/ui/playground")


@router.get("/", response_class=HTMLResponse)
async def ui_root_slash() -> Response:
    """Redirect the UI root with a trailing slash to the playground shell."""
    return _redirect_response("/ui/playground")


@router.get("/playground", response_class=HTMLResponse)
async def playground() -> HTMLResponse:
    """Serve the built-in playground shell."""
    return _html_response(_PLAYGROUND_HTML)
