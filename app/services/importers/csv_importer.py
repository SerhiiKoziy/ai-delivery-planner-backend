"""CSV delivery list importer."""

import csv
import io


def parse_csv(file_bytes: bytes) -> list[dict]:
    """Parse an uploaded CSV file into a list of raw row dicts.

    Decodes as UTF-8, falling back to utf-8-sig to gracefully handle
    Excel-exported CSVs that include a BOM.
    """
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]
