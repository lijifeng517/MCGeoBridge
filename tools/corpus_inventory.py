"""Inventory and rank candidate MCNP input decks for a validation corpus.

This scanner is intentionally dependency-free.  It does not claim that a file is
valid MCNP; it extracts reproducible geometry-complexity indicators that are
useful before running a stricter parser and converter compatibility check.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


CANDIDATE_SUFFIXES = {".i", ".in", ".inp", ".imcnp", ".mcnp"}
SURFACE_TYPES = {
    "P", "PX", "PY", "PZ",
    "SO", "S", "SX", "SY", "SZ", "SPH",
    "C/X", "C/Y", "C/Z", "CX", "CY", "CZ",
    "K/X", "K/Y", "K/Z", "KX", "KY", "KZ",
    "SQ", "GQ", "TX", "TY", "TZ",
    "RPP", "BOX", "RCC", "RHP", "HEX", "REC", "TRC", "ELL", "WED", "ARB",
}
FEATURE_PATTERNS = {
    "union": re.compile(r":"),
    "cell_complement": re.compile(r"(?<!\S)#\s*\d+", re.I),
    "group_complement": re.compile(r"#\s*\(", re.I),
    "universe": re.compile(r"\bU\s*=", re.I),
    "fill": re.compile(r"\bFILL\s*=", re.I),
    "lattice": re.compile(r"\bLAT\s*=", re.I),
    "trcl": re.compile(r"\bTRCL\s*=", re.I),
    "transform": re.compile(r"(?im)^\s*\*?TR\d*\b"),
    "like_but": re.compile(r"\bLIKE\s+\d+\s+BUT\b", re.I),
}


def _logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped[:1].lower() == "c" and (
            len(stripped) == 1 or stripped[1:2].isspace()
        ):
            if current:
                lines.append(current)
                current = ""
            continue
        if stripped.startswith("$"):
            continue
        line = line.split("$", 1)[0].strip()
        if not line:
            continue
        if raw[:5].isspace() and current:
            current += " " + line
        else:
            if current:
                lines.append(current)
            current = line
    if current:
        lines.append(current)
    return lines


def _normalized_geometry_hash(lines: list[str]) -> str:
    normalized = "\n".join(re.sub(r"\s+", " ", line.strip().upper()) for line in lines)
    return hashlib.sha256(normalized.encode("utf-8", "replace")).hexdigest()


def inspect_file(path: Path, source: str, root: Path) -> dict[str, object] | None:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            text = raw.decode("latin-1")
        except Exception:
            return None

    lines = _logical_lines(text)
    cells: list[str] = []
    surfaces: list[str] = []
    surface_histogram: dict[str, int] = {}

    for line in lines:
        fields = line.split()
        if len(fields) < 2 or not re.fullmatch(r"[+\-*]?\d+", fields[0]):
            continue
        if len(fields) > 2 and re.fullmatch(r"[+-]?\d+", fields[1]):
            transformed_type = fields[2].upper().replace("_", "/")
            if transformed_type in SURFACE_TYPES:
                surfaces.append(line)
                surface_histogram[transformed_type] = surface_histogram.get(transformed_type, 0) + 1
                continue
        if re.fullmatch(r"[+-]?\d+", fields[1]):
            cells.append(line)
            continue
        stype_index = 1
        if re.fullmatch(r"[+-]?\d+", fields[1]) and len(fields) > 2:
            stype_index = 2
        stype = fields[stype_index].upper().replace("_", "/")
        if stype in SURFACE_TYPES:
            surfaces.append(line)
            surface_histogram[stype] = surface_histogram.get(stype, 0) + 1

    feature_counts = {name: len(pattern.findall(text)) for name, pattern in FEATURE_PATTERNS.items()}
    macrobodies = sum(surface_histogram.get(k, 0) for k in {"RPP", "BOX", "RCC", "RHP", "HEX", "REC", "TRC", "ELL", "WED", "ARB"})
    quadrics = sum(surface_histogram.get(k, 0) for k in {"K/X", "K/Y", "K/Z", "KX", "KY", "KZ", "SQ", "GQ", "TX", "TY", "TZ"})

    cell_count = len(cells)
    surface_count = len(surfaces)
    feature_diversity = sum(1 for value in feature_counts.values() if value)
    moderate_size = 8 <= cell_count <= 500 and 8 <= surface_count <= 1000
    display_score = (
        min(cell_count, 150) * 0.08
        + min(surface_count, 250) * 0.05
        + feature_diversity * 2.0
        + min(macrobodies, 20) * 0.4
        + min(quadrics, 20) * 0.5
        + (3.0 if feature_counts["fill"] or feature_counts["lattice"] else 0.0)
        + (2.0 if feature_counts["trcl"] or feature_counts["transform"] else 0.0)
    )

    geometry_lines = cells + surfaces
    return {
        "source": source,
        "relative_path": path.relative_to(root).as_posix(),
        "absolute_path": str(path.resolve()),
        "bytes": len(raw),
        "cells": cell_count,
        "surfaces": surface_count,
        "surface_types": len(surface_histogram),
        "surface_histogram": surface_histogram,
        "macrobodies": macrobodies,
        "quadrics": quadrics,
        **feature_counts,
        "feature_diversity": feature_diversity,
        "moderate_size": moderate_size,
        "display_score": round(display_score, 3),
        "geometry_sha256": _normalized_geometry_hash(geometry_lines),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", help="Source repositories or folders")
    parser.add_argument("--json", required=True, dest="json_path")
    parser.add_argument("--csv", required=True, dest="csv_path")
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for value in args.roots:
        root = Path(value).resolve()
        source = root.name
        for path in root.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            # Several established MCNP test suites use extensionless names such
            # as ``INP-fill2`` or ``input_slab``.
            if path.suffix and path.suffix.lower() not in CANDIDATE_SUFFIXES:
                continue
            row = inspect_file(path, source, root)
            if row and (row["cells"] or row["surfaces"]):
                rows.append(row)

    rows.sort(key=lambda row: (-float(row["display_score"]), str(row["source"]), str(row["relative_path"])))
    json_path = Path(args.json_path)
    csv_path = Path(args.csv_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_fields = [key for key in rows[0] if key not in {"surface_histogram", "absolute_path"}] if rows else []
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in csv_fields})

    unique_geometry = len({row["geometry_sha256"] for row in rows})
    moderate = sum(bool(row["moderate_size"]) for row in rows)
    print(json.dumps({"candidates": len(rows), "unique_geometry": unique_geometry, "moderate_size": moderate}, indent=2))


if __name__ == "__main__":
    main()
