import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.core.analytics import compute_reorder_suggestions
from app.services.helper.db import engine
from app.services.helper.models import Product, StockMovement

# negative range -- unmistakably test rows if cleanup fails partway
SKU_FAST_SELLER = "TEST-ANALYTICS-FAST"
SKU_MEDIUM_SELLER = "TEST-ANALYTICS-MEDIUM"
SKU_SLOW_SELLER = "TEST-ANALYTICS-SLOW"
SKU_NO_SALES = "TEST-ANALYTICS-NONE"
SKU_STALE_SALES = "TEST-ANALYTICS-STALE"


def _product(sku: str, name: str, qty_on_hand: Decimal) -> Product:
    return Product(
        sku=sku,
        name=name,
        unit="piece",
        is_loose=False,
        cost_price=Decimal("10.00"),
        mrp=Decimal("20.00"),
        gst_slab=Decimal("0"),
        hsn_code="0000",
        qty_on_hand=qty_on_hand,
        reorder_level=Decimal("2"),
    )


class ComputeReorderSuggestionsTests(unittest.IsolatedAsyncioTestCase):
    """compute_reorder_suggestions is a formula (velocity -> days_remaining
    -> suggested_reorder_qty) same as calc_line_gst -- these hand-compute
    the expected numbers rather than only exercising it via the Telegram
    tool layer."""

    async def asyncSetUp(self):
        now = datetime.now(timezone.utc)
        stale = now - timedelta(days=30)

        async with AsyncSession(engine) as db:
            # fast seller: 28 units sold over 14 days -> velocity 2/day,
            # qty_on_hand 10 -> days_remaining 5 (<= alert_days 7),
            # suggested_reorder_qty = 2*14 - 10 = 18
            fast = _product(SKU_FAST_SELLER, "Fast Seller", Decimal("10"))
            # medium seller: 6 units sold over 14 days -> velocity 3/7 per
            # day, qty_on_hand 6 -> days_remaining 14 -- slower than "fast"
            # but still used to check sort ordering between two qualifiers
            medium = _product(SKU_MEDIUM_SELLER, "Medium Seller", Decimal("6"))
            # slow seller: 7 units sold over 14 days -> velocity 0.5/day,
            # qty_on_hand 100 -> days_remaining 200 (> alert_days 7), excluded
            slow = _product(SKU_SLOW_SELLER, "Slow Seller", Decimal("100"))
            # never sold -- no velocity signal, excluded regardless of stock
            no_sales = _product(SKU_NO_SALES, "Never Sold", Decimal("1"))
            # all sales happened outside the lookback window -- must not
            # count towards velocity, so excluded despite low stock
            stale_sales = _product(SKU_STALE_SALES, "Stale Sales", Decimal("1"))

            for p in (fast, medium, slow, no_sales, stale_sales):
                db.add(p)
            await db.flush()
            self.product_ids = {
                "fast": fast.id,
                "medium": medium.id,
                "slow": slow.id,
                "no_sales": no_sales.id,
                "stale": stale_sales.id,
            }

            for qty in (Decimal("-10"), Decimal("-10"), Decimal("-8")):
                db.add(
                    StockMovement(
                        product_id=fast.id,
                        delta_qty=qty,
                        reason="sale",
                        created_at=now,
                    )
                )
            db.add(
                StockMovement(
                    product_id=medium.id,
                    delta_qty=Decimal("-6"),
                    reason="sale",
                    created_at=now,
                )
            )
            db.add(
                StockMovement(
                    product_id=slow.id,
                    delta_qty=Decimal("-7"),
                    reason="sale",
                    created_at=now,
                )
            )
            db.add(
                StockMovement(
                    product_id=stale_sales.id,
                    delta_qty=Decimal("-50"),
                    reason="sale",
                    created_at=stale,
                )
            )
            # a receive on the fast seller must not be counted as a sale
            db.add(
                StockMovement(
                    product_id=fast.id,
                    delta_qty=Decimal("100"),
                    reason="receive",
                    created_at=now,
                )
            )
            await db.commit()

    async def asyncTearDown(self):
        async with AsyncSession(engine) as db:
            ids = list(self.product_ids.values())
            movements = (
                await db.exec(
                    select(StockMovement).where(StockMovement.product_id.in_(ids))
                )
            ).all()
            for m in movements:
                await db.delete(m)
            await db.flush()

            products = (
                await db.exec(select(Product).where(Product.id.in_(ids)))
            ).all()
            for p in products:
                await db.delete(p)
            await db.commit()

        await engine.dispose()

    async def test_fast_seller_flagged_with_hand_computed_numbers(self):
        async with AsyncSession(engine) as db:
            suggestions = await compute_reorder_suggestions(
                db, lookback_days=14, alert_days=7, target_days=14
            )

        by_sku = {s["sku"]: s for s in suggestions}
        self.assertIn(SKU_FAST_SELLER, by_sku)
        fast = by_sku[SKU_FAST_SELLER]
        self.assertEqual(fast["daily_velocity"], Decimal("2"))
        self.assertEqual(fast["days_remaining"], Decimal("5"))
        self.assertEqual(fast["suggested_reorder_qty"], Decimal("18"))

    async def test_medium_seller_hand_computed_numbers(self):
        async with AsyncSession(engine) as db:
            suggestions = await compute_reorder_suggestions(
                db, lookback_days=14, alert_days=100, target_days=14
            )

        by_sku = {s["sku"]: s for s in suggestions}
        self.assertIn(SKU_MEDIUM_SELLER, by_sku)
        medium = by_sku[SKU_MEDIUM_SELLER]
        self.assertEqual(medium["daily_velocity"], Decimal("6") / Decimal("14"))
        self.assertEqual(medium["days_remaining"], Decimal("14"))
        self.assertEqual(medium["suggested_reorder_qty"], Decimal("0"))

    async def test_slow_seller_excluded_when_runway_exceeds_alert_days(self):
        async with AsyncSession(engine) as db:
            suggestions = await compute_reorder_suggestions(
                db, lookback_days=14, alert_days=7, target_days=14
            )

        skus = {s["sku"] for s in suggestions}
        self.assertNotIn(SKU_SLOW_SELLER, skus)

    async def test_no_sales_excluded_regardless_of_low_stock(self):
        async with AsyncSession(engine) as db:
            suggestions = await compute_reorder_suggestions(
                db, lookback_days=14, alert_days=7, target_days=14
            )

        skus = {s["sku"] for s in suggestions}
        self.assertNotIn(SKU_NO_SALES, skus)

    async def test_sales_outside_lookback_window_are_ignored(self):
        async with AsyncSession(engine) as db:
            suggestions = await compute_reorder_suggestions(
                db, lookback_days=14, alert_days=7, target_days=14
            )

        skus = {s["sku"] for s in suggestions}
        self.assertNotIn(SKU_STALE_SALES, skus)

    async def test_sorted_soonest_to_run_out_first(self):
        # the dev DB has its own seeded products/sales alongside these test
        # rows, so filter down to ours before asserting relative order --
        # other real products qualifying too is expected, not a failure
        async with AsyncSession(engine) as db:
            suggestions = await compute_reorder_suggestions(
                db, lookback_days=14, alert_days=100, target_days=14
            )

        our_skus = {SKU_FAST_SELLER, SKU_MEDIUM_SELLER}
        skus_in_order = [s["sku"] for s in suggestions if s["sku"] in our_skus]
        self.assertEqual(skus_in_order, [SKU_FAST_SELLER, SKU_MEDIUM_SELLER])


if __name__ == "__main__":
    unittest.main()
