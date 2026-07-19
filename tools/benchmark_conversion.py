#!/usr/bin/env python3
"""Run reproducible MCNP-to-GDML conversion timing measurements.

The manuscript should consume the JSON emitted by this script rather than a
hand-maintained runtime table.  Each case specification is
``label|input_path|top_cell_ids``; the third field is optional.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_case(spec: str) -> tuple[str, Path, str]:
    fields = spec.split("|", 2)
    if len(fields) < 2 or not fields[0] or not fields[1]:
        raise argparse.ArgumentTypeError("case must be label|input_path|top_cell_ids")
    return fields[0], Path(fields[1]), fields[2] if len(fields) == 3 else ""


def gdml_metrics(path: Path) -> dict:
    root = ET.parse(path).getroot()
    return {
        "bytes": path.stat().st_size,
        "solids": len(root.find("solids")),
        "logical_volumes": len(root.find("structure").findall("volume")),
        "placed_volumes": sum(
            len(volume.findall("physvol")) for volume in root.find("structure").findall("volume")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", type=parse_case, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")

    root = Path(__file__).resolve().parents[1]
    converter = root / "src" / "mcnp2gdml.py"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "repeats": args.repeats,
        },
        "cases": [],
    }

    for label, source, top_cells in args.case:
        if not source.is_file():
            raise FileNotFoundError(source)
        output = args.output_dir / f"{label}.gdml"
        durations = []
        for _ in range(args.repeats):
            command = [sys.executable, str(converter), str(source), str(output)]
            if top_cells:
                command.extend(["--top-cells", top_cells])
            started = time.perf_counter()
            subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
            durations.append(time.perf_counter() - started)
        report["cases"].append(
            {
                "label": label,
                "input": str(source),
                "top_cells": top_cells,
                "seconds": durations,
                "median_seconds": statistics.median(durations),
                "metrics": gdml_metrics(output),
            }
        )

    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
