"""Run the MCGeoBridge Geant4 fixed-source scorer with dataset discovery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def geant4_dataset_environment(geant4_config: str) -> dict[str, str]:
    completed = subprocess.run(
        [geant4_config, "--datasets"], capture_output=True, text=True, check=True
    )
    environment: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) != 3:
            continue
        _, variable, path = fields
        environment[variable] = path
    if "G4NEUTRONHPDATA" not in environment:
        raise RuntimeError("Geant4 G4NDL dataset was not reported by geant4-config")
    return environment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gdml")
    parser.add_argument("output")
    parser.add_argument("--executable", required=True)
    parser.add_argument("--geant4-config", required=True)
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1234567)
    parser.add_argument("--physics", default="Shielding")
    parser.add_argument("--energy-mev", type=float, default=2.0)
    parser.add_argument("--position-mm", type=float, nargs=3, default=(0.0, 0.0, 0.0))
    parser.add_argument("--direction", type=float, nargs=3, default=(0.0, 0.0, 1.0))
    parser.add_argument("--log")
    parser.add_argument("--compute-volumes", action="store_true")
    args = parser.parse_args()
    if args.events <= 0:
        parser.error("--events must be positive")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        args.executable,
        args.gdml,
        str(output),
        "--events", str(args.events),
        "--seed", str(args.seed),
        "--physics", args.physics,
        "--energy-mev", str(args.energy_mev),
        "--position-mm", *(str(value) for value in args.position_mm),
        "--direction", *(str(value) for value in args.direction),
    ]
    if args.compute_volumes:
        command.append("--compute-volumes")
    environment = os.environ.copy()
    environment.update(geant4_dataset_environment(args.geant4_config))
    completed = subprocess.run(command, capture_output=True, text=True, env=environment)
    combined = "\n".join((completed.stdout, completed.stderr))
    if args.log:
        Path(args.log).write_text(combined, encoding="utf-8")
    if completed.returncode != 0:
        sys.stderr.write(combined)
        raise SystemExit(completed.returncode)
    result = json.loads(output.read_text(encoding="utf-8"))
    if result.get("status") != "complete" or result.get("events") != args.events:
        raise RuntimeError("transport result is incomplete or has an unexpected event count")
    print(json.dumps({
        "status": result["status"],
        "events": result["events"],
        "source_volume": result["source"].get("initial_volume", ""),
        "scored_volumes": len(result.get("volumes", [])),
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
