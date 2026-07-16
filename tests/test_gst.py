import unittest
from decimal import Decimal

from app.services.core.gst import calc_line_gst


class CalcLineGstTests(unittest.TestCase):
    def test_exact_split_at_18_percent(self):
        result = calc_line_gst(Decimal("1"), Decimal("118.00"), Decimal("18"))
        self.assertEqual(result.taxable_value, Decimal("100.00"))
        self.assertEqual(result.cgst, Decimal("9.00"))
        self.assertEqual(result.sgst, Decimal("9.00"))
        self.assertEqual(result.line_total, Decimal("118.00"))

    def test_zero_gst_loose_item(self):
        result = calc_line_gst(Decimal("2.5"), Decimal("40.00"), Decimal("0"))
        self.assertEqual(result.taxable_value, Decimal("100.00"))
        self.assertEqual(result.cgst, Decimal("0.00"))
        self.assertEqual(result.sgst, Decimal("0.00"))
        self.assertEqual(result.line_total, Decimal("100.00"))

    def test_rounds_half_up_per_line(self):
        # 100 / 1.05 = 95.238095... -> 95.24; gst_amount = 4.761904...,
        # half = 2.380952... -> 2.38 each.
        result = calc_line_gst(Decimal("2"), Decimal("50.00"), Decimal("5"))
        self.assertEqual(result.taxable_value, Decimal("95.24"))
        self.assertEqual(result.cgst, Decimal("2.38"))
        self.assertEqual(result.sgst, Decimal("2.38"))
        self.assertEqual(result.line_total, Decimal("100.00"))

    def test_quantities_are_fractional_for_loose_items(self):
        result = calc_line_gst(Decimal("0.25"), Decimal("240.00"), Decimal("5"))
        self.assertEqual(result.line_total, Decimal("60.00"))


if __name__ == "__main__":
    unittest.main()
