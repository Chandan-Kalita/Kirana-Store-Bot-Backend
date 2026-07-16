import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel

# table models get defined here so alembic/env.py's autogenerate can see them
# on SQLModel.metadata


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
    # qty_on_hand/reorder_level are in whatever unit says, fractional for loose items
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
    # the Bill id for reason="sale", null otherwise
    reference_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), ForeignKey("bill.id"), nullable=True),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )


class Conversation(SQLModel, table=True):
    # one row per chat, chat_id is the pk -- BigInteger since Telegram ids
    # can exceed int4
    chat_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    # serialized Pydantic AI message history, see app/agent/conversation.py
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
        # at most one draft bill per chat, enforced at the DB level
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
    customer_name: str | None = Field(default=None)  # for khata linkage later
    payment_mode: str | None = Field(default=None)
    payment_ref: str | None = Field(default=None)
    # totals stay null while drafting -- computed on demand from BillItem
    # rows, frozen here only at finalize
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
    # snapshot at add-time, not re-looked-up at finalize
    unit_price_at_sale: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    gst_slab_at_sale: Decimal = Field(sa_column=Column(Numeric(4, 2), nullable=False))


class Customer(SQLModel, table=True):
    __table_args__ = (
        # case-insensitive unique: "Ramesh" and "ramesh " on different days
        # must resolve to the same customer, not fragment the balance
        Index("ix_customer_name_unique", text("lower(name)"), unique=True),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    name: str
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )


class KhataEntry(SQLModel, table=True):
    __tablename__ = "khata_entry"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    customer_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("customer.id"), nullable=False, index=True
        )
    )
    # positive = credit given (debt increases), negative = payment received --
    # same sign convention as StockMovement.delta_qty. No mutable balance
    # column anywhere: balance is always SUM(delta_amount), computed on
    # demand, so concurrent entries never need row-locking the way stock
    # decrements do.
    delta_amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    note: str | None = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=_utcnow,
    )
