"""Smooth circular parallel-channel approximation of a cold plate."""

from math import log, pi, sqrt

from simulator.config import CoolingParameters


def loop_metrics(flow_lpm: float, p: CoolingParameters) -> dict:
    if flow_lpm == 0:
        return dict(
            reynolds=0.0,
            prandtl=p.heat_capacity_j_kg_k * p.viscosity_pa_s / p.conductivity_w_m_k,
            nusselt=0.0,
            h_w_m2_k=0.0,
            pressure_drop_pa=0.0,
            pump_power_w=0.0,
            regime="stagnant",
        )
    q = flow_lpm / 60000
    velocity = q / (p.parallel_channels * pi * p.channel_diameter_m**2 / 4)
    re = p.density_kg_m3 * velocity * p.channel_diameter_m / p.viscosity_pa_s
    pr = p.heat_capacity_j_kg_k * p.viscosity_pa_s / p.conductivity_w_m_k

    def turbulent(reynolds):
        f = (0.79 * log(reynolds) - 1.64) ** -2
        nu = f / 8 * (reynolds - 1000) * pr / (1 + 12.7 * sqrt(f / 8) * (pr ** (2 / 3) - 1))
        return f, nu

    if re <= 2300:
        friction, nu, regime = 64 / re, 3.66, "laminar"
    elif re < 3000:
        weight = (re - 2300) / 700
        ft, nt = turbulent(3000)
        friction = (1 - weight) * 64 / 2300 + weight * ft
        nu, regime = (1 - weight) * 3.66 + weight * nt, "transition (interpolated)"
    else:
        friction, nu = turbulent(re)
        regime = "turbulent"
    pressure = (
        friction * p.channel_length_m / p.channel_diameter_m * p.density_kg_m3 * velocity**2 / 2
    )
    return dict(
        reynolds=re,
        prandtl=pr,
        nusselt=nu,
        h_w_m2_k=nu * p.conductivity_w_m_k / p.channel_diameter_m,
        pressure_drop_pa=pressure,
        pump_power_w=pressure * q / p.pump_efficiency,
        regime=regime,
    )
