import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import app
from simulator.config import SimulationRequest
from simulator.profiles import read_current_csv

client = TestClient(app)


def test_health_and_simulate():
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/api/v1/simulate", json={"duration_seconds": 10})
    assert response.status_code == 200
    body = response.json()
    assert len(body["timeseries"]) == 6
    assert body["summary"]["stop_reason"] == "duration_completed"
    assert body["max_core_temp_c"] == body["summary"]["max_core_temp_c"]


@pytest.mark.parametrize(
    "payload",
    [
        {"duration_seconds": 0},
        {"coolant_flow_rate_lpm": -1},
        {"thermal_nodes": 20},
        {"initial_soc": 1.5},
        {"simulation_profile": "CUSTOM"},
        {"extra": True},
        {"cooling": {"pump_efficiency": 0}},
        {"constant_current_a": "NaN"},
    ],
)
def test_invalid_requests(payload):
    assert client.post("/api/v1/simulate", json=payload).status_code == 422


def test_csv_custom_profile():
    points = read_current_csv("time_s,current_a\n0,0\n5,5\n10,0\n")
    response = client.post(
        "/api/v1/simulate",
        json={
            "duration_seconds": 10,
            "simulation_profile": "CUSTOM",
            "current_points": [p.model_dump() for p in points],
        },
    )
    assert response.status_code == 200
    assert response.json()["timeseries"][1]["requested_current_a"] == pytest.approx(2)


@pytest.mark.parametrize(
    "text", ["seconds,amps\n0,1", "time_s,current_a\n0,nan", "time_s,current_a\n0,100"]
)
def test_bad_csv(text):
    with pytest.raises(ValueError):
        read_current_csv(text)


def test_unsorted_or_short_trace_rejected():
    for points in [[(0, 1), (0, 2)], [(0, 1), (2, 1)], [(1, 1), (10, 1)]]:
        with pytest.raises(ValidationError):
            SimulationRequest(
                simulation_profile="CUSTOM",
                duration_seconds=10,
                current_points=[dict(time_s=t, current_a=i) for t, i in points],
            )


def test_invalid_initial_load():
    response = client.post(
        "/api/v1/simulate",
        json={
            "simulation_profile": "CONSTANT_CURRENT",
            "constant_current_a": 50,
            "initial_soc": 0.1,
        },
    )
    assert response.status_code == 422
