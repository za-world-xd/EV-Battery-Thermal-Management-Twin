from fastapi import FastAPI, HTTPException

from simulator.analysis import flow_sweep
from simulator.config import FlowSweepRequest, SimulationRequest
from simulator.solver import simulate

app = FastAPI(
    title="EV-CellTwin",
    version="0.1.0",
    description=(
        "Educational representative-cell electro-thermal simulator. "
        "Parameters are illustrative and require experimental calibration."
    ),
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/simulate")
def run_simulation(request: SimulationRequest):
    try:
        result = simulate(request)
        return {**result["summary"], **result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Numerical integration failed") from exc


@app.post("/api/v1/flow-sweep")
def compare_flows(request: FlowSweepRequest):
    try:
        return flow_sweep(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Numerical integration failed") from exc
