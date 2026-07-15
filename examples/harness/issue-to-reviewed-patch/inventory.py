"""Small fictional inventory rule used by the reviewed-patch example."""


def should_reorder(on_hand: int, reorder_at: int) -> bool:
    """Return whether an item has reached its reorder boundary."""
    return on_hand < reorder_at
