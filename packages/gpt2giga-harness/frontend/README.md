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
budgets. The one production producer command is:

```bash
npm --prefix packages/gpt2giga-harness/frontend run build
```

Run it from the repository root before a local Harness build. It atomically
refreshes the ignored `src/gpt2giga_harness/ui/cockpit_v2/assets/` staging tree
and writes the runtime manifest, source/commit provenance, npm SBOM, and license
evidence. The Python-only Hatch consumer rejects a missing, substituted, or
stale tree. Node.js and npm are producer/CI inputs only; installed Harness
wheels and wheels rebuilt from the sealed sdist do not need them.

The GigaLoom vector master lives in `../branding/gigaloom-mark.svg`.
`npm run generate:brand` deterministically refreshes the ignored local light,
dark, mask, and Web manifest copies. The normal production build runs that step
before Vite so a stale generated mark cannot enter the packaged asset graph.

CI and release run `npm run build:release` on pinned Node.js 22.13.0 and npm
11.17.0 with clean authored inputs, upload the commit-bound tree, and inject it
into the Python artifact job. Rollback checks out the prior release and reruns
the producer, or restores that release's exact asset artifact, before rebuilding
the wheel and sdist.

Cockpit V2 is the only packaged UI at `/` and `/cockpit-v2/**`. Saved links
from the previous UI continue to redirect to canonical Cockpit routes. If the
verified Cockpit asset artifact is missing, repair or reinstall the package.
Do not move backend ownership or surface migration into this frontend package.
