#!/usr/bin/env python3
"""Aggregate schema-v2 layered geometry-validation records.

The generated JSON is intended to be archived with a manuscript release.  It
keeps the three sampling strata separate so that a total point count cannot be
misread as uniform random sampling alone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    records = []
    aggregate = {
        "cases": 0,
        "cells": 0,
        "points": 0,
        "mismatches": 0,
        "strategy_points": {
            "global_uniform": 0,
            "cell_local": 0,
            "boundary": 0,
        },
        "boundary_pairs": 0,
        "active_boundary_pairs": 0,
        "boundary_surfaces_exercised": 0,
        "boundary_surfaces_skipped": 0,
    }

    for path in sorted(args.record_dir.glob("*.validate.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 2:
            raise ValueError(f"{path}: expected schema_version 2")
        cells = data.get("cells", [])
        totals = data.get("totals", {})
        strategy = {name: 0 for name in aggregate["strategy_points"]}
        for cell in cells:
            for name in strategy:
                strategy[name] += int(cell.get("strategy_points", {}).get(name, 0))

        record = {
            "case": path.name.removesuffix(".validate.json"),
            "cells": len(cells),
            "points": int(totals.get("points", 0)),
            "mismatches": int(totals.get("mismatches", 0)),
            "strategy_points": strategy,
            "boundary_pairs": int(totals.get("boundary_pairs", 0)),
            "active_boundary_pairs": int(totals.get("active_boundary_pairs", 0)),
            "boundary_surfaces_exercised": int(
                totals.get("boundary_surfaces_exercised", 0)
            ),
            "boundary_surfaces_skipped": int(
                totals.get("boundary_surfaces_skipped", 0)
            ),
        }
        records.append(record)

        aggregate["cases"] += 1
        aggregate["cells"] += record["cells"]
        for name in (
            "points",
            "mismatches",
            "boundary_pairs",
            "active_boundary_pairs",
            "boundary_surfaces_exercised",
            "boundary_surfaces_skipped",
        ):
            aggregate[name] += record[name]
        for name, count in strategy.items():
            aggregate["strategy_points"][name] += count

    result = {
        "schema_version": 1,
        "description": (
            "Layered source-expression versus converted-solid membership "
            "validation; boundary points are two points per generated pair."
        ),
        "records": records,
        "aggregate": aggregate,
    }
    output = args.output or args.record_dir / "layered_validation_summary.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aggregate, indent=2))
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
