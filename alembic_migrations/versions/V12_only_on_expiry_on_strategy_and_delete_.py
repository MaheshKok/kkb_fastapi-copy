"""only_on_expiry on strategy and delete take_away_profit

Revision ID: 784a46a80825
Revises: dcb9ea13b15a
Create Date: 2024-02-25 19:27:29.822800

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "784a46a80825"
down_revision = "dcb9ea13b15a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("ix_take_away_profit_strategy_id", table_name="take_away_profit")
    op.drop_table("take_away_profit")
    op.add_column(
        "strategy",
        sa.Column("only_on_expiry", sa.Boolean(), server_default="False", nullable=False),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("strategy", "only_on_expiry")
    op.create_table(
        "take_away_profit",
        sa.Column("id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "profit", sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True
        ),
        sa.Column("strategy_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
        sa.Column("total_trades", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column(
            "future_profit", sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy.id"],
            name="take_away_profit_strategy_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="take_away_profit_pkey"),
    )
    op.create_index(
        "ix_take_away_profit_strategy_id", "take_away_profit", ["strategy_id"], unique=False
    )
    # ### end Alembic commands ###
