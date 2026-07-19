"""Batch-validate GDML documents against an official Geant4 schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lxml import etree


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    schema_doc = etree.parse(str(Path(args.schema).resolve()))
    schema = etree.XMLSchema(schema_doc)
    files = []
    for value in args.paths:
        path = Path(value)
        files.extend(sorted(path.glob("*.gdml")) if path.is_dir() else [path])

    results = []
    for path in files:
        errors = []
        try:
            document = etree.parse(str(path.resolve()))
            valid = schema.validate(document)
            if not valid:
                errors = [
                    {"line": error.line, "column": error.column, "message": error.message}
                    for error in schema.error_log
                ]
        except Exception as exc:  # noqa: BLE001 - validation evidence
            valid = False
            errors = [{"line": 0, "column": 0, "message": f"{type(exc).__name__}: {exc}"}]
        results.append({"path": str(path), "valid": valid, "errors": errors})

    report = {
        "schema": str(Path(args.schema)),
        "summary": {"total": len(results), "valid": sum(bool(row["valid"]) for row in results)},
        "results": results,
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    if report["summary"]["valid"] != report["summary"]["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
