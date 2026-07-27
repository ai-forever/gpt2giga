# GigaLoom performance baseline

Run the bounded, hermetic CI smoke profile:

```bash
uv run giga benchmark performance --profile ci-smoke --samples 5 --output /tmp/gigaloom-performance.json
```

The blocking profile contains only the environment-stable in-memory session
and transcript projection budgets. Filesystem, SQLite, worker, TUI, Web, RSS,
and process-startup measurements remain in `--profile local-detail`; they are
scheduled or explicitly opt-in evidence and cannot make provider or external
network latency look like a local-code regression. All profiles use only
temporary content-free fixtures: they do not read native provider homes, send
provider traffic, or retain prompts, responses, tokens, or credentials.

Every report records the tracked G6-03 baseline and a SHA-256 fingerprint of
its Python/platform/SQLite environment. The writer rejects reports above the
profile limit: 64 KiB for CI smoke, 512 KiB for local detail, and 2 MiB for TUI
or runtime detail. Pull-request CI retains the smoke artifact for 7 days.
Nightly and manual-dispatch runs capture the three detailed profiles and retain
their bounded artifacts for 14 days.

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
  --output docs/internal/evidence/GIGALOOM_G6_02_RUNTIME_PROFILE_2026-07-27.json
```

The runtime profile uses temporary content-free sessions and the local `echo`
harness. It records wall/CPU/process-peak-RSS, context-switch wakeups, bounded
SQLite statement counts, queue throughput/fairness, lock contention, worker
lifecycle/recovery, explicit loopback wake delivery, and API/SSE/TUI/Web
attribution. Schema v3 also measures one bounded session-run update against a
retained run log. It accepts a maximum 65 projected steady empty cycles per
minute and 250 ms p95 explicit wake latency. The report keeps higher
concurrency, stop-on-idle ownership, and broader API/database/event repairs
unselected after the bounded G6-02 duplicate filesystem-scan repair; it does
not access provider, external-network, or native-home state.

The JSON report is schema-versioned. Detailed profiles record wall and CPU
percentiles, process RSS, observable block I/O, stage timings, and the full
workload contract. Metrics that are not portable or not yet observable are
`null` instead of inferred. Optimization targets remain unset until the owning
performance slice reviews a measured baseline.
