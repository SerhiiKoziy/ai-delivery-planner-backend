"""Delivery orchestration: create/read/update/delete plus bulk import.

Wires together the delivery repository, the geocoding client, and the
CSV/Excel importers + row-mapping normalization.
"""

import uuid

from app.db.models.delivery import Delivery
from app.repositories.delivery_repository import DeliveryRepository
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

    def __init__(self, repository: DeliveryRepository, geocoder: GoogleGeocodingClient) -> None:
        self.repository = repository
        self.geocoder = geocoder

    async def _create_from_fields(self, fields: dict) -> Delivery:
        """Geocode the address in `fields` and persist a new Delivery."""
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

        row_results: list[DeliveryImportRowResult] = []
        imported = 0
        failed = 0

        for row_number, raw_row in enumerate(raw_rows, start=1):
            try:
                normalized = normalize_row(raw_row)
                created = await self._create_from_fields(normalized.model_dump())
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
