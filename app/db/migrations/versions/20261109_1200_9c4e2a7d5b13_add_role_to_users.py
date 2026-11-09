"""add role to users

Revision ID: 9c4e2a7d5b13
Revises: 3b9d2c41f6a8
Create Date: 2026-11-09 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c4e2a7d5b13'
down_revision: Union[str, None] = '3b9d2c41f6a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every existing account becomes a plain "user"; admins are promoted
    # explicitly afterwards with `python -m app.scripts.set_user_role`.
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
    )


def downgrade() -> None:
    op.drop_column("users", "role")
