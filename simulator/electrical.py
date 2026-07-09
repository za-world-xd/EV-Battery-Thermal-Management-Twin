"""Positive current discharges the cell. RC voltages are polarization drops."""

import numpy as np

from simulator.config import CellParameters


def map_value(name: str, soc: float, temperature_c: float, cell: CellParameters) -> float:
    table = cell.electrical_map
    rows = [np.interp(soc, table.soc, row) for row in getattr(table, name)]
    return float(np.interp(temperature_c, table.temperature_c, rows))


def ocv(soc: float, temperature_c: float, cell: CellParameters) -> float:
    if cell.electrical_map is not None:
        return map_value("ocv_v", soc, temperature_c, cell)
    # Illustrative NMC curve, not a manufacturer characterization table.
    reference = np.interp(soc, [0, 0.1, 0.2, 0.5, 0.8, 1], [3, 3.4, 3.55, 3.7, 3.95, 4.2])
    return float(reference + cell.entropy_coefficient_v_k * (temperature_c - 25))


def resistances(soc: float, temperature_c: float, cell: CellParameters):
    if cell.electrical_map is not None:
        return tuple(
            map_value(name, soc, temperature_c, cell) for name in ("r0_ohm", "r1_ohm", "r2_ohm")
        )
    factor = np.exp(1800 * (1 / (temperature_c + 273.15) - 1 / 298.15))
    factor *= 1 + 0.6 * (2 * soc - 1) ** 2
    return tuple(float(r * factor) for r in (cell.r0_ohm, cell.r1_ohm, cell.r2_ohm))


def polarization_rates(
    current: float,
    v1: float,
    v2: float,
    r1: float,
    r2: float,
    cell: CellParameters,
    soc: float = 0.5,
    temperature_c: float = 25,
):
    c1, c2 = cell.c1_f, cell.c2_f
    if cell.electrical_map is not None:
        c1 = map_value("c1_f", soc, temperature_c, cell)
        c2 = map_value("c2_f", soc, temperature_c, cell)
    return (current - v1 / r1) / c1, (current - v2 / r2) / c2


def heat_terms(
    current: float, v1: float, v2: float, soc: float, temperature_c: float, cell: CellParameters
):
    r0, r1, r2 = resistances(soc, temperature_c, cell)
    # RC capacitors store energy; I*(OCV-V) also includes their storage rate.
    irreversible = current**2 * r0 + v1**2 / r1 + v2**2 / r2
    entropy = cell.entropy_coefficient_v_k
    if cell.electrical_map is not None:
        axis = cell.electrical_map.temperature_c
        # Inside each linear segment use its slope; outside the grid OCV is clamped.
        if temperature_c < axis[0] or temperature_c > axis[-1]:
            entropy = 0.0
        else:
            i = int(
                np.clip(np.searchsorted(axis, temperature_c, side="right") - 1, 0, len(axis) - 2)
            )
            entropy = (ocv(soc, axis[i + 1], cell) - ocv(soc, axis[i], cell)) / (
                axis[i + 1] - axis[i]
            )
    reversible = -current * (temperature_c + 273.15) * entropy
    return irreversible, reversible
