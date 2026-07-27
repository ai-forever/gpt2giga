# GigaLoom performance baseline

Run the bounded, hermetic CI smoke profile:

```bash
uv run giga benchmark performance --profile ci-smoke --samples 5 --output /tmp/gigaloom-performance.json
```

Use `--profile local-detail` for an explicitly opt-in local capture. All
profiles use only temporary content-free fixtures: they do not read native
provider homes, send provider traffic, or retain prompts, responses, tokens,
or credentials.

Profile the current Textual shell and publish the G5 repair ranking with:

```bash
uv run giga benchmark performance --profile tui-detail --samples 5 --output /tmp/gigaloom-tui-profile.json
```

The TUI detail profile measures cold import, startup and first input, full and
incremental timeline projection, unchanged run polling, bounded native-output
normalization, temporary filesystem/SQLite comparators, and retained timeline
memory. It also records the current polling/rendering contract, cProfile
timing evidence, ranked target gaps, and the reviewed G5 repair budgets. A
completed profile exits successfully even when an optimization target is not
yet met; `target_status` and `ranked_bottlenecks` carry that distinction.

The JSON report is schema-versioned. It records wall and CPU percentiles,
process RSS, observable block I/O, stage timings, conservative CI smoke
budgets, and the full workload contract for later TUI and durable-runtime
profiling. Metrics that are not portable or not yet observable are `null`
instead of inferred. Optimization targets remain unset until the owning
performance slice reviews a measured baseline.
