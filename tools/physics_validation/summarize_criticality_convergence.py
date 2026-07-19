"""Summarize source-iteration diagnostics from ``mcgeobridge_criticality``.

The summary is deliberately descriptive: it reports cycle-level variation and
source-bank diversity without declaring that a criticality calculation has
converged.  That judgement also requires independent seeds and a documented
physics-data comparison with the reference calculation.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import fmean


def standard_error(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = fmean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) /
                     (len(values) * (len(values) - 1)))


def linear_slope(values: list[float]) -> float | None:
    """Return an ordinary least-squares slope per cycle, or ``None``."""
    if len(values) < 2:
        return None
    x_mean = (len(values) - 1) / 2.0
    y_mean = fmean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    return sum((index - x_mean) * (value - y_mean)
               for index, value in enumerate(values)) / denominator


def window_summary(values: list[float], window: int) -> dict[str, float | int | None]:
    selected = values[-min(window, len(values)):]
    return {
        "cycles": len(selected),
        "mean": fmean(selected),
        "standard_error": standard_error(selected),
        "minimum": min(selected),
        "maximum": max(selected),
        "linear_slope_per_cycle": linear_slope(selected),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a descriptive convergence summary from a criticality JSON result."
    )
    parser.add_argument("result", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tail", type=int, default=10,
                        help="Number of final active cycles summarized (default: 10)")
    args = parser.parse_args()
    if args.tail < 2:
        parser.error("--tail must be at least 2")

    payload = json.loads(args.result.read_text(encoding="utf-8"))
    if payload.get("status") != "complete":
        raise ValueError("criticality result is not complete")
    active = [float(value) for value in payload.get("active_cycle_keff", [])]
    diagnostics = payload.get("cycle_diagnostics", [])
    active_diagnostics = [item for item in diagnostics if item.get("phase") == "active"]
    if not active or len(active) != len(active_diagnostics):
        raise ValueError("complete active-cycle diagnostics are required")

    entropy = [float(item["source_entropy"]) for item in active_diagnostics]
    occupied = [float(item["source_occupied_bins"]) for item in active_diagnostics]
    fission_neutrons = [float(item["fission_neutrons"]) for item in active_diagnostics]
    summary = {
        "schema_version": 1,
        "source_result": str(args.result),
        "population": payload.get("population"),
        "inactive_cycles": payload.get("inactive_cycles"),
        "active_cycles": len(active),
        "reported_keff": payload.get("keff"),
        "final_active_window": {
            "keff": window_summary(active, args.tail),
            "source_entropy": window_summary(entropy, args.tail),
            "source_occupied_bins": window_summary(occupied, args.tail),
            "fission_neutrons": window_summary(fission_neutrons, args.tail),
        },
        "interpretation": (
            "Descriptive convergence diagnostics only. Do not infer physical "
            "equivalence from this file without independent-seed replication "
            "and documented source, material, and nuclear-data compatibility."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
