"""Regression test for a real production bug: `Organization.subscription_plan`
lacked `values_callable`, so SQLAlchemy bound/read the Enum column by MEMBER
NAME ("TRIAL") rather than `.value` ("trial"). Every DB default (and every
JSON response) uses `.value`, so any row written the "server_default" way —
not through the ORM's own Python-level default — became unreadable, crashing
every endpoint that resolves the caller's organization with a 500.

This inserts a raw lowercase value via `sa.text` (mimicking a
server_default/migration-authored row, bypassing the ORM's own serialization
entirely) to prove the model tolerates that storage shape, not just rows the
ORM wrote itself.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import SubscriptionPlan
from app.db.models.organization import Organization


@pytest.mark.parametrize("stored_value", ["trial", "free", "small", "medium", "large"])
async def test_lowercase_stored_value_round_trips_through_the_orm(
    db_session: AsyncSession, stored_value: str
) -> None:
    org_name = f"Raw {stored_value} org"
    now = datetime.now(UTC)
    await db_session.execute(
        text(
            "INSERT INTO organizations "
            "(id, name, subscription_plan, routes_generated_count, "
            "geocode_calls_count, ai_calls_count, created_at, updated_at) "
            "VALUES (:id, :name, :plan, 0, 0, 0, :now, :now)"
        ),
        {"id": str(uuid.uuid4()), "name": org_name, "plan": stored_value, "now": now},
    )
    await db_session.commit()

    result = await db_session.execute(select(Organization).where(Organization.name == org_name))
    fetched = result.scalar_one()
    assert fetched.subscription_plan == SubscriptionPlan(stored_value)
