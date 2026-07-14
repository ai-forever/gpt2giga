"""Validation helpers for third-party harness plugins."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from gpt2giga_harness.types import (
    HarnessCapability,
    HarnessSpec,
    spec_capability_values,
)


_HARNESS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SIMPLE_SCHEMA_TYPES = {"string", "integer", "number", "boolean", "array"}


@dataclass(frozen=True)
class HarnessValidationIssue:
    """One validation finding for a harness plugin."""

    level: str
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class HarnessValidationReport:
    """Validation report for one registered harness."""

    harness_id: str | None
    ok: bool
    issues: tuple[HarnessValidationIssue, ...]


def validate_harness_spec(spec: HarnessSpec) -> HarnessValidationReport:
    """Validate harness metadata for CLI/UI marketplace readiness."""
    issues: list[HarnessValidationIssue] = []
    harness_id = _optional_text(getattr(spec, "id", None))
    if not harness_id:
        issues.append(
            _issue(
                "error",
                "missing_id",
                "Harness id is required.",
                "id",
            )
        )
    elif _HARNESS_ID_RE.fullmatch(harness_id) is None:
        issues.append(
            _issue(
                "error",
                "invalid_id",
                "Harness id must use lowercase letters, numbers, '.', '_' or '-'.",
                "id",
            )
        )
    for field_name in ("title", "kind", "description"):
        if not _optional_text(getattr(spec, field_name, None)):
            issues.append(
                _issue(
                    "error",
                    f"missing_{field_name}",
                    f"Harness {field_name} is required.",
                    field_name,
                )
            )
    raw_capabilities = tuple(getattr(spec, "capabilities", ()) or ())
    known_capabilities = spec_capability_values(spec)
    if not known_capabilities:
        issues.append(
            _issue(
                "error",
                "no_known_capabilities",
                "At least one known harness capability is required.",
                "capabilities",
            )
        )
    for index, capability in enumerate(raw_capabilities):
        if _known_capability(capability) is None:
            issues.append(
                _issue(
                    "warning",
                    "unknown_capability",
                    f"Unknown capability is ignored by registry/UI: {capability}",
                    f"capabilities[{index}]",
                )
            )
    issues.extend(_validate_mapping_field(spec, "config_schema"))
    issues.extend(_validate_mapping_field(spec, "metadata"))
    issues.extend(_validate_mapping_field(spec, "adapter_capabilities"))
    issues.extend(_validate_mapping_field(spec, "attachment_capabilities"))
    issues.extend(_validate_config_schema(getattr(spec, "config_schema", {})))
    ok = not any(issue.level == "error" for issue in issues)
    return HarnessValidationReport(
        harness_id=harness_id,
        ok=ok,
        issues=tuple(issues),
    )


def harness_validation_report_to_dict(
    report: HarnessValidationReport,
) -> dict[str, Any]:
    """Serialize a validation report for CLI/API responses."""
    return {
        "harness_id": report.harness_id,
        "ok": report.ok,
        "issues": [
            {
                "level": issue.level,
                "code": issue.code,
                "message": issue.message,
                "field": issue.field,
            }
            for issue in report.issues
        ],
    }


def _validate_mapping_field(
    spec: HarnessSpec,
    field_name: str,
) -> tuple[HarnessValidationIssue, ...]:
    value = getattr(spec, field_name, {})
    if value is None or isinstance(value, Mapping):
        return ()
    return (
        _issue(
            "error",
            f"invalid_{field_name}",
            f"Harness {field_name} must be a mapping.",
            field_name,
        ),
    )


def _validate_config_schema(value: Any) -> tuple[HarnessValidationIssue, ...]:
    if not isinstance(value, Mapping) or not value:
        return ()
    issues: list[HarnessValidationIssue] = []
    schema_type = value.get("type")
    if schema_type not in (None, "object"):
        issues.append(
            _issue(
                "warning",
                "non_object_config_schema",
                "Only object config schemas can be rendered by the simple UI form.",
                "config_schema.type",
            )
        )
    properties = value.get("properties")
    if properties is None:
        return tuple(issues)
    if not isinstance(properties, Mapping):
        issues.append(
            _issue(
                "error",
                "invalid_config_properties",
                "config_schema.properties must be a mapping.",
                "config_schema.properties",
            )
        )
        return tuple(issues)
    for name, schema in properties.items():
        field = f"config_schema.properties.{name}"
        if not isinstance(schema, Mapping):
            issues.append(
                _issue(
                    "warning",
                    "ignored_config_property",
                    "Simple config form ignores non-object property schemas.",
                    field,
                )
            )
            continue
        property_type = schema.get("type", "string")
        if property_type not in _SIMPLE_SCHEMA_TYPES:
            issues.append(
                _issue(
                    "warning",
                    "unsupported_config_property_type",
                    f"Simple config form ignores unsupported type: {property_type}",
                    f"{field}.type",
                )
            )
    return tuple(issues)


def _known_capability(value: Any) -> str | None:
    if isinstance(value, HarnessCapability):
        return value.value
    if isinstance(value, str):
        try:
            return HarnessCapability(value).value
        except ValueError:
            return None
    return None


def _issue(
    level: str,
    code: str,
    message: str,
    field: str | None,
) -> HarnessValidationIssue:
    return HarnessValidationIssue(
        level=level,
        code=code,
        message=message,
        field=field,
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
