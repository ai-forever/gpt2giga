"""Seed coverage for the inventory fixture."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inventory import reserve_stock  # noqa: E402


class ReserveStockTests(unittest.TestCase):
    """Exercise valid and clearly invalid reservations."""

    def test_reserves_less_than_available_stock(self) -> None:
        self.assertEqual(reserve_stock(5, 2), 3)

    def test_rejects_more_than_available_stock(self) -> None:
        with self.assertRaisesRegex(ValueError, "insufficient stock"):
            reserve_stock(5, 6)

    def test_rejects_non_positive_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            reserve_stock(5, 0)


if __name__ == "__main__":
    unittest.main()
