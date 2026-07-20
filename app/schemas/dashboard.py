"""Dashboard overview and usage-history response schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class DashboardOverview(BaseModel):
    deliveries_today: int = Field(alias="deliveriesToday")
    active_drivers: int = Field(alias="activeDrivers")
    total_distance_km: float = Field(alias="totalDistanceKm")
    late_deliveries: int = Field(alias="lateDeliveries")
    active_vehicles: int = Field(alias="activeVehicles")
    drivers_on_route_today: int = Field(alias="driversOnRouteToday")
    drivers_idle_today: int = Field(alias="driversIdleToday")
    vehicles_in_use_today: int = Field(alias="vehiclesInUseToday")
    vehicles_available_today: int = Field(alias="vehiclesAvailableToday")

    model_config = ConfigDict(populate_by_name=True)


class DailyUsagePoint(BaseModel):
    date: date
    deliveries_count: int = Field(alias="deliveriesCount")
    routes_generated: int = Field(alias="routesGenerated")
    distance_km: float = Field(alias="distanceKm")

    model_config = ConfigDict(populate_by_name=True)


class DashboardUsageHistory(BaseModel):
    points: list[DailyUsagePoint]

    model_config = ConfigDict(populate_by_name=True)
