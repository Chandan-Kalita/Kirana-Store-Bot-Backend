from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import func
from sqlmodel import select

from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.core.gst import calc_line_gst
from app.services.helper.models import Bill, BillItem, Product, StockMovement

PaymentMode = Literal["cash", "upi", "card"]


async def _load_draft(db, chat_id: int) -> Bill | None:
    return (
        await db.exec(
            select(Bill).where(Bill.chat_id == chat_id, Bill.status == "draft")
        )
    ).first()


async def _load_draft_items_with_products(
    db, bill_id
) -> list[tuple[BillItem, Product]]:
    stmt = (
        select(BillItem, Product)
        .join(Product, BillItem.product_id == Product.id)
        .where(BillItem.bill_id == bill_id)
    )
    return list((await db.exec(stmt)).all())


def _bill_view(bill: Bill, rows: list[tuple[BillItem, Product]]) -> dict:
    items = []
    subtotal = cgst_total = sgst_total = total_amount = Decimal("0")
    for item, product in rows:
        line = calc_line_gst(item.qty, item.unit_price_at_sale, item.gst_slab_at_sale)
        items.append(
            {
                "sku": product.sku,
                "name": product.name,
                "qty": item.qty,
                "unit_price": item.unit_price_at_sale,
                "gst_slab": item.gst_slab_at_sale,
                "taxable_value": line.taxable_value,
                "cgst": line.cgst,
                "sgst": line.sgst,
                "line_total": line.line_total,
            }
        )
        subtotal += line.taxable_value
        cgst_total += line.cgst
        sgst_total += line.sgst
        total_amount += line.line_total

    return {
        "bill_id": str(bill.id),
        "customer_name": bill.customer_name,
        "items": items,
        "subtotal": subtotal,
        "cgst_total": cgst_total,
        "sgst_total": sgst_total,
        "total_amount": total_amount,
    }


@agent.tool(sequential=True)
async def start_bill(
    ctx: RunContext[AgentDeps], customer_name: str | None = None
) -> dict:
    """Start a new draft bill for this chat.

    There can only ever be one draft bill per chat. If one is already in
    progress, this returns its current contents instead of starting a
    second one -- tell the owner what's already on it and ask whether to
    continue it or scrap it with cancel_draft_bill.

    Args:
        customer_name: Optional customer name, for khata/credit linkage.
    """
    existing = await _load_draft(ctx.deps.db, ctx.deps.chat_id)
    if existing is not None:
        rows = await _load_draft_items_with_products(ctx.deps.db, existing.id)
        view = _bill_view(existing, rows)
        view["already_in_progress"] = True
        return view

    bill = Bill(chat_id=ctx.deps.chat_id, customer_name=customer_name)
    ctx.deps.db.add(bill)
    await ctx.deps.db.flush()

    view = _bill_view(bill, [])
    view["already_in_progress"] = False
    return view


@agent.tool(sequential=True)
async def set_item_qty(ctx: RunContext[AgentDeps], sku: str, qty: Decimal) -> dict:
    """Set (or remove) a line item's quantity on the current draft bill.

    Resolves sku against the current draft -- use search_products first if
    the owner only gave a product name. Setting qty to 0 removes the line.
    Sells at the product's current MRP. Performs a soft, non-locking stock
    and below-cost check here purely for early warning; the authoritative
    checks happen when the owner actually confirms via the Confirm button
    (see request_finalize_confirmation).

    Args:
        sku: Exact SKU of the product.
        qty: New quantity for this line, in the product's unit. 0 removes it.
    """
    if qty < 0:
        raise ModelRetry(f"qty must be >= 0, got {qty}. Use 0 to remove a line.")

    bill = await _load_draft(ctx.deps.db, ctx.deps.chat_id)
    if bill is None:
        raise ModelRetry("No draft bill for this chat. Call start_bill first.")

    product = (
        await ctx.deps.db.exec(
            select(Product).where(func.lower(Product.sku) == sku.lower())
        )
    ).first()
    if product is None:
        raise ModelRetry(
            f"No product with SKU '{sku}'. Use search_products to find the "
            "right SKU."
        )

    existing_item = (
        await ctx.deps.db.exec(
            select(BillItem).where(
                BillItem.bill_id == bill.id, BillItem.product_id == product.id
            )
        )
    ).first()

    warnings: list[str] = []
    if qty == 0:
        if existing_item is not None:
            await ctx.deps.db.delete(existing_item)
            await ctx.deps.db.flush()
    else:
        if qty > product.qty_on_hand:
            warnings.append(
                f"Only {product.qty_on_hand} {product.unit} of {product.name} "
                f"in stock (requested {qty})."
            )
        if product.mrp < product.cost_price:
            warnings.append(
                f"{product.name}: selling at {product.mrp} is below cost "
                f"price {product.cost_price}."
            )

        if existing_item is not None:
            existing_item.qty = qty
            existing_item.unit_price_at_sale = product.mrp
            existing_item.gst_slab_at_sale = product.gst_slab
            ctx.deps.db.add(existing_item)
        else:
            ctx.deps.db.add(
                BillItem(
                    bill_id=bill.id,
                    product_id=product.id,
                    qty=qty,
                    unit_price_at_sale=product.mrp,
                    gst_slab_at_sale=product.gst_slab,
                )
            )
        await ctx.deps.db.flush()

    rows = await _load_draft_items_with_products(ctx.deps.db, bill.id)
    view = _bill_view(bill, rows)
    view["warnings"] = warnings
    return view


@agent.tool(sequential=True)
async def view_draft_bill(ctx: RunContext[AgentDeps]) -> dict:
    """Show the current draft bill's line items and computed totals.

    Subtotal/CGST/SGST/total are computed fresh from the line items on
    every call, never stored while drafting -- always reflects the latest
    state.
    """
    bill = await _load_draft(ctx.deps.db, ctx.deps.chat_id)
    if bill is None:
        raise ModelRetry("No draft bill for this chat. Call start_bill first.")
    rows = await _load_draft_items_with_products(ctx.deps.db, bill.id)
    return _bill_view(bill, rows)


MAX_BILL_PAGE_SIZE = 20


@agent.tool(sequential=True)
async def list_past_bills(
    ctx: RunContext[AgentDeps],
    customer_name: str | None = None,
    offset: int = 0,
    limit: int = MAX_BILL_PAGE_SIZE,
) -> dict:
    """List finalized bills for this chat, most recent first.

    Use this for "what did I sell yesterday", "show me Ramesh's past
    bills", "find that bill for X" type requests. Only finalized bills
    show up here -- a bill still being built is a draft, not a past bill
    yet, see view_draft_bill for that.

    Args:
        customer_name: Optional filter, partial case-insensitive match
            against the bill's customer name.
        offset: Number of bills to skip, for paging past the first page.
        limit: Max bills to return, capped at 20 regardless of the value
            passed (each bill includes its full item list).
    """
    if offset < 0:
        raise ModelRetry(f"offset must be >= 0, got {offset}.")
    if limit <= 0:
        raise ModelRetry(f"limit must be positive, got {limit}.")
    limit = min(limit, MAX_BILL_PAGE_SIZE)

    filters = [Bill.chat_id == ctx.deps.chat_id, Bill.status == "finalized"]
    if customer_name:
        filters.append(Bill.customer_name.ilike(f"%{customer_name}%"))

    total = (
        await ctx.deps.db.exec(select(func.count()).select_from(Bill).where(*filters))
    ).one()
    stmt = (
        select(Bill)
        .where(*filters)
        .order_by(Bill.finalized_at.desc())
        .offset(offset)
        .limit(limit)
    )
    bills = (await ctx.deps.db.exec(stmt)).all()

    results = []
    for bill in bills:
        rows = await _load_draft_items_with_products(ctx.deps.db, bill.id)
        results.append(
            {
                "bill_id": str(bill.id),
                "customer_name": bill.customer_name,
                "payment_mode": bill.payment_mode,
                "payment_ref": bill.payment_ref,
                "finalized_at": bill.finalized_at.isoformat()
                if bill.finalized_at
                else None,
                "subtotal": bill.subtotal,
                "cgst_total": bill.cgst_total,
                "sgst_total": bill.sgst_total,
                "total_amount": bill.total_amount,
                "items": [
                    {
                        "sku": product.sku,
                        "name": product.name,
                        "qty": item.qty,
                        "unit_price": item.unit_price_at_sale,
                    }
                    for item, product in rows
                ],
            }
        )

    return {
        "total": total,
        "offset": offset,
        "count": len(results),
        "has_more": offset + len(results) < total,
        "bills": results,
    }


@agent.tool(sequential=True)
async def cancel_draft_bill(ctx: RunContext[AgentDeps]) -> dict:
    """Hard-delete the current draft bill and its line items.

    Safe to fully delete -- a draft hasn't touched stock or created any
    StockMovement rows, so nothing needs to be reversed.
    """
    bill = await _load_draft(ctx.deps.db, ctx.deps.chat_id)
    if bill is None:
        raise ModelRetry("No draft bill for this chat to cancel.")

    items = (
        await ctx.deps.db.exec(select(BillItem).where(BillItem.bill_id == bill.id))
    ).all()
    for item in items:
        await ctx.deps.db.delete(item)
    # flush items before deleting the bill, no relationship() to order this
    # for us and it'll trip the FK otherwise
    await ctx.deps.db.flush()

    await ctx.deps.db.delete(bill)
    await ctx.deps.db.flush()

    return {"cancelled": True, "bill_id": str(bill.id)}


@agent.tool(sequential=True)
async def request_finalize_confirmation(
    ctx: RunContext[AgentDeps],
    payment_mode: PaymentMode,
    payment_ref: str | None = None,
) -> dict:
    """Ask the owner to confirm finalizing the current draft bill.

    Call this once the bill is fully built and the owner has told you how
    they paid (and a reference, if they gave one). This does NOT finalize
    anything by itself -- it stores the payment details on the draft and
    shows the owner Confirm/Cancel buttons; the bill only finalizes if they
    tap Confirm. There is no other way to finalize a bill -- no tool call
    and nothing said in chat can do it, only that button tap.

    After calling this, just state the item list and total in your reply
    (returned here) -- do not also ask "shall I finalize?" in text, the
    buttons already ask that, and don't call this again unless the bill
    actually changed since the last call.

    Args:
        payment_mode: How the owner says they paid -- cash, upi, or card.
        payment_ref: Optional reference (UPI txn id, card auth code, etc)
            if the owner gave one.
    """
    bill = await _load_draft(ctx.deps.db, ctx.deps.chat_id)
    if bill is None:
        raise ModelRetry("No draft bill for this chat. Call start_bill first.")

    rows = await _load_draft_items_with_products(ctx.deps.db, bill.id)
    if not rows:
        raise ModelRetry(
            "Draft bill has no items. Add some with set_item_qty first."
        )

    bill.payment_mode = payment_mode
    bill.payment_ref = payment_ref
    ctx.deps.db.add(bill)
    await ctx.deps.db.flush()

    ctx.deps.pending_confirmation = True

    view = _bill_view(bill, rows)
    view["payment_mode"] = payment_mode
    view["payment_ref"] = payment_ref
    return view


async def finalize_confirmed_bill(db, chat_id: int) -> dict:
    """Deduct stock and freeze totals for the current draft bill.

    Called only from the Confirm-button callback in tasks.py -- not an
    @agent.tool, so the LLM has no way to reach this directly. Reads
    payment_mode/payment_ref off the bill, set earlier by
    request_finalize_confirmation.

    Refuses (returns {"ok": False, "message": ...}) if a line would
    oversell stock or sell below cost. Idempotent: finalize flips status
    away from "draft", so a repeat call just reports the already-finalized
    bill instead of double-deducting.
    """
    bill = (
        await db.exec(
            select(Bill)
            .where(Bill.chat_id == chat_id, Bill.status == "draft")
            .with_for_update()
        )
    ).first()

    if bill is None:
        last = (
            await db.exec(
                select(Bill)
                .where(Bill.chat_id == chat_id, Bill.status == "finalized")
                .order_by(Bill.finalized_at.desc())
                .limit(1)
            )
        ).first()
        if last is not None:
            return {
                "ok": True,
                "already_finalized": True,
                "bill_id": str(last.id),
                "total_amount": last.total_amount,
            }
        return {"ok": False, "message": "No draft bill found for this chat."}

    rows = await _load_draft_items_with_products(db, bill.id)
    if not rows:
        return {"ok": False, "message": "Draft bill has no items."}
    if not bill.payment_mode:
        return {
            "ok": False,
            "message": "No payment mode on file for this draft.",
        }

    # lock products in a fixed order to avoid deadlocking against another
    # finalize touching the same products
    product_ids = sorted({item.product_id for item, _ in rows})
    locked_products = (
        await db.exec(
            select(Product).where(Product.id.in_(product_ids)).with_for_update()
        )
    ).all()
    products_by_id = {p.id: p for p in locked_products}

    oversell: list[str] = []
    below_cost: list[str] = []
    for item, _ in rows:
        product = products_by_id[item.product_id]
        if item.qty > product.qty_on_hand:
            oversell.append(
                f"{product.name}: need {item.qty}, only {product.qty_on_hand} "
                f"{product.unit} in stock"
            )
        if item.unit_price_at_sale < product.cost_price:
            below_cost.append(
                f"{product.name}: selling at {item.unit_price_at_sale}, cost "
                f"is {product.cost_price}"
            )

    if oversell:
        return {
            "ok": False,
            "message": "Not enough stock: " + "; ".join(oversell),
        }
    if below_cost:
        return {
            "ok": False,
            "message": "Priced below cost: " + "; ".join(below_cost),
        }

    line_items = []
    subtotal = cgst_total = sgst_total = total_amount = Decimal("0")
    for item, _ in rows:
        product = products_by_id[item.product_id]
        line = calc_line_gst(item.qty, item.unit_price_at_sale, item.gst_slab_at_sale)
        subtotal += line.taxable_value
        cgst_total += line.cgst
        sgst_total += line.sgst
        total_amount += line.line_total

        product.qty_on_hand -= item.qty
        db.add(product)
        db.add(
            StockMovement(
                product_id=product.id,
                delta_qty=-item.qty,
                reason="sale",
                reference_id=bill.id,
            )
        )
        line_items.append(
            {
                "sku": product.sku,
                "name": product.name,
                "qty": item.qty,
                "unit_price": item.unit_price_at_sale,
                "line_total": line.line_total,
            }
        )

    bill.status = "finalized"
    bill.subtotal = subtotal
    bill.cgst_total = cgst_total
    bill.sgst_total = sgst_total
    bill.total_amount = total_amount
    bill.finalized_at = datetime.now(timezone.utc)
    db.add(bill)
    await db.flush()

    return {
        "ok": True,
        "bill_id": str(bill.id),
        "customer_name": bill.customer_name,
        "payment_mode": bill.payment_mode,
        "payment_ref": bill.payment_ref,
        "items": line_items,
        "subtotal": subtotal,
        "cgst_total": cgst_total,
        "sgst_total": sgst_total,
        "total_amount": total_amount,
    }
