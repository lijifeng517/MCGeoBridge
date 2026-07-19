"""Run the minimal Geant4 GDML loader in an isolated process per corpus case."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import subprocess
import time
from pathlib import Path


RESULT_RE = re.compile(r"MCGEOBRIDGE_RESULT\s+(.*)")


def run_case(
    index, source_row, gdml_dir, executable, schema,
    overlap_resolution, overlap_method, overlap_tolerance_mm, point_dir, timeout
):
    path = gdml_dir / f"{source_row['case_id']}.gdml"
    command = [
        executable, str(path), schema, str(overlap_resolution), overlap_method,
        str(overlap_tolerance_mm),
    ]
    point_path = point_dir / f"{source_row['case_id']}.points.tsv" if point_dir else None
    if point_path is not None and point_path.exists():
        command.append(str(point_path))
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        output = "\n".join((completed.stdout, completed.stderr))
        match = RESULT_RE.search(output)
        metrics = {}
        if match:
            for token in match.group(1).split():
                key, value = token.split("=", 1)
                metrics[key] = int(value)
        loaded = bool(match and metrics.get("world") == 1)
        overlap_details = [
            line.partition("MCGEOBRIDGE_OVERLAP_EVENT ")[2]
            for line in output.splitlines()
            if line.startswith("MCGEOBRIDGE_OVERLAP_EVENT ")
        ]
        sampling_details = [
            line.partition("MCGEOBRIDGE_SAMPLING_WARNING ")[2]
            for line in output.splitlines()
            if line.startswith("MCGEOBRIDGE_SAMPLING_WARNING ")
        ]
        row = {
            "case_id": source_row["case_id"],
            "path": str(path),
            "returncode": completed.returncode,
            "loaded": loaded,
            "metrics": metrics,
            "overlap_details": overlap_details,
            "sampling_details": sampling_details,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "error_tail": "\n".join(output.strip().splitlines()[-12:]) if not loaded else "",
        }
    except subprocess.TimeoutExpired as exc:
        row = {
            "case_id": source_row["case_id"],
            "path": str(path),
            "returncode": None,
            "loaded": False,
            "metrics": {},
            "overlap_details": [],
            "sampling_details": [],
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "error_tail": f"timeout: {exc}",
        }
    return index, row


def make_report(
    results, overlap_resolution, overlap_method, overlap_tolerance_mm,
    wall_seconds, complete
):
    completed = [row for row in results if row is not None]
    summary = {
        "total": len(results),
        "completed": len(completed),
        "loaded": sum(bool(row["loaded"]) for row in completed),
        "overlap_checked": overlap_resolution > 0,
        "overlap_method": overlap_method if overlap_resolution > 0 else None,
        "overlap_tolerance_mm": overlap_tolerance_mm if overlap_resolution > 0 else None,
        "zero_overlap_cases": sum(
            bool(row["loaded"]) and row["metrics"].get("overlap_volumes") == 0
            for row in completed
        ) if overlap_resolution > 0 else None,
        "actual_overlap_cases": sum(
            bool(row["loaded"]) and row["metrics"].get("overlap_volumes", 0) > 0
            for row in completed
        ) if overlap_resolution > 0 else None,
        "invalid_surface_cases": sum(
            bool(row["loaded"]) and row["metrics"].get("invalid_surface_volumes", 0) > 0
            for row in completed
        ) if overlap_resolution > 0 else None,
        "clean_overlap_checks": sum(
            bool(row["loaded"])
            and row["metrics"].get("overlap_volumes", 0) == 0
            and row["metrics"].get("invalid_surface_volumes", 0) == 0
            and row["metrics"].get("other_warning_events", 0) == 0
            and row["metrics"].get("interior_sampling_failed_volumes", 0) == 0
            for row in completed
        ) if overlap_resolution > 0 else None,
        "point_checked_cases": sum(
            bool(row["loaded"]) and row["metrics"].get("point_queries", 0) > 0
            for row in completed
        ),
        "point_queries": sum(
            row["metrics"].get("point_queries", 0) for row in completed
        ),
        "point_mismatches": sum(
            row["metrics"].get("point_mismatches", 0) for row in completed
        ),
        "point_missing_solids": sum(
            row["metrics"].get("point_missing_solids", 0) for row in completed
        ),
        "point_mismatch_cases": sum(
            bool(row["loaded"]) and row["metrics"].get("point_mismatches", 0) > 0
            for row in completed
        ),
        "timeouts": sum(row["returncode"] is None for row in completed),
        "interior_sampling_failed_cases": sum(
            bool(row["loaded"])
            and row["metrics"].get("interior_sampling_failed_volumes", 0) > 0
            for row in completed
        ) if overlap_method == "interior" and overlap_resolution > 0 else None,
        "interior_sampling_incomplete_cases": sum(
            bool(row["loaded"])
            and row["metrics"].get("interior_sampling_incomplete_volumes", 0) > 0
            for row in completed
        ) if overlap_method == "interior" and overlap_resolution > 0 else None,
        "case_seconds": round(sum(row["elapsed_seconds"] for row in completed), 6),
        "wall_seconds": round(wall_seconds, 6),
        "complete": complete,
    }
    return {"summary": summary, "results": completed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-report", required=True)
    parser.add_argument("--gdml-dir", required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--overlap-resolution", type=int, default=0)
    parser.add_argument("--overlap-method", choices=("surface", "interior"), default="surface")
    parser.add_argument("--overlap-tolerance-mm", type=float, default=0.02)
    parser.add_argument("--point-dir", default="")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    smoke = json.loads(Path(args.smoke_report).read_text(encoding="utf-8"))
    results = [None] * len(smoke["results"])
    report_path = Path(args.report)
    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                run_case,
                index,
                source_row,
                Path(args.gdml_dir),
                args.executable,
                args.schema,
                args.overlap_resolution,
                args.overlap_method,
                args.overlap_tolerance_mm,
                Path(args.point_dir) if args.point_dir else None,
                args.timeout,
            )
            for index, source_row in enumerate(smoke["results"])
        ]
        for completed_count, future in enumerate(as_completed(futures), 1):
            index, row = future.result()
            results[index] = row
            report = make_report(
                results,
                args.overlap_resolution,
                args.overlap_method,
                args.overlap_tolerance_mm,
                time.perf_counter() - wall_started,
                complete=False,
            )
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            if not row["loaded"]:
                status = "fail"
            elif row["metrics"].get("overlap_volumes", 0) > 0:
                status = "overlap"
            elif row["metrics"].get("invalid_surface_volumes", 0) > 0:
                status = "surface-warning"
            else:
                status = "ok"
            print(
                f"[{completed_count}/{len(results)}] {status} "
                f"{row['case_id']} ({row['elapsed_seconds']:.2f}s)",
                flush=True,
            )

    report = make_report(
        results,
        args.overlap_resolution,
        args.overlap_method,
        args.overlap_tolerance_mm,
        time.perf_counter() - wall_started,
        complete=True,
    )
    summary = report["summary"]
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["loaded"] != summary["total"]:
        raise SystemExit(1)
    if summary["point_mismatches"] or summary["point_missing_solids"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
