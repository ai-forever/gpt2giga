# Documentation

GigaLoom is developed in
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom). This site is
built from Markdown in `docs/` through the Docusaurus wrapper in `docs-site/`.
Repository-wide contribution, disclosure, and ownership rules live in
[`CONTRIBUTING.md`](https://github.com/krakenalt/gigaloom/blob/main/CONTRIBUTING.md),
[`SECURITY.md`](https://github.com/krakenalt/gigaloom/blob/main/SECURITY.md),
and
[`GOVERNANCE.md`](https://github.com/krakenalt/gigaloom/blob/main/GOVERNANCE.md).

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
- standalone user, operations, security, architecture, and release guides;
- links to target-owned files in `krakenalt/gigaloom`;
- explicitly labeled historical or canonical gateway references.

## Update rules

- Keep README and `docs-site/sidebars.ts` consistent with the list of core documents.
- For links to files outside `docs/`, use GitHub URLs; otherwise the published site may lead beyond the Pages artifact.
- Do not publish secrets, local `.env`, credentials, keys, or raw traffic payloads.
- Current development links must point to `krakenalt/gigaloom`.
- Keep gateway links in `gateway-integration.md` and source-repository links in
  `source-history.md` explicitly labeled.

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
