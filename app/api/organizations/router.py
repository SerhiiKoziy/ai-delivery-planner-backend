"""Organization API routes: expose the caller's subscription plan and
usage quotas (routes, geocoding, AI calls) so the frontend can show
remaining allowance."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user, get_organization_repository
from app.core.plans import (
    PLAN_AI_CALL_LIMITS,
    PLAN_API_REQUEST_LIMITS,
    PLAN_GEOCODE_LIMITS,
    PLAN_ROUTE_LIMITS,
)
from app.db.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organization import OrganizationRead

router = APIRouter(tags=["organizations"], dependencies=[Depends(get_current_user)])


def _remaining(limit: int | None, used: int) -> int | None:
    return None if limit is None else max(limit - used, 0)


@router.get("/me", response_model=OrganizationRead)
async def get_my_organization(
    current_user: User = Depends(get_current_user),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> OrganizationRead:
    """Return the caller's organization: subscription plan, and usage/quota
    for routes, geocoding, and AI calls, plus a combined total."""
    organization = await org_repo.get(current_user.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    plan = organization.subscription_plan
    routes_limit = PLAN_ROUTE_LIMITS.get(plan)
    geocode_limit = PLAN_GEOCODE_LIMITS.get(plan)
    ai_limit = PLAN_AI_CALL_LIMITS.get(plan)

    limits = (routes_limit, geocode_limit, ai_limit)
    api_requests_used = (
        organization.routes_generated_count
        + organization.geocode_calls_count
        + organization.ai_calls_count
    )
    # PLAN_API_REQUEST_LIMITS gives a plan an explicit combined cap (TRIAL's
    # is intentionally below the sum of its per-category caps). Absent an
    # explicit entry, fall back to summing the three per-category limits —
    # which only means something if every one of them is itself capped; if
    # any is unlimited, the combined total is unbounded too.
    explicit_limit = PLAN_API_REQUEST_LIMITS.get(plan)
    api_requests_limit = (
        explicit_limit
        if explicit_limit is not None
        else (None if None in limits else sum(limits))  # type: ignore[arg-type]
    )

    return OrganizationRead(
        id=str(organization.id),
        name=organization.name,
        subscription_plan=plan,
        routes_generated_count=organization.routes_generated_count,
        routes_limit=routes_limit,
        routes_remaining=_remaining(routes_limit, organization.routes_generated_count),
        geocode_calls_count=organization.geocode_calls_count,
        geocode_calls_limit=geocode_limit,
        geocode_calls_remaining=_remaining(geocode_limit, organization.geocode_calls_count),
        ai_calls_count=organization.ai_calls_count,
        ai_calls_limit=ai_limit,
        ai_calls_remaining=_remaining(ai_limit, organization.ai_calls_count),
        api_requests_used=api_requests_used,
        api_requests_limit=api_requests_limit,
        api_requests_remaining=_remaining(api_requests_limit, api_requests_used),
    )
