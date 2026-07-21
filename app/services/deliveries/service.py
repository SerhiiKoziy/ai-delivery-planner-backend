"""Delivery orchestration: create/read/update/delete plus bulk import.

Wires together the delivery repository, the geocoding client, and the
CSV/Excel importers + row-mapping normalization.
"""

import uuid

from app.core.plans import (
    MAX_IMPORT_ROWS_PER_REQUEST,
    PLAN_API_REQUEST_LIMITS,
    PLAN_GEOCODE_LIMITS,
    QuotaExceededError,
)
from app.db.models.delivery import Delivery
from app.db.models.organization import Organization
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.delivery import (
    DeliveryCreate,
    DeliveryImportResult,
    DeliveryImportRowResult,
    DeliveryRead,
    DeliveryUpdate,
)
from app.services.geocoding.client import GoogleGeocodingClient
from app.services.importers.csv_importer import parse_csv
from app.services.importers.excel_importer import parse_excel
from app.services.importers.mapping import normalize_row


class DeliveryService:
    """Application-level orchestration for the deliveries vertical slice."""

    def __init__(
        self,
        repository: DeliveryRepository,
        geocoder: GoogleGeocodingClient,
        org_repo: OrganizationRepository,
        organization: Organization,
    ) -> None:
        self.repository = repository
        self.geocoder = geocoder
        self.org_repo = org_repo
        self.organization = organization

    async def _consume_geocode_quota(self) -> None:
        """Reject with `QuotaExceededError` once the organization's plan has
        exhausted its lifetime geocoding allowance, or its combined
        API-request allowance (if the plan has one) — checked and consumed
        atomically, immediately before the paid Google Geocoding API call."""
        plan = self.organization.subscription_plan
        limit = PLAN_GEOCODE_LIMITS.get(plan)
        combined_limit = PLAN_API_REQUEST_LIMITS.get(plan)

        combined_used = (
            self.organization.routes_generated_count
            + self.organization.geocode_calls_count
            + self.organization.ai_calls_count
        )
        if combined_limit is not None and combined_used >= combined_limit:
            raise QuotaExceededError(
                f"API request limit reached for the '{plan.value}' plan "
                f"({combined_limit} total calls). Upgrade your plan to continue."
            )

        allowed = await self.org_repo.try_consume_quota(
            self.organization.id,
            counter_column="geocode_calls_count",
            limit=limit,
            combined_limit=combined_limit,
        )
        if not allowed:
            raise QuotaExceededError(
                f"Geocoding limit reached for the '{plan.value}' plan ({limit} addresses). "
                "Upgrade your plan to geocode more addresses."
            )

    async def _create_from_fields(self, fields: dict) -> Delivery:
        """Geocode the address in `fields` and persist a new Delivery."""
        await self._consume_geocode_quota()
        address = fields["address"]
        coordinates = await self.geocoder.geocode(address)

        if coordinates is not None:
            fields["latitude"], fields["longitude"] = coordinates
            fields["status"] = "geocoded"
        else:
            fields["latitude"] = None
            fields["longitude"] = None
            fields["status"] = "geocode_failed"

        return await self.repository.create(**fields)

    async def create(self, payload: DeliveryCreate) -> Delivery:
        fields = payload.model_dump()
        return await self._create_from_fields(fields)

    async def get(self, delivery_id: uuid.UUID) -> Delivery | None:
        return await self.repository.get(delivery_id)

    async def list_all(self) -> list[Delivery]:
        return await self.repository.list()

    async def update(self, delivery_id: uuid.UUID, payload: DeliveryUpdate) -> Delivery | None:
        data = payload.model_dump(exclude_unset=True)
        if "address" in data:
            await self._consume_geocode_quota()
            coordinates = await self.geocoder.geocode(data["address"])
            if coordinates is not None:
                data["latitude"], data["longitude"] = coordinates
                data["status"] = "geocoded"
            else:
                data["latitude"] = None
                data["longitude"] = None
                data["status"] = "geocode_failed"
        return await self.repository.update(delivery_id, **data)

    async def delete(self, delivery_id: uuid.UUID) -> bool:
        return await self.repository.delete(delivery_id)

    async def import_file(self, filename: str, file_bytes: bytes) -> DeliveryImportResult:
        lower_name = filename.lower()
        if lower_name.endswith(".csv"):
            raw_rows = parse_csv(file_bytes)
        elif lower_name.endswith(".xlsx") or lower_name.endswith(".xls"):
            raw_rows = parse_excel(file_bytes)
        else:
            raise ValueError(f"Unsupported file extension for import: {filename!r}")

        if len(raw_rows) > MAX_IMPORT_ROWS_PER_REQUEST:
            raise ValueError(
                f"Import file has {len(raw_rows)} rows, exceeding the per-request limit of "
                f"{MAX_IMPORT_ROWS_PER_REQUEST}. Split it into smaller batches."
            )

        row_results: list[DeliveryImportRowResult] = []
        imported = 0
        failed = 0
        quota_exhausted = False

        for row_number, raw_row in enumerate(raw_rows, start=1):
            if quota_exhausted:
                failed += 1
                row_results.append(
                    DeliveryImportRowResult(
                        row_number=row_number,
                        success=False,
                        error="Geocoding limit reached for this organization's plan; row not processed.",
                    )
                )
                continue

            try:
                normalized = normalize_row(raw_row)
                created = await self._create_from_fields(normalized.model_dump())
            except QuotaExceededError as exc:
                quota_exhausted = True
                failed += 1
                row_results.append(
                    DeliveryImportRowResult(row_number=row_number, success=False, error=str(exc))
                )
            except Exception as exc:  # noqa: BLE001 - one bad row must not abort the batch
                failed += 1
                row_results.append(
                    DeliveryImportRowResult(row_number=row_number, success=False, error=str(exc))
                )
            else:
                imported += 1
                row_results.append(
                    DeliveryImportRowResult(
                        row_number=row_number,
                        success=True,
                        delivery=DeliveryRead.model_validate(created),
                    )
                )

        return DeliveryImportResult(
            total_rows=len(raw_rows),
            imported=imported,
            failed=failed,
            rows=row_results,
        )
