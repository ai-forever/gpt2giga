# GigaLoom governance

GigaLoom is maintained in the personal-owner repository
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom). Repository
ownership does not grant permission to bypass the safety, review, or release
contracts below.

## Named ownership

| Surface | Primary owner | Backup owner | Activation gate |
| --- | --- | --- | --- |
| Repository administration, rulesets, Actions and incidents | [`@krakenalt`](https://github.com/krakenalt) | `backup-github-maintainer` | A distinct GitHub account must accept admin access and enable 2FA before S5-02. |
| Vulnerability intake and coordinated disclosure | [`@krakenalt`](https://github.com/krakenalt) | `backup-github-maintainer` | Private vulnerability reporting and backup access must both be verified before public use. |
| Release approval, tags and GitHub Releases | [`@krakenalt`](https://github.com/krakenalt) | `backup-github-maintainer` | The main and release-tag rulesets must be active before the first tag. |
| PyPI project ownership and compromised-publisher recovery | Ruslan Yakupov (`primary-pypi-owner`; exact service account verified at S5-04) | `backup-pypi-owner` | A distinct PyPI owner must accept the invitation and enable 2FA before S5-04. |
| Documentation, triage and ordinary maintenance | [`@krakenalt`](https://github.com/krakenalt) | `backup-github-maintainer` | Backup acceptance is required before public cutover. |

The backup names above are stable governance roles, not claims that an
unidentified person already has access. Their state is
`blocked_pending_acceptance`. The primary maintainer must record the accepted
human account for each role in private recovery records without committing
personal contact data. One person may fill both backup roles only if that
person has independently accepted both invitations and enabled 2FA on both
services.

The repository does not infer a PyPI username from a GitHub handle. The
`primary-pypi-owner` service account remains
`blocked_pending_S5_04_verification` until PyPI shows the accepted owner state.

The exact evidence to collect without exposing private recovery details is in
[the owner recovery checklist](.github/OWNER_RECOVERY_CHECKLIST.md).

Until those gates are satisfied, the repository is not governance-ready for a
public push or package release. No source-organization team, secret, bot, or
publisher is inherited.

## Changes and decisions

- Ordinary changes use a pull request, focused tests, and the stable checks in
  [the repository policy specification](.github/repository-policy.json).
- Security-boundary, release, packaging, dependency, and governance changes
  require review by the primary owner or the accepted backup owner.
- Breaking compatibility changes require migration notes and a normal release;
  published artifacts and accepted Git history are not rewritten.
- Emergency changes use the same reviewable commit path. If an administrator
  bypass is necessary to restore the repository, the actor records why, the
  exact ref and commit, and the follow-up review in a public incident summary
  after sensitive details are removed.

## Owner unavailable

The accepted backup GitHub maintainer may freeze releases, disable a compromised
workflow or credential, open a private security advisory, and apply a reviewed
corrective commit. The accepted backup PyPI owner may remove a compromised
publisher, yank an affected version when justified, and preserve the immutable
files and hashes for investigation. Neither owner may replace an existing PyPI
version or rewrite protected Git history.

If the relevant backup role is still `blocked_pending_acceptance`, stop. Do not
publish, retag, weaken rulesets, copy source-repository credentials, or claim
recovery readiness.

## Issue and pull-request history

Issues and pull requests are not transferred objects. When work moves from
`ai-forever/gpt2giga`:

1. create a new target issue or pull request only with explicit mutation
   authority;
2. link the immutable source URL and label it as historical context;
3. identify the new target discussion as a continuation, not a migration of
   comments, approvals, authorship, timestamps, reactions, or review state;
4. add a backlink in the source only when separately authorized;
5. never recreate releases or edit quoted participants to make history appear
   native to GigaLoom.

Security reports remain private and follow [SECURITY.md](SECURITY.md).
