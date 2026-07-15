# Fictional review task

Review a proposed artifact-download change before anyone edits the repository.
The change would accept a project-relative artifact name, resolve it under the
project's retained-artifact directory, and return the file through the local
API.

The review must answer four questions:

1. Which existing modules own safe path resolution, policy decisions, artifact
   metadata, and response redaction?
2. Which traversal, symlink, authorization, and secret-bearing cases could
   cross a trust boundary?
3. Which positive, negative, and race-oriented tests are required before an
   implementation is reviewable?
4. Which existing contract should own the change without introducing a second
   artifact-path abstraction?

This is analysis-only. The explorer, security, tests, and maintainability roles
must not modify the repository. The synthesizer must cite each retained child
artifact and preserve any failed or missing child evidence. Implementation is a
separate guarded workflow.
