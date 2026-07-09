import numpy as np
import pytest
from scipy.integrate import solve_ivp

from simulator.config import CellParameters, CoolingParameters, SimulationRequest
from simulator.cooling import loop_metrics
from simulator.electrical import heat_terms, ocv, polarization_rates, resistances
from simulator.solver import simulate


@pytest.mark.parametrize("nodes", [2, 4, 8])
def test_conservation_of_energy(nodes):
    result = simulate(SimulationRequest(duration_seconds=120, thermal_nodes=nodes))
    s = result["summary"]
    assert abs(s["energy_balance_residual_j"]) < 1e-5
    assert s["stored_thermal_energy_j"] + s["coolant_heat_rejected_j"] + s[
        "ambient_heat_rejected_j"
    ] == pytest.approx(s["total_heat_generated_kj"] * 1000, abs=1e-5)


def test_open_circuit_relaxation():
    cell = CellParameters()
    _, r1, r2 = resistances(0.5, 25, cell)
    initial = np.array([0.12, 0.08])
    taus = np.array([r1 * cell.c1_f, r2 * cell.c2_f])
    result = solve_ivp(
        lambda t, v: polarization_rates(0, *v, r1, r2, cell),
        [0, 300],
        initial,
        rtol=1e-10,
        atol=1e-12,
    )
    expected = initial * np.exp(-300 / taus)
    np.testing.assert_allclose(result.y[:, -1], expected, rtol=1e-6, atol=1e-10)
    voltage = ocv(0.5, 25, cell) - sum(result.y[:, -1])
    assert voltage == pytest.approx(ocv(0.5, 25, cell), abs=0.002)


def test_pumping_power_affinity_laminar():
    p = CoolingParameters()
    a, b = loop_metrics(0.2, p), loop_metrics(0.4, p)
    assert b["regime"] == "laminar"
    # Laminar Darcy friction is 64/Re: pressure is linear, pump power quadratic.
    assert b["pressure_drop_pa"] / a["pressure_drop_pa"] == pytest.approx(2)
    assert b["pump_power_w"] / a["pump_power_w"] == pytest.approx(4)


def test_pump_power_definition_and_turbulent_branch():
    p = CoolingParameters(parallel_channels=1)
    a = loop_metrics(4, p)
    assert a["regime"] == "turbulent"
    assert a["nusselt"] > 3.66
    assert a["pump_power_w"] == pytest.approx(a["pressure_drop_pa"] * 4 / 60000 / p.pump_efficiency)


def test_zero_flow_and_no_load_equilibrium():
    p = SimulationRequest(
        simulation_profile="CONSTANT_CURRENT",
        constant_current_a=0,
        ambient_temp_c=25,
        initial_temp_c=25,
        coolant_flow_rate_lpm=0,
        duration_seconds=60,
    )
    result = simulate(p)
    assert result["summary"]["max_core_temp_c"] == pytest.approx(25)
    assert result["summary"]["final_soc"] == pytest.approx(p.initial_soc)
    assert result["hydraulics"]["pump_power_w"] == 0


def test_soc_coulomb_counting():
    p = SimulationRequest(
        simulation_profile="CONSTANT_CURRENT",
        constant_current_a=2,
        initial_soc=0.5,
        duration_seconds=100,
    )
    assert simulate(p)["summary"]["final_soc"] == pytest.approx(0.5 - 200 / 18000)


def test_heat_positive_dissipation_and_entropy_sign():
    cell = CellParameters()
    discharge = heat_terms(5, 0, 0, 0.5, 25, cell)
    charge = heat_terms(-5, 0, 0, 0.5, 25, cell)
    assert discharge[0] > 0
    assert charge[0] == discharge[0]
    assert charge[1] == -discharge[1]
    assert discharge[1] < 0
    assert heat_terms(0, 0.1, 0.1, 0.5, 25, cell)[0] > 0


def test_thermal_derating_reduces_current():
    p = SimulationRequest(
        simulation_profile="FAST_CHARGE",
        initial_soc=0.3,
        initial_temp_c=50,
        coolant_inlet_temp_c=50,
        ambient_temp_c=50,
        duration_seconds=30,
    )
    result = simulate(p)
    assert result["summary"]["derating_event_triggered"]
    assert abs(result["timeseries"][0]["current_a"]) < abs(
        result["timeseries"][0]["requested_current_a"]
    )


def test_charge_and_discharge_stop_at_soc_limits():
    for soc, current, reason in [(0.031, 2, "minimum_soc"), (0.979, -0.5, "maximum_soc")]:
        result = simulate(
            SimulationRequest(
                initial_soc=soc,
                constant_current_a=current,
                simulation_profile="CONSTANT_CURRENT",
                duration_seconds=300,
            )
        )
        assert result["summary"]["stop_reason"] == reason
        assert result["summary"]["elapsed_seconds"] < 300
        assert result["timeseries"][-1]["time_s"] == result["summary"]["elapsed_seconds"]


def test_voltage_cutoff_precedes_full_charge():
    result = simulate(
        SimulationRequest(
            initial_soc=0.969,
            constant_current_a=-2,
            simulation_profile="CONSTANT_CURRENT",
            duration_seconds=300,
        )
    )
    assert result["summary"]["stop_reason"] == "maximum_voltage"
    assert result["timeseries"][-1]["terminal_voltage_v"] == pytest.approx(4.25)


def test_cooling_flow_reduces_temperature():
    p = SimulationRequest(
        simulation_profile="CONSTANT_CURRENT",
        constant_current_a=10,
        initial_soc=0.8,
        initial_temp_c=30,
        duration_seconds=120,
    )
    cooled = simulate(p)["summary"]["max_core_temp_c"]
    uncooled = simulate(p.model_copy(update={"coolant_flow_rate_lpm": 0}))["summary"][
        "max_core_temp_c"
    ]
    assert cooled < uncooled
