# Live GigaChat integration tests

`tests/live/` contains opt-in pytest tests that bring up a real gateway stack
and call the actual upstream GigaChat through the SDK. A regular `pytest tests/`
run stays hermetic: these tests are skipped until you explicitly enable them.

The live suite covers:

- OpenAI-compatible model list/retrieve, Chat Completions, streaming Chat
  Completions, Responses, and Embeddings;
- Anthropic-compatible Messages, streaming Messages, and count_tokens;
- Gemini-compatible model list/retrieve, GenerateContent, streamGenerateContent,
  countTokens, and embedContent;
- LiteLLM-compatible model/info;
- client header profiles in the style of Codex CLI, Claude Code, and Gemini CLI.

## Setting up secrets

Create a local, git-ignored `.env.live` file:

```dotenv
GPT2GIGA_RUN_LIVE_TESTS=1

# Preferred option for username/password authorization.
GIGACHAT_USER=<your-gigachat-username>
GIGACHAT_PASSWORD=<your-gigachat-password>
GIGACHAT_BASE_URL=<your-gigachat-base-url>

GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True

# Optional test override settings.
GPT2GIGA_LIVE_MODEL=GigaChat-2-Max
GPT2GIGA_LIVE_EMBEDDINGS_MODEL=EmbeddingsGigaR
GPT2GIGA_LIVE_BACKEND_MODES=v1,v2
```

Alternative authorization options are also supported:

```dotenv
GIGACHAT_CREDENTIALS=<your-oauth-credentials>
# or
GIGACHAT_ACCESS_TOKEN=<your-access-token>
```

By default the tests load `.env.live`. To use a different file:

```sh
GPT2GIGA_LIVE_ENV_FILE=/path/to/live.env uv run pytest tests/live -m live_gigachat
```

## Running

```sh
uv run pytest tests/live -m live_gigachat
```

By default the live suite checks both backend contracts through the versioned
gateway prefixes for OpenAI, Anthropic, and Gemini:

```dotenv
GPT2GIGA_LIVE_BACKEND_MODES=v1,v2
```

For a shorter smoke run, you can keep a single contract:

```dotenv
GPT2GIGA_LIVE_BACKEND_MODES=v1
```

Do not commit live credentials. Use `.env.live`, shell environment variables, or
your CI system's secret store.
