# Release

GigaLoom releases the `gpt2giga-harness` distribution from exact tags shaped
as `gpt2giga-harness-vX.Y.Z`.

## Maintainer checklist

1. Confirm the named GitHub and PyPI backup owners have accepted access with
   2FA under the
   [governance policy](https://github.com/krakenalt/gigaloom/blob/main/GOVERNANCE.md).
2. Update both package changelogs and confirm the package version.
3. Build frontend assets and run the complete non-live quality gate.
4. Build wheel and sdist without workspace sources.
5. Verify package metadata, included assets, checksums, and isolated install.
6. Ensure the release commit is on `main` and the documented main/tag rulesets
   are active.
7. Create the exact immutable tag only after external publication prerequisites
   are authorized and ready.

The release workflow validates repository identity, tag/version agreement,
history, commit SHA, and artifact set before publication. Manual dispatch is
build-and-attest only; it cannot publish.

Public Trusted Publisher registration, tags, GitHub releases, and package
publication are external mutations and remain separate authorized gates. See
the repository's [release recovery runbook](https://github.com/krakenalt/gigaloom/blob/main/.github/RELEASE_RECOVERY.md).
