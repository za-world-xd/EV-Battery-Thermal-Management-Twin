"""Compare cooling choices under the same initial state and requested load."""

from simulator.config import FlowSweepRequest, SimulationRequest
from simulator.solver import simulate


def flow_sweep(request: FlowSweepRequest) -> dict:
    runs = []
    for flow in request.flow_rates_lpm:
        config = request.simulation.model_dump()
        config["coolant_flow_rate_lpm"] = flow
        result = simulate(SimulationRequest.model_validate(config))
        runs.append(
            {
                "flow_rate_lpm": flow,
                **result["summary"],
                "pump_power_w": result["hydraulics"]["pump_power_w"],
                "pressure_drop_pa": result["hydraulics"]["pressure_drop_pa"],
            }
        )
    return {
        "runs": runs,
        "configuration": request.model_dump(),
        "warnings": [
            "Thermal exposure is an indicator, not a predicted lifespan or SOH.",
            "Cutoff and derating can change delivered load and run duration; compare these too.",
        ],
    }
