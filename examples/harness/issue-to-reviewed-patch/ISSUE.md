# Equality-boundary reorder bug

`inventory.should_reorder()` must return `True` when `on_hand` is equal to
`reorder_at`. The current implementation handles only quantities below the
threshold, so the equality regression in `tests/test_inventory.py` fails.

Make the smallest source change that restores the documented boundary. Run the
focused test suite and retain the exact command and outcome for review. Do not
change the source checkout directly: the implementation must stay in the
Harness-owned worktree until an operator reviews and explicitly applies it.
