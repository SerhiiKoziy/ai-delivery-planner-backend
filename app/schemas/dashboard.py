"""Dashboard overview response schema."""

from pydantic import BaseModel, ConfigDict, Field


class DashboardOverview(BaseModel):
    deliveries_today: int = Field(alias="deliveriesToday")
    active_drivers: int = Field(alias="activeDrivers")
    total_distance_km: float = Field(alias="totalDistanceKm")
    late_deliveries: int = Field(alias="lateDeliveries")

    model_config = ConfigDict(populate_by_name=True)
