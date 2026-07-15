import unittest

from inventory import should_reorder


class ReorderRuleTests(unittest.TestCase):
    def test_reorders_below_threshold(self) -> None:
        self.assertTrue(should_reorder(2, 3))

    def test_reorders_at_threshold(self) -> None:
        self.assertTrue(should_reorder(3, 3))

    def test_does_not_reorder_above_threshold(self) -> None:
        self.assertFalse(should_reorder(4, 3))


if __name__ == "__main__":
    unittest.main()
