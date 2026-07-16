from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class LineGst:
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    line_total: Decimal


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def calc_line_gst(qty: Decimal, unit_price: Decimal, gst_slab: Decimal) -> LineGst:
    """GST breakdown for one bill line.

    unit_price is treated as GST-inclusive (Indian Legal Metrology rules
    require packaged-goods MRP to already include all taxes), so the taxable
    value is back-calculated rather than added on top. taxable_value and
    line_total are rounded first (each a single clean division/product);
    cgst is then rounded from half the *rounded* gst amount, and sgst takes
    the exact remainder rather than being rounded independently -- that
    guarantees taxable_value + cgst + sgst == line_total for every line
    (and hence for every bill, being a sum of balanced lines). Rounding
    cgst and sgst independently, as an earlier version of this function
    did, can leave the two off by a paisa from the total (e.g.
    26.79 + 1.61 + 1.61 = 30.01 when line_total is really 30.00).
    """
    line_total = _round(qty * unit_price)
    taxable_value = _round(line_total / (1 + gst_slab / 100))
    gst_amount = line_total - taxable_value
    cgst = _round(gst_amount / 2)
    sgst = gst_amount - cgst

    return LineGst(
        taxable_value=taxable_value,
        cgst=cgst,
        sgst=sgst,
        line_total=line_total,
    )
