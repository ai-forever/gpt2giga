# Source history and migration

GigaLoom was extracted from the combined
[`ai-forever/gpt2giga`](https://github.com/ai-forever/gpt2giga) repository with
filtered history. That link is a **historical source reference**. Current
development, documentation edits, issues, releases, and project links point to
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom).

The distribution name `gpt2giga-harness`, Python namespace
`gpt2giga_harness`, commands `giga` and `gpt2giga-harness`, and existing local
state paths remain stable across the repository split.

Older changelog comparison links intentionally point to the historical source
repository so pre-split tags remain resolvable. They do not imply current
ownership or a source checkout dependency.

For migration from the old combined prerelease package, uninstall the combined
artifact, install the standalone `gpt2giga-harness` distribution, and retain
the backed-up `~/.gpt2giga/harness` state. See the detailed
[Harness migration section](harness.md#migration-from-the-combined-prerelease).
