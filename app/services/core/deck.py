from io import BytesIO
from typing import Annotated, Literal, Union

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches
from pydantic import BaseModel, Field

_CHART_TYPES = {
    "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "line": XL_CHART_TYPE.LINE,
    "pie": XL_CHART_TYPE.PIE,
}


class TitleSlide(BaseModel):
    type: Literal["title"] = "title"
    title: str
    subtitle: str | None = None


class TextSlide(BaseModel):
    type: Literal["text"] = "text"
    title: str
    bullets: list[str]


class TableSlide(BaseModel):
    type: Literal["table"] = "table"
    title: str
    headers: list[str]
    rows: list[list[str]]


class ChartSeries(BaseModel):
    name: str
    values: list[float]


class ChartSlide(BaseModel):
    type: Literal["chart"] = "chart"
    title: str
    chart_type: Literal["bar", "line", "pie"]
    categories: list[str]
    series: list[ChartSeries]


# discriminated on "type" -- pydantic renders this as oneOf + discriminator
# in the JSON schema, which Anthropic-style tool calling (incl. DeepSeek's
# Anthropic-compatible endpoint) accepts natively. This is what forces the
# model to produce genuinely structured slide content instead of free text.
SlideSpec = Annotated[
    Union[TitleSlide, TextSlide, TableSlide, ChartSlide], Field(discriminator="type")
]


def _add_title_slide(prs: Presentation, spec: TitleSlide) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = spec.title
    if spec.subtitle:
        slide.placeholders[1].text = spec.subtitle


def _add_text_slide(prs: Presentation, spec: TextSlide) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = spec.title
    body = slide.placeholders[1].text_frame
    body.clear()
    for i, bullet in enumerate(spec.bullets):
        paragraph = body.paragraphs[0] if i == 0 else body.add_paragraph()
        paragraph.text = bullet


def _add_table_slide(prs: Presentation, spec: TableSlide) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = spec.title
    rows, cols = len(spec.rows) + 1, len(spec.headers)
    table = slide.shapes.add_table(
        rows, cols, Inches(0.5), Inches(1.5), Inches(9), Inches(0.4 * rows)
    ).table
    for c, header in enumerate(spec.headers):
        table.cell(0, c).text = header
    for r, row in enumerate(spec.rows, start=1):
        for c, value in enumerate(row):
            table.cell(r, c).text = value


def _add_chart_slide(prs: Presentation, spec: ChartSlide) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = spec.title
    chart_data = CategoryChartData()
    chart_data.categories = spec.categories
    for series in spec.series:
        chart_data.add_series(series.name, series.values)
    slide.shapes.add_chart(
        _CHART_TYPES[spec.chart_type],
        Inches(0.5), Inches(1.5), Inches(9), Inches(5),
        chart_data,
    )


_RENDERERS = {
    "title": _add_title_slide,
    "text": _add_text_slide,
    "table": _add_table_slide,
    "chart": _add_chart_slide,
}


def render_deck(title: str, slides: list) -> bytes:
    """Deterministically build a python-pptx presentation from SlideSpec
    objects: one deck title slide up front, then one slide per spec.
    ChartSlide gets a native pptx chart object, not a pasted image."""
    prs = Presentation()
    _add_title_slide(prs, TitleSlide(title=title))
    for spec in slides:
        _RENDERERS[spec.type](prs, spec)

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()
