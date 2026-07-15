# Nightly compatibility guardian

This disposable repository packages the second Harness north-star workflow:
one read-only triage profile, a pinned Codex/Claude/Gemini compatibility eval,
an on-demand review workflow, and a nightly schedule source. The durable worker
runs the schedule while the cockpit is closed and retains the adapter version,
event-schema dimensions, scorecard, baseline identity, and occurrence audit.

The example never edits the project. The schedule targets the eval directly so
that only failed deterministic checks create Attention; the workflow is the
separate operator-triggered path that reruns the same immutable matrix and
invokes evidence-backed triage only on failure.

## 1. Prepare a disposable copy

From the `gpt2giga` repository root, with its virtual environment activated:

```bash
EXAMPLE_PARENT="$(mktemp -d)"
cp -R examples/harness/nightly-compatibility-guardian \
  "$EXAMPLE_PARENT/nightly-guardian"
cd "$EXAMPLE_PARENT/nightly-guardian"
git init -b main
git config user.email "harness-example@example.invalid"
git config user.name "Harness Example"
git add .
git commit -m "test: seed nightly compatibility example"
export GPT2GIGA_HARNESS_DATA_DIR="$PWD/.local/harness"
```

The example requires configured Codex, Claude, and Gemini CLIs plus a running
`gpt2giga` gateway for model-backed execution. It pins API mode `v2`, model
`GigaChat-2-Max`, two deterministic tasks, and one read-only workspace policy.

## 2. Review the packaged contract

```bash
giga doctor .
giga agent list --workspace .
giga workflow validate \
  .giga/workflows/nightly-compatibility-guardian.yaml
giga workflow run nightly-compatibility-guardian \
  --workspace . \
  --dry-run \
  --json
giga eval list --workspace . --json
giga schedule preview \
  .giga/schedule-sources/nightly-compatibility-guardian.yaml \
  --workspace . \
  --json
```

The preview captures an immutable snapshot and hash of the eval. The generated
`.giga/schedules/` definition is ignored in this disposable example because it
contains the copy's captured target path; the reviewed portable input remains
under `.giga/schedule-sources/`.

## 3. Pin a reviewed baseline

Start the gateway, then run the fixed matrix once:

```bash
gpt2giga
```

```bash
giga eval run nightly-compatibility \
  --workspace . \
  --model GigaChat-2-Max \
  --api-mode v2 \
  --json
giga ui --workspace .
```

In Eval Lab, inspect the six cells, confirm the adapter dimensions, and pin the
passing scorecard as the baseline. A future delta is comparable only when API
mode and the complete adapter-dimension snapshot match.

## 4. Test and enable the nightly schedule

Keep a durable worker running under your normal supervisor or in a terminal:

```bash
giga worker start
```

In another terminal:

```bash
giga schedule create \
  .giga/schedule-sources/nightly-compatibility-guardian.yaml \
  --workspace . \
  --json
giga schedule test-now nightly-compatibility-guardian \
  --workspace . \
  --json
giga schedule show nightly-compatibility-guardian \
  --workspace . \
  --json
giga schedule enable nightly-compatibility-guardian \
  --workspace . \
  --json
```

Enable succeeds only after `test-now` passes for the exact schedule hash. The
worker then owns nightly execution independently of the UI. A later failed eval
moves that schedule to `needs_attention`, pauses it, and retains the scorecard
and occurrence instead of repeatedly notifying on an unreviewed contract.

## 5. Triage retained evidence

The eval metadata and `COMPATIBILITY_TASK.md` define exactly four categories:

- `product`: Harness orchestration or contract failure;
- `adapter`: native CLI or normalized event-schema drift;
- `model`: truthful execution that missed the deterministic task;
- `environment`: proxy, credential, executable, network, or worker failure.

Use the on-demand workflow after opening the failed scorecard. It reruns the
same matrix and activates the triager only if a cell still fails:

```bash
giga workflow run nightly-compatibility-guardian \
  --workspace . \
  --prompt "Triage the retained nightly regression evidence." \
  --json
```

The triager is read-only and must cite retained evidence. Updating the pinned
baseline, changing the matrix, or dismissing Attention remains a separate
reviewed operator decision.
