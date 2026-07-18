"""Harness registry and plugin discovery."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Iterable

from gpt2giga_harness.executables import ExecutableResolver
from gpt2giga_harness.harnesses import (
    ClaudeCodeHarness,
    CodexCliHarness,
    DirectChatHarness,
    EchoHarness,
    GeminiCliHarness,
)
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.plugins import HarnessValidationReport, validate_harness_spec
from gpt2giga_harness.registries import (
    EntryPointFamily,
    RegistrationOutcome,
    RegistryCollisionError,
    VersionedRegistryKernel,
)
from gpt2giga_harness.types import redact_secrets

ENTRY_POINT_GROUP = "gpt2giga.harnesses"
NEUTRAL_ENTRY_POINT_GROUP = "agent_workbench.harness_adapters.v1"
HARNESS_ADAPTER_ENTRY_POINTS = EntryPointFamily(
    registry_id="harness_adapter",
    api_version=1,
    primary_group=NEUTRAL_ENTRY_POINT_GROUP,
    compatibility_groups=(ENTRY_POINT_GROUP,),
)
MAX_DISCOVERY_ERRORS = 20
MAX_DISCOVERY_ERROR_CHARS = 400
BUILTIN_HARNESSES = (
    DirectChatHarness,
    CodexCliHarness,
    ClaudeCodeHarness,
    GeminiCliHarness,
    EchoHarness,
)


class UnknownHarnessError(KeyError):
    """Raised when a harness id is not registered."""


class HarnessRegistry:
    """Store and discover harness implementations."""

    def __init__(self) -> None:
        self._kernel = VersionedRegistryKernel[BaseHarness](
            HARNESS_ADAPTER_ENTRY_POINTS
        )
        self.validation_reports: dict[str, HarnessValidationReport] = {}
        self.discovery_errors: list[str] = []

    def register(self, harness: BaseHarness) -> None:
        """Register one harness instance."""
        self._register(
            harness,
            identity=_implementation_identity(type(harness)),
            source=f"runtime:{type(harness).__module__}.{type(harness).__qualname__}",
        )

    def _register(
        self,
        harness: BaseHarness,
        *,
        identity: str,
        source: str,
        allow_equivalent_duplicate: bool = False,
    ) -> RegistrationOutcome:
        spec = harness.spec()
        report = validate_harness_spec(spec)
        if not report.harness_id:
            raise ValueError("Harness id is required.")
        outcome = self._kernel.register(
            item_id=report.harness_id,
            item=harness,
            identity=identity,
            source=source,
            allow_equivalent_duplicate=allow_equivalent_duplicate,
        )
        if outcome is RegistrationOutcome.ADDED:
            self.validation_reports[report.harness_id] = report
        return outcome

    def get(self, harness_id: str) -> BaseHarness:
        """Return a registered harness by id."""
        harness = self._kernel.get(harness_id)
        if harness is None:
            raise UnknownHarnessError(harness_id)
        return harness

    def list(self) -> tuple[BaseHarness, ...]:
        """Return registered harnesses in registration order."""
        return self._kernel.values()

    def ids(self) -> tuple[str, ...]:
        """Return registered harness ids."""
        return self._kernel.ids()

    def validation_report(self, harness_id: str) -> HarnessValidationReport | None:
        """Return the last validation report for a registered harness."""
        return self.validation_reports.get(harness_id)

    @classmethod
    def with_builtins(
        cls,
        *,
        executable_resolver: ExecutableResolver | None = None,
    ) -> "HarnessRegistry":
        """Create a registry with built-in harnesses."""
        resolver = executable_resolver or ExecutableResolver.path_only()
        registry = cls()
        registry.register_many(
            (
                DirectChatHarness(),
                CodexCliHarness(executable_resolver=resolver),
                ClaudeCodeHarness(executable_resolver=resolver),
                GeminiCliHarness(executable_resolver=resolver),
                EchoHarness(),
            )
        )
        return registry

    def register_many(self, harnesses: Iterable[BaseHarness]) -> None:
        """Register multiple harness instances."""
        for harness in harnesses:
            self.register(harness)

    def load_entry_points(
        self,
        *,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        """Load third-party harnesses from package entry points."""
        try:
            all_entry_points = entry_points()
        except Exception as exc:  # pragma: no cover - defensive importlib path
            self._record_discovery_error(
                "Harness entry-point discovery failed: "
                f"{type(exc).__name__} (details omitted)."
            )
            return
        for group in HARNESS_ADAPTER_ENTRY_POINTS.groups:
            selected = sorted(
                _select_entry_points(all_entry_points, group),
                key=_entry_point_sort_key,
            )
            for entry_point in selected:
                entry_name = str(getattr(entry_point, "name", "<unnamed>"))
                source = f"entry-point:{group}:{entry_name}"
                try:
                    loaded = entry_point.load()
                    harness = _load_entry_point_harness(
                        loaded,
                        executable_resolver=executable_resolver,
                    )
                    self._register(
                        harness,
                        identity=_entry_point_identity(entry_point, loaded),
                        source=source,
                        allow_equivalent_duplicate=True,
                    )
                except RegistryCollisionError as exc:
                    self._record_discovery_error(
                        "Harness id collision for "
                        f"{exc.item_id!r}: keeping {exc.existing_source}; "
                        f"rejected {exc.incoming_source}."
                    )
                except Exception as exc:  # pragma: no cover - plugin failure path
                    self._record_discovery_error(
                        f"{source}: {type(exc).__name__} (details omitted)."
                    )

    def _record_discovery_error(self, message: str) -> None:
        if len(self.discovery_errors) >= MAX_DISCOVERY_ERRORS:
            return
        safe_message = str(redact_secrets(message))
        self.discovery_errors.append(safe_message[:MAX_DISCOVERY_ERROR_CHARS])


def create_default_registry(
    *,
    include_entry_points: bool = True,
    config_path: str | None = None,
    executable_resolver: ExecutableResolver | None = None,
) -> HarnessRegistry:
    """Create the default registry used by CLI and UI."""
    resolver = executable_resolver or ExecutableResolver.from_user_config(config_path)
    registry = HarnessRegistry.with_builtins(executable_resolver=resolver)
    if include_entry_points:
        registry.load_entry_points(executable_resolver=resolver)
    return registry


def _select_entry_points(all_entry_points, group: str):
    if hasattr(all_entry_points, "select"):
        return all_entry_points.select(group=group)
    return all_entry_points.get(group, ())


def _entry_point_sort_key(entry_point) -> tuple[str, str]:
    return (
        str(getattr(entry_point, "name", "")),
        str(getattr(entry_point, "value", "")),
    )


def _entry_point_identity(entry_point, loaded) -> str:
    value = getattr(entry_point, "value", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _implementation_identity(loaded)


def _implementation_identity(implementation) -> str:
    if isinstance(implementation, BaseHarness):
        implementation = type(implementation)
    module = getattr(implementation, "__module__", type(implementation).__module__)
    qualname = getattr(
        implementation,
        "__qualname__",
        type(implementation).__qualname__,
    )
    return f"{module}:{qualname}"


def _load_entry_point_harness(
    loaded,
    *,
    executable_resolver: ExecutableResolver | None = None,
):
    if isinstance(loaded, BaseHarness):
        return loaded
    if isinstance(loaded, type):
        if loaded in {CodexCliHarness, ClaudeCodeHarness, GeminiCliHarness}:
            harness = loaded(executable_resolver=executable_resolver)
        else:
            harness = loaded()
    elif callable(loaded):
        harness = loaded()
    else:
        raise TypeError("entry point must expose a BaseHarness class or factory")
    if not isinstance(harness, BaseHarness):
        raise TypeError("entry point did not create a BaseHarness instance")
    return harness
