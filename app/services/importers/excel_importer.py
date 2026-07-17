"""Excel (.xlsx) delivery list importer, backed by openpyxl/pandas."""


def parse_excel(file_bytes: bytes) -> list[dict]:
    """Parse an uploaded Excel file into a list of raw row dicts."""
    raise NotImplementedError
