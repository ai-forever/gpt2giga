# Changelog

All notable changes to the gpt2giga project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.4a2] - 2026-07-17

### Added
- **LAR-1 semantic routing**: optional classifier for metadata.lar1 on POST /v1/chat/completions. The proxy automatically selects a GigaChat tier (gigachat-fast, gigachat-pro, local) based on confidence, evidence, and time signals from the agent. Disabled by default via LAR1_ENABLED=false. Includes lar1_router.py, lar1.py model, integration into openai/chat_completions.py, and lifecycle.

## [0.2.4a1] - 2026-07-16

### Fixed
- **OpenAI Responses history**: `output_text` parts from earlier turns are now transformed alongside `input_text`, so Codex app-server continuity retains conversation and subagent context.
- **Request-context CPU usage**: replaced expensive PBKDF2 for IP and API-key correlation fingerprints with fast keyed HMAC-SHA256 so middleware no longer blocks the event loop with two 100,000-iteration computations per request.
- **Hidden DEBUG payload serialization**: payload preparation and redaction are now skipped entirely at the default `INFO` level, including response and streaming paths.
- **`PASS_TOKEN` resources**: credential-specific GigaChat clients are reused through a bounded LRU pool, remain leased through stream completion, and close on eviction or shutdown.
- **Non-blocking sinks**: JSONL traffic logs are batched through a background queue, while observability export is moved out of the request path into a bounded queue with configurable backpressure.
- **Middleware overhead**: request-id, validation, path normalization, and pass-token middleware now use pure ASGI; three nested response iterators are replaced with one ASGI `send` interceptor.

## [0.2.3a2] - 2026-07-14

### Fixed
- **Claude Code model pinning**: trusted Claude CLI requests from Harness now preserve the selected upstream GigaChat model for Anthropic Messages and `count_tokens` in GigaChat v1/v2 modes and concurrency accounting without changing the model in the public Anthropic response.
