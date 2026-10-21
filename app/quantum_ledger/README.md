# quantum_ledger

Durable record + analysis of every job sent to an IBM quantum backend (real
QPU via `qiskit-ibm-runtime`, or a local fake-device emulator): **what was
sent, what came back, and what an ordinary CPU computes for the same circuit**.

Self-contained: no imports from the host app. To reuse it, copy this folder.

## What one row (`quantum_job_ledger`) holds

| Group | Columns |
|---|---|
| Who/where | `tenant_id`, `source`/`source_id`/`source_step`, `provider`, `is_real_hardware`, `backend_name/version`, `channel`, `instance`, `job_id`, `session_id` (never the API token) |
| Sent | `logical_qasm` (OpenQASM 2, re-loadable), `isa_qasm` (what the device ran), depths/op counts, `physical_qubits`, `parameters`, `run_options`, `shots`, optional `problem` (Ising: h, J, const) |
| Device state | `calibration`: T1/T2, readout/gate errors of the used qubits and couplers, calibration timestamp, rough expected success probability |
| Received | `counts`, `memory` (every shot, in order), `result_metadata`, raw `job_metrics`, `ibm_status`, `qpu_seconds` |
| CPU reference | `cpu_ideal_distribution` (exact statevector), `classical_reference` (caller's solver: optimum, time), optional `cpu_noisy_counts` (device noise model on Aer) |
| Comparison | `comparison` JSON + columns `tvd_vs_ideal`, `hellinger_fidelity`, `measured_optimum_frequency`, `ideal_optimum_probability` |
| Time | `transpile_ms`, `cpu_ideal_ms`, `classical_solve_ms`, `queue_ms`, `execution_ms`, `wait_wall_ms`, `submitted_at` / `started_at` / `finished_at` / `received_at` |

## Never losing a result

```
open()            -> "prepared"  (circuits, calibration, CPU ideal: before anything is sent)
mark_submitted()  -> "submitted" (job_id committed immediately)
complete()        -> "completed" (raw result + comparison)
mark_timeout()    -> "timeout"   (still running at IBM)
sync()/sync_pending() -> fetches submitted/timeout real-QPU jobs from IBM by job_id
```

Local emulator jobs live in process memory and can't be recovered after the
process ends; `sync` marks them failed with that reason.

## Qiskit threading rule

Qiskit 2.x segfaults when its objects are used from a new thread after the
thread that previously did Qiskit work exited. Use `runtime.run_qiskit(...)`
for every Qiskit call (one long-lived worker thread), and
`runtime.wait_until_done(job, timeout)` to wait for a remote job without
blocking that thread.

## Integrating into another FastAPI + SQLAlchemy (async) project

1. Copy `quantum_ledger/` into the project's package.
2. Alembic `env.py`: `target_metadata = [Base.metadata, LedgerBase.metadata]`,
   then `alembic revision --autogenerate` creates `quantum_job_ledger`.
3. Dependencies:

```python
def get_ledger(db=Depends(get_db), user=Depends(get_current_user)):
    return QuantumLedger(db, tenant_id=user.organization_id)  # or tenant_id=None

def get_runtime_service():  # None if IBM isn't configured
    return lambda: QiskitRuntimeService(channel=..., token=..., instance=...)

app.include_router(build_ledger_router(get_ledger, get_runtime_service),
                   prefix="/api/v1/quantum/ledger", dependencies=[Depends(get_current_user)])
```

4. Around each job:

```python
rec = await ledger.open(source="my_feature", provider="ibm_quantum", is_real_hardware=True,
                        backend=backend, logical_circuit=qc, isa_circuit=isa, shots=4096,
                        problem=ising_problem_from_arrays(J, h, const),           # optional
                        classical_reference={"method": ..., "optimal_cost": ..., "solve_ms": ...})
job = await run_qiskit(lambda: SamplerV2(mode=backend).run([isa], shots=4096))
await ledger.mark_submitted(rec.id, job.job_id())
try:
    await wait_until_done(job, timeout_seconds=600)
    extracted, _ = await run_qiskit(wait_and_extract, job, 60)
    await ledger.complete(rec.id, extracted)
except TimeoutError as exc:
    await ledger.mark_timeout(rec.id, str(exc))      # recover later with sync()
```

## API (`build_ledger_router`)

| Method | Path | |
|---|---|---|
| GET | `/` | list (filters: `status`, `backend_name`, `source_id`, `real_hardware`) |
| GET | `/summary` | status mix, per-backend fidelity/TVD/lift, timing percentiles, QPU seconds |
| GET | `/{id}` | full record (QASM, calibration, counts, per-shot memory, CPU reference) |
| GET | `/{id}/analysis` | chart-ready: outcome table (measured vs ideal vs cost), per-qubit marginals, shot drift, timeline, timings, circuit growth, calibration |
| POST | `/{id}/sync` | ask IBM for a submitted/timed-out job |
| POST | `/sync-pending` | sync every recoverable real-QPU job |
| POST | `/{id}/recompute` | re-derive comparison from stored raw data |

Requires: SQLAlchemy 2 (async), FastAPI, Pydantic 2, NumPy; Qiskit,
qiskit-aer and qiskit-ibm-runtime for anything that touches circuits.
