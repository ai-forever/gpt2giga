# Documentation

This site is built from the Markdown files in `docs/` through the Docusaurus wrapper in `docs-site/` and is published to GitHub Pages.

## Local build

Install Node.js `20+`, then the Docusaurus dependencies:

```sh
cd docs-site
npm ci
```

Build the site:

```sh
npm run build
```

For a local preview:

```sh
npm run start
```

By default, Docusaurus opens the site at `http://127.0.0.1:3000/`.
To check the production artifact after the build:

```sh
npm run serve
```

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
