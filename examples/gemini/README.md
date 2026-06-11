# Gemini-like examples

These examples call the `gpt2giga` Gemini-compatible REST surface directly.

Default base URL:

```bash
http://localhost:8090/v1
```

Override it with:

```bash
export GEMINI_BASE_URL=http://localhost:8090/v2
```

If proxy API-key auth is enabled, set:

```bash
export GPT2GIGA_API_KEY=your-proxy-key
```

Gemini `:generateContent`, `:streamGenerateContent`, `:countTokens`,
`:embedContent`, and `:batchEmbedContents` routes are mounted at the root path,
`/v1`, `/v2`, and `/v1beta`, matching the rest of the public API wiring.
`/v1` forces the GigaChat v1 backend path and `/v2` forces the v2 backend path.

Gemini-shaped model discovery is available at `/v1beta/models`. On the shared
`/models`, `/v1/models`, and `/v2/models` paths the proxy returns Gemini model
shape when the request looks like a Google/Gemini client request, for example
when it includes `X-Goog-Api-Client`.

Run examples from the repo root:

```bash
uv run python examples/gemini/generate_content/basic.py
uv run python examples/gemini/generate_content/stream.py
uv run python examples/gemini/count_tokens/basic.py
uv run python examples/gemini/embeddings/basic.py
uv run python examples/gemini/models/basic.py
```

Prepared but not mounted by default:

```bash
uv run python examples/gemini/files/basic.py
uv run python examples/gemini/batches/basic.py
```
