# Harness first-run demo

This disposable repository exercises the public Harness first-run path without
credentials, a proxy, an external agent CLI, or public-network access. The data
is fictional and the runtime state stays inside the copied demo directory.

From the `gpt2giga` repository root, with its virtual environment activated:

```bash
DEMO_PARENT="$(mktemp -d)"
cp -R examples/harness/first-run-demo "$DEMO_PARENT/inventory-demo"
cd "$DEMO_PARENT/inventory-demo"
git init -b main
export GPT2GIGA_HARNESS_DATA_DIR="$PWD/.local/harness"

giga init --name harness-first-run-demo
giga doctor .
giga harness run echo \
  --no-start-proxy \
  --workspace . \
  --mode read \
  --prompt "Summarize the fictional inventory task" \
  --json
giga eval run smoke \
  --no-start-proxy \
  --workspace . \
  --harness echo \
  --json
```

The Echo run should return `"ok": true`. The generated smoke eval should
report `"status": "passed"`, with two passing cases and no failed cases.
`giga doctor .` may report degraded optional proxy or external-CLI capabilities;
each such check includes its remediation, while the local Echo path remains
available.

What the setup changes:

- `giga init` writes non-secret starter definitions under `.giga/`;
- Harness run/eval records stay under `.local/harness/` because the demo sets
  `GPT2GIGA_HARNESS_DATA_DIR` explicitly;
- both directories are ignored in this disposable repository;
- `inventory.csv` and `TASK.md` are fake, safe inputs for later read-only agent
  experiments.

No command in this tour mutates the source checkout or contacts an upstream
model. Remove the temporary parent directory when you finish inspecting it.
