"""broker fields made options

Revision ID: 8967acf94e32
Revises: 26c4f6ed6ca0
Create Date: 2024-02-04 20:12:42.867338

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "8967acf94e32"
down_revision = "26c4f6ed6ca0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "broker", "access_token", existing_type=sa.TEXT(), type_=sa.String(), nullable=True
    )
    op.alter_column("broker", "username", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("broker", "password", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("broker", "api_key", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("broker", "app_id", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("broker", "totp", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("broker", "twoFA", existing_type=sa.INTEGER(), nullable=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("broker", "twoFA", existing_type=sa.INTEGER(), nullable=False)
    op.alter_column("broker", "totp", existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column("broker", "app_id", existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column("broker", "api_key", existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column("broker", "password", existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column("broker", "username", existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column(
        "broker", "access_token", existing_type=sa.String(), type_=sa.TEXT(), nullable=False
    )
    # ### end Alembic commands ###
