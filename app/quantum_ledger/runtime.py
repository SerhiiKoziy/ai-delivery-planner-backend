"""Where Qiskit code is allowed to run.

Qiskit (2.x, with qiskit-aer / qiskit-ibm-runtime) segfaults the whole
process when its objects are used from a thread after the thread that
previously did Qiskit work has exited — exactly what asyncio.to_thread /
short-lived executors do across requests (reproduced: transpile + sample in
one fresh thread, then build a circuit in another -> SIGSEGV). So every
Qiskit call goes through ONE long-lived worker thread.

Side effect: Qiskit work is serialized process-wide. That's fine for
transpiling/decoding (milliseconds) and the local emulator (seconds); the
long part of a real-QPU job — waiting in IBM's queue — is NOT done on this
thread: `wait_until_done` polls job.status() (plain HTTP) elsewhere and only
the final result decoding hops onto the Qiskit thread.
"""

import asyncio
import functools
import time
from concurrent.futures import ThreadPoolExecutor

from .ibm import CANCELLED_STATUSES, DONE_STATUSES, FAILED_STATUSES, status_name

_QISKIT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qiskit")
TERMINAL_STATUSES = DONE_STATUSES | FAILED_STATUSES | CANCELLED_STATUSES


async def run_qiskit(fn, /, *args, **kwargs):
    """Run a (blocking) Qiskit-touching callable on the dedicated Qiskit thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_QISKIT_EXECUTOR, functools.partial(fn, *args, **kwargs))


async def wait_until_done(
    job, timeout_seconds: float, *, first_interval: float = 0.5, max_interval: float = 10.0
) -> str:
    """Poll a job's status until it is terminal; raises TimeoutError otherwise.

    Status calls are HTTP for IBM jobs and a future check for local ones —
    no Qiskit objects are touched, so they may run on any thread.
    """
    deadline = time.monotonic() + timeout_seconds
    interval = first_interval
    while True:
        status = await asyncio.to_thread(status_name, job)
        if status in TERMINAL_STATUSES:
            return status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"job still {status} after {timeout_seconds:.0f}s")
        await asyncio.sleep(min(interval, remaining))
        interval = min(interval * 2, max_interval)
