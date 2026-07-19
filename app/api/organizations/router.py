"""Organization API routes: expose the caller's subscription plan and
route-generation quota usage so the frontend can show remaining allowance."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user, get_organization_repository
from app.core.plans import PLAN_ROUTE_LIMITS
from app.db.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organization import OrganizationRead

router = APIRouter(tags=["organizations"], dependencies=[Depends(get_current_user)])


@router.get("/me", response_model=OrganizationRead)
async def get_my_organization(
    current_user: User = Depends(get_current_user),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> OrganizationRead:
    """Return the caller's organization: subscription plan, routes generated
    so far, and how many (if any) remain under the plan's quota."""
    organization = await org_repo.get(current_user.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    limit = PLAN_ROUTE_LIMITS.get(organization.subscription_plan)
    remaining = None if limit is None else max(limit - organization.routes_generated_count, 0)

    return OrganizationRead(
        id=str(organization.id),
        name=organization.name,
        subscription_plan=organization.subscription_plan,
        routes_generated_count=organization.routes_generated_count,
        routes_limit=limit,
        routes_remaining=remaining,
    )
