"""Organization read schema: exposes the caller's subscription plan and
usage against their plan's quotas (routes, geocoding, AI calls), plus a
combined "API requests" summary across all three for a single headline
used/remaining figure on the dashboard."""

from pydantic import BaseModel, ConfigDict, Field

from app.core.plans import SubscriptionPlan


class OrganizationRead(BaseModel):
    id: str
    name: str
    subscription_plan: SubscriptionPlan = Field(alias="subscriptionPlan")
    routes_generated_count: int = Field(alias="routesGeneratedCount")
    routes_limit: int | None = Field(alias="routesLimit")
    routes_remaining: int | None = Field(alias="routesRemaining")
    geocode_calls_count: int = Field(alias="geocodeCallsCount")
    geocode_calls_limit: int | None = Field(alias="geocodeCallsLimit")
    geocode_calls_remaining: int | None = Field(alias="geocodeCallsRemaining")
    ai_calls_count: int = Field(alias="aiCallsCount")
    ai_calls_limit: int | None = Field(alias="aiCallsLimit")
    ai_calls_remaining: int | None = Field(alias="aiCallsRemaining")
    # Combined across all three quotas above: `None` limit/remaining means at
    # least one of the underlying quotas is unlimited, so a single combined
    # cap wouldn't mean anything.
    api_requests_used: int = Field(alias="apiRequestsUsed")
    api_requests_limit: int | None = Field(alias="apiRequestsLimit")
    api_requests_remaining: int | None = Field(alias="apiRequestsRemaining")

    model_config = ConfigDict(populate_by_name=True)
