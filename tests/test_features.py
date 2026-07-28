import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import app
from simulator.config import CellParameters, ElectricalMap, SimulationRequest
from simulator.drive import current_for_power, standard_cycle, vehicle_power
from simulator.electrical import heat_terms, map_value, ocv, polarization_rates, resistances
from simulator.profiles import read_speed_csv
from simulator.solver import simulate

ROOT = Path(__file__).resolve().parents[1]


def mapped_cell():
    return CellParameters.model_validate(
        json.loads((ROOT / "data/illustrative_cell_map.json").read_text())["cell"]
    )


def test_map_interpolation_changes_all_rc_parameters():
    cell = mapped_cell()
    assert ocv(0.5, 25, cell) == pytest.approx(3.7)
    assert resistances(0.5, 25, cell)[0] == pytest.approx(0.0195)
    assert map_value("c1_f", 0.5, 25, cell) == pytest.approx(2700)
    assert map_value("c2_f", 0.5, 25, cell) == pytest.approx(13000)
    assert ocv(-0.1, -10, cell) == pytest.approx(2.9975)
    r1, r2 = resistances(0.5, 25, cell)[1:]
    rates = polarization_rates(5, 0, 0, r1, r2, cell, 0.5, 25)
    np.testing.assert_allclose(rates, [5 / 2700, 5 / 13000])
    assert heat_terms(5, 0, 0, 0.5, 25, cell)[1] == pytest.approx(-5 * 298.15 * 0.0001)


def test_map_grid_rejects_shape_unsorted_and_invalid_values():
    original = mapped_cell().electrical_map.model_dump()
    for update in [
        {"soc": [1, 0, 0.5]},
        {"c1_f": [[200]]},
        {"r0_ohm": [[-1, 0.02, 0.02]] * 2},
        {"temperature_c": [0, float("nan")]},
    ]:
        with pytest.raises(ValidationError):
            ElectricalMap.model_validate({**original, **update})


def test_mapped_simulation_preserves_thermal_balance():
    result = simulate(SimulationRequest(cell=mapped_cell(), duration_seconds=20, initial_soc=0.5))
    assert abs(result["summary"]["energy_balance_residual_j"]) < 1e-6
    assert any("Electrical maps clamp" in warning for warning in result["warnings"])


def test_speed_trace_validation_and_header():
    for text in ["time_s,current_a\n0,1", "time_s,speed_kph\n0,-1"]:
        with pytest.raises(ValueError):
            read_speed_csv(text)
    for points in [[(1, 0), (10, 20)], [(0, 0), (0, 1)], [(0, 0), (5, 10)]]:
        with pytest.raises(ValueError):
            SimulationRequest(
                simulation_profile="CUSTOM_SPEED",
                duration_seconds=10,
                speed_points=[dict(time_s=t, speed_kph=v) for t, v in points],
            )


def test_bundled_trace_provenance_and_reference_values():
    for file, sha in [
        ("wltc_class3b.txt", "3df48abd608c5b01abf5c0d8c64a4e5c030f164b3bd98d4073361b46eb6fef67"),
        ("us06.txt", "84e9d8cc16fcd4ee3c30c3880f333eb25b61352e56f24e453411a7245c725ad2"),
    ]:
        assert hashlib.sha256((ROOT / "simulator/cycles" / file).read_bytes()).hexdigest() == sha
    time, speed = standard_cycle("WLTP_CLASS_3")
    assert len(time) == 1801
    assert time[-1] == 1800
    assert sum(speed) == pytest.approx(83758.6)
    time, speed = standard_cycle("US06")
    assert time[-1] == 600
    assert max(speed) == pytest.approx(80.3 * 1.609344)


@pytest.mark.parametrize("profile", ["WLTP_CLASS_3", "US06"])
def test_standard_cycle_runs_offline_without_uploaded_current(profile):
    response = TestClient(app).post(
        "/api/v1/simulate", json={"simulation_profile": profile, "duration_seconds": 30}
    )
    assert response.status_code == 200
    result = response.json()
    assert any(r["speed_kph"] > 0 for r in result["timeseries"])
    assert result["summary"]["unmet_drive_energy_wh"] < 1e-7
    for row in result["timeseries"]:
        assert row["pack_power_w"] == pytest.approx(row["requested_drive_power_w"])


def test_power_balance_and_regeneration():
    for power in [-30000, 0, 80000]:
        current = current_for_power(power, 3.7, 0.02, 3840)
        assert current * (3.7 - current * 0.02) * 3840 == pytest.approx(power)
    assert current_for_power(1e9, 3.7, 0.02, 3840) <= 50
    p = SimulationRequest().vehicle
    assert vehicle_power(20, -2, p) < 0
    assert vehicle_power(0, 0, p) == p.auxiliary_power_w


def test_custom_speed_csv_and_thermal_exposure():
    points = read_speed_csv("time_s,speed_kph\n0,72\n10,72\n")
    result = simulate(
        SimulationRequest(
            simulation_profile="CUSTOM_SPEED",
            speed_points=points,
            duration_seconds=10,
            initial_soc=0.5,
            initial_temp_c=50,
            coolant_inlet_temp_c=50,
            ambient_temp_c=50,
        )
    )
    assert result["summary"]["exposure_above_45_c_degree_min"] > 0
    assert result["summary"]["charge_throughput_ah"] > 0
    assert result["summary"]["unmet_drive_energy_wh"] > 0
    assert result["summary"]["derating_event_triggered"]


def test_homogeneous_pack_scaling_and_heat_breakdown():
    result = simulate(SimulationRequest(duration_seconds=10))
    assert result["pack"]["total_heat_generated_kj"] == pytest.approx(
        result["summary"]["total_heat_generated_kj"] * 3840
    )
    for row in result["timeseries"]:
        assert row["pack_voltage_v"] == pytest.approx(row["terminal_voltage_v"] * 96)
        assert row["pack_current_a"] == pytest.approx(row["current_a"] * 40)
        assert row["ohmic_heat_w"] + row["polarization_heat_w"] == pytest.approx(
            row["irreversible_heat_w"]
        )
    assert abs(result["pack"]["energy_balance_residual_j"]) < 1e-5


def test_flow_comparison_api_and_invalid_rates():
    client = TestClient(app)
    response = client.post(
        "/api/v1/flow-sweep",
        json={"simulation": {"duration_seconds": 10}, "flow_rates_lpm": [0, 4.5]},
    )
    assert response.status_code == 200
    a, b = response.json()["runs"]
    assert a["pump_power_w"] == 0
    assert b["pump_power_w"] > 0
    assert b["max_core_temp_c"] <= a["max_core_temp_c"]
    for rates in [[1], [1, 1], [-1, 2], [1, "NaN"]]:
        assert client.post("/api/v1/flow-sweep", json={"flow_rates_lpm": rates}).status_code == 422


def test_short_current_pulse_is_not_skipped():
    result = simulate(
        SimulationRequest(
            simulation_profile="CUSTOM",
            duration_seconds=10,
            initial_soc=0.5,
            current_points=[
                {"time_s": 0, "current_a": 0},
                {"time_s": 5, "current_a": 0},
                {"time_s": 5.001, "current_a": 10},
                {"time_s": 5.002, "current_a": 0},
                {"time_s": 10, "current_a": 0},
            ],
        )
    )
    assert result["summary"]["final_soc"] == pytest.approx(0.5 - 0.01 / 18000, abs=1e-10)
