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
- GitHub links to deployment manifests and other files outside `docs/`.

## Update rules

- Keep README and `docs-site/sidebars.ts` consistent with the list of core documents.
- For links to files outside `docs/`, use GitHub URLs; otherwise the published site may lead beyond the Pages artifact.
- Do not publish secrets, local `.env`, credentials, keys, or raw traffic payloads.
- When deployment behavior changes, update `docs/deployment.md`, `deploy/README.md`, and the relevant Compose manifests together.
- When compatibility behavior changes, update `docs/api-compatibility.md` and `docs/client-parameter-compatibility.md`.
