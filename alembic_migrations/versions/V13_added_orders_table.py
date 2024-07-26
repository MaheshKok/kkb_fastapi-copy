"""added orders table

Revision ID: 4314ffab5ee3
Revises: 784a46a80825
Create Date: 2024-05-19 02:05:37.937861

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "4314ffab5ee3"
down_revision = "784a46a80825"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "order",
        sa.Column("order_id", sa.String(), nullable=False),
        sa.Column("unique_order_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("orderstatus", sa.String(), nullable=True),
        sa.Column("text", sa.String(), nullable=True),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_exit", sa.String(), nullable=False),
        sa.Column("future_entry_price_received", sa.Float(), nullable=False),
        sa.Column("entry_received_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("entry_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column("executed_price", sa.String(), nullable=True),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("strategy_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy.id"], ondelete="CASCADE"),
        sa.Column("trade_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["trade_id"], ["trade.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("unique_order_id"),
    )
    op.create_index(op.f("ix_order_expiry"), "order", ["expiry"], unique=False)
    op.create_index(op.f("ix_order_instrument"), "order", ["instrument"], unique=False)
    op.create_index(op.f("ix_order_option_type"), "order", ["option_type"], unique=False)
    op.create_index(op.f("ix_order_strategy_id"), "order", ["strategy_id"], unique=False)
    op.create_index(op.f("ix_order_entry_exit"), "order", ["entry_exit"], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_order_strategy_id"), table_name="order")
    op.drop_index(op.f("ix_order_option_type"), table_name="order")
    op.drop_index(op.f("ix_order_instrument"), table_name="order")
    op.drop_index(op.f("ix_order_expiry"), table_name="order")
    op.drop_table("order")
    # ### end Alembic commands ###
