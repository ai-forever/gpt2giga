"""Protected built-in UI routes."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import HTMLResponse, RedirectResponse


router = APIRouter(prefix="/ui", include_in_schema=False)


_PLAYGROUND_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga playground</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #111827;
      --muted: #5f6b7a;
      --border: #d7dce3;
      --accent: #0f766e;
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
      width: min(960px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 48px 0;
    }

    section {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 28px;
      box-shadow: 0 12px 30px rgb(17 24 39 / 8%);
    }

    h1 {
      margin: 0 0 12px;
      font-size: 30px;
      line-height: 1.2;
      font-weight: 700;
      letter-spacing: 0;
    }

    p {
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.6;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-top: 24px;
      color: var(--accent);
      font-size: 14px;
      font-weight: 600;
    }

    .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
    }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>gpt2giga playground</h1>
      <p>
        The protected UI is mounted. The multi-protocol request builder,
        response panels, and helper endpoints are implemented in the next
        playground tasks.
      </p>
      <div class="status"><span class="dot"></span>UI serving baseline ready</div>
    </section>
  </main>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
async def ui_root():
    """Redirect the UI root to the playground shell."""
    return RedirectResponse(url="/ui/playground")


@router.get("/", response_class=HTMLResponse)
async def ui_root_slash():
    """Redirect the UI root with a trailing slash to the playground shell."""
    return RedirectResponse(url="/ui/playground")


@router.get("/playground", response_class=HTMLResponse)
async def playground():
    """Serve the built-in playground shell."""
    return HTMLResponse(_PLAYGROUND_HTML)
