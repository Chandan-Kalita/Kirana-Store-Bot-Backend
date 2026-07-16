import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.core.analytics import STORE_TZ
from app.services.core.gst import calc_line_gst
from app.services.helper.models import Bill, BillItem, Product
from app.services.helper.settings import get_settings


async def get_shop_header(db) -> dict:
    """Shop name/GSTIN for invoice headers. Reads Settings for now -- takes
    db so this can become a Preference lookup once Phase 7 lands, with no
    caller needing to change."""
    settings = get_settings()
    return {"shop_name": settings.shop_name, "shop_gstin": settings.shop_gstin}


def render_invoice_pdf(
    bill: Bill, rows: list[tuple[BillItem, Product]], shop_header: dict
) -> bytes:
    """GST invoice PDF for one finalized bill. Recomputes every line via
    calc_line_gst -- same function everything else in the app uses -- and
    sums those same recomputed lines for the footer, rather than mixing
    recomputed rows with the bill's stored totals. Both are mathematically
    identical (same inputs, same pure function), but this keeps the one
    document self-consistent by construction."""
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(shop_header["shop_name"], styles["Title"]))
    if shop_header.get("shop_gstin"):
        story.append(Paragraph(f"GSTIN: {shop_header['shop_gstin']}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    invoice_no = str(bill.id)[:8].upper()
    invoice_date = bill.finalized_at.astimezone(STORE_TZ).strftime("%d %b %Y, %I:%M %p")
    story.append(Paragraph(f"TAX INVOICE #{invoice_no}", styles["Heading2"]))
    story.append(Paragraph(f"Date: {invoice_date}", styles["Normal"]))
    story.append(Paragraph(f"Customer: {bill.customer_name or 'Walk-in'}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    table_data = [
        ["Item", "HSN", "Qty", "Unit Price", "Taxable Value", "CGST", "SGST", "Total"]
    ]
    subtotal = cgst_total = sgst_total = grand_total = Decimal("0")
    for item, product in rows:
        line = calc_line_gst(item.qty, item.unit_price_at_sale, item.gst_slab_at_sale)
        table_data.append(
            [
                product.name,
                product.hsn_code,
                str(item.qty),
                str(item.unit_price_at_sale),
                str(line.taxable_value),
                str(line.cgst),
                str(line.sgst),
                str(line.line_total),
            ]
        )
        subtotal += line.taxable_value
        cgst_total += line.cgst
        sgst_total += line.sgst
        grand_total += line.line_total

    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(f"Subtotal: {subtotal}", styles["Normal"]))
    story.append(Paragraph(f"CGST: {cgst_total}", styles["Normal"]))
    story.append(Paragraph(f"SGST: {sgst_total}", styles["Normal"]))
    story.append(Paragraph(f"<b>Grand Total: {grand_total}</b>", styles["Normal"]))
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(f"Payment: {bill.payment_mode or '-'}", styles["Normal"])
    )
    if bill.payment_ref:
        story.append(Paragraph(f"Reference: {bill.payment_ref}", styles["Normal"]))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4).build(story)
    return buffer.getvalue()
