# GigaLoom performance baseline

Run the bounded, hermetic CI smoke profile:

```bash
uv run giga benchmark performance --profile ci-smoke --samples 5 --output /tmp/gigaloom-performance.json
```

Use `--profile local-detail` for an explicitly opt-in local capture. Both
profiles use only temporary content-free fixtures: they do not read native
provider homes, send provider traffic, or retain prompts, responses, tokens,
or credentials.

The JSON report is schema-versioned. It records wall and CPU percentiles,
process RSS, observable block I/O, stage timings, conservative CI smoke
budgets, and the full workload contract for later TUI and durable-runtime
profiling. Metrics that are not portable or not yet observable are `null`
instead of inferred. Optimization targets remain unset until the owning
performance slice reviews a measured baseline.
