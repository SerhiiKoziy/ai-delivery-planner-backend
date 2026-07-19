"""add geocode and ai call counters to organizations

Revision ID: 5d892b1c63a4
Revises: 767eaaa0d893
Create Date: 2026-07-19 19:57:05.114280+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d892b1c63a4'
down_revision: Union[str, None] = '767eaaa0d893'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("geocode_calls_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "organizations",
        sa.Column("ai_calls_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "ai_calls_count")
    op.drop_column("organizations", "geocode_calls_count")
