# Workspace package boundaries

This document freezes the package ownership contract at the pre-split baseline
`e267531cf2b3a4382b5aa303f95f8bd33dc5ef9e`. It is an implementation inventory
for the `uv` workspace migration, not a change to the current source layout.

## Distribution contract

| Owner | Distribution | Python namespace | Version | Commands |
| --- | --- | --- | --- | --- |
| Gateway | `gpt2giga` | `gpt2giga` | `0.2.2a1` | `gpt2giga` |
| Harness | `gpt2giga-harness` | `gpt2giga_harness` | `0.0.1` | `giga`, `gpt2giga-harness` |

The Harness distribution initially depends on exactly `gpt2giga==0.2.2a1`.
The gateway must never import `gpt2giga_harness`. The existing
`gpt2giga.harnesses` plugin entry-point group remains unchanged; only its
targets move to `gpt2giga_harness.harnesses.*`.

Supported installation modes are gateway-only, Harness with its resolved
gateway dependency, and both workspace members editable from the repository
root. The combined `gpt2giga==0.3.0a1` build is only the pre-extraction
relocation checkpoint and must not be published.

## Source ownership

The baseline contains 85 Harness Python files, 55 Harness test files, and 133
Python files that reference `gpt2giga.harness`. These are migration audit
counts, not permanent assertions.

| Baseline source | Target owner and location | Action |
| --- | --- | --- |
| `gpt2giga/harness/**` | `packages/gpt2giga-harness/src/gpt2giga_harness/**` | Move and rename imports |
| `gpt2giga/tools/**` | `packages/gpt2giga-harness/src/gpt2giga_harness/tools/**` | Move with Harness contracts |
| `gpt2giga/protocols/openai/stream_accumulator.py` | `packages/gpt2giga-harness/src/gpt2giga_harness/protocols/openai/stream_accumulator.py` | Move with Direct Chat |
| Other `gpt2giga/**` | `packages/gpt2giga/src/gpt2giga/**` | Retain in gateway |
| `gpt2giga/harness/ui/assets/**` | Harness package data | Preserve HTML, CSS, and JavaScript assets |

Harness retains only these gateway boundaries initially:

- `gpt2giga.protocols.normalized` models used by Direct Chat;
- `from gpt2giga import run` used by optional local sidecar startup.

Current `gpt2giga.tools` imports in MCP, managed MCP, runtime policy, and UI
tool routes relocate to `gpt2giga_harness.tools`. Direct Chat's accumulator
import relocates with the accumulator. Gateway OpenAI streaming and
`chat_completions.py` return to the `origin/main` implementation when that move
happens.

## Metadata and dependency cleanup

- Move `pyyaml` and `python-dateutil` from combined metadata to Harness.
- Do not retain the branch-only direct `certifi` requirement without a new,
  evidenced direct runtime use.
- Restore the removed `gitleaks` hook to the `origin/main` repository-tooling
  baseline in a dedicated cleanup change; it belongs to neither wheel.
- Replace combined `0.3.0a1` metadata with the fixed member versions above.
- Record both `gpt2giga` and `gpt2giga-harness` distribution versions in
  `gpt2giga_harness.runtime.fingerprint`.

## Relocation inventory

The mechanical migration must cover all of the following surfaces:

- project metadata, scripts, entry points, dependencies, extras, build backend,
  and package data in `pyproject.toml`, plus the single root `uv.lock`;
- UI resource loading and the installed-wheel smoke in
  `tests/harness/test_ui_packaging.py`;
- distribution lookup in `gpt2giga/harness/runtime/fingerprint.py`;
- all imports and monkeypatch strings under `tests/harness/**`;
- path-bearing project-selection assertions in `tests/harness/test_project.py`
  and `tests/harness/test_project_api.py`;
- Harness documentation and scaffold/template strings in `README.md`,
  `docs/harness.md`, `docs/harness-killer-features.md`, `.env.example`, and
  Harness source modules;
- source-path filters and commands in `.github/workflows/**`, with particular
  attention to `ci.yaml`, `nightly-smoke.yaml`, `pip-audit.yaml`,
  `docker-smoke.yaml`, `docker_image.yaml`, `publish-ghcr.yml`,
  `publish-pypi.yml`, `codeql.yaml`, and `codeflash.yaml`;
- `Dockerfile` copy/build/install paths, keeping the production image
  gateway-only;
- root pytest, coverage, Ruff, and pre-commit configuration.

Cross-boundary test ownership is explicit: `tests/test_tools_contracts.py`
moves to Harness ownership; the stream-accumulator coverage in
`tests/test_protocol/test_openai_normalized_streaming.py` moves with the
accumulator; normalized protocol tests stay gateway-owned; `tests/harness/**`
remains the Harness and cross-package integration suite until isolation is
proven. The test directory does not otherwise move during the split.

## Artifact content contract

The gateway artifact contains `gpt2giga`, the `gpt2giga` command, and gateway
extras only. It contains no `gpt2giga_harness`, Harness UI assets, Harness
commands or entry points, relocated tool contracts, or relocated accumulator.

The Harness artifact contains `gpt2giga_harness`, its UI assets, both Harness
commands, all built-in entries in `gpt2giga.harnesses`, and an exact published
requirement on `gpt2giga==0.2.2a1`. Workspace source wiring must not appear in
built metadata.

`tests/test_workspace_split_contract.py` enforces the dependency direction now
and progressively enables source and metadata assertions when each workspace
member appears.
