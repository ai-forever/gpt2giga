# Provider-owned authentication capability matrix

Status: accepted for GigaLoom roadmap slice G3-00 on 2026-07-26.

> Generated from packaged schema-v1 primary-source evidence. It describes provider-owned surfaces; it does not authorize a login, credential read, browser launch, or G3-01 broker.

## Frozen matrix

| Provider | Pinned CLI | Start | Status | Logout | Revoke | Headless boundary |
| --- | --- | --- | --- | --- | --- | --- |
| Codex CLI | `0.144.3` | codex login; app-server account/login/start | app-server account/read; app-server account/updated | codex logout; app-server account/logout | provider account or workspace control | browser login needs an interactive browser callback; device-code login still requires the user to complete provider authentication; API keys and enterprise access tokens are separate trusted-automation paths |
| Claude Code | `2.1.212` | claude auth login; interactive /login | claude auth status; interactive /status | claude auth logout; interactive /logout | provider account, organization, or cloud-provider control | browser login may require copying a URL and pasting a code in SSH, WSL, or containers; cloud-provider and API-key modes are owned outside the subscription browser flow; status precedence must be respected before claiming which credential is active |
| Gemini CLI | `0.46.0` | gemini interactive authentication chooser; interactive /auth | no documented machine-readable account-status command | provider-owned interactive authentication reset only | Google account, API key, or Google Cloud control | Google-account browser login is not supported as a new headless login; headless mode requires an existing cached credential, API key, or Vertex AI credentials; third-party software must not harvest or piggyback on Gemini CLI OAuth |

## Safety contract

- The provider CLI or selected cloud provider owns credentials, refresh, logout, and revocation.
- An installed executable or compatible `--help` surface never proves that an account is ready.
- GigaLoom may retain capability evidence, status class, source, and recovery guidance; it must not retain tokens, raw credential files, browser callbacks, or unredacted command output.
- Version drift is fail-closed. G3-01 must re-review the exact CLI version before enabling a broker path.
- Gemini CLI OAuth may not be harvested or piggybacked by third-party software. Only provider-owned interactive guidance or separately supported API-key/Vertex paths are admissible.

## Provider detail

### Codex CLI

- Credential owner: `codex`.
- Storage classes: `codex_home_secret_file`, `operating_system_credential_store`.
- Flows: `chatgpt_browser`, `chatgpt_device_code`, `api_key`, `enterprise_access_token`.
- Identity projection: provider account label may be shown ephemerally; do not persist it in diagnostics.
- Status projection: auth mode, plan type, requires-auth, and credential-source class.
- Expiry projection: not documented as a stable account field.
- Scope projection: not documented as a stable account field.
- Cancellation: app-server account/login/cancel cancels a pending managed ChatGPT login.
- Timeout: the future broker must impose its own bounded timeout.
- Recovery: retry provider-owned login; use device-code flow when the browser callback is brittle; log out and sign in again after credential or workspace mismatch.
- Terms review date: `2026-07-26`.
- Primary sources: [authentication](https://learn.chatgpt.com/docs/auth), [app_server](https://learn.chatgpt.com/docs/app-server), [terms](https://openai.com/policies/terms-of-use/).

### Claude Code

- Credential owner: `claude_code_or_selected_cloud_provider`.
- Storage classes: `operating_system_credential_store`, `provider_config_home_secret_file`, `environment_or_external_credential_helper`.
- Flows: `claude_ai_browser`, `claude_console_browser`, `cloud_provider_environment`, `api_key_or_helper`.
- Identity projection: provider-reported account and organization label may be shown ephemerally.
- Status projection: machine-readable auth status and active credential-source class.
- Expiry projection: expired state and provider warning may be shown when disclosed.
- Scope projection: do not infer scopes beyond provider-reported status.
- Cancellation: no stable machine cancellation surface is documented for an in-progress auth login.
- Timeout: the future broker must impose its own bounded timeout.
- Recovery: claude auth logout followed by claude auth login; copy the provider URL and paste the returned code for remote terminals; use provider cloud-credential recovery for Bedrock, Vertex, or Foundry.
- Terms review date: `2026-07-26`.
- Primary sources: [authentication](https://code.claude.com/docs/en/authentication), [cli_reference](https://code.claude.com/docs/en/cli-usage), [terms](https://www.anthropic.com/legal/consumer-terms).

### Gemini CLI

- Credential owner: `gemini_cli_or_selected_google_cloud_provider`.
- Storage classes: `gemini_cli_user_state`, `environment_secret`, `google_cloud_application_default_credentials`.
- Flows: `google_account_browser`, `gemini_api_key`, `vertex_ai`, `google_cloud_ambient_credentials`.
- Identity projection: unavailable without a documented provider-owned machine surface.
- Status projection: unknown unless the provider CLI reports it through a reviewed surface.
- Expiry projection: not documented as a stable machine field.
- Scope projection: not documented as a stable machine field.
- Cancellation: no documented machine cancellation surface is frozen.
- Timeout: the future broker must impose its own bounded timeout.
- Recovery: return to the provider-owned interactive authentication chooser; configure an API key or Vertex AI credential for headless use; revoke or rotate credentials in the owning Google service.
- Terms review date: `2026-07-26`.
- Primary sources: [authentication](https://geminicli.com/docs/get-started/authentication/), [commands](https://geminicli.com/docs/reference/commands/), [terms](https://geminicli.com/docs/resources/tos-privacy/).

## Consequences

G3-01 may consume this matrix to design a bounded native login broker. That later slice still requires isolated homes, bounded subprocesses, typed status, cancellation and recovery tests. This slice does not launch provider commands, authenticate, inspect native homes, or bind accounts to sessions.
