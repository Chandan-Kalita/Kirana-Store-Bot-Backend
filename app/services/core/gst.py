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
    value is back-calculated rather than added on top. line_total is
    rounded first (a single clean product -- this is what the customer
    actually pays, authoritative). CGST and SGST are each rounded straight
    from the same formula, taxable_value_raw * gst_slab / 200 -- since the
    CGST and SGST rates are always identical halves of the slab, this
    naturally produces the same rounded value for both, no special-casing
    needed. taxable_value is then the remainder, line_total - cgst - sgst,
    rather than being rounded independently -- that's what guarantees
    taxable_value + cgst + sgst == line_total for every line (and hence
    every bill, being a sum of balanced lines), while also guaranteeing
    cgst == sgst always. Rounding taxable_value independently, as an
    earlier version of this function did, could leave cgst and sgst a
    paisa apart from each other to make the total balance instead.
    """
    line_total = _round(qty * unit_price)
    taxable_value_raw = line_total / (1 + gst_slab / 100)
    cgst = _round(taxable_value_raw * gst_slab / 200)
    sgst = _round(taxable_value_raw * gst_slab / 200)
    taxable_value = line_total - cgst - sgst

    return LineGst(
        taxable_value=taxable_value,
        cgst=cgst,
        sgst=sgst,
        line_total=line_total,
    )
