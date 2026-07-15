# Cross-harness review team

This disposable repository packages the third Harness north-star workflow.
Codex explores the bounded task, Claude reviews security, Gemini reviews tests,
and Codex reviews maintainability. Four durable read-only child jobs fan out
with bounded concurrency, then one Codex synthesis step receives their retained
typed artifacts.

The workflow never edits the project. Every profile uses `mode: read` and
`workspace_policy: current`; implementation remains a separate guarded
workflow. Synthesis uses `condition: always`, so a failed child remains visible
as a failed step with a retained run artifact and does not silently erase the
other review evidence.

## 1. Prepare a disposable copy

From the `gpt2giga` repository root, with its virtual environment activated:

```bash
EXAMPLE_PARENT="$(mktemp -d)"
cp -R examples/harness/cross-harness-review-team \
  "$EXAMPLE_PARENT/review-team"
cd "$EXAMPLE_PARENT/review-team"
git init -b main
git config user.email "harness-example@example.invalid"
git config user.name "Harness Example"
git add .
git commit -m "test: seed cross-harness review example"
export GPT2GIGA_HARNESS_DATA_DIR="$PWD/.local/harness"
```

Model-backed execution requires configured Codex, Claude, and Gemini CLIs plus
a running `gpt2giga` gateway. The packaged task is fictional and contains no
credentials or captured traffic.

## 2. Review the packaged contract

```bash
giga doctor .
giga agent list --workspace .
giga workflow validate \
  .giga/workflows/cross-harness-review-team.yaml
giga workflow run cross-harness-review-team \
  --workspace . \
  --dry-run \
  --json
giga eval list --workspace . --json
```

The dry-run must show four first-level steps and one final synthesis step. The
profiles pin the role-to-harness mapping and expose no edit-mode profile.

## 3. Run the durable review team

Keep the worker running under your normal supervisor or in a terminal:

```bash
giga worker start
```

In another terminal:

```bash
giga workflow run cross-harness-review-team \
  --workspace . \
  --prompt "Review the fictional artifact-download task in REVIEW_TASK.md." \
  --json
```

Inspect the workflow run in the CLI or cockpit. Each child step owns a distinct
durable job and `harness_run` artifact. The synthesis prompt receives bounded,
redaction-safe summaries plus typed artifact references. Its verdict must cite
the child step and retained run id for each conclusion.

If one role fails, the workflow finishes failed after synthesis rather than
presenting a partial review as success. The successful child evidence and the
failed child's run artifact remain attached to their original steps.

## 4. Verify the packaged contract

```bash
giga eval run cross-harness-review-contract \
  --workspace . \
  --json
```

This read-only eval checks the reviewed configuration contract. Editing,
applying a patch, committing, pushing, and hosted writes are intentionally not
part of this example.
