"""Build reproducible showcase and syntax-coverage selections.

The coverage set is selected mechanically from the inventory: unique geometry,
8--500 cells, and 8--1000 surfaces.  The showcase set is deliberately curated
for recognisable nuclear/engineering geometry and is kept separate so that the
paper does not confuse visual examples with an unbiased compatibility corpus.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


SHOWCASE = [
    {
        "id": "spent_fuel_canister",
        "source": "project-existing/Zenodo",
        "path": "test/engineering_cases/NormalOperation_SpentFuel_mcnp",
        "domain": "spent-fuel storage and criticality",
        "reason": "Recognisable canister, fuel assemblies, pins, and repeated lattice hierarchy.",
        "tier": "primary"
    },
    {
        "id": "zppr20c_fast_reactor",
        "source": "project-existing benchmark",
        "path": "test/ZPPR20C-B6.txt",
        "domain": "fast-reactor critical benchmark",
        "reason": "Large zoned reactor model suitable for a full-model section view.",
        "tier": "primary"
    },
    {
        "id": "elite_fusion_model",
        "source": "F4Enix",
        "path": "docs/source/examples/input/jupyters/E-Lite.i",
        "domain": "fusion neutronics",
        "reason": "Compact ITER E-Lite-like engineering model with many arbitrarily oriented planes.",
        "tier": "primary"
    },
    {
        "id": "he_u_tinkertoy",
        "source": "openmc_mcnp_adapter",
        "path": "tests/models/tinkertoy.mcnp",
        "domain": "criticality assembly",
        "reason": "HEU cylinders, steel rods, universes, fills, and repeated components; already converts in the baseline.",
        "tier": "primary"
    },
    {
        "id": "fusion_tokamak",
        "source": "MontePy",
        "path": "demo/models/fusion_tokomak.imcnp",
        "domain": "fusion reactor concept",
        "reason": "A clear toroidal radial build that directly exercises torus surfaces.",
        "tier": "primary"
    },
    {
        "id": "radiation_room_rotated",
        "source": "mcnpgo",
        "path": "examples/results/newroom_45.mcnp",
        "domain": "shielding room and detector placement",
        "reason": "Room, inserted detector geometry, macrobodies, transforms, universes, fills, and lattices.",
        "tier": "primary"
    },
    {
        "id": "mccad_parts_collection",
        "source": "McCAD-Library",
        "path": "examples/collection_of_solids/MCFile.i",
        "domain": "CAD-to-CSG engineering parts",
        "reason": "Collection of 54 solids and 131 surfaces with matching STEP geometry for visual comparison.",
        "tier": "advanced"
    },
    {
        "id": "geouned_triangle_assembly",
        "source": "GEOUNED",
        "path": "testing/outMCNP/large/Triangle.i",
        "domain": "large CAD-derived assembly",
        "reason": "295 cells and 343 surfaces provide a visually strong stress test.",
        "tier": "advanced"
    }
]


def classify_failure(error_tail: str) -> str:
    last = next((line for line in reversed(error_tail.splitlines()) if line.strip()), "")
    if "Unknown surface type" in last:
        detail = last.split("Unknown surface type", 1)[1].split(" in data line", 1)[0].strip()
        return f"surface_parser:{detail}"
    if "Unexpected character" in last:
        detail = last.split("Unexpected character", 1)[1].split(" in geometry", 1)[0].strip(" :'\"")
        return f"cell_parser:{detail}"
    if "NotImplementedError" in last:
        return "not_implemented"
    if "KeyError" in last:
        return "missing_reference"
    if "ValueError" in last:
        return "other_value_error"
    return "other"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--smoke-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    report = json.loads(Path(args.smoke_report).read_text(encoding="utf-8"))
    result_by_hash = {row["geometry_sha256"]: row for row in report["results"]}

    unique: dict[str, dict] = {}
    for row in inventory:
        if row["moderate_size"]:
            unique.setdefault(row["geometry_sha256"], row)

    coverage = []
    for sha, row in unique.items():
        test = result_by_hash.get(sha, {})
        coverage.append({
            key: row[key] for key in (
                "source", "relative_path", "cells", "surfaces", "surface_types",
                "surface_histogram", "macrobodies", "quadrics", "union",
                "cell_complement", "group_complement", "universe", "fill",
                "lattice", "trcl", "transform", "like_but",
                "feature_diversity", "display_score", "geometry_sha256", "file_sha256"
            )
        } | {
            "baseline_converted": bool(test.get("converted")),
            "baseline_xml_well_formed": bool(test.get("xml_well_formed")),
            "baseline_gdml_integrity_valid": bool(test.get("gdml_integrity_valid")),
            "baseline_warning_count": int(test.get("warning_count", 0)),
            "baseline_warning_categories": test.get("warning_categories", {}),
            "baseline_failure_class": "" if test.get("converted") else classify_failure(test.get("error_tail", ""))
        })

    source_counts = Counter(row["source"] for row in inventory)
    unique_counts = defaultdict(set)
    for row in inventory:
        unique_counts[row["source"]].add(row["geometry_sha256"])
    failures = Counter(row["baseline_failure_class"] for row in coverage if not row["baseline_converted"])

    output = {
        "schema_version": 2,
        "selection_rule": {
            "coverage": "first occurrence of each normalized geometry hash; 8-500 cells; 8-1000 surfaces",
            "showcase": "manual selection for nuclear relevance, visual recognisability, and syntax diversity"
        },
        "summary": {
            "downloaded_candidates": len(inventory),
            "unique_geometries": len({row["geometry_sha256"] for row in inventory}),
            "coverage_cases": len(coverage),
            "baseline_converted": sum(row["baseline_converted"] for row in coverage),
            "baseline_xml_well_formed": sum(row["baseline_xml_well_formed"] for row in coverage),
            "baseline_gdml_integrity_valid": sum(row["baseline_gdml_integrity_valid"] for row in coverage),
            "baseline_geometry_clean": sum(
                not row["baseline_warning_categories"].get("geometry", 0)
                and not row["baseline_warning_categories"].get("bbox", 0)
                and not row["baseline_warning_categories"].get("other", 0)
                for row in coverage
            ),
            "source_material_complete": sum(
                not row["baseline_warning_categories"].get("source_material_missing", 0)
                for row in coverage
            ),
            "source_candidate_counts": dict(sorted(source_counts.items())),
            "source_unique_counts": {key: len(value) for key, value in sorted(unique_counts.items())},
            "baseline_failure_classes": dict(failures.most_common())
        },
        "showcase": SHOWCASE,
        "coverage": coverage
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
