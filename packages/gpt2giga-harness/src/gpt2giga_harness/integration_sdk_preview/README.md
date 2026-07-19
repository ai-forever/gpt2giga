# Adapter/Integration SDK preview v1

This internal preview supports two versioned extension surfaces:

- Harness adapters use `agent_workbench.harness_adapters.v1`, strict
  `AdapterManifest` schema v1, `giga harness scaffold`, and
  `giga harness conformance`.
- Integration packages use strict `IntegrationPackage` schema v1; target
  drivers use `agent_workbench.extension_targets.v1` and strict
  `ExtensionTargetDescriptor` schema v1. Use `giga integration scaffold` and
  `giga integration conformance` for offline authoring and CI.

The schemas and samples in this package are authoritative examples for the
current preview. Unknown fields and future schema versions fail closed. A
successful conformance report validates shape, immutable pins, policy
non-authority, and any supplied target compatibility; it does not approve or
install a package.

## Compatibility policy

- The SDK API, manifest schemas, and entry-point groups are independently
  versioned. Consumers must request the exact supported version.
- Additive or breaking schema changes require a new schema/API version because
  v1 parsers reject unknown fields.
- Existing v1 entry-point groups are not repurposed with incompatible
  semantics. A replacement uses a new versioned group.
- This preview remains in the `gpt2giga_harness` namespace until the neutral
  namespace/extraction gate is accepted.

## Deprecation policy

- Deprecations name a replacement and an earliest removal release.
- Removal requires at least two preview releases and 30 calendar days of
  notice; security removals may fail closed earlier and must document why.
- Conformance output remains content-free and never turns catalog or trust
  evidence into installation authority.

Public marketplace publication, namespace extraction, release signing, and
long-term public API stability are outside this internal preview.
