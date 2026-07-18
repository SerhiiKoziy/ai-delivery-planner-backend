"""add organization_id multi-tenancy

Revision ID: 80a2c7bc8521
Revises: 20c7edeeddc2
Create Date: 2026-07-18 22:51:29.335603+00:00

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80a2c7bc8521'
down_revision: Union[str, None] = '20c7edeeddc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fixed id for the one shared organization that absorbs pre-existing
# deliveries/depots/drivers/vehicles/routes rows, none of which record who
# created them — there's no way to attribute that data to a specific user.
LEGACY_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
RESOURCE_TABLES = ["deliveries", "depots", "drivers", "vehicles", "routes"]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add as nullable first — existing rows need a value before this can
    # become NOT NULL below.
    op.add_column("users", sa.Column("organization_id", sa.Uuid(), nullable=True))
    for table in RESOURCE_TABLES:
        op.add_column(table, sa.Column("organization_id", sa.Uuid(), nullable=True))

    # 2. Backfill. Each existing user gets its own brand-new Organization,
    # preserving "one user = one org" retroactively (matches what
    # POST /auth/register does for new users going forward). The 5 resource
    # tables have no owning-user column at all, so their existing rows all
    # move into one shared "Legacy Data" organization instead of being
    # attributed to a specific user.
    existing_users = bind.execute(sa.text("SELECT id, email FROM users")).fetchall()
    for user_id, email in existing_users:
        org_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO organizations (id, name, created_at, updated_at) "
                "VALUES (:id, :name, now(), now())"
            ),
            {"id": org_id, "name": f"{email}'s Organization"},
        )
        bind.execute(
            sa.text("UPDATE users SET organization_id = :org_id WHERE id = :user_id"),
            {"org_id": org_id, "user_id": user_id},
        )

    legacy_org_exists = bind.execute(
        sa.text("SELECT 1 FROM organizations WHERE id = :id"), {"id": LEGACY_ORG_ID}
    ).first()
    if legacy_org_exists is None:
        bind.execute(
            sa.text(
                "INSERT INTO organizations (id, name, created_at, updated_at) "
                "VALUES (:id, 'Legacy Data', now(), now())"
            ),
            {"id": LEGACY_ORG_ID},
        )
    for table in RESOURCE_TABLES:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET organization_id = :org_id WHERE organization_id IS NULL"
            ),
            {"org_id": LEGACY_ORG_ID},
        )

    # 3. Every row now has a value — enforce NOT NULL + FK.
    op.alter_column("users", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_users_organization_id", "users", "organizations", ["organization_id"], ["id"]
    )
    for table in RESOURCE_TABLES:
        op.alter_column(table, "organization_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_organization_id", table, "organizations", ["organization_id"], ["id"]
        )


def downgrade() -> None:
    op.drop_constraint("fk_users_organization_id", "users", type_="foreignkey")
    op.drop_column("users", "organization_id")
    for table in RESOURCE_TABLES:
        op.drop_constraint(f"fk_{table}_organization_id", table, type_="foreignkey")
        op.drop_column(table, "organization_id")
    # Backfilled Organization rows (per-user orgs + the shared "Legacy Data"
    # one) are intentionally left in place — harmless orphaned rows, and
    # safer than guessing which ones this migration created versus real ones
    # created by the app since upgrade.
