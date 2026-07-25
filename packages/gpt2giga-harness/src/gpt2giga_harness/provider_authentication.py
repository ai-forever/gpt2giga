"""Reviewed provider-owned authentication capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from typing import Any, Mapping

from gpt2giga_harness.cli_capabilities import CLI_PROBE_CONTRACTS
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot

PROVIDER_AUTH_SCHEMA_VERSION = 1
PROVIDER_AUTH_EVIDENCE_PATH = "evidence/provider_authentication/v1/matrix.json"
PROVIDER_AUTH_SOURCE = "reviewed_provider_authentication_evidence_v1"
_PROVIDER_IDS = ("codex-cli", "claude-code", "gemini-cli")
_PROVIDER_KEYS = {
    "credential_owner",
    "display_name",
    "flows",
    "harness_id",
    "headless_limitations",
    "pinned_cli_version",
    "projection",
    "recovery",
    "sources",
    "storage_location_classes",
    "surfaces",
    "terms_reviewed_at",
    "timeout",
    "cancellation",
    "version_window",
}
_SURFACE_KEYS = {"start", "status", "logout", "revoke"}
_PROJECTION_KEYS = {"identity", "status", "expiry", "scopes"}


class ProviderAuthenticationEvidenceError(ValueError):
    """Raised when retained authentication evidence is missing or malformed."""


@dataclass(frozen=True)
class ProviderAuthenticationEvidence:
    """Strict source-bound matrix with a semantic digest."""

    reviewed_at: str
    providers: tuple[Mapping[str, Any], ...]
    evidence_hash: str


def load_provider_authentication_evidence() -> ProviderAuthenticationEvidence:
    """Load the packaged G3-00 evidence without reading native provider state."""
    resource = files("gpt2giga_harness").joinpath(PROVIDER_AUTH_EVIDENCE_PATH)
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ProviderAuthenticationEvidenceError(
            "Provider authentication evidence is unavailable"
        ) from exc
    return parse_provider_authentication_evidence(payload)


def parse_provider_authentication_evidence(
    payload: Mapping[str, Any],
) -> ProviderAuthenticationEvidence:
    """Parse one exact schema and reject incomplete or forward-drifted claims."""
    if not isinstance(payload, Mapping):
        raise ProviderAuthenticationEvidenceError("Evidence must be an object")
    if set(payload) != {"schema_version", "reviewed_at", "providers"}:
        raise ProviderAuthenticationEvidenceError("Evidence fields are invalid")
    if payload.get("schema_version") != PROVIDER_AUTH_SCHEMA_VERSION:
        raise ProviderAuthenticationEvidenceError("Evidence schema is unsupported")
    reviewed_at = _required_text(payload.get("reviewed_at"), "reviewed_at")
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, list) or len(raw_providers) != len(_PROVIDER_IDS):
        raise ProviderAuthenticationEvidenceError("Provider evidence is incomplete")

    providers = tuple(_parse_provider(item) for item in raw_providers)
    if tuple(item["harness_id"] for item in providers) != _PROVIDER_IDS:
        raise ProviderAuthenticationEvidenceError(
            "Provider evidence order or identity is invalid"
        )
    canonical = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return ProviderAuthenticationEvidence(
        reviewed_at=reviewed_at,
        providers=providers,
        evidence_hash=hashlib.sha256(canonical).hexdigest(),
    )


def build_provider_authentication_capability_matrix(
    cli_snapshots: Mapping[str, CliCapabilitySnapshot] | None = None,
    *,
    evidence: ProviderAuthenticationEvidence | None = None,
) -> dict[str, Any]:
    """Build the G3-00 matrix without starting, reading, or mutating login state."""
    evidence = evidence or load_provider_authentication_evidence()
    snapshots = cli_snapshots or {}
    providers = []
    for contract in evidence.providers:
        harness_id = str(contract["harness_id"])
        providers.append(
            {
                **dict(contract),
                "runtime_evidence": _runtime_evidence(
                    contract,
                    snapshots.get(harness_id),
                ),
                "broker_status": "not_implemented",
                "live_login_authorized": False,
            }
        )
    return {
        "schema_version": PROVIDER_AUTH_SCHEMA_VERSION,
        "generated_from": PROVIDER_AUTH_SOURCE,
        "reviewed_at": evidence.reviewed_at,
        "evidence_hash": evidence.evidence_hash,
        "providers": providers,
    }


def render_provider_authentication_capability_matrix_markdown(
    matrix: Mapping[str, Any],
) -> str:
    """Render the reviewed matrix as a stable public architecture document."""
    providers = list(matrix.get("providers", ()))
    lines = [
        "# Provider-owned authentication capability matrix",
        "",
        (
            "Status: accepted for GigaLoom roadmap slice G3-00 on "
            f"{matrix.get('reviewed_at', 'unknown')}."
        ),
        "",
        (
            "> Generated from packaged schema-v1 primary-source evidence. "
            "It describes provider-owned surfaces; it does not authorize a login, "
            "credential read, browser launch, or G3-01 broker."
        ),
        "",
        "## Frozen matrix",
        "",
        (
            "| Provider | Pinned CLI | Start | Status | Logout | Revoke | "
            "Headless boundary |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for provider in providers:
        surfaces = provider["surfaces"]
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown(provider["display_name"]),
                    f"`{_markdown(provider['pinned_cli_version'])}`",
                    _markdown("; ".join(surfaces["start"])),
                    _markdown("; ".join(surfaces["status"])),
                    _markdown("; ".join(surfaces["logout"])),
                    _markdown("; ".join(surfaces["revoke"])),
                    _markdown("; ".join(provider["headless_limitations"])),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Safety contract",
            "",
            "- The provider CLI or selected cloud provider owns credentials, refresh, "
            "logout, and revocation.",
            "- An installed executable or compatible `--help` surface never proves "
            "that an account is ready.",
            "- GigaLoom may retain capability evidence, status class, source, and "
            "recovery guidance; it must not retain tokens, raw credential files, "
            "browser callbacks, or unredacted command output.",
            "- Version drift is fail-closed. G3-01 must re-review the exact CLI "
            "version before enabling a broker path.",
            "- Gemini CLI OAuth may not be harvested or piggybacked by third-party "
            "software. Only provider-owned interactive guidance or separately "
            "supported API-key/Vertex paths are admissible.",
            "",
            "## Provider detail",
            "",
        ]
    )
    for provider in providers:
        lines.extend(
            [
                f"### {_markdown(provider['display_name'])}",
                "",
                f"- Credential owner: `{_markdown(provider['credential_owner'])}`.",
                "- Storage classes: "
                + ", ".join(
                    f"`{_markdown(value)}`"
                    for value in provider["storage_location_classes"]
                )
                + ".",
                "- Flows: "
                + ", ".join(f"`{_markdown(value)}`" for value in provider["flows"])
                + ".",
                f"- Identity projection: {_markdown(provider['projection']['identity'])}.",
                f"- Status projection: {_markdown(provider['projection']['status'])}.",
                f"- Expiry projection: {_markdown(provider['projection']['expiry'])}.",
                f"- Scope projection: {_markdown(provider['projection']['scopes'])}.",
                f"- Cancellation: {_markdown(provider['cancellation'])}.",
                f"- Timeout: {_markdown(provider['timeout'])}.",
                "- Recovery: "
                + "; ".join(_markdown(value) for value in provider["recovery"])
                + ".",
                f"- Terms review date: `{_markdown(provider['terms_reviewed_at'])}`.",
                "- Primary sources: "
                + ", ".join(
                    f"[{_markdown(source['id'])}]({source['url']})"
                    for source in provider["sources"]
                )
                + ".",
                "",
            ]
        )
    lines.extend(
        [
            "## Consequences",
            "",
            "G3-01 may consume this matrix to design a bounded native login broker. "
            "That later slice still requires isolated homes, bounded subprocesses, "
            "typed status, cancellation and recovery tests. This slice does not "
            "launch provider commands, authenticate, inspect native homes, or bind "
            "accounts to sessions.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_provider(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROVIDER_KEYS:
        raise ProviderAuthenticationEvidenceError("Provider fields are invalid")
    provider = dict(value)
    harness_id = _required_text(provider.get("harness_id"), "harness_id")
    if harness_id not in _PROVIDER_IDS:
        raise ProviderAuthenticationEvidenceError("Provider identity is invalid")
    contract = CLI_PROBE_CONTRACTS[harness_id]
    version_window = _string_mapping(
        provider.get("version_window"),
        {"minimum", "maximum_exclusive"},
        "version_window",
    )
    if version_window != {
        "minimum": contract.minimum_version,
        "maximum_exclusive": contract.maximum_version_exclusive,
    }:
        raise ProviderAuthenticationEvidenceError(
            "Provider version window does not match the CLI contract"
        )
    provider["version_window"] = version_window
    provider["surfaces"] = _string_list_mapping(
        provider.get("surfaces"), _SURFACE_KEYS, "surfaces"
    )
    provider["projection"] = _string_mapping(
        provider.get("projection"), _PROJECTION_KEYS, "projection"
    )
    for field in (
        "display_name",
        "pinned_cli_version",
        "credential_owner",
        "cancellation",
        "timeout",
        "terms_reviewed_at",
    ):
        provider[field] = _required_text(provider.get(field), field)
    for field in (
        "flows",
        "storage_location_classes",
        "headless_limitations",
        "recovery",
    ):
        provider[field] = list(_string_list(provider.get(field), field))
    raw_sources = provider.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ProviderAuthenticationEvidenceError("Provider sources are invalid")
    provider["sources"] = [_parse_source(item) for item in raw_sources]
    return provider


def _parse_source(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"id", "url", "claims"}:
        raise ProviderAuthenticationEvidenceError("Provider source is invalid")
    url = _required_text(value.get("url"), "source.url")
    if not url.startswith("https://"):
        raise ProviderAuthenticationEvidenceError("Provider source URL is invalid")
    return {
        "id": _required_text(value.get("id"), "source.id"),
        "url": url,
        "claims": list(_string_list(value.get("claims"), "source.claims")),
    }


def _runtime_evidence(
    contract: Mapping[str, Any],
    snapshot: CliCapabilitySnapshot | None,
) -> Mapping[str, Any]:
    if snapshot is None:
        return {"status": "not_probed", "reason": "no hermetic CLI evidence supplied"}
    if snapshot.harness_id != contract["harness_id"] or not snapshot.compatible:
        return {"status": "blocked", "reason": "CLI capability contract is unproven"}
    if snapshot.parsed_version != contract["pinned_cli_version"]:
        return {
            "status": "blocked",
            "reason": "installed CLI version is outside the exact reviewed pin",
        }
    return {
        "status": "reviewed_pin_present",
        "reason": "bounded version and help evidence matches the reviewed pin",
    }


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderAuthenticationEvidenceError(f"{field_name} must be text")
    return value.strip()


def _string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ProviderAuthenticationEvidenceError(f"{field_name} must be a list")
    return tuple(_required_text(item, field_name) for item in value)


def _string_mapping(
    value: Any,
    expected_keys: set[str],
    field_name: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ProviderAuthenticationEvidenceError(f"{field_name} is invalid")
    return {
        key: _required_text(value.get(key), f"{field_name}.{key}")
        for key in sorted(expected_keys)
    }


def _string_list_mapping(
    value: Any,
    expected_keys: set[str],
    field_name: str,
) -> dict[str, list[str]]:
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ProviderAuthenticationEvidenceError(f"{field_name} is invalid")
    return {
        key: list(_string_list(value.get(key), f"{field_name}.{key}"))
        for key in sorted(expected_keys)
    }


def _markdown(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
