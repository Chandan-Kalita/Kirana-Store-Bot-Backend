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
    value is back-calculated rather than added on top. Each figure is
    rounded independently before returning -- callers sum already-rounded
    lines for a bill total, matching how a printed GST invoice rounds line
    by line rather than rounding the total once at the end.
    """
    line_total = qty * unit_price
    taxable_value = line_total / (1 + gst_slab / 100)
    gst_amount = line_total - taxable_value
    half_gst = gst_amount / 2

    return LineGst(
        taxable_value=_round(taxable_value),
        cgst=_round(half_gst),
        sgst=_round(half_gst),
        line_total=_round(line_total),
    )
