# Security policy

## Supported versions

Before the first target-owned release, only the current `main` branch is
eligible for security fixes. After publication, the latest non-yanked release
and `main` are supported unless a release note states a narrower window.
Historical `gpt2giga-harness` releases remain owned by their source repository
and are not silently reissued here.

## Report a vulnerability

Do not open a public issue, discussion, or pull request for a suspected
vulnerability.

Use GitHub private vulnerability reporting at
<https://github.com/krakenalt/gigaloom/security/advisories/new>. If that channel
is unavailable, contact the primary security owner
[`@krakenalt`](https://github.com/krakenalt) through the verified contact on
that profile and ask for a private channel before sending sensitive details.
The named backup is the `backup-github-maintainer` role defined in
[GOVERNANCE.md](GOVERNANCE.md); public use remains blocked until a distinct
account has accepted that role with 2FA.

Include a minimal redacted reproduction, affected version or commit, impact,
and a safe way to validate the report. Do not send credentials, live tokens,
private user content, raw provider traffic, or destructive proof-of-concept
steps.

## Response targets

- acknowledgement within 3 business days;
- initial severity and scope assessment within 7 business days;
- a remediation or status update within 14 business days;
- coordinated disclosure timing agreed with the reporter, normally after a
  fix is available.

These are response targets, not a promise to expose investigation details or
unsafe reproduction data.

## Incident and publisher recovery

The primary security and release owner is `@krakenalt`. The backup GitHub and
PyPI roles, activation criteria, and unavailable-owner procedure are defined
in [GOVERNANCE.md](GOVERNANCE.md). Release-specific recovery is in
[`.github/RELEASE_RECOVERY.md`](.github/RELEASE_RECOVERY.md).

For a compromised repository, workflow, token, signing identity, or publisher:

1. freeze releases and preserve workflow, audit, artifact, and hash evidence;
2. revoke only the compromised access path and rotate affected credentials;
3. verify protected refs and published artifacts against retained hashes;
4. repair through a reviewed commit and a new immutable package version;
5. yank an unsafe version only when necessary, without deleting or replacing
   its files;
6. publish a redacted incident summary after containment.

Never force-push accepted history, move a published release tag, overwrite a
PyPI version, copy a source-organization secret, or expose a reporter's
identity without consent.
