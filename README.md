# EV-CellTwin

EV-CellTwin is an educational electro-thermal simulation workbench for exploring how
an electric-vehicle battery cell responds to changing electrical loads and liquid
cooling conditions. It models one representative lithium-ion cell and can scale that
cell to a homogeneous series/parallel pack. The project is intended to make the
relationship between current, voltage, heat generation, temperature, coolant flow,
and delivered energy visible in a reproducible local application.

The default parameters are illustrative rather than measured. This project is not a
calibrated digital twin, a battery-management system, a safety controller, or a
replacement for experimentally validated engineering analysis.

## What the project does

For each simulation, EV-CellTwin:

1. Selects a current, charging, drive-speed, or uploaded trace profile.
2. Solves the cell's electrical state using an OCV model and two RC polarization
   branches.
3. Converts electrical losses and reversible heat into thermal generation.
4. Propagates heat through a lumped two-to-eight-node finite-volume thermal network.
5. Estimates cold-plate convection, coolant heat rejection, pressure drop, and pump
   energy for the requested flow rate.
6. Stops when illustrative SOC, voltage, or temperature limits are reached, while
   recording warnings, energy balances, thermal exposure, and the complete time series.

The same simulation engine powers all three interfaces:

- **Streamlit dashboard** — interactively configure runs, inspect plots, compare flow
  rates, pin a baseline, and export JSON or CSV results.
- **FastAPI service** — submit simulations and flow sweeps programmatically through
  `/api/v1/simulate` and `/api/v1/flow-sweep`; interactive OpenAPI documentation is
  available at `/docs`.
- **Command-line replay** — rerun a saved configuration or complete result without
  opening a browser, which helps reproduce calculations after exporting them.

## How the model is organized

```text
load profile / vehicle speed
          |
          v
  electrical 2RC cell model ---> cell current, voltage, SOC, heat
          |                                      |
          v                                      v
  pack scaling                         thermal network (2-8 nodes)
                                                 |
                              cold-plate hydraulics and coolant heat rejection
                                                 |
                                                 v
                                  temperatures, energy, warnings, reports
```

The electrical model treats positive current as discharge and negative current as
charge. A vehicle speed profile is converted to pack power using inertia, aerodynamic
drag, rolling resistance, road grade, drivetrain efficiency, regenerative efficiency,
and auxiliary load before the battery current is solved. The pack representation
shares one state across all cells; it does not simulate cell imbalance, module
gradients, or coolant manifold distribution.

## Repository layout

| Path | Purpose |
| --- | --- |
| [`simulator/`](simulator) | Core configuration, profiles, electrical, thermal, cooling, solver, analysis, and reporting code |
| [`app/dashboard.py`](app/dashboard.py) | Streamlit user interface |
| [`app/api.py`](app/api.py) | FastAPI application and HTTP endpoints |
| [`data/`](data) | Example current/speed traces and an explicitly synthetic electrical map |
| [`tests/`](tests) | Physics, API, reporting, feature, and dashboard-flow tests |
| [`compose.yaml`](compose.yaml) | Docker Compose definition for the dashboard and API |

Use the dashboard for exploration, the API for integration, and the CLI for
repeatable offline runs. See the sections below for setup, request examples,
supported profiles, exports, assumptions, and validation boundaries.

## Run locally

Python 3.11+ is required. From this directory on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m streamlit run app/dashboard.py
```

Open http://localhost:8501. In another terminal, start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

API documentation: http://localhost:8000/docs. On Linux/macOS, replace
`.\.venv\Scripts\python.exe` with `.venv/bin/python`.

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=simulator --cov=app.api
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Docker configuration is provided: `docker compose up --build` starts both services.
The dashboard runs the same solver locally and does not require the API service.
No public deployment or live demo is assumed.
Docker has not been built in the development environment. The dashboard is a functional
draft without visual direction; browser/mobile and keyboard inspection remain pending.

## API example

POST `/api/v1/simulate` with JSON:

```json
{
  "initial_soc": 0.7,
  "initial_temp_c": 30,
  "ambient_temp_c": 35,
  "coolant_flow_rate_lpm": 4.5,
  "coolant_inlet_temp_c": 22,
  "simulation_profile": "DEMO_URBAN",
  "duration_seconds": 1800,
  "thermal_nodes": 2
}
```

The response exposes summary fields at the top level for the original API contract,
alongside `summary`, `pack`, `hydraulics`, `timeseries`, `warnings`, and the
complete `configuration`. Timeseries include current, SOC, voltage, temperatures,
and heat terms. Summary temperatures use adaptive solver nodes as well as output
samples; they are numerical estimates of peaks, not guaranteed continuous maxima.

Supported profiles: `DEMO_URBAN`, `DEMO_AGGRESSIVE`, `CONSTANT_CURRENT`,
`FAST_CHARGE`, `CUSTOM`, `CUSTOM_SPEED`, `WLTP_CLASS_3`, and `US06`.
Demo profiles are synthetic.
Fast charge requests a constant 0.1C to 3C current, with thermal derating and
voltage/SOC cutoffs; it does not implement a full CC-CV charger.

Uploaded profiles require `current_points`, for example:

```json
{
  "simulation_profile": "CUSTOM",
  "duration_seconds": 10,
  "current_points": [
    {"time_s": 0, "current_a": 0},
    {"time_s": 5, "current_a": 5},
    {"time_s": 10, "current_a": 0}
  ]
}
```

Dashboard CSV uploads use exactly `time_s,current_a`, with strictly increasing
times starting at zero and covering the requested duration. The sample in
`data/example_current.csv` covers 120 seconds. Values interpolate linearly.
WLTP_CLASS_3 uses the bundled 1800-second WLTC Class 3b speed schedule from JRC.
US06 uses the bundled 600-second EPA speed schedule. Both work offline without an
upload. Longer requested runs repeat the schedule and report a warning. You can
override either with an uploaded current trace, whose compliance is not verified.
These speed profiles do not constitute a certified regulatory test.

CUSTOM_SPEED accepts `speed_points` with `time_s` and `speed_kph`, or a dashboard
CSV with the header `time_s,speed_kph`. See `data/example_speed.csv` (60 seconds).
The vehicle model converts speed and interval acceleration to pack power using
inertia, aerodynamic drag, rolling resistance, road grade, drivetrain efficiency,
regenerative efficiency and auxiliary load. The algebraic battery power balance
then determines cell current. Inputs live in the `vehicle` request object.
The low-current electrical root and a 50 A per-cell limit bound the demand.
Thermal derating can reduce delivered power further. `unmet_drive_energy_wh`
records the discrepancy while the simulation runs. The speed schedule remains imposed;
this is not a forward vehicle dynamics model that slows down when power is limited.
Requests reject unknown fields, non-finite numbers, and out-of-range values.

## Pack and cooling comparisons

The `pack` request object defaults to `series_cells=96, parallel_cells=40`.
For an isolated cell, set both to 1. Inputs and original summary temperatures,
SOC, capacity and heat remain per-cell; pack voltage/current, capacity and aggregate
thermal energies are reported separately. All cells share the same state, so this
does not resolve imbalances, module gradients or coolant manifold flow distribution.
The specified flow and pump power belong to the entire pack cold plate. Aggregate
heat exchange is limited by the coolant heat-capacity rate, shared among all cells.

POST `/api/v1/flow-sweep` to compare two to eight distinct flow rates:

```json
{
  "simulation": {
    "simulation_profile": "US06",
    "duration_seconds": 600,
    "initial_soc": 0.8
  },
  "flow_rates_lpm": [0, 2, 4.5, 8]
}
```

The dashboard's flow comparison uses the last saved simulation configuration.
It plots peak core temperature against pump energy and exports the comparison.
Reports include delivered energy, elapsed duration, final SOC, charge throughput,
and integrated temperature excess above 35/45 Celsius in degree-minutes. Compare
delivered energy and duration too: derating/cutoffs can change the served load.
Thermal exposure is a stress indicator, not a battery lifespan or SOH prediction.

## Compare and reproduce runs

Use **Pin this run as baseline** to retain a successful run in the current browser
session. Later simulations overlay its core-temperature curve and show changes in
peak temperature, final SOC and pump energy. **Clear baseline** removes the reference.
Check duration and delivered energy before interpreting lower temperatures: a run
that stopped early may have served less load. Baselines last only for the session;
download the complete run JSON to keep a permanent record.

Each result displays a short SHA-256 configuration ID. Inputs with different JSON
key ordering or equivalent numeric types produce the same ID. This identifies inputs;
it does not encode the software revision. Keep the code version with exported runs
when comparing calculations made after model changes.

Replay a configuration JSON or a downloaded complete run without starting a browser:

```powershell
.\.venv\Scripts\python.exe -m simulator celltwin-run.json --output artifacts/repeated-run.json --csv artifacts/repeated-run.csv
```

The command creates destination directories and rejects input/output path collisions.
The CSV includes every thermal node as a separate unit-labeled column, along with
the electrical, pack and heat quantities. The dashboard uses the same CSV exporter.

## Electrical parameter maps

The optional `cell.electrical_map` object accepts SOC and temperature axes, plus
`ocv_v`, `r0_ohm`, `r1_ohm`, `r2_ohm`, `c1_f`, and `c2_f` matrices. Rows correspond
to temperatures and columns to SOC. Each axis must increase strictly; matrices
must match both axes and contain finite, physically bounded values. Bilinear
interpolation supplies all six state-dependent parameters, clamped at grid edges.
The temperature slope of the mapped OCV supplies the reversible heat coefficient.
Outside the temperature grid, the clamped OCV has zero temperature slope.

`data/illustrative_cell_map.json` is an explicitly synthetic example, not measured
cell characterization. Paste its contents into the dashboard parameter-overrides
field, or merge its `cell` object into an API request. The same field accepts
`cooling` geometry/property overrides and `vehicle` model overrides. Saved run JSON
contains every parameter needed to repeat a calculation.

## Model and units

Positive current means discharge; negative current means charge. Temperature
inputs/outputs are Celsius, but the entropic heat term uses Kelvin.

```text
V = OCV(SOC,T) - I R0 - v1 - v2
dSOC/dt = -I / (3600 capacity_Ah)
dvk/dt = (I - vk/Rk) / Ck
Q_irreversible = I² R0 + v1²/R1 + v2²/R2
Q_reversible = -I T dOCV/dT
```

`I*(OCV-V)` includes energy storage in the polarization capacitors, so this
implementation uses resistor dissipation for thermal generation. R0/R1/R2 vary
with temperature and SOC. Without a map, C1/C2 and the entropic coefficient remain
constant illustrative inputs. With a map, the local voltage-state ECM uses mapped
capacitances and resistances; it does not model energy exchanged by changing
empirical capacitance parameters. No aging or SOH evolution is implemented.

Thermal nodes form a finite-volume chain: the first node receives heat, adjacent
nodes exchange heat, and the final casing node exchanges with coolant and ambient.
Core capacitance is distributed among internal nodes; surface capacitance is
assigned to the casing. Equal links sum to the specified core-to-surface resistance.
This is a lumped spatial approximation, not a cylindrical geometry-resolved PDE.
Energy integrals track generation, coolant rejection, ambient rejection, and storage.

Hydraulics approximate parallel smooth circular channels with constant representative
50/50 water/ethylene glycol properties. Laminar flow uses Darcy f=64/Re and Nu=3.66;
Re=2300 to 3000 interpolates to the turbulent branch, which uses Gnielinski.
Hydraulic diameter alone would not accurately describe arbitrary microchannels.
Pressure includes straight-channel friction only; fittings and manifolds are omitted.
Laminar pressure drop scales linearly with flow, not quadratically. Pump electrical
power is pressure drop times volumetric flow divided by efficiency.

Cell coolant conductance includes contact resistance and a finite coolant capacity-rate
correction. The inlet temperature is prescribed, the outlet is not a dynamic state,
and no radiator or chiller energy is included. Pump energy applies to the complete
cold-plate loop. The `pack` output scales representative-cell thermal energies
by the cell count; shared coolant heat capacity bounds aggregate rejection.
At zero flow coolant rejection is disabled while ambient convection remains.

Current derating decreases linearly between 45 and 55 °C. Integration stops at
2%/98% SOC, 2.5/4.25 V, or 65 °C. These limits illustrate control behavior and
are not validated operating limits for a particular cell. There is no runaway model.

## Validation and next inputs

Tests check thermal energy conservation, analytical RC relaxation, coulomb counting,
hydraulic scaling, zero-flow equilibrium, cooling response, derating, cutoff events,
CSV validation, parameter-map interpolation, speed-to-power/current balance, pack
scaling, trace hashes, flow comparison, API behavior, and dashboard flows.
Integration restarts at trace knots so narrow uploaded pulses cannot be skipped
between adaptive RK45 steps. Coverage is measured when tests run;
there is no claimed experimental accuracy.

For quantitative engineering use, supply measured OCV/SOC/temperature and pulse-test
RC maps, thermal characterization, coolant property tables, actual cold-plate geometry,
and measured current traces with temperature/voltage validation data. A pack model
beyond homogeneous scaling also needs cell variability and a coolant manifold model.
Publishing requires a repository remote and a hosting choice. No credentials are
needed to run this project locally.

Original briefs, local guides, agent instructions, private data, environments, and
generated reports are ignored by Git. This README stays tracked so a checkout can
be installed and run.

## References

- [MathWorks equivalent circuit battery](https://www.mathworks.com/help/autoblks/ref/equivalentcircuitbattery.html), electrical model and temperature-dependent parameters.
- [Sandia, Rosewater dissertation](https://www.sandia.gov/app/uploads/sites/163/2021/08/DM_Rosewater_Dissertation.pdf), equivalent-circuit battery heat generation.
- [COMSOL pipe heat transfer equations](https://doc.comsol.com/6.3/doc/com.comsol.help.pipe/pipe_ug_heattransfer.06.17.html), laminar and Gnielinski convection regimes.
- [EPA driving schedules](https://www.epa.gov/vehicle-and-fuel-emissions-testing/dynamometer-drive-schedules), source of the bundled US06 trace.
- [JRC WLTP repository](https://github.com/JRCSTU/wltp), source of the bundled WLTC Class 3b trace.

Bundled data provenance, checksums, and third-party license details are in
`THIRD_PARTY_NOTICES.txt`. The JRC trace retains its EUPL license; the original
project code uses MIT.

These sources support model structure, not the illustrative default parameter values.
