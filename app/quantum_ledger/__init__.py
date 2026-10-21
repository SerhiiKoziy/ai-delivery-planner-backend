"""quantum_ledger — durable record + analysis of jobs sent to IBM quantum
backends. Self-contained: copy this folder into another project (see README.md).
"""

from .analysis import compare, ising_problem_from_arrays
from .api import build_ledger_router
from .ibm import ExtractedResult, extract, wait_and_extract
from .models import LedgerBase, QuantumJobRecord
from .service import LedgerNotFoundError, QuantumLedger

__all__ = [
    "ExtractedResult",
    "LedgerBase",
    "LedgerNotFoundError",
    "QuantumJobRecord",
    "QuantumLedger",
    "build_ledger_router",
    "compare",
    "extract",
    "ising_problem_from_arrays",
    "wait_and_extract",
]
