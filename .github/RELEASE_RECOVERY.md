# GigaLoom release recovery

The release workflow is intentionally fail-closed. It accepts only a published
GitHub release whose exact `gpt2giga-harness-v<version>` tag points at a commit
on target `main` after the history floor in `release-policy.json`. Manual
dispatch builds and attests the same artifacts but cannot publish them.

The committed target lock resolves the exact optional gateway dependency from
the public package index. Do not add a token secret, candidate artifact,
temporary index, or publisher bypass. Trusted Publisher configuration remains
an external S5-04 gate.

The primary release and recovery owner is `@krakenalt`. The named
`backup-github-maintainer` and `backup-pypi-owner` roles, their distinct-account
and 2FA criteria, and the unavailable-owner boundary are defined in
[`GOVERNANCE.md`](../GOVERNANCE.md). Release and public cutover remain blocked
while either required role is `blocked_pending_acceptance`.

## Failure handling

- Guard or ancestry failure: do not retag. Delete or correct only an unpublished
  draft release, then create a new published release from the intended `main`
  commit after the policy and package version are reviewed.
- Existing PyPI version: stop. Published versions are immutable; increment the
  package version and create a new tag instead of overwriting files.
- Build, hash, SBOM, license, or attestation failure: keep the release visible
  as failed evidence, fix the source, and create a new version. Never upload an
  unverified local artifact.
- GitHub release-asset failure before publication: rerun the failed job only if
  the attached files are absent and PyPI still reports the version missing.
- PyPI success followed by a later failure: do not rerun publication. Verify
  the public file hashes against the retained workflow artifact and repair only
  missing GitHub release assets from that exact artifact.
- Pages failure: keep the previous deployment. Rebuild the same commit locally;
  do not change `url` or `baseUrl` to work around a broken documentation link.
- Compromised publisher or OIDC binding: freeze releases, preserve workflow and
  package-index evidence, remove only the compromised binding, and verify
  published hashes. The accepted backup PyPI owner may yank an unsafe version
  but must never delete or overwrite it.
- Primary owner unavailable: the accepted backup GitHub maintainer freezes
  repository release paths and preserves refs; the accepted backup PyPI owner
  freezes or removes the publisher. If either role has not accepted, stop
  instead of weakening rulesets or inventing a replacement identity.

Rollback means reverting the automation commit before any release is published.
It never means deleting or replacing an immutable package-index version.
