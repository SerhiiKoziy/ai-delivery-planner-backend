"""add is_verified to users

Revision ID: 767eaaa0d893
Revises: 67fc9ba222f8
Create Date: 2026-07-19 19:53:26.605362+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '767eaaa0d893'
down_revision: Union[str, None] = '67fc9ba222f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='true' grandfathers in every pre-existing user (created
    # before email verification existed); the app always passes
    # is_verified=False explicitly on new registrations, overriding this
    # default for rows inserted from here on.
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_verified")
