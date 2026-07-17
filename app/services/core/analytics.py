from datetime import date as date_
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import select

from app.services.helper.models import Bill, BillItem, Product, StockMovement

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


async def compute_reorder_suggestions(
    db, lookback_days: int = 14, alert_days: int = 7, target_days: int = 14
) -> list[dict]:
    """Products projected to run out within alert_days, soonest first.

    Unlike a static reorder_level check (list_low_stock), this estimates
    actual sales pace: total units sold (StockMovement reason="sale") over
    the last lookback_days, divided by the full window length to get a
    daily velocity. That denominator is always lookback_days, even for a
    product that's only had stock/sales for part of the window -- a known,
    deliberate simplification (a new fast-seller's velocity is
    underestimated until it's been selling for the full window) rather than
    solving precisely for how long each product has actually existed.

    days_remaining = qty_on_hand / daily_velocity. suggested_reorder_qty
    tops up to target_days of runway on top of current stock:
    max(0, daily_velocity * target_days - qty_on_hand). Products with no
    sales in the window are skipped entirely -- zero velocity is no signal,
    not "infinite runway".
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    window = Decimal(lookback_days)

    rows = (
        await db.exec(
            select(
                Product.sku,
                Product.name,
                Product.qty_on_hand,
                func.sum(-StockMovement.delta_qty),
            )
            .join(StockMovement, StockMovement.product_id == Product.id)
            .where(
                StockMovement.reason == "sale",
                StockMovement.created_at >= cutoff,
            )
            .group_by(Product.id, Product.sku, Product.name, Product.qty_on_hand)
        )
    ).all()

    suggestions = []
    for sku, name, qty_on_hand, units_sold in rows:
        daily_velocity = units_sold / window
        if daily_velocity <= 0:
            continue
        days_remaining = qty_on_hand / daily_velocity
        if days_remaining > alert_days:
            continue
        suggested_reorder_qty = max(
            Decimal("0"), daily_velocity * target_days - qty_on_hand
        )
        suggestions.append(
            {
                "sku": sku,
                "name": name,
                "qty_on_hand": qty_on_hand,
                "daily_velocity": daily_velocity,
                "days_remaining": days_remaining,
                "suggested_reorder_qty": suggested_reorder_qty,
            }
        )

    suggestions.sort(key=lambda s: s["days_remaining"])
    return suggestions
