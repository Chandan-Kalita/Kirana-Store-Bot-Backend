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
CHAT_ID_A = -900001
CHAT_ID_B = -900002


class ConcurrentFinalizeTests(unittest.IsolatedAsyncioTestCase):
    """Two different chats racing to finalize bills against the same
    product, with combined demand exceeding stock. Uses two genuinely
    separate AsyncSessions (each gets its own pooled connection) so the
    row-locking inside finalize_confirmed_bill is exercised for real, not
    simulated -- a single shared session isn't safe for concurrent use and
    would defeat the point of this test."""

    async def asyncSetUp(self):
        async with AsyncSession(engine) as setup_session:
            product = Product(
                sku="TEST-CONCURRENCY-SKU",
                name="Test Concurrency Product",
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

            for chat_id in (CHAT_ID_A, CHAT_ID_B):
                bill = Bill(
                    chat_id=chat_id, status="draft", payment_mode="cash"
                )
                setup_session.add(bill)
                await setup_session.flush()
                setup_session.add(
                    BillItem(
                        bill_id=bill.id,
                        product_id=self.product_id,
                        qty=Decimal("6"),
                        unit_price_at_sale=product.mrp,
                        gst_slab_at_sale=product.gst_slab,
                    )
                )
            await setup_session.commit()

    async def asyncTearDown(self):
        async with AsyncSession(engine) as db:
            bills = (
                await db.exec(
                    select(Bill).where(Bill.chat_id.in_([CHAT_ID_A, CHAT_ID_B]))
                )
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
        # -- without disposing it here, a later test's asyncSetUp can be
        # handed a connection opened under this (now-closed) loop and fail
        # with "attached to a different loop"
        await engine.dispose()

    async def test_two_chats_racing_for_insufficient_combined_stock(self):
        # 10 in stock, two draft bills each wanting 6 -> combined demand 12
        # exceeds stock, so exactly one must win
        async def finalize(chat_id: int) -> dict:
            async with AsyncSession(engine) as db:
                outcome = await finalize_confirmed_bill(db, chat_id)
                await db.commit()
                return outcome

        results = await asyncio.gather(
            finalize(CHAT_ID_A), finalize(CHAT_ID_B)
        )

        successes = [r for r in results if r["ok"]]
        failures = [r for r in results if not r["ok"]]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(failures), 1, results)
        self.assertIn("stock", failures[0]["message"].lower())

        async with AsyncSession(engine) as db:
            product = await db.get(Product, self.product_id)
            # exactly one deduction of 6 from 10 -- never negative,
            # never double-counted
            self.assertEqual(product.qty_on_hand, Decimal("4"))


if __name__ == "__main__":
    unittest.main()
