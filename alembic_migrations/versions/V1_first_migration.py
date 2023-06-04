"""first_migration

Revision ID: 39d46951f3a1
Revises:
Create Date: 2023-06-04 02:35:21.390795

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "39d46951f3a1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=False),
        sa.Column("token_expiry", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "broker",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=True),
        sa.Column("app_id", sa.String(), nullable=True),
        sa.Column("totp", sa.String(), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_broker_user_id"), "broker", ["user_id"], unique=False)
    op.create_table(
        "strategy",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nfo_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("broker_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("completed_profit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["broker_id"],
            ["broker.id"],
        ),
        sa.ForeignKeyConstraint(
            ["completed_profit_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_broker_id"), "strategy", ["broker_id"], unique=False)
    op.create_index(
        op.f("ix_strategy_completed_profit_id"), "strategy", ["completed_profit_id"], unique=False
    )
    op.create_index(op.f("ix_strategy_nfo_type"), "strategy", ["nfo_type"], unique=False)
    op.create_index(op.f("ix_strategy_symbol"), "strategy", ["symbol"], unique=False)
    op.create_index(op.f("ix_strategy_user_id"), "strategy", ["user_id"], unique=False)
    op.create_table(
        "completed_profit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.Column("futures_profit", sa.Float(), nullable=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_completed_profit_strategy_id"), "completed_profit", ["strategy_id"], unique=False
    )
    op.create_table(
        "till_yesterdays_profit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_till_yesterdays_profit_strategy_id"),
        "till_yesterdays_profit",
        ["strategy_id"],
        unique=False,
    )
    op.create_table(
        "trade",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.Column("future_entry_price", sa.Float(), nullable=True),
        sa.Column("future_exit_price", sa.Float(), nullable=True),
        sa.Column("future_profit", sa.Float(), nullable=True),
        sa.Column("placed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("exited_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trade_expiry"), "trade", ["expiry"], unique=False)
    op.create_index(op.f("ix_trade_option_type"), "trade", ["option_type"], unique=False)
    op.create_index(op.f("ix_trade_strategy_id"), "trade", ["strategy_id"], unique=False)
    op.drop_table("alembic_version")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "alembic_version",
        sa.Column("version_num", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint("version_num", name="alembic_version_pkc"),
    )
    op.drop_index(op.f("ix_trade_strategy_id"), table_name="trade")
    op.drop_index(op.f("ix_trade_option_type"), table_name="trade")
    op.drop_index(op.f("ix_trade_expiry"), table_name="trade")
    op.drop_table("trade")
    op.drop_index(
        op.f("ix_till_yesterdays_profit_strategy_id"), table_name="till_yesterdays_profit"
    )
    op.drop_table("till_yesterdays_profit")
    op.drop_index(op.f("ix_completed_profit_strategy_id"), table_name="completed_profit")
    op.drop_table("completed_profit")
    op.drop_index(op.f("ix_strategy_user_id"), table_name="strategy")
    op.drop_index(op.f("ix_strategy_symbol"), table_name="strategy")
    op.drop_index(op.f("ix_strategy_nfo_type"), table_name="strategy")
    op.drop_index(op.f("ix_strategy_completed_profit_id"), table_name="strategy")
    op.drop_index(op.f("ix_strategy_broker_id"), table_name="strategy")
    op.drop_table("strategy")
    op.drop_index(op.f("ix_broker_user_id"), table_name="broker")
    op.drop_table("broker")
    op.drop_table("user")
    # ### end Alembic commands ###
