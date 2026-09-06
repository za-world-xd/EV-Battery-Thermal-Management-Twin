"""Repeat a saved run with python -m simulator run.json --output repeated.json."""

import argparse
import json
from pathlib import Path

from simulator.reporting import configuration_id, load_configuration, timeseries_csv
from simulator.solver import simulate


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run EV-CellTwin from configuration or saved run JSON"
    )
    parser.add_argument("configuration", type=Path)
    parser.add_argument(
        "--output", type=Path, required=True, help="Destination for complete run JSON"
    )
    parser.add_argument("--csv", type=Path, help="Optional destination for all-node timeseries CSV")
    args = parser.parse_args(argv)
    targets = [args.output] + ([args.csv] if args.csv else [])
    paths = [args.configuration.resolve(), *(target.resolve() for target in targets)]
    if len(set(paths)) != len(paths):
        parser.error("Input, JSON output and CSV output must use different paths")
    try:
        request = load_configuration(args.configuration.read_text(encoding="utf-8-sig"))
        result = simulate(request)
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        if args.csv:
            args.csv.write_text(timeseries_csv(result), encoding="utf-8", newline="")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Simulation failed: {exc}\n")
    print(
        f"Configuration {configuration_id(result['configuration'])}: "
        f"{result['summary']['stop_reason']} at {result['summary']['elapsed_seconds']:.2f} s"
    )
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
