# GigaLoom examples

These examples demonstrate standalone GigaLoom workflows. They use temporary or
fixture repositories and do not require a gateway source checkout.

- [Native CLI prefix](harness/native-cli-prefix/README.md): preserve native
  Codex, Claude, and Gemini arguments, streams, and exit status.
- [First-run demo](harness/first-run-demo/README.md): local onboarding without
  provider credentials.
- [Issue to reviewed patch](harness/issue-to-reviewed-patch/README.md):
  worktree-isolated implementation, review, and post-apply evaluation.
- [Nightly compatibility guardian](harness/nightly-compatibility-guardian/README.md):
  pinned capability checks with durable scheduling.
- [Cross-harness review team](harness/cross-harness-review-team/README.md):
  read-only fan-out, retained child evidence, and synthesis.

Run an example only after reading its own prerequisites and expected authority
scope. Tests and examples must not inspect or mutate real native provider homes,
`~/.gpt2giga/harness`, or unrelated project `.giga/` state.
