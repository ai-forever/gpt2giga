"""Small inventory reservation domain used by the comparison fixture."""


def reserve_stock(available: int, requested: int) -> int:
    """Return remaining stock after accepting a valid reservation."""
    if available < 0 or requested <= 0:
        raise ValueError("stock and reservation values must be positive")
    if requested >= available:
        raise ValueError("insufficient stock")
    return available - requested
