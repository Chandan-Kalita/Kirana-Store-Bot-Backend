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

    def test_line_always_balances_even_when_cgst_sgst_split_unevenly(self):
        # 3 x 10.00 @ 12% -> taxable 26.79, gst_amount 3.21, which doesn't
        # split evenly in half (1.605/1.605) -- cgst and sgst must differ
        # by a paisa here, not both round the same way, or the line stops
        # summing to line_total. Regression case for a bill seen in
        # production where subtotal+cgst+sgst came out to 30.01 against a
        # 30.00 total.
        result = calc_line_gst(Decimal("3"), Decimal("10.00"), Decimal("12"))
        self.assertEqual(result.taxable_value, Decimal("26.79"))
        self.assertEqual(result.cgst, Decimal("1.61"))
        self.assertEqual(result.sgst, Decimal("1.60"))
        self.assertEqual(result.line_total, Decimal("30.00"))
        self.assertEqual(
            result.taxable_value + result.cgst + result.sgst, result.line_total
        )

    def test_lines_always_balance_across_a_range_of_inputs(self):
        for qty in (Decimal("1"), Decimal("0.25"), Decimal("3"), Decimal("4")):
            for price in (Decimal("10.00"), Decimal("12.00"), Decimal("118.00")):
                for slab in (Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18")):
                    result = calc_line_gst(qty, price, slab)
                    with self.subTest(qty=qty, price=price, slab=slab):
                        self.assertEqual(
                            result.taxable_value + result.cgst + result.sgst,
                            result.line_total,
                        )


if __name__ == "__main__":
    unittest.main()
