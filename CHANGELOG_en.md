# Changelog

All notable changes to the gpt2giga project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2026-02-09

### Added
- **Anthropic Messages API**: New `POST /v1/messages` endpoint for Anthropic Messages API compatibility
  - Streaming support (SSE) in Anthropic format (`message_start`, `content_block_delta`, `message_stop`, etc.)
  - Anthropic message conversion (text, image, tool_use, tool_result) to GigaChat format
  - Anthropic tool conversion (`input_schema`) to GigaChat functions format
  - `tool_choice` support (auto, tool, none)
  - System prompt support (`system`) as string or content block array
  - `stop_reason` mapping (end_turn, tool_use, max_tokens)
- **Extended Thinking (Reasoning)**: Support for Anthropic `thinking` parameter
  - `thinking.budget_tokens` mapped to GigaChat `reasoning_effort` (high/medium/low)
  - GigaChat `reasoning_content` converted to Anthropic `thinking` content block
  - Reasoning support in streaming (`thinking_delta`)
- **Anthropic API Examples**: Added examples in `examples/anthropic/`:
  - `messages.py` — basic request
  - `messages_stream.py` — streaming
  - `system_prompt.py` — system prompt
  - `multi_turn.py` — multi-turn conversation
  - `function_calling.py` — function calling (tool use)
  - `image_url.py` — image from URL
  - `base64_image.py` — base64 image
  - `reasoning.py` — extended thinking

## [0.1.1] - 2026-02-06

### Added
- **GitHub Templates**: Added Pull Request and Issue (bug report) templates to improve contribution process (#58)
- **$ref Resolution in Schemas**: Added `_resolve_schema_refs` function for handling JSON Schema references (#57)
- **Missing Properties Handling**: Implemented proper handling of schemas without `properties` field

### Changed
- **request_mapper.py Refactoring**: Logic split into separate modules for better maintainability:
  - `content_utils.py` — utilities for content handling
  - `message_utils.py` — utilities for message handling
  - `schema_utils.py` — utilities for schema handling
- **Extended Test Coverage**: Added tests for streaming and tool conversion

### Fixed
- **Responses API Streaming**: Fixed streaming responses in Responses API (#60)
- **Function Calling in Streaming**: Fixed function call handling during streaming in Responses API

## [0.1.0b2] - 2025-01-21

### Added
- Python 3.14 support
- Updated tiktoken library

### Changed
- Test refactoring
- Updated library dependencies

### Fixed
- Creating new GigaChat instance when pass_token=True

## [0.1.0b] - 2025-12-26

### Added
- **Pydantic v2**: Full project migration to Pydantic v2.
- **Dependency Management**: Project and CI migration to `uv`.
- **Configuration**: Added `pydantic-settings` library for convenient settings management via CLI and environment variables.
- **Error Handling**: Implemented error mapping for proper exception handling.
- **Structured Output**: Added structured output support as a function.
- **GigaChat Integration**: Added integration with `gigachat` package.
- **Tests**: Significantly expanded test coverage.

### Changed
- **Protocol Refactoring**: `protocol.py` logic split into `request_mapper.py`, `response_mapper.py`, and `attachments.py` modules.
- **Logic Separation**: Completely separated `chat_completion` and `responses` logic.
- **Examples**: Updated ports in usage examples.

### Fixed
- **Streaming**: Fixed streaming response issues.
- **Responses API**: Fixed errors in Responses API.
- **CI/CD**: Fixed SSL error in GitHub Actions.
- **Security**: Fixed vulnerabilities in dependencies.

## [0.0.15.post1] - 2025-01-21

### Added
- API key authorization with support for various methods (query parameter, x-api-key header, Bearer token)
- Logging using loguru library
- System endpoints for monitoring (/health, /ping, /logs)
- HTML page for real-time log viewing
- File parsing support
- Workflow for GHCR publishing
- Workflow for PyPI publishing

### Changed
- Migration to FastAPI
- Switched to loguru for logging

### Fixed
- Fixed exception handling during byte decoding
- Fixed validation error for developer role
- Fixed Python versions in workflows

## [0.0.14] - 2024-12

### Added
- mTLS authentication support
- Docker Compose configuration

### Changed
- Updated README documentation

## [0.0.13] - 2024-11

### Added
- Basic proxy server functionality
- Streaming generation support
- Embeddings support
- Function calling support
- Structured output support

---

[0.1.2b1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.1...v0.1.2b1
[0.1.1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0...v0.1.1
[0.1.0b2]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0b...v0.1.0b2
[0.1.0b]: https://github.com/ai-forever/gpt2giga/compare/v0.0.15.post1...v0.1.0b
[0.0.15.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.0.14...v0.0.15.post1
[0.0.14]: https://github.com/ai-forever/gpt2giga/compare/v0.0.13...v0.0.14
[0.0.13]: https://github.com/ai-forever/gpt2giga/releases/tag/v0.0.13
