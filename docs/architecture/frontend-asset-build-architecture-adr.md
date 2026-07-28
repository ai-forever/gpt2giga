# ADR: Frontend asset build architecture

Status: accepted for GigaLoom roadmap slice G8-03 on 2026-07-28.

Implementation status: implemented by G8-04 on 2026-07-28. Compiled bundles are
ignored; the deterministic producer, Python-only fail-closed consumer,
commit-bound CI/release handoff, sealed sdist, SBOM/license evidence, and
rollback contract described here are enforced in source and tests.

## Context

Cockpit is authored in React and TypeScript under
`packages/gpt2giga-harness/frontend`. Its pinned npm graph produces a
content-addressed, integrity-checked asset tree under the Python package. The
installed Harness wheel serves that tree without Node.js or network access.

The compiled tree is currently tracked. The Harness sdist deliberately omits
the frontend source and npm toolchain while retaining the compiled assets. It
can therefore build an offline wheel without Node.js, but it cannot regenerate
those assets or prove that they match the authored frontend revision.

G8-04 must remove compiled JS, CSS, source maps, and generated declarations
from Git without weakening these properties:

- clean source can produce both wheel and sdist;
- a wheel built from the sdist remains Node-free and serves Cockpit offline;
- Gateway and Harness remain independently buildable;
- missing, stale, or substituted assets fail the build instead of producing a
  wheel with a broken UI;
- the producer toolchain, licenses, SBOM, output hashes, and release provenance
  are reviewable and reproducible.

For this decision, an offline build means that all locked Python and npm inputs
or an already-produced verified asset artifact are available locally. It does
not imply that an empty machine can reconstruct npm dependencies without a
cache or supplied artifacts.

## Options compared

| Criterion | PEP 517 Node build hook | Separate versioned asset package | CI-injected verified assets |
| --- | --- | --- | --- |
| Clean-clone build | Implicitly runs npm during Python build | Requires resolving two release artifacts | Explicit producer step, then normal Python build |
| Offline Python build | Requires Node plus the npm cache | Requires the asset package locally | Requires only the verified asset tree |
| Node availability | Required by wheel and sdist producers | Required only by asset-package producer | Required only by the frontend producer job |
| Editable install | Hidden Node side effects during install | Version skew between editable Python and assets | Explicit local frontend build into an ignored staging tree |
| Wheel from sdist | Needs frontend source, Node, and npm inputs in the sdist | Needs another exact package | Uses the sealed verified tree embedded in the sdist |
| Cache and reproducibility | PEP 517 cache hides a second package-manager graph | Good per artifact, but two versions must stay aligned | Asset digest is the cache key and Python input |
| Platform support | Every Python build platform needs the Node toolchain | Runtime is portable; release ordering is not | Producer runs on the pinned platform; wheel remains pure Python |
| SBOM and licenses | Python and npm evidence are coupled inside one opaque build | Evidence can be attached to the asset package | Producer publishes explicit npm SBOM/license evidence beside the tree |
| Release recovery | Re-run the mixed Python/Node build | Recover and republish the missing exact asset version first | Rebuild or restore the commit-bound asset artifact, then rebuild Python |
| Repository contract | Keeps two packages but makes PEP 517 invoke Node | Adds a third independently versioned distribution | Preserves the two-member workspace and one Harness runtime artifact |

### PEP 517 Node build hook

Hatch build hooks can add ignored generated artifacts or force-include files in
a target. They are suitable for validation and inclusion, but using one to run
`npm ci` and Vite would make Node and the npm dependency graph implicit
requirements of every isolated Python source build. PEP 517 build isolation
does not describe or provision that non-Python graph. It would also make an
sdist-to-wheel build depend on Node and frontend source, and would add hidden
side effects to editable installs.

This option is rejected. G8-04 may add a Python-only Hatch hook that validates
and includes an already-produced tree; that is a consumer guard, not a Node
build hook.

### Separate versioned asset package

A dedicated asset wheel or archive gives the frontend an independent release
identity, but GigaLoom does not need independent runtime rollout of its browser
shell. The design would add a third distribution, exact-version coupling,
release ordering, another offline-install input, and a new recovery path for
asset/Python skew. The current two-member workspace and one installed Harness
artifact are simpler and already provide the required runtime boundary.

This option is rejected for the current product. It may be reconsidered only
if Cockpit gains a real independent release cadence or multiple Python
consumers.

### CI-injected verified assets

The frontend producer and Python package consumer remain separate build
stages. The producer uses the pinned Node/npm graph to create one complete
Cockpit tree. CI passes that tree as a commit-bound, content-addressed build
artifact to the Python build, which validates and embeds it in the Harness
wheel and sdist. The asset artifact is a build input, not a separately
published runtime dependency.

This option is selected.

## Decision

G8-04 will implement the following contract.

1. Authored TypeScript, configuration, the npm lockfile, the canonical brand
   source, and deterministic producer scripts remain tracked. Compiled output
   is generated into an ignored staging tree at the existing Python package
   resource location so installed and editable loaders keep one path.
2. One documented producer command starts from a clean staging tree, runs the
   pinned frontend build, and emits the existing per-file integrity manifest
   plus content-free provenance. Provenance binds the Git revision, frontend
   input digest, lockfile digest, canonical brand digest, Node/npm versions,
   output-tree digest, and SBOM/license evidence.
3. CI and release workflows run the producer in a dedicated Node job and pass
   the exact tree and provenance to the Python artifact job. The transfer is
   hash-verified and tied to the same source revision. It does not fetch
   mutable “latest” assets.
4. A Python-only Hatch consumer validates the manifest, all file sizes and
   hashes, the complete allowlisted tree, provenance, source revision when the
   authored source is present, and the absence of symlinks, path escapes, and
   unexpected files. Missing or stale input fails with the exact local
   recovery command.
5. The verified tree is included in both direct wheels and sdists. The sdist
   remains a sealed Python source artifact: it contains the verified Cockpit
   tree and consumer metadata, not the frontend toolchain. Building a wheel
   from that sdist requires neither Node nor network access.
6. Editable development uses the same ignored staging path. The explicit
   frontend producer command refreshes it atomically; the verifier rejects a
   source/provenance mismatch so old local output cannot shadow newer authored
   source.
7. The Gateway build remains completely independent. The Harness build has two
   explicit modes: produce-and-package from a source checkout, or consume a
   previously verified tree supplied by the same CI/release run.
8. Release evidence retains the asset digest, npm SBOM/license report, Python
   wheel/sdist hashes, and provenance attestation together. Rollback checks out
   the prior release source and either deterministically rebuilds or restores
   its commit-bound verified asset artifact before rebuilding the Python
   packages.

The consumer must never run npm, contact a registry, accept an unsigned or
unbound mutable asset location, or silently build a wheel without Cockpit.

## Spike evidence

The G8-03 local spike used a Git archive of the accepted G8-02 revision and
removed compiled assets only inside that temporary copy.

- `npm ci --offline --ignore-scripts` restored 301 packages from the local
  cache, and the production producer recreated 53 packaged asset files.
- The normal frontend gate passed 37 test files and 137 tests. Two production
  builds produced the same asset-tree digest:
  `997003971b3db91353df7d11410f4250d468a596ee6ee1388ee342a3a5a6ec9b`.
- A direct injected Harness wheel and a Node-free wheel rebuilt from its sdist
  were byte-identical:
  `4d6773a1edef8a65f4de02edb75d8fc522aed474f9213895340f64d1f96f1af0`.
- The sdist retained the verified asset manifest and omitted the frontend
  toolchain.
- Building the same temporary source with the asset directory empty currently
  succeeds and creates an incomplete wheel. This proves that the fail-closed
  Python consumer is mandatory before tracked output can be removed.

The local spike had Node.js 22.12 while the repository contract and CI require
22.13 or newer; npm reported that mismatch. The architecture decision does not
accept that local runtime as release evidence. G8-04 must run reproducibility,
platform, SBOM/license, and release recovery gates under the pinned toolchain.

## Consequences

The Python package build stays deterministic, offline-capable, and Node-free
when it consumes a verified tree. Frontend production becomes an explicit
supply-chain stage with reviewable evidence rather than an implicit side
effect or tracked source.

The cost is a new staging/verification contract and CI artifact handoff. G8-04
must implement and test that contract before deleting any tracked compiled
file. Until then, the current bundle remains the rollback and packaging source.

## References

- [Hatch build-hook interface](https://github.com/pypa/hatch/blob/master/docs/plugins/build-hook/reference.md)
- [Hatch generated-artifact configuration](https://github.com/pypa/hatch/blob/master/docs/config/build.md)
