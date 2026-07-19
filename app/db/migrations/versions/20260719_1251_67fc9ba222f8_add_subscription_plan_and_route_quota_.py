"""add subscription plan and route quota to organizations

Revision ID: 67fc9ba222f8
Revises: 80a2c7bc8521
Create Date: 2026-07-19 12:51:50.080233+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67fc9ba222f8'
down_revision: Union[str, None] = '80a2c7bc8521'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Stored as VARCHAR + CHECK (native_enum=False), not a native Postgres
    # ENUM type, so adding future plan tiers is a plain constraint change
    # instead of an ALTER TYPE ... ADD VALUE migration.
    op.add_column(
        "organizations",
        sa.Column(
            "subscription_plan",
            sa.Enum("trial", "free", "small", "medium", "large", native_enum=False, length=20, name="subscriptionplan"),
            nullable=False,
            server_default="trial",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("routes_generated_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "routes_generated_count")
    op.drop_column("organizations", "subscription_plan")
