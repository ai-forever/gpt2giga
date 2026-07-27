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
timing evidence, ranked target gaps, and the reviewed G5 repair budgets.
Schema v3 names the cold-start, warm-start, and long-session closure workloads;
its `status` is `passed` only when every accepted G5 repair metric is within
budget. The command still exits successfully when it writes a complete report;
`status`, `target_status`, and `ranked_bottlenecks` carry the closure decision.

Measure the G6 durable worker and request path locally:

```bash
uv run giga benchmark performance --profile runtime-detail --samples 20 \
  --output docs/internal/evidence/GIGALOOM_G6_01_RUNTIME_PROFILE_2026-07-27.json
```

The runtime profile uses temporary content-free sessions and the local `echo`
harness. It records wall/CPU/process-peak-RSS, context-switch wakeups, bounded
SQLite statement counts, queue throughput/fairness, lock contention, worker
lifecycle/recovery, explicit loopback wake delivery, and API/SSE/TUI/Web
attribution. Schema v2 accepts a maximum 65 projected steady empty cycles per
minute and 250 ms p95 explicit wake latency. The report keeps higher
concurrency, stop-on-idle ownership, and request/database repairs unselected;
it does not access provider, external-network, or native-home state.

The JSON report is schema-versioned. It records wall and CPU percentiles,
process RSS, observable block I/O, stage timings, conservative CI smoke
budgets, and the full workload contract for later TUI and durable-runtime
profiling. Metrics that are not portable or not yet observable are `null`
instead of inferred. Optimization targets remain unset until the owning
performance slice reviews a measured baseline.
