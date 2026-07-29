# Owner and recovery acceptance checklist

This checklist is a specification, not evidence that an external action has
already happened. Record only non-secret evidence. Keep recovery codes,
personal contact details, tokens, and private advisory content outside the
repository.

## S5-02 — GitHub backup and repository protection

- [ ] A human account distinct from `@krakenalt` has accepted the named
      `backup-github-maintainer` role.
- [ ] The backup account has 2FA enabled and can reach repository settings and
      private vulnerability reports.
- [ ] Default workflow token permission is read-only and Actions cannot approve
      pull requests.
- [ ] `protect-main` and `protect-gigaloom-release-tags` match
      `.github/repository-policy.json`.
- [ ] Required checks exactly match the successful job names emitted by
      `.github/workflows/ci.yaml`.
- [ ] Main and protected release tags reject deletion and force-push; the
      emergency admin bypass produces an audit event.
- [ ] Secret scanning and push protection are enabled without copying any
      source-organization secret.
- [ ] The primary and backup owners can open the private reporting channel and
      identify the first containment steps in `SECURITY.md`.

## S5-04 — PyPI backup and publisher handoff

- [ ] PyPI shows the exact accepted service username for Ruslan Yakupov in the
      named `primary-pypi-owner` role; no GitHub-to-PyPI username inference is
      used.
- [ ] A human account distinct from the primary owner has accepted the named
      `backup-pypi-owner` role for `gigaloom`.
- [ ] The backup PyPI owner has 2FA enabled.
- [ ] The pending Trusted Publisher names PyPI project `gigaloom` and binds
      only `krakenalt/gigaloom`, the exact publish workflow, and the protected
      release environment.
- [ ] Manual workflow dispatch cannot publish.
- [ ] The source workflow is incapable of publishing before the target
      publisher is used.
- [ ] Both owners can freeze or remove a compromised publisher and can explain
      why an existing PyPI version must never be overwritten.

## Recovery drill

- [ ] The backup GitHub maintainer can freeze releases, preserve protected refs
      and workflow evidence, and prepare a reviewed corrective commit.
- [ ] The backup PyPI owner can compare public files with retained hashes, yank
      an unsafe version when authorized, and leave immutable evidence intact.
- [ ] A primary-owner-unavailable drill stops safely if either backup role is
      not accepted.
- [ ] Issue and pull-request continuation uses source links and does not claim
      transferred comments, authorship, timestamps, approvals, or review state.
- [ ] The drill records date, actor handles, repository/package role shown by
      the service, 2FA confirmation, exact policy commit, and result without
      storing secrets.

Public push remains blocked until S5-01 authority. Repository protection and
GitHub backup acceptance remain blocked until S5-02. Publisher mutation, PyPI
backup acceptance, tags, releases, and publication remain blocked until S5-04.
