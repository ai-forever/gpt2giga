---
id: prompt-caching
title: Prompt caching
---

# Prompt caching

GigaChat keeps a prefix key-value (KV) cache for a short window. When a later
request shares an unchanged prefix with an earlier one, GigaChat reuses the
cached state instead of reprocessing those tokens, and reports the reused count
as `precached_prompt_tokens`.

The gateway surfaces that number as OpenAI
`usage.prompt_tokens_details.cached_tokens` and Anthropic
`cache_read_input_tokens`, so any OpenAI/Anthropic client can observe cache
hits without changing its code.

## What was measured

The behaviour below was measured against the live GigaChat API with
`GigaChat-2-Max` and a stable system prompt of roughly 1200 tokens. Treat the
numbers as an order of magnitude, not a contract.

| Observation | Result |
|---|---|
| Cache lifetime (TTL) after the last hit | roughly 30 seconds |
| Reused tokens on a repeated long prefix | up to ~99% of prompt tokens |
| Cache-hit rate with a fixed `X-Session-ID` | 100% (15/15, two runs) |
| Cache-hit rate with a random `X-Session-ID` per call | 87% (13/15, two runs) |

Two conclusions follow:

- The cache is short-lived. It helps interactive workloads (agents, chat,
  multi-step tool loops, retries) where follow-up requests arrive within
  seconds, and does little for batch jobs that run minutes apart.
- A stable `X-Session-ID` improves the hit rate. It keeps requests on the same
  cache entry instead of relying on the upstream's own content routing.

## Enabling it

### 1. Client header pass-through

Any client can send `X-Session-ID`. The gateway forwards it upstream unchanged:

```bash
curl http://localhost:8090/v1/chat/completions \
  -H "Authorization: Bearer <proxy-api-key>" \
  -H "X-Session-ID: conversation-123" \
  -H "Content-Type: application/json" \
  -d '{"model": "GigaChat-2-Max", "messages": [{"role": "user", "content": "..."}]}'
```

Use one identifier per logical conversation and a different one for unrelated
dialogues. `GIGACHAT_SESSION_ID` sets a global default that the request header
overrides.

### 2. Derived session affinity

Many OpenAI/Anthropic/Gemini clients cannot send custom headers. When enabled,
the gateway derives a deterministic `X-Session-ID` from the request's own stable
prefix — a one-way hash of the prompt text, never the raw content:

```dotenv
GPT2GIGA_CACHE_SESSION_DERIVATION_ENABLED=True
GPT2GIGA_CACHE_SESSION_DERIVATION_SCOPE=prefix
GPT2GIGA_CACHE_SESSION_DERIVATION_MIN_PREFIX_TOKENS=1024
```

| Variable | Default | Purpose |
|---|---:|---|
| `GPT2GIGA_CACHE_SESSION_DERIVATION_ENABLED` | `False` | Derive an upstream `X-Session-ID` from the request's stable prefix. |
| `GPT2GIGA_CACHE_SESSION_DERIVATION_SCOPE` | `prefix` | `prefix` hashes the system prompt plus the leading user turn; `system` hashes only the system prompt. |
| `GPT2GIGA_CACHE_SESSION_DERIVATION_MIN_PREFIX_TOKENS` | `1024` | Minimum estimated prefix tokens before a derived session is applied. |

Derivation applies to OpenAI Chat Completions, OpenAI Responses, Anthropic
Messages, and Gemini GenerateContent. It is skipped when:

- the client already supplies `X-Session-ID`;
- `GIGACHAT_SESSION_ID` is configured (the operator's default wins);
- the request has no usable prefix;
- the prefix is shorter than `GPT2GIGA_CACHE_SESSION_DERIVATION_MIN_PREFIX_TOKENS`
  (short prompts gain little, so they are left untouched).

Derivation never changes the generated answer. It only influences which upstream
cache entry a request lands on.

## Where the cache helps

The ~30s lifetime fits request patterns that repeat within seconds:

- **Multi-step agents and tool loops.** Each step resends the growing history;
  the unchanged prefix is cached between steps.
- **Retries and fallbacks.** A retry seconds after a timeout reuses the prefix.
- **Parallel sub-tasks with a shared prompt.** Concurrent calls with the same
  system prompt hit the same entry.
- **Interactive chat.** A follow-up turn inside the same conversation reuses the
  earlier history.

It helps little for batch or scheduled workloads that run minutes apart, or for
requests whose prefix changes on every call.

## Verifying cache hits

Read `usage.prompt_tokens_details.cached_tokens` (OpenAI shape) or
`cache_read_input_tokens` (Anthropic shape) in the response. A non-zero value
means the upstream reused cached tokens for that request.
