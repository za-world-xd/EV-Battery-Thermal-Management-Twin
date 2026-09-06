import csv
import io
import json
import subprocess
import sys

import pytest

from simulator.__main__ import main
from simulator.config import SimulationRequest
from simulator.reporting import configuration_id, load_configuration, timeseries_csv
from simulator.solver import simulate


def test_configuration_ids_normalize_key_order_defaults_and_numeric_types():
    config = SimulationRequest().model_dump()
    assert configuration_id(config) == configuration_id(dict(reversed(list(config.items()))))
    assert configuration_id({}) == configuration_id(config)
    assert configuration_id({"nominal_capacity_ah": 5.0}) == configuration_id(config)
    assert configuration_id({"coolant_flow_rate_lpm": 0}) != configuration_id(config)


def test_saved_run_and_bare_config_load_identically():
    request = SimulationRequest(duration_seconds=5)
    result = simulate(request)
    assert load_configuration(json.dumps(result)) == request
    assert load_configuration(request.model_dump_json()) == request
    with pytest.raises(ValueError):
        load_configuration('{"initial_soc":3}')


def test_csv_contains_every_thermal_node_and_preserves_timestamps():
    result = simulate(SimulationRequest(duration_seconds=5, thermal_nodes=4))
    rows = list(csv.DictReader(io.StringIO(timeseries_csv(result))))
    assert len(rows) == len(result["timeseries"])
    assert float(rows[-1]["time_s"]) == 5
    assert "node_temperatures_c" not in rows[0]
    for original, row in zip(result["timeseries"], rows, strict=True):
        for index, value in enumerate(original["node_temperatures_c"], start=1):
            assert float(row[f"thermal_node_{index}_temp_c"]) == value


def test_cli_repeats_exported_run_and_creates_output_directories(tmp_path):
    original = simulate(SimulationRequest(duration_seconds=5))
    source = tmp_path / "saved.json"
    source.write_text(json.dumps(original), encoding="utf-8")
    target = tmp_path / "results" / "repeat.json"
    tabular = tmp_path / "results" / "repeat.csv"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "simulator",
            str(source),
            "--output",
            str(target),
            "--csv",
            str(tabular),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    repeated = json.loads(target.read_text(encoding="utf-8"))
    assert repeated["summary"] == original["summary"]
    assert repeated["configuration"] == original["configuration"]
    assert "thermal_node_2_temp_c" in tabular.read_text(encoding="utf-8")


def test_cli_rejects_invalid_inputs_and_path_collisions(tmp_path, capsys):
    source = tmp_path / "config.json"
    source.write_text('{"initial_soc":3}', encoding="utf-8")
    target = tmp_path / "result.json"
    with pytest.raises(SystemExit) as invalid:
        main([str(source), "--output", str(target)])
    assert invalid.value.code == 1
    assert not target.exists()
    assert "Simulation failed" in capsys.readouterr().err
    with pytest.raises(SystemExit) as collision:
        main([str(source), "--output", str(source)])
    assert collision.value.code == 2
    assert source.read_text(encoding="utf-8") == '{"initial_soc":3}'
