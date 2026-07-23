#!/usr/bin/env python3
"""Run reproducible MCNP-to-GDML conversion timing measurements.

The manuscript should consume the JSON emitted by this script rather than a
hand-maintained runtime table.  Each case specification is
``label|input_path|top_cell_ids``; the third field is optional.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
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


def physical_memory_bytes() -> int | None:
    """Return installed memory without adding a third-party dependency."""
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", type=parse_case, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--converter",
        type=Path,
        help="converter entry point; defaults to src/mcnp2gdml.py in this checkout",
    )
    parser.add_argument(
        "--environment-note",
        default="",
        help="operator-supplied hardware/storage note recorded verbatim with the run",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")

    root = Path(__file__).resolve().parents[1]
    converter = args.converter if args.converter else root / "src" / "mcnp2gdml.py"
    if not converter.is_file():
        raise FileNotFoundError(converter)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count_logical": os.cpu_count(),
            "physical_memory_bytes": physical_memory_bytes(),
            "output_filesystem": os.path.splitdrive(args.output_dir.resolve())[0],
            "environment_note": args.environment_note,
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
        quartiles = statistics.quantiles(durations, n=4, method="inclusive") if len(durations) > 1 else [durations[0]] * 3
        report["cases"].append(
            {
                "label": label,
                "input": str(source),
                "top_cells": top_cells,
                "seconds": durations,
                "median_seconds": statistics.median(durations),
                "minimum_seconds": min(durations),
                "maximum_seconds": max(durations),
                "q1_seconds": quartiles[0],
                "q3_seconds": quartiles[2],
                "iqr_seconds": quartiles[2] - quartiles[0],
                "metrics": gdml_metrics(output),
            }
        )

    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
