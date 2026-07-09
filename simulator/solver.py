"""Coupled 2RC and finite-volume thermal network, integrated with RK45."""

import numpy as np

from simulator.config import SimulationRequest
from simulator.cooling import loop_metrics
from simulator.drive import current_for_power, speed_load, speed_schedule
from simulator.electrical import heat_terms, ocv, polarization_rates, resistances
from simulator.integration import integrate
from simulator.profiles import requested_current


def simulate(p: SimulationRequest) -> dict:
    cell = p.cell
    n = p.thermal_nodes
    cell_count = p.pack.series_cells * p.pack.parallel_cells
    schedule = speed_schedule(p)
    hydraulics = loop_metrics(p.coolant_flow_rate_lpm, p.cooling)
    h = hydraulics["h_w_m2_k"]
    conductance = 1 / (cell.contact_resistance_k_w + 1 / (h * cell.contact_area_m2)) if h else 0
    # Limit heat transfer by the finite heat capacity rate of the flowing coolant.
    capacity_rate = (
        p.coolant_flow_rate_lpm / 60000 * p.cooling.density_kg_m3 * p.cooling.heat_capacity_j_kg_k
    )
    ua = (
        capacity_rate * (-np.expm1(-conductance * cell_count / capacity_rate)) / cell_count
        if capacity_rate
        else 0
    )
    capacities = np.array(
        [cell.core_capacity_j_k / (n - 1)] * (n - 1) + [cell.surface_capacity_j_k]
    )
    edge_conductance = (n - 1) / cell.core_surface_resistance_k_w
    initial_temp = p.ambient_temp_c if p.initial_temp_c is None else p.initial_temp_c
    trace_times = np.array([point.time_s for point in p.current_points])
    trace_currents = np.array([point.current_a for point in p.current_points])
    # SOC, RC voltages, thermal nodes, then energy/exposure/throughput integrals.
    y0 = np.r_[p.initial_soc, 0.0, 0.0, np.full(n, initial_temp), np.zeros(8)]

    def quantities(t, y):
        soc, v1, v2 = y[:3]
        tc = y[3]
        r0, r1, r2 = resistances(soc, tc, cell)
        available_voltage = ocv(soc, tc, cell) - v1 - v2
        request = (
            float(np.interp(t, trace_times, trace_currents))
            if len(trace_times)
            else requested_current(t, p)
        )
        if schedule is not None:
            _, power = speed_load(t, schedule, p)
            request = current_for_power(power, available_voltage, r0, cell_count)
        scale = float(np.clip((55 - tc) / 10, 0, 1)) if p.thermal_derating else 1.0
        current = request * scale
        voltage = available_voltage - current * r0
        qi, qe = heat_terms(current, v1, v2, soc, tc, cell)
        qc = ua * (y[3 + n - 1] - p.coolant_inlet_temp_c)
        qa = cell.ambient_conductance_w_k * (y[3 + n - 1] - p.ambient_temp_c)
        return current, voltage, qi, qe, qc, qa, r1, r2, request

    def rhs(t, y):
        current, voltage, qi, qe, qc, qa, r1, r2, _ = quantities(t, y)
        delivered_power = current * voltage * cell_count
        demand = speed_load(t, schedule, p)[1] if schedule is not None else delivered_power
        balance = np.zeros(n)
        balance[0] = qi + qe
        flux = edge_conductance * np.diff(y[3 : 3 + n])
        balance[:-1] += flux
        balance[1:] -= flux
        balance[-1] -= qc + qa
        return np.r_[
            -current / (3600 * p.nominal_capacity_ah),
            polarization_rates(current, y[1], y[2], r1, r2, cell, y[0], y[3]),
            balance / capacities,
            qi + qe,
            qc,
            qa,
            abs(current) / 3600,
            max(y[3] - 35, 0) / 60,
            max(y[3] - 45, 0) / 60,
            delivered_power / 3600,
            abs(demand - delivered_power) / 3600,
        ]

    def low_soc(t, y):
        return y[0] - 0.02

    def high_soc(t, y):
        return 0.98 - y[0]

    def low_voltage(t, y):
        return quantities(t, y)[1] - 2.5

    def high_voltage(t, y):
        return 4.25 - quantities(t, y)[1]

    def overtemperature(t, y):
        return 65 - max(y[3 : 3 + n])

    events = [low_soc, high_soc, low_voltage, high_voltage, overtemperature]
    reasons = [
        "minimum_soc",
        "maximum_soc",
        "minimum_voltage",
        "maximum_voltage",
        "temperature_cutoff",
    ]
    for event in events:
        event.terminal = True
        event.direction = -1
    initial_margins = [event(0, y0) for event in events]
    if min(initial_margins) <= 0:
        raise ValueError("Initial load is outside the 2.5-4.25 V or temperature operating limits")

    knots = trace_times
    if schedule is not None:
        cycle_times = schedule[0]
        knots = np.concatenate(
            [cycle_times + offset for offset in np.arange(0, p.duration_seconds, cycle_times[-1])]
        )
    solution = integrate(rhs, y0, p.duration_seconds, events, knots)
    if not solution.success:
        raise RuntimeError(solution.message)
    end = float(solution.t[-1])
    times = np.unique(np.r_[np.arange(0, end, p.output_interval_s), end])
    states = solution.sol(times)
    rows = []
    for t, y in zip(times, states.T, strict=True):
        current, voltage, qi, qe, qc, qa, _, _, request = quantities(t, y)
        r0 = resistances(y[0], y[3], cell)[0]
        speed, demand = speed_load(t, schedule, p) if schedule is not None else (None, None)
        rows.append(
            dict(
                time_s=float(t),
                soc=float(y[0]),
                current_a=current,
                requested_current_a=request,
                terminal_voltage_v=voltage,
                core_temp_c=float(y[3]),
                surface_temp_c=float(y[3 + n - 1]),
                node_temperatures_c=y[3 : 3 + n].tolist(),
                irreversible_heat_w=qi,
                ohmic_heat_w=current**2 * r0,
                polarization_heat_w=qi - current**2 * r0,
                entropic_heat_w=qe,
                coolant_heat_w=qc,
                ambient_heat_w=qa,
                pack_voltage_v=voltage * p.pack.series_cells,
                pack_current_a=current * p.pack.parallel_cells,
                pack_power_w=current * voltage * cell_count,
                speed_kph=speed,
                requested_drive_power_w=demand,
            )
        )
    final = states[:, -1]
    stored = float(np.dot(capacities, final[3 : 3 + n] - initial_temp))
    generated, rejected, ambient = (float(x) for x in final[3 + n : 6 + n])
    residual = generated - rejected - ambient - stored
    # Summaries use internal solver nodes as well as requested output timestamps.
    dense_states = solution.sol(np.unique(np.r_[solution.t, times]))
    max_core = float(np.max(dense_states[3]))
    max_surface = float(np.max(dense_states[3 + n - 1]))
    derated = any(
        abs(quantities(t, y)[0]) + 1e-7 < abs(quantities(t, y)[-1])
        for t, y in zip(solution.t, solution.y.T, strict=True)
    )
    stop_reason = next(
        (reason for reason, hits in zip(reasons, solution.t_events, strict=True) if len(hits)),
        "duration_completed",
    )
    warnings = [
        "Illustrative, uncalibrated cell and coolant parameters. Not a safety controller.",
        "Homogeneous pack: identical cell states; no cell variation or manifold gradients.",
        "Prescribed coolant inlet temperature; chiller energy and pack gradients omitted.",
    ]
    if p.simulation_profile.startswith("DEMO"):
        warnings.append("Synthetic current profile, not a certified WLTP or US06 schedule.")
    if p.simulation_profile in {"WLTP_CLASS_3", "US06"} and p.current_points:
        warnings.append("Uploaded trace label is user supplied; compliance is not verified.")
    elif schedule is not None:
        warnings.append("Speed schedule converted with an illustrative vehicle load model.")
        if p.duration_seconds > schedule[0][-1]:
            warnings.append("The standard speed schedule repeats for the requested duration.")
    if cell.electrical_map is not None:
        warnings.append(
            "Electrical maps clamp outside their axes; parameter accuracy is user supplied."
        )
        warnings.append("Mapped RC capacitances use a local empirical voltage-state ECM.")
    if p.coolant_flow_rate_lpm == 0:
        warnings.append("Zero flow disables coolant heat rejection; ambient convection remains.")
    return dict(
        summary=dict(
            max_core_temp_c=max_core,
            max_surface_temp_c=max_surface,
            final_soc=float(final[0]),
            total_heat_generated_kj=generated / 1000,
            cooling_energy_consumed_wh=hydraulics["pump_power_w"] * end / 3600,
            thermal_limit_exceeded=max_core > 45,
            derating_event_triggered=derated,
            elapsed_seconds=end,
            stop_reason=stop_reason,
            stored_thermal_energy_j=stored,
            coolant_heat_rejected_j=rejected,
            ambient_heat_rejected_j=ambient,
            energy_balance_residual_j=residual,
            charge_throughput_ah=float(final[-5]),
            exposure_above_35_c_degree_min=float(final[-4]),
            exposure_above_45_c_degree_min=float(final[-3]),
            delivered_pack_energy_wh=float(final[-2]),
            unmet_drive_energy_wh=float(final[-1]),
        ),
        pack=dict(
            series_cells=p.pack.series_cells,
            parallel_cells=p.pack.parallel_cells,
            cell_count=cell_count,
            capacity_ah=p.nominal_capacity_ah * p.pack.parallel_cells,
            total_heat_generated_kj=generated * cell_count / 1000,
            stored_thermal_energy_j=stored * cell_count,
            coolant_heat_rejected_j=rejected * cell_count,
            ambient_heat_rejected_j=ambient * cell_count,
            energy_balance_residual_j=residual * cell_count,
        ),
        hydraulics=hydraulics,
        timeseries=rows,
        warnings=warnings,
        configuration=p.model_dump(),
    )
