# Documentation

This site is built from the Markdown files in `docs/` through the Docusaurus wrapper in `docs-site/` and is published to GitHub Pages.

## Local build

Install Node.js `20+`, then the Docusaurus dependencies:

```sh
make docs-install
```

Build the site:

```sh
make docs-build
```

For a local preview:

```sh
make docs
```

By default, Docusaurus opens the site at `http://127.0.0.1:3000/`.
This builds and serves all configured locales, so the language switcher works locally.
For faster one-locale development with hot reload:

```sh
make docs-dev
```

Docusaurus dev server serves one locale per run. To preview the Russian locale in dev mode:

```sh
make docs-dev-ru
```

Use `make docs` or `make docs-preview` when checking the locale switcher between English and Russian.

## What gets published

The public site includes:

- user guides from `docs/*.md`;
- architecture notes from `docs/architecture/`;
- links to runnable examples and integration guides in the repository;
- GitHub links to deployment manifests and other files outside `docs/`;
- migration-only tombstones for legacy documentation routes.

## Gateway quality and release boundary

The repository coverage badge and the `--cov-fail-under=80` gate measure the
standalone `gpt2giga` gateway source.

Only an exact gateway `v<version>` release may publish `gpt2giga` from this
repository. A manual release workflow run builds and attests artifacts without
publishing. Split-out product distributions have no publisher in this
repository.

## Update rules

- Keep README and `docs-site/sidebars.ts` consistent with the list of core documents.
- For links to files outside `docs/`, use GitHub URLs; otherwise the published site may lead beyond the Pages artifact.
- Do not publish secrets, local `.env`, credentials, keys, or raw traffic payloads.
- When deployment behavior changes, update `docs/deployment.md`, `deploy/README.md`, and the relevant Compose manifests together.
- When compatibility behavior changes, update `docs/api-compatibility.md` and `docs/client-parameter-compatibility.md`.

Ignored `docs/internal/**` and `docs/codex/**` are local coordination state, not
public documentation sources. Update the English source and its Russian locale
in one change set, preserving code blocks, warnings, and behavior limitations.

## Pre-PR validation

```sh
python3 scripts/check_docs.py
make docs-build
git diff --check
```

After the build, inspect changed pages in a browser at desktop and narrow
widths. Check navigation, search, the locale switcher, code copy, and the
browser console.
