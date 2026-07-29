# AGENTS.md — examples

## Scope and rules

- Examples demonstrate the public proxy through real OpenAI, Anthropic, Gemini,
  or Agents SDK clients. Do not import internal `gpt2giga` implementation
  modules.
- Keep each example small, self-contained, copyable, and visibly useful when it
  runs. Put reusable application logic and tests in their owning package.
- Use placeholder credentials such as `api_key="0"`; never add real tokens,
  certificates, or machine-specific paths.
- Keep base URLs and version prefixes consistent with the route contract being
  demonstrated. Do not silently switch an example between env-selected, v1,
  v2, and Gemini-style endpoints.
- Clearly label examples for API families whose router code exists but is not
  mounted publicly. Do not present prepared Files/Batches examples as working
  E2E support.
- Update the relevant example index or family README when adding, moving, or
  changing an example.

## Validation

`openai-agents` examples require the integrations dependency group:

```bash
uv sync --group integrations
```

```bash
uv run ruff check examples
uv run ruff format --check examples
```

Run a changed example only against an explicitly configured local proxy. Treat
`scripts/run_examples_smoke.py` as an external E2E check: it requires a live
proxy/upstream and is not part of the default offline quality gate.
