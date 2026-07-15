import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel

# Table models get defined here (or in submodules imported below) and
# registered on SQLModel.metadata, which alembic/env.py targets for autogenerate.

# unit/reason are plain strings at the DB layer -- validated against
# Unit/StockMovementReason enums (defined at the application/schema layer,
# not here) before hitting the model.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(SQLModel, table=True):
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    sku: str = Field(sa_column_kwargs={"unique": True}, index=True)
    name: str
    unit: str
    is_loose: bool
    cost_price: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    mrp: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    gst_slab: Decimal = Field(sa_column=Column(Numeric(4, 2), nullable=False))
    hsn_code: str
    # canonical unit per product is whatever `unit` says (e.g. kg for loose
    # dal/rice/sugar, piece for packaged goods) -- qty_on_hand and
    # reorder_level are always expressed in that unit, fractional allowed
    # (0.25 kg) for is_loose products.
    qty_on_hand: Decimal = Field(sa_column=Column(Numeric(10, 3), nullable=False))
    reorder_level: Decimal = Field(sa_column=Column(Numeric(10, 3), nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, onupdate=_utcnow
        ),
        default_factory=_utcnow,
    )


class StockMovement(SQLModel, table=True):
    __tablename__ = "stock_movement"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    product_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("product.id"), nullable=False, index=True
        )
    )
    # positive for receiving, negative for a sale/adjustment
    delta_qty: Decimal = Field(sa_column=Column(Numeric(10, 3), nullable=False))
    reason: str
    # no FK yet -- Bill table doesn't exist; add the real FK once Bill lands
    # in a later migration, don't block this one on ordering.
    reference_id: int | None = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )
