# AGENTS.md — integrations

## Scope and rules

- Keep this directory documentation- and config-sample-only. Runtime code and
  runnable demonstrations belong in packages or `examples/`.
- Use safe placeholders in every `.env.example` and config sample. Never copy
  values from a real `.env`.
- Verify auth, API mode, base URL, path normalization, and supported API claims
  against `src/gpt2giga/app/factory.py`, the relevant
  `api/*/routes.py` aggregator, and `.env.example`.
- Keep tool-specific commands aligned with the tool's current configuration
  format. Preserve useful user-owned settings in migration instructions.
- Keep nginx samples aligned with `deploy/nginx.yaml`, forwarded headers, TLS
  assumptions, and the gateway's path-prefix behavior.
- Mark unmounted or unsupported APIs explicitly; file presence in
  `routers/` is not evidence of public support.
- When an integration is added or renamed, update the repository integration
  index and any Docusaurus links that expose it.

## Validation

Check every edited command and path against the repository. If docs-site content
or links change, run `npm --prefix docs-site run build`. Do not launch or
authenticate an external integration merely to validate documentation unless
the user explicitly requests it.
