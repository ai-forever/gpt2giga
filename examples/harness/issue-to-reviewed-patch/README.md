# Issue to reviewed patch

This disposable repository packages the first Harness north-star workflow as
reviewed project definitions: three agent profiles, one durable workflow, and
one post-apply eval. The example starts with an intentional equality-boundary
regression in `inventory.py` and keeps every model-authored mutation in a
Harness-owned worktree until an operator reviews and explicitly applies it.

## 1. Prepare a disposable copy

From the `gpt2giga` repository root, with its virtual environment activated:

```bash
EXAMPLE_PARENT="$(mktemp -d)"
cp -R examples/harness/issue-to-reviewed-patch "$EXAMPLE_PARENT/reviewed-patch"
cd "$EXAMPLE_PARENT/reviewed-patch"
git init -b main
git config user.email "harness-example@example.invalid"
git config user.name "Harness Example"
git add .
git commit -m "test: seed reviewed patch example"
export GPT2GIGA_HARNESS_DATA_DIR="$PWD/.local/harness"
```

The initial focused suite has one expected failure at the equality boundary:

```bash
python -m unittest discover -s tests -v
```

## 2. Inspect the packaged contract without starting an agent

```bash
giga doctor .
giga agent list --workspace .
giga workflow validate .giga/workflows/issue-to-reviewed-patch.yaml
giga workflow run issue-to-reviewed-patch \
  --workspace . \
  --prompt "$(cat ISSUE.md)" \
  --dry-run \
  --json
giga eval list --workspace . --json
```

The workflow plan is `plan -> implement -> review -> evidence`. The implementer
uses `mode: edit` plus `workspace_policy: worktree`; the reviewer receives a
bounded patch/diff handoff and remains read-only. The workflow contains no
apply, commit, push, hosted-write, shell, or generic approval node.

## 3. Run the reviewed-patch workflow

This stage requires a configured `gpt2giga` gateway and Codex CLI. Start the
gateway in one terminal and the loopback cockpit/worker in another:

```bash
gpt2giga
```

```bash
giga ui --workspace .
```

Then start the workflow from a third terminal:

```bash
giga workflow run issue-to-reviewed-patch \
  --workspace . \
  --prompt "$(cat ISSUE.md)" \
  --json
```

Save the returned workflow run id and inspect progress with:

```bash
giga workflow status <workflow_run_id> --json
```

Before approval, `git status --short` in this source checkout must remain
empty. In the cockpit's Workflows run detail, inspect the retained implementer
patch and reviewer verdict, select the patch, and prepare the merge queue. Apply
only after the Approval Center shows the exact source commit, patch SHA-256,
changed files, and branch intent you reviewed. Harness refuses stale source,
changed patch, dirty checkout, truncated diff, or reused approval evidence.

## 4. Verify after explicit apply

After the reviewed patch is applied locally, run the packaged eval:

```bash
giga eval run reviewed-patch-verification \
  --workspace . \
  --harness codex-cli \
  --json
```

A successful scorecard has one passing case and contains the
`REVIEWED_PATCH_VERIFIED` marker. Applying, committing, pushing, and opening a
hosted pull request remain separate operator decisions; this example performs
none of them automatically.
