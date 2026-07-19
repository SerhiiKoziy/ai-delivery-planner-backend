"""Organization read schema: exposes the caller's subscription plan and
route-generation usage against their plan's quota."""

from pydantic import BaseModel, ConfigDict, Field

from app.core.plans import SubscriptionPlan


class OrganizationRead(BaseModel):
    id: str
    name: str
    subscription_plan: SubscriptionPlan = Field(alias="subscriptionPlan")
    routes_generated_count: int = Field(alias="routesGeneratedCount")
    routes_limit: int | None = Field(alias="routesLimit")
    routes_remaining: int | None = Field(alias="routesRemaining")

    model_config = ConfigDict(populate_by_name=True)
