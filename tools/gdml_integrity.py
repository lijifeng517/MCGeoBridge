"""Check internal name and reference integrity of generated GDML files.

This is intentionally independent of Geant4.  It catches dangling references,
duplicate identifiers, and missing setup/world declarations before the more
expensive schema and Geant4 loading stages.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def _names(parent):
    if parent is None:
        return []
    return [node.get("name") for node in list(parent) if node.get("name")]


def _duplicates(names):
    return sorted(name for name, count in Counter(names).items() if count > 1)


def validate_gdml_file(path: str | Path) -> dict[str, object]:
    path = Path(path)
    errors: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:  # noqa: BLE001 - validation evidence
        return {"path": str(path), "valid": False, "errors": [f"XML parse error: {exc}"]}

    define = root.find("define")
    materials = root.find("materials")
    solids = root.find("solids")
    structure = root.find("structure")
    setup = root.find("setup")

    define_names = set(_names(define))
    material_names = set(_names(materials))
    solid_names = set(_names(solids))
    volume_names = set(_names(structure))

    for label, names in (
        ("define", _names(define)),
        ("material", _names(materials)),
        ("solid", _names(solids)),
        ("volume", _names(structure)),
    ):
        duplicates = _duplicates(names)
        if duplicates:
            errors.append(f"duplicate {label} names: {', '.join(duplicates[:10])}")

    if structure is not None:
        for ref in structure.findall(".//materialref"):
            if ref.get("ref") not in material_names:
                errors.append(f"dangling materialref: {ref.get('ref')}")
        for ref in structure.findall(".//solidref"):
            if ref.get("ref") not in solid_names:
                errors.append(f"dangling solidref: {ref.get('ref')}")
        for ref in structure.findall(".//volumeref"):
            if ref.get("ref") not in volume_names:
                errors.append(f"dangling volumeref: {ref.get('ref')}")

    if solids is not None:
        for tag in ("first", "second"):
            for ref in solids.findall(f".//{tag}"):
                if ref.get("ref") not in solid_names:
                    errors.append(f"dangling {tag} solid reference: {ref.get('ref')}")

    for parent in (solids, structure):
        if parent is None:
            continue
        for tag in ("positionref", "rotationref", "scaleref"):
            for ref in parent.findall(f".//{tag}"):
                if ref.get("ref") not in define_names:
                    errors.append(f"dangling {tag}: {ref.get('ref')}")

    if materials is not None:
        for fraction in materials.findall(".//fraction"):
            if fraction.get("ref") not in material_names:
                errors.append(f"dangling fraction reference: {fraction.get('ref')}")

    if setup is None:
        errors.append("missing setup element")
    else:
        world = setup.find("world")
        if world is None or world.get("ref") not in volume_names:
            errors.append(f"missing or dangling world reference: {None if world is None else world.get('ref')}")

    return {
        "path": str(path),
        "valid": not errors,
        "errors": errors,
        "counts": {
            "defines": len(define_names),
            "materials_and_elements": len(material_names),
            "solids": len(solid_names),
            "volumes": len(volume_names),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--report")
    args = parser.parse_args()

    files = []
    for value in args.paths:
        path = Path(value)
        files.extend(sorted(path.glob("*.gdml")) if path.is_dir() else [path])
    results = [validate_gdml_file(path) for path in files]
    report = {
        "summary": {"total": len(results), "valid": sum(bool(row["valid"]) for row in results)},
        "results": results,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    if report["summary"]["valid"] != report["summary"]["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
