"""Run with streamlit run app/dashboard.py after installing the project."""

import json

import plotly.graph_objects as go
import streamlit as st
from pydantic import ValidationError

from simulator.analysis import flow_sweep
from simulator.config import FlowSweepRequest, SimulationRequest
from simulator.profiles import read_current_csv, read_speed_csv
from simulator.reporting import configuration_id, timeseries_csv
from simulator.solver import simulate

st.set_page_config(page_title="EV-CellTwin | Thermal workbench", layout="wide")
st.title("EV-CellTwin")
st.caption("Representative-cell electro-thermal workbench · draft without visual direction")
st.warning(
    "Educational model with illustrative parameters. Requires experimental calibration. "
    "Do not use its temperature limits as a battery safety controller."
)

with st.sidebar:
    st.header("Operating conditions")
    profile = st.selectbox(
        "Current profile",
        [
            "DEMO_URBAN",
            "DEMO_AGGRESSIVE",
            "FAST_CHARGE",
            "CONSTANT_CURRENT",
            "CUSTOM",
            "CUSTOM_SPEED",
            "WLTP_CLASS_3",
            "US06",
        ],
    )
    duration = st.number_input("Duration (s)", 1, 7200, 1800)
    soc = st.slider("Initial state of charge", 0.03, 0.97, 0.70, 0.01)
    temperature = st.number_input("Initial cell temperature (°C)", -20.0, 60.0, 30.0)
    ambient = st.number_input("Ambient temperature (°C)", -20.0, 60.0, 35.0)
    inlet = st.number_input("Coolant inlet temperature (°C)", -20.0, 60.0, 22.0)
    flow = st.number_input("Cold-plate flow (L/min)", 0.0, 20.0, 4.5, 0.25)
    capacity = st.number_input("Nominal capacity (Ah)", 0.5, 20.0, 5.0, 0.5)
    nodes = st.selectbox("Thermal nodes", [2, 4, 6, 8])
    derating = st.checkbox("Derate current above 45 °C", True)
    rate = st.number_input("Charge rate (C)", 0.1, 3.0, 2.0, 0.1, disabled=profile != "FAST_CHARGE")
    current = st.number_input(
        "Constant current (A, positive discharges)",
        -50.0,
        50.0,
        5.0,
        disabled=profile != "CONSTANT_CURRENT",
    )
    uploaded = st.file_uploader(
        "Current trace CSV",
        type=["csv"],
        disabled=profile not in {"CUSTOM", "CUSTOM_SPEED", "WLTP_CLASS_3", "US06"},
    )
    st.caption(
        "Current CSV: time_s,current_a. Custom speed CSV: time_s,speed_kph. "
        "WLTP Class 3b and US06 use bundled speed traces unless a current CSV is supplied. "
        "Standard schedules repeat when duration exceeds their length."
    )
    st.subheader("Pack and vehicle")
    series = st.number_input("Cells in series", 1, 300, 96)
    parallel = st.number_input("Cells in parallel", 1, 200, 40)
    mass = st.number_input("Vehicle mass (kg)", 100.0, 10000.0, 1800.0, 50.0)
    auxiliaries = st.number_input("Auxiliary load (W)", 0.0, 10000.0, 500.0, 50.0)
    grade = st.number_input("Road grade (%)", -20.0, 20.0, 0.0, 0.5)
    overrides = st.text_area(
        "Cell, cooling and vehicle overrides (JSON)",
        "{}",
        help="Optional cell/cooling/vehicle objects using the API schema. "
        "Cell.electrical_map accepts temperature rows and SOC columns.",
    )
    run = st.button("Run simulation", type="primary", width="stretch", key="run")

if run:
    try:
        points = []
        speeds = []
        st.session_state.pop("sweep", None)
        if profile in {"CUSTOM", "CUSTOM_SPEED"} and uploaded is None:
            if profile == "CUSTOM":
                raise ValueError("Upload a current trace before running this profile.")
            raise ValueError("Upload a speed trace before running this profile.")
        if uploaded is not None and profile in {"CUSTOM", "CUSTOM_SPEED", "WLTP_CLASS_3", "US06"}:
            if uploaded.size > 2_000_000:
                raise ValueError("CSV must be smaller than 2 MB.")
            text = uploaded.getvalue().decode("utf-8-sig")
            if profile == "CUSTOM_SPEED":
                speeds = read_speed_csv(text)
            else:
                points = read_current_csv(text)
        extra = json.loads(overrides)
        if not isinstance(extra, dict) or set(extra) - {"cell", "cooling", "vehicle"}:
            raise ValueError("Overrides must be an object containing cell, cooling or vehicle.")
        vehicle = dict(mass_kg=mass, auxiliary_power_w=auxiliaries, road_grade_percent=grade)
        if not isinstance(extra.get("vehicle", {}), dict):
            raise ValueError("Vehicle overrides must be an object.")
        vehicle.update(extra.pop("vehicle", {}))
        request = SimulationRequest(
            simulation_profile=profile,
            duration_seconds=duration,
            initial_soc=soc,
            initial_temp_c=temperature,
            ambient_temp_c=ambient,
            coolant_inlet_temp_c=inlet,
            coolant_flow_rate_lpm=flow,
            nominal_capacity_ah=capacity,
            thermal_nodes=nodes,
            thermal_derating=derating,
            charge_c_rate=rate,
            constant_current_a=current,
            current_points=points,
            speed_points=speeds,
            pack=dict(series_cells=series, parallel_cells=parallel),
            vehicle=vehicle,
            **extra,
        )
        with st.spinner("Integrating electrical and thermal states..."):
            st.session_state["result"] = simulate(request)
    except (ValueError, ValidationError, RuntimeError) as exc:
        st.session_state.pop("result", None)
        st.error(str(exc))

result = st.session_state.get("result")
if result is None:
    st.info("Choose operating conditions, then run a simulation to view temperatures and energy.")
else:
    st.caption(
        f"Configuration {configuration_id(result['configuration'])}. "
        "Run again after changing inputs. Download the run JSON to save these inputs."
    )
    summary = result["summary"]
    baseline = st.session_state.get("baseline")
    baseline_summary = baseline["summary"] if baseline is not None else None
    pump_delta = (
        summary["cooling_energy_consumed_wh"] - baseline_summary["cooling_energy_consumed_wh"]
        if baseline_summary
        else None
    )
    a, b, c = st.columns(3)
    a.metric(
        "Peak core",
        f"{summary['max_core_temp_c']:.2f} °C",
        delta=(
            f"{summary['max_core_temp_c'] - baseline_summary['max_core_temp_c']:+.2f} °C"
            if baseline_summary
            else None
        ),
        delta_color="off",
    )
    b.metric(
        "Final SOC",
        f"{summary['final_soc']:.1%}",
        delta=(
            f"{100 * (summary['final_soc'] - baseline_summary['final_soc']):+.2f} percentage points"
            if baseline_summary
            else None
        ),
        delta_color="off",
    )
    c.metric(
        "Pump energy (whole loop)",
        f"{summary['cooling_energy_consumed_wh']:.3f} Wh",
        delta=f"{pump_delta:+.3f} Wh" if pump_delta is not None else None,
        delta_color="off",
    )
    if baseline is not None:
        saved = baseline["configuration"]
        st.caption(
            f"Deltas compare against {configuration_id(saved)}: "
            f"{saved['simulation_profile']}, {saved['coolant_flow_rate_lpm']:g} L/min, "
            f"duration {baseline_summary['elapsed_seconds']:g} s. "
            "Compare elapsed duration and served load before judging temperature changes."
        )
    if st.button("Pin this run as baseline", key="pin_baseline"):
        st.session_state["baseline"] = result
        st.rerun()
    if baseline is not None and st.button("Clear baseline", key="clear_baseline"):
        st.session_state.pop("baseline", None)
        st.rerun()
    st.write(f"Stopped at {summary['elapsed_seconds']:.1f} s: {summary['stop_reason']}.")
    if summary["derating_event_triggered"]:
        st.warning("Thermal derating reduced the requested current during this run.")
    if summary["thermal_limit_exceeded"]:
        st.warning("Core temperature exceeded the illustrative 45 °C threshold.")

    rows = result["timeseries"]
    time = [r["time_s"] for r in rows]

    def chart(title, fields, unit):
        figure = go.Figure()
        for field, label, color, dash in fields:
            figure.add_trace(
                go.Scatter(
                    x=time,
                    y=[r[field] for r in rows],
                    name=label,
                    line=dict(color=color, dash=dash),
                )
            )
        if title == "Core and casing response" and baseline is not None:
            reference = baseline["timeseries"]
            figure.add_trace(
                go.Scatter(
                    x=[r["time_s"] for r in reference],
                    y=[r["core_temp_c"] for r in reference],
                    name="Baseline core",
                    line=dict(color="#555555", dash="dot"),
                )
            )
        figure.update_layout(
            title=title,
            xaxis_title="Time (s)",
            yaxis_title=unit,
            template="plotly_white",
            height=340,
            legend=dict(orientation="h", y=-0.3),
            margin=dict(l=35, r=15),
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    chart(
        "Core and casing response",
        [
            ("core_temp_c", "Core", "#a33b20", "solid"),
            ("surface_temp_c", "Surface", "#245b72", "dash"),
        ],
        "Temperature (°C)",
    )
    st.subheader("Electrical load and heat")
    chart(
        "Applied current",
        [
            ("current_a", "Applied", "#245b72", "solid"),
            ("requested_current_a", "Requested", "#555555", "dot"),
        ],
        "Current (A)",
    )
    chart(
        "Terminal voltage",
        [("terminal_voltage_v", "Cell voltage", "#245b72", "solid")],
        "Voltage (V)",
    )
    chart(
        "Heat generation",
        [
            ("ohmic_heat_w", "Ohmic", "#a33b20", "solid"),
            ("polarization_heat_w", "Polarization", "#555555", "dot"),
            ("entropic_heat_w", "Reversible", "#245b72", "dash"),
        ],
        "Power (W)",
    )
    st.subheader("Energy accounting and coolant loop")
    st.json(
        {
            "thermal_energy": {k: v for k, v in summary.items() if k.endswith("_j")},
            "hydraulics": result["hydraulics"],
            "homogeneous_pack": result["pack"],
            "exposure_indicators": {
                k: v for k, v in summary.items() if "exposure_" in k or "throughput" in k
            },
        },
        expanded=True,
    )
    for warning in result["warnings"]:
        st.caption(warning)
    with st.expander("Reproduce this run"):
        st.json(result["configuration"])
    st.download_button(
        "Download timeseries CSV", timeseries_csv(result), "celltwin-timeseries.csv", "text/csv"
    )
    st.download_button(
        "Download complete run JSON",
        json.dumps(result, indent=2),
        "celltwin-run.json",
        "application/json",
    )

    if rows[0]["speed_kph"] is not None:
        st.subheader("Drive schedule and delivered load")
        chart(
            "Vehicle speed",
            [("speed_kph", "Requested schedule", "#245b72", "solid")],
            "Speed (km/h)",
        )
        chart(
            "Pack power",
            [
                ("pack_power_w", "Delivered", "#245b72", "solid"),
                ("requested_drive_power_w", "Requested", "#555555", "dot"),
            ],
            "Power (W)",
        )
        st.write(
            f"Unmet drive energy: {summary['unmet_drive_energy_wh']:.3f} Wh. "
            "The speed trace is imposed; reduced power does not slow the vehicle model."
        )

st.subheader("Coolant flow comparison")
st.caption(
    "Compare pump energy and thermal exposure using the last saved run. "
    "Exposure is not a lifespan or SOH prediction."
)
flows = st.multiselect(
    "Compare flow rates (L/min)",
    [0.0, 1.0, 2.0, 4.5, 8.0, 12.0, 20.0],
    default=[0.0, 2.0, 4.5, 8.0],
)
if st.button("Compare cooling flows", disabled=result is None, key="compare"):
    try:
        comparison = FlowSweepRequest(simulation=result["configuration"], flow_rates_lpm=flows)
        with st.spinner("Simulating each coolant flow..."):
            st.session_state["sweep"] = flow_sweep(comparison)
    except (ValueError, RuntimeError) as exc:
        st.session_state.pop("sweep", None)
        st.error(str(exc))

if "sweep" in st.session_state:
    sweep = st.session_state["sweep"]
    st.dataframe(sweep["runs"], hide_index=True)
    fig = go.Figure(
        go.Scatter(
            x=[r["cooling_energy_consumed_wh"] for r in sweep["runs"]],
            y=[r["max_core_temp_c"] for r in sweep["runs"]],
            text=[f"{r['flow_rate_lpm']:g} L/min" for r in sweep["runs"]],
            mode="markers+text",
            textposition="top center",
            marker_color="#96351e",
        )
    )
    fig.update_layout(
        xaxis_title="Pump energy (Wh)",
        yaxis_title="Peak core temperature (°C)",
        template="plotly_white",
        height=360,
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    for note in sweep["warnings"]:
        st.caption(note)
    st.download_button(
        "Download flow comparison JSON",
        json.dumps(sweep, indent=2),
        "celltwin-flow-comparison.json",
        "application/json",
    )
