"""Excel (.xlsx) delivery list importer, backed by openpyxl."""

import io

import openpyxl


def parse_excel(file_bytes: bytes) -> list[dict]:
    """Parse an uploaded Excel file into a list of raw row dicts.

    Reads the first worksheet, treating row 1 as headers and every
    subsequent non-empty row as a raw dict keyed by those headers.
    Rows where every cell is None are skipped.
    """
    workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    worksheet = workbook.worksheets[0]

    rows_iter = worksheet.iter_rows(values_only=True)
    try:
        headers = next(rows_iter)
    except StopIteration:
        return []

    headers = [str(h) if h is not None else "" for h in headers]

    rows: list[dict] = []
    for row in rows_iter:
        if all(cell is None for cell in row):
            continue
        rows.append(dict(zip(headers, row, strict=False)))
    return rows
