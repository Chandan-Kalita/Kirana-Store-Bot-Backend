import uuid

from pydantic_ai import ModelRetry, RunContext
from sqlmodel import select

from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.core.deck import SlideSpec, render_deck
from app.services.core.invoice import get_shop_header, render_invoice_pdf
from app.services.core.telegram import send_document
from app.services.helper.models import Bill, BillItem, Product

MAX_DECK_SLIDES = 15


async def _find_bill(db, chat_id: int, bill_id: str | None) -> Bill | None:
    # no bill_id given -- "send me that bill" is a deictic reference to
    # this conversation, so this branch stays chat-scoped: the shop's most
    # recent sale overall isn't necessarily what "that bill" means here.
    if bill_id is None:
        return (
            await db.exec(
                select(Bill)
                .where(Bill.chat_id == chat_id, Bill.status == "finalized")
                .order_by(Bill.finalized_at.desc())
                .limit(1)
            )
        ).first()

    # explicit bill_id -- shop-wide. A bill is a real shop sale regardless
    # of which chat created it; naming one by id shouldn't get silently
    # refused just because a different chat finalized it.
    try:
        parsed_id = uuid.UUID(bill_id)
    except ValueError:
        raise ModelRetry(f"'{bill_id}' isn't a valid bill id.")
    return (await db.exec(select(Bill).where(Bill.id == parsed_id))).first()


@agent.tool(sequential=True)
async def generate_invoice_pdf(
    ctx: RunContext[AgentDeps], bill_id: str | None = None
) -> str:
    """Generate and send a GST-correct PDF invoice for a finalized bill.

    Defaults to the most recent finalized bill for this chat if no bill_id
    is given -- covers "send me that bill" without the owner needing to
    know the id. Refuses if the bill doesn't exist or isn't finalized yet
    (a draft has no frozen totals to invoice).

    Args:
        bill_id: Specific bill id, if the owner wants an older one. Omit
            for the most recent finalized bill.
    """
    bill = await _find_bill(ctx.deps.db, ctx.deps.chat_id, bill_id)
    if bill is None:
        raise ModelRetry(
            "No such bill for this chat. Use list_past_bills to find the right one."
        )
    if bill.status != "finalized":
        raise ModelRetry(
            "That bill isn't finalized yet -- only finalized bills have an invoice."
        )

    rows = (
        await ctx.deps.db.exec(
            select(BillItem, Product)
            .join(Product, BillItem.product_id == Product.id)
            .where(BillItem.bill_id == bill.id)
        )
    ).all()
    shop_header = await get_shop_header(ctx.deps.db)
    pdf_bytes = render_invoice_pdf(bill, rows, shop_header)

    invoice_no = str(bill.id)[:8].upper()
    await send_document(
        ctx.deps.chat_id,
        f"invoice-{invoice_no}.pdf",
        pdf_bytes,
        caption=f"Invoice #{invoice_no}",
    )
    return f"Sent invoice #{invoice_no} (total {bill.total_amount})."


@agent.tool(sequential=True)
async def build_analysis_deck(
    ctx: RunContext[AgentDeps], title: str, slides: list[SlideSpec]
) -> str:
    """Render and send a PowerPoint analysis deck.

    This only renders and sends -- it does not gather any numbers itself.
    Before calling this, gather every figure you need via tool calls
    (get_sales_summary, get_sales_trend, list_low_stock, etc.) and put
    only those retrieved figures into the slides; never estimate or round
    a number from memory. 1-15 slides.

    Args:
        title: Deck title, shown on the opening slide.
        slides: The slide content, 1-15 slides, each a title/text/table/chart slide.
    """
    if not 1 <= len(slides) <= MAX_DECK_SLIDES:
        raise ModelRetry(
            f"Need 1-{MAX_DECK_SLIDES} slides, got {len(slides)}."
        )

    deck_bytes = render_deck(title, slides)
    await send_document(ctx.deps.chat_id, f"{title}.pptx", deck_bytes, caption=title)
    return f"Sent '{title}' ({len(slides)} slides)."
