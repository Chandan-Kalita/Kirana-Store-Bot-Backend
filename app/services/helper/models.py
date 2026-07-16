import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
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
    # set to the originating Bill's id for reason="sale" movements; null for
    # receive/adjustment.
    reference_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), ForeignKey("bill.id"), nullable=True),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )


class Conversation(SQLModel, table=True):
    # one row per Telegram chat -- chat_id is already unique per chat, no
    # separate surrogate id needed. BigInteger: Telegram chat ids can exceed
    # postgres's 32-bit int4 range.
    chat_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    # serialized Pydantic AI message history (see app/agent/conversation.py)
    messages: list = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, onupdate=_utcnow
        ),
        default_factory=_utcnow,
    )


class ConversationArchive(SQLModel, table=True):
    __tablename__ = "conversation_archive"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    chat_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    messages: list = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    archived_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )


class Bill(SQLModel, table=True):
    __tablename__ = "bill"
    __table_args__ = (
        # at most one draft bill per chat -- the DB-level guardrail against
        # two bills in flight at once corrupting stock, not just app logic.
        Index(
            "ix_bill_chat_id_draft_unique",
            "chat_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    chat_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    status: str = Field(default="draft")
    # for khata linkage in Phase 4
    customer_name: str | None = Field(default=None)
    # only ever set at finalize, never during drafting
    payment_mode: str | None = Field(default=None)
    payment_ref: str | None = Field(default=None)
    # only computed and frozen onto the row at finalize -- while drafting,
    # totals are derived on demand from BillItem rows (see gst.py) so there's
    # no denormalized running total to drift out of sync with the line items.
    subtotal: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(10, 2), nullable=True)
    )
    cgst_total: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(10, 2), nullable=True)
    )
    sgst_total: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(10, 2), nullable=True)
    )
    total_amount: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(10, 2), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )
    finalized_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class BillItem(SQLModel, table=True):
    __tablename__ = "bill_item"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    bill_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("bill.id"), nullable=False, index=True
        )
    )
    product_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("product.id"), nullable=False, index=True
        )
    )
    qty: Decimal = Field(sa_column=Column(Numeric(10, 3), nullable=False))
    # snapshot at add-time, not looked up fresh at finalize -- a mid-
    # conversation price change elsewhere shouldn't silently alter an
    # in-progress bill.
    unit_price_at_sale: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    gst_slab_at_sale: Decimal = Field(sa_column=Column(Numeric(4, 2), nullable=False))
