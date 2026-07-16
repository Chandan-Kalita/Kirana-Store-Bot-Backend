import asyncio
import unittest
from decimal import Decimal

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.tools.bills import finalize_confirmed_bill
from app.services.helper.db import engine
from app.services.helper.models import Bill, BillItem, Product, StockMovement

# negative range -- Telegram chat ids are never negative, keeps these
# unmistakably test rows if a cleanup step ever fails partway
CHAT_ID_SEQUENTIAL = -900011
CHAT_ID_CONCURRENT = -900012


class IdempotentFinalizeTests(unittest.IsolatedAsyncioTestCase):
    """A retried Confirm -- whether Telegram redelivering the update or the
    owner double-tapping the button -- must never double-decrement stock.
    finalize_confirmed_bill's idempotency comes from the draft->finalized
    status flip under a row lock, not a separate idempotency key; both
    variants here exercise that directly."""

    async def asyncSetUp(self):
        async with AsyncSession(engine) as setup_session:
            product = Product(
                sku="TEST-IDEMPOTENCY-SKU",
                name="Test Idempotency Product",
                unit="piece",
                is_loose=False,
                cost_price=Decimal("10.00"),
                mrp=Decimal("20.00"),
                gst_slab=Decimal("0"),
                hsn_code="0000",
                qty_on_hand=Decimal("10"),
                reorder_level=Decimal("2"),
            )
            setup_session.add(product)
            await setup_session.flush()
            self.product_id = product.id

            for chat_id in (CHAT_ID_SEQUENTIAL, CHAT_ID_CONCURRENT):
                bill = Bill(
                    chat_id=chat_id, status="draft", payment_mode="cash"
                )
                setup_session.add(bill)
                await setup_session.flush()
                setup_session.add(
                    BillItem(
                        bill_id=bill.id,
                        product_id=self.product_id,
                        qty=Decimal("3"),
                        unit_price_at_sale=product.mrp,
                        gst_slab_at_sale=product.gst_slab,
                    )
                )
            await setup_session.commit()

    async def asyncTearDown(self):
        async with AsyncSession(engine) as db:
            chat_ids = [CHAT_ID_SEQUENTIAL, CHAT_ID_CONCURRENT]
            bills = (
                await db.exec(select(Bill).where(Bill.chat_id.in_(chat_ids)))
            ).all()
            for bill in bills:
                items = (
                    await db.exec(
                        select(BillItem).where(BillItem.bill_id == bill.id)
                    )
                ).all()
                for item in items:
                    await db.delete(item)
                movements = (
                    await db.exec(
                        select(StockMovement).where(
                            StockMovement.reference_id == bill.id
                        )
                    )
                ).all()
                for movement in movements:
                    await db.delete(movement)
            await db.flush()
            for bill in bills:
                await db.delete(bill)
            await db.flush()

            product = await db.get(Product, self.product_id)
            if product is not None:
                await db.delete(product)
            await db.commit()

        # IsolatedAsyncioTestCase gives each test method its own event
        # loop, but `engine`'s connection pool is a process-wide singleton
        # -- without disposing it here, the next test's asyncSetUp can be
        # handed a connection opened under this (now-closed) loop and fail
        # with "attached to a different loop"
        await engine.dispose()

    async def test_sequential_retry_reports_already_finalized(self):
        async with AsyncSession(engine) as db:
            first = await finalize_confirmed_bill(db, CHAT_ID_SEQUENTIAL)
            await db.commit()

        async with AsyncSession(engine) as db:
            second = await finalize_confirmed_bill(db, CHAT_ID_SEQUENTIAL)
            await db.commit()

        self.assertTrue(first["ok"])
        self.assertNotIn("already_finalized", first)
        self.assertTrue(second["ok"])
        self.assertTrue(second.get("already_finalized"))
        self.assertEqual(second["bill_id"], first["bill_id"])

        async with AsyncSession(engine) as db:
            product = await db.get(Product, self.product_id)
            # one deduction of 3 from 10 -- the retry must not have moved
            # stock again
            self.assertEqual(product.qty_on_hand, Decimal("7"))

    async def test_concurrent_double_tap_only_finalizes_once(self):
        # simulates two near-simultaneous Cloud Tasks for the same Confirm
        # tap -- both calls target the same chat_id/draft at once
        async def finalize() -> dict:
            async with AsyncSession(engine) as db:
                outcome = await finalize_confirmed_bill(db, CHAT_ID_CONCURRENT)
                await db.commit()
                return outcome

        results = await asyncio.gather(finalize(), finalize())

        successes = [r for r in results if r["ok"] and not r.get("already_finalized")]
        already_finalized = [r for r in results if r.get("already_finalized")]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(already_finalized), 1, results)

        async with AsyncSession(engine) as db:
            product = await db.get(Product, self.product_id)
            # one deduction of 3 from 10 -- never decremented twice
            self.assertEqual(product.qty_on_hand, Decimal("7"))


if __name__ == "__main__":
    unittest.main()
