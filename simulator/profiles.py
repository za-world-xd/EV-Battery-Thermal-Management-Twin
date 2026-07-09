import csv
import io

import numpy as np

from simulator.config import CurrentPoint, SimulationRequest, SpeedPoint


def requested_current(t: float, p: SimulationRequest) -> float:
    if p.current_points:
        return float(
            np.interp(
                t, [x.time_s for x in p.current_points], [x.current_a for x in p.current_points]
            )
        )
    if p.simulation_profile == "FAST_CHARGE":
        return -p.charge_c_rate * p.nominal_capacity_ah
    if p.simulation_profile == "CONSTANT_CURRENT":
        return p.constant_current_a
    # Synthetic current schedules, deliberately not labeled as regulated drive cycles.
    phase = t % 120
    if p.simulation_profile == "DEMO_AGGRESSIVE":
        return float(np.interp(phase, [0, 15, 35, 55, 75, 95, 120], [0, 22, 10, -6, 25, 4, 0]))
    return float(np.interp(phase, [0, 20, 40, 60, 80, 100, 120], [0, 7, 4, -2, 0, 5, 0]))


def read_current_csv(text: str) -> list[CurrentPoint]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames != ["time_s", "current_a"]:
        raise ValueError("CSV header must be exactly: time_s,current_a")
    points = []
    for row in reader:
        if len(points) >= 15000:
            raise ValueError("CSV is limited to 15000 samples")
        points.append(CurrentPoint.model_validate(row))
    return points


def read_speed_csv(text: str) -> list[SpeedPoint]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames != ["time_s", "speed_kph"]:
        raise ValueError("CSV header must be exactly: time_s,speed_kph")
    points = []
    for row in reader:
        if len(points) >= 15000:
            raise ValueError("CSV is limited to 15000 samples")
        points.append(SpeedPoint.model_validate(row))
    return points
