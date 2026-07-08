# Unified Harness

Unified Harness is a local control surface on top of `gpt2giga`. It lets you
choose a harness, choose a GigaChat model, choose the explicit GigaChat Chat
Completions backend mode (`/v1` or `/v2`), and run quick smoke tests from either
the CLI or a small browser UI.

It does not replace the existing `gpt2giga` proxy entry point. You can still
start the proxy yourself as before, then use `giga` or `gpt2giga-harness` as the
local harness client. For local `127.0.0.1` proxy URLs, the direct-chat harness
can also start a temporary `gpt2giga` sidecar when the proxy is down and real
GigaChat credentials are already present in the environment.

## Quickstart

Start the proxy:

```bash
uv run gpt2giga
```

In another terminal, inspect the harness environment:

```bash
giga doctor
giga harness list
```

If the proxy is not running, `giga chat`, `giga harness run direct-chat`, and
real external agent CLI runs try to start a local sidecar by default. Disable
that for a single command with:

```bash
giga chat --no-start-proxy --api-mode v2 --model GigaChat-2-Max "Привет"
```

Run direct Chat Completions smoke tests through explicit backend routes:

```bash
giga chat --api-mode v2 --model GigaChat-2-Max "Привет"
giga chat --api-mode v1 --model GigaChat-2-Max "Привет"
```

The same flow through the generic harness command:

```bash
giga harness run direct-chat \
  --api-mode v2 \
  --model GigaChat-2-Max \
  --prompt "Hello from the harness"
```

Open the local UI:

```bash
giga ui
```

By default the UI binds to `127.0.0.1:8091`. To bind remotely you must opt in:

```bash
giga ui --host 0.0.0.0 --allow-remote
```

Remote binding can expose local harness execution. Use it only behind a trusted
network boundary.

## Configuration

CLI flags override environment variables. Useful variables:

```bash
GPT2GIGA_HARNESS_PROXY_URL=http://127.0.0.1:8090
GPT2GIGA_HARNESS_API_KEY=<local-proxy-api-key>
GPT2GIGA_HARNESS_DEFAULT_MODEL=GigaChat-2-Max
GPT2GIGA_HARNESS_DEFAULT_API_MODE=v2
GPT2GIGA_HARNESS_UI_HOST=127.0.0.1
GPT2GIGA_HARNESS_UI_PORT=8091
GPT2GIGA_HARNESS_AUTO_START_PROXY=True
GPT2GIGA_HARNESS_PROXY_START_TIMEOUT_SECONDS=15
```

If `GPT2GIGA_HARNESS_API_KEY` is not set, the harness falls back to
`GPT2GIGA_API_KEY` for calls to the local proxy. It never passes
`GIGACHAT_CREDENTIALS`, OAuth tokens, certificates, or `.env` contents to
external agent CLIs.

Auto-start is local-only. It supports `http://127.0.0.1:<port>`,
`http://localhost:<port>`, and `http://[::1]:<port>`. It refuses remote hosts,
does not create fake upstream credentials, and starts the child proxy with a
generated local `GPT2GIGA_API_KEY` if one is not already configured.

External agent harnesses run the same proxy preflight before launching Codex,
Claude Code, or Gemini CLI. If a sidecar is started, the generated local proxy
key is passed only through the agent-specific local API-key environment variable
and remains redacted from JSON/UI results.

## Built-in Harnesses

| Harness | Status | Purpose |
|---|---|---|
| `direct-chat` | MVP | Sends OpenAI-style Chat Completions to `/v1/chat/completions` or `/v2/chat/completions`. |
| `echo` | MVP | Local no-network smoke harness for tests and UI checks. |
| `codex-cli` | MVP | Builds and runs a sanitized `codex exec` command against the local proxy. |
| `claude-code` | MVP | Builds and runs sanitized Claude Code print-mode commands against the local proxy. |
| `gemini-cli` | MVP | Builds and runs sanitized Gemini CLI headless commands against the local proxy. |

Inspect one harness:

```bash
giga harness inspect direct-chat
```

Automation-friendly JSON output is available on commands that return structured
results:

```bash
giga harness list --json
giga harness run echo --prompt "hello" --json
```

## Codex CLI Harness

The Codex harness is intentionally conservative. `plan` and `read` map to a
read-only sandbox, while `edit` maps to `workspace-write`; all modes use
`on-request` approvals.

```bash
giga harness run codex-cli \
  --mode plan \
  --model GigaChat-2-Max \
  --api-mode v2 \
  --workspace . \
  --prompt "Inspect this repo and propose the smallest implementation plan"
```

Backward-friendly alias:

```bash
giga run --agent codex --mode plan --workspace . "Inspect this repo"
```

Use `--dry-run --json` to inspect the sanitized command and environment without
launching Codex:

```bash
giga harness run codex-cli --prompt "Inspect" --dry-run --json
```

## Claude Code Harness

The Claude Code harness uses print mode and points Claude at the selected
explicit `gpt2giga` API mode through `ANTHROPIC_BASE_URL`:

```bash
giga harness run claude-code \
  --mode plan \
  --model GigaChat-2-Max \
  --api-mode v2 \
  --workspace . \
  --prompt "Inspect this repo"
```

`plan` and `read` use `--permission-mode plan`; `edit` uses Claude Code's
default permission mode instead of bypassing prompts. The harness also uses
`--bare`, `--safe-mode`, `--no-session-persistence`, and a sanitized environment
that only includes the local proxy API key as `ANTHROPIC_API_KEY`.

Backward-friendly alias:

```bash
giga run --agent claude --mode plan --workspace . "Inspect this repo"
```

## Gemini CLI Harness

The Gemini CLI harness uses headless prompt mode and points Gemini at the
selected explicit `gpt2giga` API mode through `GOOGLE_GEMINI_BASE_URL`:

```bash
giga harness run gemini-cli \
  --mode plan \
  --model GigaChat-2-Max \
  --api-mode v2 \
  --workspace . \
  --prompt "Inspect this repo"
```

`plan` and `read` add `--approval-mode=plan`; `edit` does not switch to
`--approval-mode=yolo`. Real runs use a temporary `HOME` with
`.gemini/settings.json` pinned to `gemini-api-key` auth, avoiding cached Google
auth when the local proxy API key should be used.

Backward-friendly alias:

```bash
giga run --agent gemini --mode plan --workspace . "Inspect this repo"
```

## Browser UI

`giga ui` serves the local Harness Control Panel as one no-build HTML page. It
binds to `127.0.0.1:8091` by default. Remote binding is rejected unless you pass
`--allow-remote`.

The UI is populated from `HarnessRegistry`, so built-in and entry-point
harnesses appear in the browser without frontend code changes. It shows each
harness' availability status, kind, capabilities, tags, and missing/error
details when discovery fails.

The run configuration panel includes:

- harness selection;
- model input with proxy-backed model suggestions when available;
- explicit API mode selection: `v1` maps to `/v1/chat/completions`, and `v2`
  maps to `/v2/chat/completions`;
- capability and mode selection;
- optional workspace path for harnesses that declare workspace support;
- dry-run and stream toggles where the selected harness supports them;
- prompt input;
- output, events, raw request, raw response, command, and passive diff panels;
- copy buttons for the equivalent CLI command and direct-chat curl command.

Echo runs entirely locally and does not require credentials. Direct-chat sends
requests through the configured local proxy or auto-started local sidecar and
therefore needs real GigaChat credentials for live upstream responses. External
agent CLI harnesses such as Codex, Claude Code, and Gemini can be previewed with
dry-run even when their executable is missing.

The UI stores only non-secret preferences such as selected harness, API mode,
mode, and model name. It does not store prompt text, workspace paths, API keys,
or GigaChat credentials. Curl previews always use
`Authorization: Bearer <GPT2GIGA_API_KEY>` as a placeholder and never expose the
real local proxy key.

The stream checkbox passes `stream=true` to the harness request when the harness
declares streaming support. The browser page still renders the final result
after the backend call completes; it does not implement SSE or WebSocket event
streaming yet.

## Model Selection Notes

The direct harness always sends the requested `model` field to the proxy. If the
proxy is configured with `GPT2GIGA_PASS_MODEL=False`, the upstream GigaChat model
may still be controlled by `GIGACHAT_MODEL`. `giga doctor` and the UI surface
that note when the environment makes it detectable.

Model discovery tries these endpoints in the selected mode first:

```text
GET /v2/models
GET /v1/models
GET /models
```

If discovery fails, the UI still accepts manual model input.

## Add a New Harness

1. Create `gpt2giga/harness/harnesses/my_harness.py`.
2. Subclass `BaseHarness`.
3. Implement `spec()`, `availability()`, and `run()`.
4. Register the class in `BUILTIN_HARNESSES` or expose a package entry point:

   ```toml
   [project.entry-points."gpt2giga.harnesses"]
   my-harness = "my_package.my_harness:MyHarness"
   ```

5. Add tests that do not require live GigaChat credentials.
6. Run:

   ```bash
   giga harness list
   giga ui
   ```

For a starting template:

```bash
giga harness scaffold my-harness
```

## Troubleshooting

Start with:

```bash
giga doctor
```

Common checks:

- proxy is reachable at `GPT2GIGA_HARNESS_PROXY_URL` or
  `http://127.0.0.1:8090`;
- if relying on auto-start, `giga doctor` reports `Proxy / Auto-start: ready`;
- `GPT2GIGA_API_KEY` or `GPT2GIGA_HARNESS_API_KEY` matches the proxy when API-key
  auth is enabled;
- `GIGACHAT_CREDENTIALS` is present for real upstream calls;
- the selected mode uses the intended explicit route: `/v1/chat/completions` or
  `/v2/chat/completions`;
- external CLI harnesses report `missing` until the matching executable is on
  `PATH`; startup errors from broken CLI installations are reported by the run
  result;
- real external CLI harness runs perform proxy preflight before launching the
  CLI, so proxy auto-start errors are reported directly instead of being buried
  in agent stdout/stderr.

## Current Limitations

The first MVP runs direct Chat Completions plus Codex, Claude Code, and Gemini
CLI command paths. External agent behavior still depends on each installed CLI's
current support for custom local API endpoints and non-interactive modes; use
`--dry-run --json` first when validating a new workstation.
