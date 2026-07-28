# Operations

GigaLoom is local-first. Runtime state lives under `~/.gpt2giga/harness`, while
project-scoped state lives under `.giga/` in a registered project.

## Start and inspect

```sh
giga doctor
giga ui
giga tui
```

The browser UI binds to `127.0.0.1:8091` by default. Do not expose it on an
untrusted network without the explicitly documented remote identity profile.

## Backup and recovery

Stop active GigaLoom processes before copying state. Back up the complete
`~/.gpt2giga/harness` directory and any project `.giga/` directories so SQLite
files, JSON/JSONL records, evidence, and metadata remain consistent.

Package uninstall does not remove user state. Restore into the same paths only
while GigaLoom is stopped, then run `giga doctor`.

## Troubleshooting

- Missing provider: install its native CLI and use its native login/status
  command.
- Refused action: review the requested scope; do not bypass a failed approval
  or policy check.
- Stale browser assets: reinstall the released package. Source contributors
  should rebuild the frontend before syncing Python dependencies.
- Optional gateway unavailable: verify the `gpt2giga` extra is installed; no
  gateway source checkout is expected.

## Quality baseline

The repository owns a separate GigaLoom coverage badge. The split baseline is
**84.59%**, measured on 2026-07-29 by the non-live standalone test gate. It is a
recorded baseline, not a claim about an unverified remote run. The quality gate
requires at least 80% coverage and excludes opt-in live provider tests.
