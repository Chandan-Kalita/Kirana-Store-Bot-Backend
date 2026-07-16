"""add check constraints for product and bill_item

Revision ID: c98c16510393
Revises: 9c538a20ac43
Create Date: 2026-07-16 22:31:24.096779

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c98c16510393'
down_revision: Union[str, Sequence[str], None] = '9c538a20ac43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # autogenerate doesn't diff CheckConstraints -- written by hand
    op.create_check_constraint(
        "ck_product_qty_on_hand_non_negative", "product", "qty_on_hand >= 0"
    )
    op.create_check_constraint(
        "ck_product_cost_price_non_negative", "product", "cost_price >= 0"
    )
    op.create_check_constraint(
        "ck_product_mrp_non_negative", "product", "mrp >= 0"
    )
    op.create_check_constraint(
        "ck_bill_item_qty_positive", "bill_item", "qty > 0"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_bill_item_qty_positive", "bill_item", type_="check")
    op.drop_constraint("ck_product_mrp_non_negative", "product", type_="check")
    op.drop_constraint("ck_product_cost_price_non_negative", "product", type_="check")
    op.drop_constraint(
        "ck_product_qty_on_hand_non_negative", "product", type_="check"
    )
