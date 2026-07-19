"""Run MCNP-to-GDML conversion over a ranked external corpus.

Unlike the original engineering smoke runner, this tool preserves warnings,
records timing, verifies that output XML is well formed, and deduplicates decks
by their normalized geometry hash.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from gdml_integrity import validate_gdml_file


def _warning_categories(warnings: list[str]) -> dict[str, int]:
    categories = {"geometry": 0, "material": 0, "source_material_missing": 0, "bbox": 0, "other": 0}
    for warning in warnings:
        lower = warning.lower()
        if "has no m card" in lower:
            categories["source_material_missing"] += 1
        elif "material" in lower or "density" in lower or "atomic mass" in lower:
            categories["material"] += 1
        elif "extents found" in lower or "bbox" in lower:
            categories["bbox"] += 1
        elif any(
            marker in lower
            for marker in ("fallback", "unsupported", "recursive", "cyclic", "lattice", "fill universe")
        ):
            categories["geometry"] += 1
        else:
            categories["other"] += 1
    return categories


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory")
    parser.add_argument("--converter", default="src/mcnp2gdml.py")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--moderate-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    if args.moderate_only:
        rows = [row for row in rows if row.get("moderate_size")]

    deduplicated: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        digest = str(row["geometry_sha256"])
        if digest in seen:
            continue
        seen.add(digest)
        deduplicated.append(row)
    if args.limit > 0:
        deduplicated = deduplicated[: args.limit]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    converter = Path(args.converter).resolve()
    results: list[dict[str, object]] = []

    for index, row in enumerate(deduplicated, 1):
        case_id = f"{index:04d}_{row['source']}_{Path(str(row['relative_path'])).stem}"
        output = output_dir / f"{case_id}.gdml"
        command = [sys.executable, str(converter), str(row["absolute_path"]), str(output)]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                encoding="utf-8",
                errors="replace",
            )
            elapsed = time.perf_counter() - started
            combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
            warnings = [line.strip() for line in combined.splitlines() if "[warn]" in line.lower()]
            warning_categories = _warning_categories(warnings)
            xml_ok = False
            xml_error = ""
            if completed.returncode == 0 and output.exists():
                try:
                    ET.parse(output)
                    xml_ok = True
                except Exception as exc:  # noqa: BLE001 - recorded as test evidence
                    xml_error = f"{type(exc).__name__}: {exc}"
            integrity = validate_gdml_file(output) if xml_ok else {"valid": False, "errors": []}
            error_tail = "\n".join(combined.strip().splitlines()[-8:]) if completed.returncode else ""
            result = {
                **row,
                "case_id": case_id,
                "returncode": completed.returncode,
                "converted": completed.returncode == 0 and output.exists(),
                "xml_well_formed": xml_ok,
                "xml_error": xml_error,
                "gdml_integrity_valid": bool(integrity["valid"]),
                "gdml_integrity_errors": integrity["errors"],
                "warning_count": len(warnings),
                "warnings": warnings,
                "warning_categories": warning_categories,
                "error_tail": error_tail,
                "elapsed_seconds": round(elapsed, 6),
                "gdml_bytes": output.stat().st_size if output.exists() else 0,
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                **row,
                "case_id": case_id,
                "returncode": None,
                "converted": False,
                "xml_well_formed": False,
                "xml_error": "timeout",
                "gdml_integrity_valid": False,
                "gdml_integrity_errors": [],
                "warning_count": 0,
                "warnings": [],
                "warning_categories": _warning_categories([]),
                "error_tail": str(exc),
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "gdml_bytes": output.stat().st_size if output.exists() else 0,
            }
        results.append(result)
        status = "ok" if result["converted"] and result["xml_well_formed"] else "fail"
        print(f"[{index}/{len(deduplicated)}] {status}: {row['source']}/{row['relative_path']}")

    summary = {
        "total": len(results),
        "converted": sum(bool(row["converted"]) for row in results),
        "xml_well_formed": sum(bool(row["xml_well_formed"]) for row in results),
        "gdml_integrity_valid": sum(bool(row["gdml_integrity_valid"]) for row in results),
        "with_warnings": sum(int(row["warning_count"]) > 0 for row in results),
        "geometry_clean": sum(
            int(row["warning_categories"]["geometry"]) == 0
            and int(row["warning_categories"]["bbox"]) == 0
            and int(row["warning_categories"]["other"]) == 0
            for row in results
        ),
        "source_material_complete": sum(
            int(row["warning_categories"]["source_material_missing"]) == 0 for row in results
        ),
        "timeouts": sum(row["xml_error"] == "timeout" for row in results),
        "elapsed_seconds": round(sum(float(row["elapsed_seconds"]) for row in results), 6),
    }
    report = {"summary": summary, "results": results}
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
