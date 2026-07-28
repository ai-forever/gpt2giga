# Harness Cockpit V2 frontend

This package-local React/TypeScript/Vite project owns only the browser shell
introduced by roadmap slice P2.5-02. FastAPI, the Harness runtime, policy,
approvals, redaction, durable state, and SSE semantics remain authoritative.

From this directory, run:

```bash
npm ci --ignore-scripts
npm run check
```

`npm run check` runs type checking, lint, unit tests, two deterministic
production builds, manifest validation, compression, and initial bundle
budgets. Generated content-hashed assets are committed under
`src/gpt2giga_harness/ui/cockpit_v2/assets/` and packaged into the Python wheel.
Node.js and npm are build/CI inputs only; installed Harness wheels do not need
them.

The GigaLoom vector master lives in `../branding/gigaloom-mark.svg`.
`npm run generate:brand` deterministically refreshes the local light, dark,
mask, Web manifest, and documentation copies. The normal production
build runs that step before Vite so a stale generated mark cannot enter the
packaged asset graph.

Cockpit V2 is the only packaged UI at `/` and `/cockpit-v2/**`. Saved links
from the previous UI continue to redirect to canonical Cockpit routes. If the
verified Cockpit asset artifact is missing, repair or reinstall the package.
Do not move backend ownership or surface migration into this frontend package.
