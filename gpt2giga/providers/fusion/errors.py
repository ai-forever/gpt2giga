"""Fusion provider exceptions."""


class FusionError(Exception):
    """Base class for Fusion provider errors."""


class FusionConfigurationError(FusionError, ValueError):
    """Raised when a Fusion request or preset is invalid."""


class FusionExecutionError(FusionError):
    """Raised when Fusion execution cannot produce a useful result."""
