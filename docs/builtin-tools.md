# Built-in tools

This document records the mapping of provider built-in tools to the `tools` of
GigaChat Chat Completions v2. The source of truth for GigaChat here is the
installed `gigachat` SDK, not the website or external documentation.

## Source of truth

In `pyproject.toml` the package is pinned to the range `gigachat>=0.2.2a1,<0.3.0`.
For this range, the canonical list of built-in tools comes from the SDK models:

- `gigachat.models.chat_completions.ChatTool`;
- the SDK shorthand normalizer `_normalize_tool`;
- the local helper object `gpt2giga.common.tools.GIGACHAT_BUILTIN_TOOL_TYPES`.

The SDK accepts exactly these built-in tool fields:

| GigaChat tool | SDK field | Configuration shape |
|---|---|---|
| Web search | `web_search` | `ChatWebSearchTool`: `type`, `indexes`, `flags` plus SDK-compatible extra fields |
| URL content extraction | `url_content_extraction` | `dict[str, Any]` |
| Code interpreter | `code_interpreter` | `dict[str, Any]` |
| Image generation | `image_generate` | `dict[str, Any]` |
| 3D model generation | `model_3d_generate` | `dict[str, Any]` |

`functions` in `ChatTool` is a wrapper for user function tools.
It is not a GigaChat built-in tool: it is mapped separately from
OpenAI/Anthropic/Gemini function declarations.

## Where tools are executed

Built-in tools are sent upstream only through the GigaChat Chat Completions v2
contract. On public routes this means:

- `/v2/...` always uses the v2 backend contract;
- root routes use v2 only with `GPT2GIGA_GIGACHAT_API_MODE=v2`;
- `/v1/...` uses the legacy GigaChat chat contract, where built-in tools are not
  passed as executable tools.

If the same built-in tool is passed several times in one request through
different aliases, the first canonical field reaches the GigaChat payload.
A forced `tool_choice` for supported built-in tools turns into a
GigaChat `ChatToolConfig(mode="tool", tool_name="<canonical tool>")`.

## OpenAI mapping

OpenAI Chat Completions and Responses tools are normalized by `type`.

| OpenAI tool type | GigaChat tool | Notes |
|---|---|---|
| `web_search` | `web_search` | Direct canonical mapping |
| `web_search_*` | `web_search` | Covers dated OpenAI types, for example `web_search_2025_08_26` |
| `web_search_preview` | `web_search` | Preview alias |
| `web_search_preview_*` | `web_search` | Dated preview aliases |
| `code_interpreter` | `code_interpreter` | Direct canonical mapping |
| `image_generation` | `image_generate` | Alias for OpenAI Responses image generation |
| `image_generate` | `image_generate` | Canonical GigaChat passthrough without renaming |
| `url_content_extraction` | `url_content_extraction` | Canonical GigaChat passthrough without renaming |
| `model_3d_generate` | `model_3d_generate` | Native GigaChat passthrough without renaming |
| `function` | `functions` wrapper | A user function, not a built-in tool |
| `namespace` | `functions` wrapper | Responses namespace tools are flattened into GigaChat function names |

The configuration is read from the canonical field, the alias field, and
non-structured top-level keys. For example:

```json
{
  "type": "web_search_preview",
  "indexes": ["web"],
  "flags": ["trusted"]
}
```

turns into:

```json
{"web_search": {"indexes": ["web"], "flags": ["trusted"]}}
```

## Anthropic mapping

Anthropic Messages tools use versioned provider tool names.
The proxy strips provider/version suffixes where the meaning maps cleanly to a
GigaChat SDK built-in tool.

| Anthropic tool type | GigaChat tool | Notes |
|---|---|---|
| `web_search` | `web_search` | Direct provider alias |
| `web_search_*` | `web_search` | Covers dated SDK names, for example `web_search_20250305` |
| `web_fetch` | `url_content_extraction` | URL fetch maps to URL content extraction |
| `web_fetch_*` | `url_content_extraction` | Covers dated SDK names, for example `web_fetch_20250910` |
| `code_execution` | `code_interpreter` | Code execution maps to the interpreter |
| `code_execution_*` | `code_interpreter` | Covers dated SDK names, for example `code_execution_20250825` |
| Custom tools with `input_schema` | `functions` wrapper | A user function, not a built-in tool |

## Gemini mapping

Gemini `tools` entries do not contain a `type` field. The adapter maps known
tool-object keys to GigaChat built-in tools, and keeps unsupported keys in
`raw_extensions["unsupportedTools"]` for diagnostics.

| Gemini tool key | GigaChat tool | Notes |
|---|---|---|
| `googleSearch` / `google_search` | `web_search` | Google search maps to web search |
| `googleSearchRetrieval` / `google_search_retrieval` | `web_search` | The legacy/retrieval search form is best-effort mapped to web search |
| `urlContext` / `url_context` | `url_content_extraction` | URL context maps to URL content extraction |
| `codeExecution` / `code_execution` | `code_interpreter` | Code execution maps to the interpreter |
| `functionDeclarations` / `function_declarations` | `functions` wrapper | User functions, not built-in tools |

For Gemini requests, only the configuration object from a supported Gemini tool
key is passed into the canonical GigaChat field:

```json
{"googleSearch": {"indexes": ["web"]}}
```

turns into:

```json
{"type": "web_search", "web_search": {"indexes": ["web"]}}
```

`toolConfig.functionCallingConfig` applies only to Gemini function declarations.
It does not force, filter, or remove provider built-in tools.

## Not mapped

Provider built-in tools remain unsupported if the GigaChat SDK does not provide a
semantically equivalent `ChatTool` field.

| Provider | Examples without a mapping | Behavior |
|---|---|---|
| OpenAI | `file_search`, `computer`, `computer_use_preview`, `mcp`, `tool_search`, `shell`, `local_shell`, `apply_patch`, freeform `custom` | Ignored or kept only in compatibility diagnostics depending on the route |
| Anthropic | `tool_search*`, `memory*`, `bash*`, `text_editor*`, `advisor`, MCP tools, computer-use tools | Accepted where allowed by the compatibility policy, but not sent to GigaChat as executable built-in tools |
| Gemini | `fileSearch`, `googleMaps`, `computerUse`, `mcpServers`, `enterpriseWebSearch`, `parallelAiSearch`, Vertex/RAG/retrieval tools | Kept in the `unsupportedTools` diagnostics and not applied by GigaChat |

This approach is intentionally conservative: similar names are not enough for a
mapping. A mapping appears only when the GigaChat SDK has an executable field
with the same operational meaning.

## Update checklist

When a provider SDK adds or renames built-in tools:

1. Check the installed provider SDKs and the GigaChat SDK models.
2. Update `gpt2giga.common.tools.normalize_gigachat_builtin_tool_type`.
3. For Gemini object-key tools, update `gpt2giga.protocols.gemini.adapter`.
4. Add request-builder and adapter tests.
5. Update this document, as well as `api-compatibility.md` and
   `client-parameter-compatibility.md`, if the public behavior changes.
