"""added cfd_strategy table

Revision ID: 2d391b35abe8
Revises: 98d005381e5f
Create Date: 2023-10-24 00:41:18.384657

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "2d391b35abe8"
down_revision = "98d005381e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "cfd_strategy",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("min_quantity", sa.Float(), nullable=False),
        sa.Column("margin_for_min_quantity", sa.Float(), nullable=False),
        sa.Column("incremental_step_size", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("funds", sa.Float(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("broker_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["broker_id"], ["broker_clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cfd_strategy_broker_id"), "cfd_strategy", ["broker_id"], unique=False
    )
    op.create_index(
        op.f("ix_cfd_strategy_instrument"), "cfd_strategy", ["instrument"], unique=False
    )
    op.create_index(op.f("ix_cfd_strategy_user_id"), "cfd_strategy", ["user_id"], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_cfd_strategy_user_id"), table_name="cfd_strategy")
    op.drop_index(op.f("ix_cfd_strategy_instrument"), table_name="cfd_strategy")
    op.drop_index(op.f("ix_cfd_strategy_broker_id"), table_name="cfd_strategy")
    op.drop_table("cfd_strategy")
    # ### end Alembic commands ###
