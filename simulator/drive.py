"""Longitudinal vehicle load and algebraic pack power balance."""

from functools import lru_cache
from importlib.resources import files

import numpy as np

from simulator.config import SimulationRequest, VehicleParameters


@lru_cache(maxsize=2)
def standard_cycle(name: str):
    root = files("simulator").joinpath("cycles")
    if name == "WLTP_CLASS_3":
        speed = np.fromstring(root.joinpath("wltc_class3b.txt").read_text(), sep=" ")
        time = np.arange(len(speed), dtype=float)
    elif name == "US06":
        data = np.loadtxt(root.joinpath("us06.txt").open(), skiprows=2)
        time, speed = data[:, 0], data[:, 1] * 1.609344
    else:
        raise ValueError("Unknown standard speed cycle")
    time.setflags(write=False)
    speed.setflags(write=False)
    return time, speed


def vehicle_power(speed_m_s: float, acceleration_m_s2: float, v: VehicleParameters) -> float:
    angle = np.arctan(v.road_grade_percent / 100)
    rolling = v.mass_kg * 9.80665 * v.rolling_resistance * np.cos(angle)
    gravity = v.mass_kg * 9.80665 * np.sin(angle)
    drag = 0.5 * v.air_density_kg_m3 * v.drag_coefficient * v.frontal_area_m2 * speed_m_s**2
    inertia = v.mass_kg * v.rotating_mass_factor * acceleration_m_s2
    wheel = (rolling + gravity + drag + inertia) * speed_m_s
    electric = wheel / v.drivetrain_efficiency if wheel >= 0 else wheel * v.regen_efficiency
    return float(electric + v.auxiliary_power_w)


def speed_schedule(p: SimulationRequest):
    if p.simulation_profile == "CUSTOM_SPEED":
        return (
            np.array([x.time_s for x in p.speed_points]),
            np.array([x.speed_kph for x in p.speed_points]),
        )
    if p.simulation_profile in {"WLTP_CLASS_3", "US06"} and not p.current_points:
        return standard_cycle(p.simulation_profile)
    return None


def speed_load(t: float, schedule, p: SimulationRequest):
    times, speeds = schedule
    # Standard cycles repeat only when a longer duration is explicitly requested.
    local = t % times[-1] if t > times[-1] else t
    index = int(np.clip(np.searchsorted(times, local, side="right") - 1, 0, len(times) - 2))
    speed = float(np.interp(local, times, speeds))
    acceleration = (speeds[index + 1] - speeds[index]) / (times[index + 1] - times[index]) / 3.6
    return speed, vehicle_power(speed / 3.6, acceleration, p.vehicle)


def current_for_power(power_w: float, available_voltage: float, r0: float, cells: int):
    per_cell = power_w / cells
    # Use the low-current root; rationalized form also behaves well at zero load.
    discriminant = max(available_voltage**2 - 4 * r0 * per_cell, 0)
    current = 2 * per_cell / (available_voltage + np.sqrt(discriminant))
    physical_limit = available_voltage / (2 * r0)
    return float(np.clip(current, -50, min(50, physical_limit)))
