"""Portable run inputs and tabular exports shared by the UI and CLI."""

import csv
import hashlib
import io
import json

from simulator.config import SimulationRequest


def configuration_id(configuration: dict) -> str:
    request = SimulationRequest.model_validate(configuration)
    normalized = SimulationRequest.model_validate(request.model_dump()).model_dump(mode="json")
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def load_configuration(text: str) -> SimulationRequest:
    payload = json.loads(text)
    if isinstance(payload, dict) and "configuration" in payload:
        payload = payload["configuration"]
    return SimulationRequest.model_validate(payload)


def timeseries_csv(result: dict) -> str:
    rows = []
    for row in result["timeseries"]:
        flattened = {k: v for k, v in row.items() if k != "node_temperatures_c"}
        flattened.update(
            {
                f"thermal_node_{i + 1}_temp_c": value
                for i, value in enumerate(row["node_temperatures_c"])
            }
        )
        rows.append(flattened)
    output = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output.getvalue()
