"""One-off dev utility: wipes existing product/khata/bill data (all test
leftover, not real) and reseeds ~6 months of backdated, internally
consistent data -- products, customers+khata history, and finalized bills
with proper GST math and stock movements. Not part of the deployed app.

Run: .venv/bin/python scripts/seed_backdated_data.py
"""

import asyncio
import random
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.core.analytics import STORE_TZ
from app.services.core.gst import calc_line_gst
from app.services.helper.db import engine
from app.services.helper.models import (
    Bill,
    BillItem,
    Customer,
    KhataEntry,
    Product,
    StockMovement,
)

random.seed(20260716)

WINDOW_DAYS = 180
CHAT_IDS = [1111111111, 2222222222]

PRODUCTS = [
    # sku, name, unit, is_loose, cost, mrp, gst, hsn, reorder_level, initial_qty
    ("ASH-ATTA-5KG", "Aashirvaad Atta 5kg", "packet", False, "210.00", "250.00", "5", "1101", "10", "200"),
    ("TATA-SALT-1KG", "Tata Salt 1kg", "packet", False, "18.00", "24.00", "5", "2501", "20", "300"),
    ("AMUL-BUTTER-100G", "Amul Butter 100g", "packet", False, "48.00", "58.00", "12", "0405", "15", "150"),
    ("FORTUNE-OIL-1L", "Fortune Sunflower Oil 1L", "packet", False, "145.00", "165.00", "5", "1512", "10", "150"),
    ("MAGGI-2MIN-70G", "Maggi 2-Minute Noodles 70g", "packet", False, "10.00", "14.00", "12", "1902", "50", "400"),
    ("PARLE-G", "Parle-G Biscuits", "packet", False, "8.00", "10.00", "18", "1905", "40", "120"),
    ("SURF-EXCEL-1KG", "Surf Excel 1kg", "packet", False, "95.00", "115.00", "18", "3402", "15", "100"),
    ("SUGAR-LOOSE", "Sugar (Loose)", "kg", True, "38.00", "45.00", "0", "1701", "20", "150"),
    ("RICE-LOOSE", "Rice (Loose)", "kg", True, "42.00", "52.00", "0", "1006", "20", "150"),
    ("DAL-LOOSE", "Toor Dal (Loose)", "kg", True, "95.00", "115.00", "0", "0713", "15", "100"),
]

CUSTOMERS = ["Ramesh", "Suresh", "Meena", "Ganesh", "Lakshmi"]
PAYMENT_MODES = ["cash"] * 5 + ["upi"] * 3 + ["card"] * 2


def _random_finalized_at(day_offset: int) -> datetime:
    """A plausible IST business-hour timestamp `day_offset` days ago, as UTC."""
    day = datetime.now(STORE_TZ).date() - timedelta(days=day_offset)
    local_time = time(hour=random.randint(9, 20), minute=random.randint(0, 59))
    local_dt = datetime.combine(day, local_time, tzinfo=STORE_TZ)
    return local_dt.astimezone(timezone.utc)


def _qty_for(is_loose: bool) -> Decimal:
    if is_loose:
        return Decimal(random.choice(["0.25", "0.5", "1", "1.5", "2", "3"]))
    return Decimal(random.randint(1, 6))


async def wipe_existing(session: AsyncSession) -> None:
    # child tables first to respect FKs
    await session.exec(delete(BillItem))
    await session.exec(delete(StockMovement))
    await session.exec(delete(Bill))
    await session.exec(delete(KhataEntry))
    await session.exec(delete(Customer))
    await session.exec(delete(Product))
    await session.commit()
    print("wiped existing product/khata/bill data")


async def seed_products(session: AsyncSession) -> dict[str, Product]:
    products: dict[str, Product] = {}
    start = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    for sku, name, unit, is_loose, cost, mrp, gst, hsn, reorder, initial_qty in PRODUCTS:
        product = Product(
            sku=sku,
            name=name,
            unit=unit,
            is_loose=is_loose,
            cost_price=Decimal(cost),
            mrp=Decimal(mrp),
            gst_slab=Decimal(gst),
            hsn_code=hsn,
            qty_on_hand=Decimal(initial_qty),
            reorder_level=Decimal(reorder),
            created_at=start,
            updated_at=start,
        )
        session.add(product)
        products[sku] = product
    await session.flush()

    for product in products.values():
        session.add(
            StockMovement(
                product_id=product.id,
                delta_qty=product.qty_on_hand,
                reason="receive",
                created_at=start,
            )
        )
    await session.flush()
    print(f"seeded {len(products)} products")
    return products


async def seed_customers(session: AsyncSession) -> None:
    for name in CUSTOMERS:
        first_seen = random.randint(WINDOW_DAYS - 30, WINDOW_DAYS)
        customer = Customer(name=name, created_at=_random_finalized_at(first_seen))
        session.add(customer)
        await session.flush()

        balance = Decimal("0")
        num_entries = random.randint(3, 8)
        days = sorted(random.sample(range(first_seen), min(first_seen, num_entries)), reverse=True)
        for day_offset in days:
            if balance <= 0 or random.random() < 0.7:
                amount = Decimal(random.randint(100, 800))
                balance += amount
                delta, note = amount, "credit"
            else:
                max_payment = min(balance, Decimal("500"))
                amount = (
                    max_payment
                    if max_payment < 50
                    else Decimal(random.randint(50, int(max_payment)))
                )
                balance -= amount
                delta, note = -amount, "payment"
            session.add(
                KhataEntry(
                    customer_id=customer.id,
                    delta_amount=delta,
                    note=note,
                    created_at=_random_finalized_at(day_offset),
                )
            )
    await session.flush()
    print(f"seeded {len(CUSTOMERS)} customers with khata history")


async def seed_bills(session: AsyncSession, products: dict[str, Product]) -> None:
    running_qty = {sku: p.qty_on_hand for sku, p in products.items()}
    initial_qty = {sku: Decimal(row[9]) for row in PRODUCTS for sku in [row[0]]}
    skus = list(products.keys())

    bill_count = 0
    for day_offset in range(WINDOW_DAYS, -1, -1):
        if random.random() < 0.15:  # skip some days entirely, real shops don't sell every day evenly
            continue
        for _ in range(random.randint(1, 4)):
            finalized_at = _random_finalized_at(day_offset)
            chat_id = random.choice(CHAT_IDS)
            customer_name = random.choice([None, None, *CUSTOMERS])
            payment_mode = random.choice(PAYMENT_MODES)

            line_skus = random.sample(skus, random.randint(1, 3))
            lines = []
            for sku in line_skus:
                product = products[sku]
                qty = _qty_for(product.is_loose)
                if running_qty[sku] - qty < initial_qty[sku] * Decimal("0.1"):
                    # restock before selling below ~10% of initial stock
                    restock_qty = initial_qty[sku]
                    session.add(
                        StockMovement(
                            product_id=product.id,
                            delta_qty=restock_qty,
                            reason="receive",
                            created_at=finalized_at,
                        )
                    )
                    running_qty[sku] += restock_qty
                running_qty[sku] -= qty
                lines.append((product, qty))

            bill = Bill(
                chat_id=chat_id,
                status="finalized",
                customer_name=customer_name,
                payment_mode=payment_mode,
                payment_ref=None,
                created_at=finalized_at,
                finalized_at=finalized_at,
            )
            session.add(bill)
            await session.flush()

            subtotal = cgst_total = sgst_total = total_amount = Decimal("0")
            for product, qty in lines:
                line = calc_line_gst(qty, product.mrp, product.gst_slab)
                subtotal += line.taxable_value
                cgst_total += line.cgst
                sgst_total += line.sgst
                total_amount += line.line_total

                session.add(
                    BillItem(
                        bill_id=bill.id,
                        product_id=product.id,
                        qty=qty,
                        unit_price_at_sale=product.mrp,
                        gst_slab_at_sale=product.gst_slab,
                    )
                )
                session.add(
                    StockMovement(
                        product_id=product.id,
                        delta_qty=-qty,
                        reason="sale",
                        reference_id=bill.id,
                        created_at=finalized_at,
                    )
                )

            bill.subtotal = subtotal
            bill.cgst_total = cgst_total
            bill.sgst_total = sgst_total
            bill.total_amount = total_amount
            session.add(bill)
            bill_count += 1

        if day_offset % 30 == 0:
            await session.flush()

    for sku, product in products.items():
        product.qty_on_hand = running_qty[sku]
        session.add(product)

    await session.flush()
    print(f"seeded {bill_count} finalized bills over the last {WINDOW_DAYS} days")


async def main() -> None:
    async with AsyncSession(engine) as session:
        await wipe_existing(session)
        products = await seed_products(session)
        await seed_customers(session)
        await seed_bills(session, products)
        await session.commit()
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
