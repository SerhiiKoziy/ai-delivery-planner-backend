"""Subscription plan tiers and their route-generation quotas.

There's no billing/payment integration yet — every organization starts (and
today, stays) on TRIAL. FREE/SMALL/MEDIUM/LARGE exist so the column and API
shape are ready for when paid tiers are wired up; their limits are
placeholders until real pricing is defined.
"""

import enum


class SubscriptionPlan(str, enum.Enum):
    TRIAL = "trial"
    FREE = "free"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


DEFAULT_SUBSCRIPTION_PLAN = SubscriptionPlan.TRIAL


class QuotaExceededError(Exception):
    """Raised when an organization has exhausted a plan-based usage quota."""


# Lifetime cap on how many routes an organization may generate via
# POST /routes/optimize. `None` means unlimited. TRIAL's cap exists to bound
# how many OR-Tools/geocoding-backed generation requests an unpaid org can
# rack up; the paid tiers are unlimited until real per-tier quotas are set.
PLAN_ROUTE_LIMITS: dict[SubscriptionPlan, int | None] = {
    SubscriptionPlan.TRIAL: 50,
    SubscriptionPlan.FREE: 5,
    SubscriptionPlan.SMALL: None,
    SubscriptionPlan.MEDIUM: None,
    SubscriptionPlan.LARGE: None,
}

# Lifetime cap on how many addresses an organization may geocode (delivery
# create/update/import all call the paid Google Geocoding API once per
# address). Sized a bit above PLAN_ROUTE_LIMITS' TRIAL cap since one route
# typically covers several deliveries.
PLAN_GEOCODE_LIMITS: dict[SubscriptionPlan, int | None] = {
    SubscriptionPlan.TRIAL: 500,
    SubscriptionPlan.FREE: 50,
    SubscriptionPlan.SMALL: None,
    SubscriptionPlan.MEDIUM: None,
    SubscriptionPlan.LARGE: None,
}

# Lifetime cap on how many OpenAI-backed calls an organization may make
# (/ai/analyze, /ai/chat, /ai/explain, /ai/replan — one unit per HTTP call
# regardless of how many underlying OpenAI requests it makes internally).
PLAN_AI_CALL_LIMITS: dict[SubscriptionPlan, int | None] = {
    SubscriptionPlan.TRIAL: 20,
    SubscriptionPlan.FREE: 20,
    SubscriptionPlan.SMALL: None,
    SubscriptionPlan.MEDIUM: None,
    SubscriptionPlan.LARGE: None,
}

# Flat safety cap on rows per single import request (CSV/XLSX), independent
# of plan — bounds how many geocode calls one HTTP request can trigger in a
# single shot, regardless of remaining quota. Kept comfortably above every
# PLAN_GEOCODE_LIMITS value so the two caps don't collide for any plan.
MAX_IMPORT_ROWS_PER_REQUEST = 1000
