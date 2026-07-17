from decimal import Decimal
from typing import Literal

from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import func, or_
from sqlmodel import select

from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.core.analytics import compute_reorder_suggestions
from app.services.helper.models import Product, StockMovement

Unit = Literal["kg", "g", "litre", "ml", "packet", "dozen", "piece"]


@agent.tool(sequential=True)
async def search_products(ctx: RunContext[AgentDeps], query: str) -> list[dict]:
    """Search products by name or SKU, case-insensitive partial match.

    Call this first whenever the owner names a product by a loose or
    ambiguous name (e.g. "atta", "sugar") to resolve it to an exact SKU --
    every other product tool takes an exact sku, not a fuzzy name.

    Args:
        query: Free-text search term, matched against both name and SKU.
    """
    like = f"%{query}%"
    stmt = select(Product).where(
        or_(Product.name.ilike(like), Product.sku.ilike(like))
    )
    products = (await ctx.deps.db.exec(stmt)).all()
    return [
        {
            "sku": p.sku,
            "name": p.name,
            "unit": p.unit,
            "qty_on_hand": p.qty_on_hand,
            "mrp": p.mrp,
            "gst_slab": p.gst_slab,
        }
        for p in products
    ]


MAX_PAGE_SIZE = 100


@agent.tool(sequential=True)
async def list_products(
    ctx: RunContext[AgentDeps], offset: int = 0, limit: int = MAX_PAGE_SIZE
) -> dict:
    """List all products, alphabetically, paginated.

    Use this for a full catalog listing (e.g. "list all products"). For
    resolving a specific name to a SKU, use search_products instead. If
    has_more is true in the response, call again with offset advanced by
    the returned count to get the next page.

    Args:
        offset: Number of products to skip from the start of the list.
        limit: Max products to return, capped at 100 regardless of the
            value passed.
    """
    if offset < 0:
        raise ModelRetry(f"offset must be >= 0, got {offset}.")
    if limit <= 0:
        raise ModelRetry(f"limit must be positive, got {limit}.")
    limit = min(limit, MAX_PAGE_SIZE)

    total = (
        await ctx.deps.db.exec(select(func.count()).select_from(Product))
    ).one()
    stmt = select(Product).order_by(Product.name).offset(offset).limit(limit)
    products = (await ctx.deps.db.exec(stmt)).all()

    return {
        "total": total,
        "offset": offset,
        "count": len(products),
        "has_more": offset + len(products) < total,
        "products": [
            {
                "sku": p.sku,
                "name": p.name,
                "unit": p.unit,
                "qty_on_hand": p.qty_on_hand,
                "mrp": p.mrp,
                "gst_slab": p.gst_slab,
            }
            for p in products
        ],
    }


@agent.tool(sequential=True)
async def add_product(
    ctx: RunContext[AgentDeps],
    sku: str,
    name: str,
    unit: Unit,
    is_loose: bool,
    cost_price: Decimal,
    mrp: Decimal,
    gst_slab: Decimal,
    hsn_code: str,
    reorder_level: Decimal,
    initial_qty: Decimal = Decimal("0"),
) -> dict:
    """Create a new product.

    Args:
        sku: Unique stock-keeping unit code for the product.
        name: Display name, e.g. "Aashirvaad Atta 5kg".
        unit: One of kg, g, litre, ml, packet, dozen, piece.
        is_loose: True for loose items sold by weight/volume (0% GST,
            fractional quantities), False for packaged items.
        cost_price: What the store pays per unit.
        mrp: Maximum retail price per unit.
        gst_slab: GST percentage slab, e.g. 0, 5, 12, 18.
        hsn_code: HSN classification code for the product.
        reorder_level: Quantity at or below which the product is low stock.
        initial_qty: Starting quantity on hand, defaults to 0.
    """
    existing = (
        await ctx.deps.db.exec(
            select(Product).where(func.lower(Product.sku) == sku.lower())
        )
    ).first()
    if existing is not None:
        raise ModelRetry(
            f"SKU '{sku}' already exists ({existing.name}). Report that to "
            "the owner, or use receive_stock if they meant to add stock."
        )

    product = Product(
        sku=sku,
        name=name,
        unit=unit,
        is_loose=is_loose,
        cost_price=cost_price,
        mrp=mrp,
        gst_slab=gst_slab,
        hsn_code=hsn_code,
        qty_on_hand=initial_qty,
        reorder_level=reorder_level,
    )
    ctx.deps.db.add(product)
    await ctx.deps.db.flush()

    return {
        "sku": product.sku,
        "name": product.name,
        "unit": product.unit,
        "qty_on_hand": product.qty_on_hand,
    }


@agent.tool(sequential=True)
async def receive_stock(
    ctx: RunContext[AgentDeps],
    sku: str,
    qty: Decimal,
    cost_price: Decimal | None = None,
    mrp: Decimal | None = None,
) -> dict:
    """Record stock received for an existing product.

    Args:
        sku: Exact SKU of the product receiving stock -- resolve via
            search_products first if the owner only gave a name.
        qty: Quantity received, in the product's own unit. Must be positive.
        cost_price: New cost price, if it changed on this delivery.
        mrp: New MRP, if it changed on this delivery.
    """
    if qty <= 0:
        raise ModelRetry(f"qty must be positive, got {qty}.")

    product = (
        await ctx.deps.db.exec(
            select(Product)
            .where(func.lower(Product.sku) == sku.lower())
            .with_for_update()
        )
    ).first()
    if product is None:
        raise ModelRetry(
            f"No product with SKU '{sku}'. Use search_products to find the "
            "right SKU, or add_product if it's genuinely new."
        )

    product.qty_on_hand += qty
    if cost_price is not None:
        product.cost_price = cost_price
    if mrp is not None:
        product.mrp = mrp
    ctx.deps.db.add(product)

    ctx.deps.db.add(
        StockMovement(product_id=product.id, delta_qty=qty, reason="receive")
    )
    await ctx.deps.db.flush()

    return {
        "sku": product.sku,
        "name": product.name,
        "unit": product.unit,
        "qty_on_hand": product.qty_on_hand,
    }


@agent.tool(sequential=True)
async def list_low_stock(
    ctx: RunContext[AgentDeps], threshold: Decimal | None = None
) -> list[dict]:
    """List products at or below their reorder point, worst shortfall first.

    Args:
        threshold: If given, flags products with qty_on_hand <= threshold
            instead of each product's own reorder_level.
    """
    stmt = select(Product)
    if threshold is not None:
        stmt = stmt.where(Product.qty_on_hand <= threshold)
    else:
        stmt = stmt.where(Product.qty_on_hand <= Product.reorder_level)
    products = list((await ctx.deps.db.exec(stmt)).all())

    def shortfall(p: Product) -> Decimal:
        base = threshold if threshold is not None else p.reorder_level
        return base - p.qty_on_hand

    products.sort(key=shortfall, reverse=True)
    return [
        {
            "sku": p.sku,
            "name": p.name,
            "qty_on_hand": p.qty_on_hand,
            "reorder_level": p.reorder_level,
        }
        for p in products
    ]


@agent.tool(sequential=True)
async def suggest_reorders(
    ctx: RunContext[AgentDeps], lookback_days: int = 14, alert_days: int = 7
) -> list[dict]:
    """Predict what's about to run out based on actual sales pace, soonest first.

    Different question from list_low_stock: list_low_stock answers "what's
    below the manually-set reorder point" (static, ignores how fast
    anything is actually selling). This answers "what should I reorder" /
    "what's going to run out soon" -- it estimates daily sales velocity
    from recent StockMovement history and flags anything projected to run
    out within alert_days, even a product that's still comfortably above
    its reorder_level but selling fast enough to run dry within the week.
    Prefer this one whenever the owner asks what to reorder or what's
    running low in a forward-looking sense; use list_low_stock for a
    simple "below threshold" check.

    Args:
        lookback_days: How many days of sales history to compute velocity
            from. Defaults to 14.
        alert_days: Only flag products projected to run out within this
            many days. Defaults to 7.
    """
    if lookback_days <= 0:
        raise ModelRetry(f"lookback_days must be positive, got {lookback_days}.")
    if alert_days <= 0:
        raise ModelRetry(f"alert_days must be positive, got {alert_days}.")

    return await compute_reorder_suggestions(
        ctx.deps.db, lookback_days=lookback_days, alert_days=alert_days
    )
