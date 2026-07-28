# Release

GigaLoom releases the `gpt2giga-harness` distribution from exact tags shaped
as `gpt2giga-harness-vX.Y.Z`.

## Maintainer checklist

1. Update both package changelogs and confirm the package version.
2. Build frontend assets and run the complete non-live quality gate.
3. Build wheel and sdist without workspace sources.
4. Verify package metadata, included assets, checksums, and isolated install.
5. Ensure the release commit is on `main`.
6. Create the exact immutable tag only after external publication prerequisites
   are authorized and ready.

The release workflow validates repository identity, tag/version agreement,
history, commit SHA, and artifact set before publication. Manual dispatch is
build-and-attest only; it cannot publish.

Public Trusted Publisher registration, tags, GitHub releases, and package
publication are external mutations and remain separate authorized gates. See
the repository's [release recovery runbook](https://github.com/krakenalt/gigaloom/blob/main/.github/RELEASE_RECOVERY.md).
