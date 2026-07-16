from datetime import date as date_
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import select

from app.services.helper.models import Bill, BillItem, Product

_TWO_PLACES = Decimal("0.01")

STORE_TZ = ZoneInfo("Asia/Kolkata")
PAYMENT_MODES = ("cash", "upi", "card")


def resolve_day_bounds(date_str: str | None = None) -> tuple[datetime, datetime, date_]:
    """UTC [start, end) bounds for one IST calendar day, plus the resolved
    date. Defaults to "today" in IST if date_str is None.

    Bill.finalized_at is stored in UTC, but a kirana owner's "today" means
    the IST calendar day, not the UTC one -- naive UTC day boundaries would
    misfile a bill finalized late evening IST (already past midnight UTC)
    into the wrong day. Raises ValueError on a malformed date_str; callers
    turn that into a ModelRetry.
    """
    day = date_.fromisoformat(date_str) if date_str is not None else datetime.now(STORE_TZ).date()
    start_local = datetime.combine(day, time.min, tzinfo=STORE_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), day


async def compute_summary(db, start: datetime, end: datetime, top_n: int = 5) -> dict:
    """Aggregate finalized bills in [start, end) (UTC): totals, GST split,
    payment-mode breakdown, and top items by revenue.

    Range-based rather than "today"-specific -- a future weekly analysis
    deck needs the exact same aggregation over a 7-day window instead of 1
    day, so daily close and the weekly deck can both call this with a
    different window instead of duplicating query logic that could drift
    out of sync between the two.
    """
    filters = (
        Bill.status == "finalized",
        Bill.finalized_at >= start,
        Bill.finalized_at < end,
    )

    total_sales, cgst_total, sgst_total, bill_count = (
        await db.exec(
            select(
                func.coalesce(func.sum(Bill.total_amount), 0),
                func.coalesce(func.sum(Bill.cgst_total), 0),
                func.coalesce(func.sum(Bill.sgst_total), 0),
                func.count(),
            ).where(*filters)
        )
    ).one()

    by_mode = dict(
        (
            await db.exec(
                select(Bill.payment_mode, func.sum(Bill.total_amount))
                .where(*filters)
                .group_by(Bill.payment_mode)
            )
        ).all()
    )
    payment_totals = {mode: by_mode.get(mode, Decimal("0")) for mode in PAYMENT_MODES}

    top_rows = (
        await db.exec(
            select(
                Product.sku,
                Product.name,
                func.sum(BillItem.qty),
                func.sum(BillItem.qty * BillItem.unit_price_at_sale),
            )
            .join(Bill, BillItem.bill_id == Bill.id)
            .join(Product, BillItem.product_id == Product.id)
            .where(*filters)
            .group_by(Product.id, Product.sku, Product.name)
            .order_by(func.sum(BillItem.qty * BillItem.unit_price_at_sale).desc())
            .limit(top_n)
        )
    ).all()

    return {
        "total_sales": total_sales,
        "cgst_total": cgst_total,
        "sgst_total": sgst_total,
        "bill_count": bill_count,
        "payment_totals": payment_totals,
        "top_items": [
            {
                "sku": sku,
                "name": name,
                "qty": qty,
                # qty(3dp) * unit_price(2dp) is 5dp in postgres, round to money precision
                "revenue": revenue.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            }
            for sku, name, qty, revenue in top_rows
        ],
    }


async def compute_daily_breakdown(db, start: datetime, end: datetime) -> list[dict]:
    """Per-IST-day sales totals for finalized bills in [start, end) (UTC),
    for trend charts. One query, grouped in Python by IST calendar day
    (STORE_TZ) rather than N per-day queries or a Postgres AT TIME ZONE
    query -- keeps the one IST-conversion rule in one place, tested once.
    """
    rows = (
        await db.exec(
            select(Bill.finalized_at, Bill.total_amount).where(
                Bill.status == "finalized",
                Bill.finalized_at >= start,
                Bill.finalized_at < end,
            )
        )
    ).all()

    buckets: dict[date_, Decimal] = {}
    for finalized_at, total_amount in rows:
        day = finalized_at.astimezone(STORE_TZ).date()
        buckets[day] = buckets.get(day, Decimal("0")) + total_amount

    return [
        {"date": day.isoformat(), "total_sales": total}
        for day, total in sorted(buckets.items())
    ]
