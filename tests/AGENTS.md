# AGENTS.md — tests

## Scope

The root pytest configuration collects the entire `tests/` tree: gateway,
compatibility/golden, integration, smoke, live, scripts, and packaging
contracts. Do not infer coverage from an old directory inventory.

## Test design

- Add the smallest regression test that fails for the bug or missing behavior,
  then implement the fix.
- Test at the owning layer: pure transformations and policy as unit tests,
  mounted behavior through FastAPI clients, persistence through temporary
  stores, and packaging through built/installed artifacts.
- Mock GigaChat and other external services by default. Only `tests/live/` may
  call real upstream services, and those tests must remain explicit opt-in.
- Pytest asyncio auto mode is enabled. Do not add
  `@pytest.mark.asyncio` unless a test needs explicit plugin options.
- Use `create_app()` plus an explicit `ProxyConfig` for app-wide gateway
  behavior. Avoid ambient env and singleton state.
- Use `tmp_path`, isolated repositories, and temporary homes. Never read or
  mutate real credentials or provider state.
- Assert redaction whenever request bodies, tool arguments, credentials,
  environment values, stored events, previews, or provenance are involved.
- Change golden fixtures only for an intentional client-visible wire contract;
  review the human-readable diff.
- Keep package-boundary tests strict: gateway installs must not expose
  GigaLoom or `gpt2giga_harness` surfaces.
- Files/Batches modules exist without public aggregator mounts; tests must not
  assume that importing a router makes its API public.
- Admin, debug, replay, and metrics route tests must explicitly enable the
  corresponding settings instead of relying on ambient defaults.
- Markers are selective, not exhaustive. Do not use `pytest -m unit` as a
  substitute for the relevant path or full suite.

## Validation

During iteration, run the narrowest relevant pytest node with
`uv run pytest ... -q -n 0` when xdist worker startup would dominate the test.
Directory and full-suite runs inherit local `-n auto`; GitHub Actions overrides
it with the workflow's explicit `-n 4`.

Full pytest/coverage gate:

```bash
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```

Run the full gate after shared fixtures/config, app composition, public
protocol, package metadata, or artifact contracts change.
