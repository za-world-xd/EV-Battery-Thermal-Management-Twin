"""SI units internally; user-facing temperatures are in degrees Celsius."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class ElectricalMap(Parameters):
    soc: list[float] = Field(min_length=2, max_length=30)
    temperature_c: list[float] = Field(min_length=2, max_length=20)
    ocv_v: list[list[float]]
    r0_ohm: list[list[float]]
    r1_ohm: list[list[float]]
    r2_ohm: list[list[float]]
    c1_f: list[list[float]]
    c2_f: list[list[float]]

    @model_validator(mode="after")
    def check_grid(self):
        import math

        for axis, low, high in [(self.soc, 0, 1), (self.temperature_c, -40, 100)]:
            if not all(math.isfinite(x) and low <= x <= high for x in axis):
                raise ValueError("Map axes must be finite and in the supported range")
            if any(b <= a for a, b in zip(axis, axis[1:], strict=False)):
                raise ValueError("Map axes must increase strictly")
        limits = {
            "ocv_v": (2, 5),
            "r0_ohm": (0.001, 1),
            "r1_ohm": (0.001, 1),
            "r2_ohm": (0.001, 1),
            "c1_f": (100, 1e6),
            "c2_f": (100, 1e6),
        }
        for name, (low, high) in limits.items():
            grid = getattr(self, name)
            if len(grid) != len(self.temperature_c) or any(len(r) != len(self.soc) for r in grid):
                raise ValueError(f"{name} must have temperature rows and SOC columns")
            if not all(math.isfinite(v) and low <= v <= high for row in grid for v in row):
                raise ValueError(f"{name} values must be finite and between {low} and {high}")
        return self


class CellParameters(Parameters):
    electrical_map: ElectricalMap | None = None
    r0_ohm: float = Field(0.018, gt=0, le=1)
    r1_ohm: float = Field(0.010, gt=0, le=1)
    c1_f: float = Field(2400, ge=100, le=1e6)
    r2_ohm: float = Field(0.006, gt=0, le=1)
    c2_f: float = Field(12000, ge=100, le=1e6)
    core_capacity_j_k: float = Field(55, ge=10, le=10000)
    surface_capacity_j_k: float = Field(15, ge=5, le=10000)
    core_surface_resistance_k_w: float = Field(2.0, ge=0.1, le=100)
    contact_resistance_k_w: float = Field(0.3, ge=0.05, le=100)
    contact_area_m2: float = Field(0.004, ge=0.0001, le=1)
    ambient_conductance_w_k: float = Field(0.04, ge=0, le=10)
    entropy_coefficient_v_k: float = Field(0.0001, ge=-0.001, le=0.001)


class CoolingParameters(Parameters):
    # Representative 50/50 WEG properties held constant near room temperature.
    density_kg_m3: float = Field(1060, ge=900, le=1300)
    viscosity_pa_s: float = Field(0.003, ge=0.0005, le=0.05)
    conductivity_w_m_k: float = Field(0.4, ge=0.1, le=1)
    heat_capacity_j_kg_k: float = Field(3300, ge=1000, le=5000)
    channel_diameter_m: float = Field(0.003, ge=0.001, le=0.02)
    channel_length_m: float = Field(0.5, ge=0.01, le=10)
    parallel_channels: int = Field(8, ge=1, le=100)
    pump_efficiency: float = Field(0.45, ge=0.05, le=1)


class CurrentPoint(Parameters):
    time_s: float = Field(ge=0, le=7200)
    current_a: float = Field(ge=-50, le=50)


class SpeedPoint(Parameters):
    time_s: float = Field(ge=0, le=7200)
    speed_kph: float = Field(ge=0, le=300)


class PackParameters(Parameters):
    series_cells: int = Field(96, ge=1, le=300)
    parallel_cells: int = Field(40, ge=1, le=200)


class VehicleParameters(Parameters):
    mass_kg: float = Field(1800, ge=100, le=10000)
    drag_coefficient: float = Field(0.28, ge=0.1, le=1.5)
    frontal_area_m2: float = Field(2.2, ge=0.5, le=10)
    rolling_resistance: float = Field(0.01, ge=0, le=0.1)
    air_density_kg_m3: float = Field(1.225, ge=0.5, le=2)
    drivetrain_efficiency: float = Field(0.9, ge=0.2, le=1)
    regen_efficiency: float = Field(0.65, ge=0, le=1)
    auxiliary_power_w: float = Field(500, ge=0, le=10000)
    road_grade_percent: float = Field(0, ge=-20, le=20)
    rotating_mass_factor: float = Field(1.05, ge=1, le=1.5)


class SimulationRequest(Parameters):
    cell_type: Literal["21700_NMC"] = "21700_NMC"
    nominal_capacity_ah: float = Field(5, ge=0.5, le=20)
    initial_soc: float = Field(0.9, gt=0.02, lt=0.98)
    ambient_temp_c: float = Field(35, ge=-20, le=60)
    initial_temp_c: float | None = Field(None, ge=-20, le=60)
    coolant_flow_rate_lpm: float = Field(4.5, ge=0, le=20)
    coolant_inlet_temp_c: float = Field(22, ge=-20, le=60)
    simulation_profile: Literal[
        "DEMO_URBAN",
        "DEMO_AGGRESSIVE",
        "FAST_CHARGE",
        "CONSTANT_CURRENT",
        "CUSTOM",
        "CUSTOM_SPEED",
        "WLTP_CLASS_3",
        "US06",
    ] = "DEMO_URBAN"
    duration_seconds: float = Field(1800, ge=1, le=7200)
    output_interval_s: float = Field(2, ge=0.5, le=60)
    constant_current_a: float = Field(5, ge=-50, le=50)
    charge_c_rate: float = Field(2, ge=0.1, le=3)
    thermal_nodes: int = Field(2, ge=2, le=8)
    thermal_derating: bool = True
    current_points: list[CurrentPoint] = Field(default_factory=list, max_length=15000)
    speed_points: list[SpeedPoint] = Field(default_factory=list, max_length=15000)
    pack: PackParameters = Field(default_factory=PackParameters)
    vehicle: VehicleParameters = Field(default_factory=VehicleParameters)
    cell: CellParameters = Field(default_factory=CellParameters)
    cooling: CoolingParameters = Field(default_factory=CoolingParameters)

    @model_validator(mode="after")
    def check_trace(self):
        if self.simulation_profile == "CUSTOM" or self.current_points:
            if self.simulation_profile not in {"CUSTOM", "WLTP_CLASS_3", "US06"}:
                raise ValueError("current_points are only used by uploaded current profiles")
            points = self.current_points
            if len(points) < 2 or points[0].time_s != 0:
                raise ValueError("Uploaded profiles need at least two points starting at time_s=0")
            if any(b.time_s <= a.time_s for a, b in zip(points, points[1:], strict=False)):
                raise ValueError("Trace timestamps must increase strictly")
            if points[-1].time_s < self.duration_seconds:
                raise ValueError("Trace must cover the requested simulation duration")
        if self.simulation_profile == "CUSTOM_SPEED":
            points = self.speed_points
            if len(points) < 2 or points[0].time_s != 0:
                raise ValueError("Speed traces need at least two points starting at time_s=0")
            if any(b.time_s <= a.time_s for a, b in zip(points, points[1:], strict=False)):
                raise ValueError("Speed timestamps must increase strictly")
            if points[-1].time_s < self.duration_seconds:
                raise ValueError("Speed trace must cover the requested duration")
        elif self.speed_points:
            raise ValueError("speed_points require CUSTOM_SPEED")
        if self.current_points and self.speed_points:
            raise ValueError("Choose either a current trace or a speed trace")
        return self


class FlowSweepRequest(Parameters):
    simulation: SimulationRequest = Field(default_factory=SimulationRequest)
    flow_rates_lpm: list[float] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def check_flows(self):
        import math

        if any(not math.isfinite(x) or not 0 <= x <= 20 for x in self.flow_rates_lpm):
            raise ValueError("Flow rates must be finite and between 0 and 20 L/min")
        if len(set(self.flow_rates_lpm)) != len(self.flow_rates_lpm):
            raise ValueError("Choose distinct flow rates")
        return self
