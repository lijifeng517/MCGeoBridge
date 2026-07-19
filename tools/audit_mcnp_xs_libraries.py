"""Audit whether an MCNP material-card library suffix can be reproduced locally.

The tool intentionally does not modify the input deck.  It records candidate
cross-section identifiers so that any later material-library adaptation remains
reviewable and can be excluded from a reference calculation when appropriate.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


ZAID_TOKEN = re.compile(r"(?<![A-Za-z0-9])(\d{4,6})\.(\d{2}c)\b", re.IGNORECASE)


def normalized_zaid(value: str) -> str:
    return str(int(value))


def deck_zaids(path: Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        for match in ZAID_TOKEN.finditer(line):
            zaid, suffix = match.groups()
            found.setdefault(normalized_zaid(zaid), set()).add(suffix.lower())
    return found


def xsdir_zaids(path: Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        fields = line.split()
        if not fields:
            continue
        match = ZAID_TOKEN.fullmatch(fields[0])
        if not match:
            continue
        zaid, suffix = match.groups()
        found.setdefault(normalized_zaid(zaid), set()).add(suffix.lower())
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report local cross-section-library coverage for an MCNP input deck."
    )
    parser.add_argument("input", type=Path, help="MCNP input deck")
    parser.add_argument("xsdir", type=Path, help="MCNP XSDIR index")
    parser.add_argument("output", type=Path, help="JSON audit output")
    parser.add_argument(
        "--preferred-suffix",
        default="81c",
        help="Preferred local continuous-energy suffix to assess (default: 81c)",
    )
    args = parser.parse_args()

    requested = deck_zaids(args.input)
    available = xsdir_zaids(args.xsdir)
    entries = []
    for zaid in sorted(requested, key=int):
        local = sorted(available.get(zaid, set()))
        original = sorted(requested[zaid])
        entries.append({
            "zaid": zaid,
            "deck_suffixes": original,
            "preferred_suffix_available": args.preferred_suffix.lower() in local,
            "available_suffixes": local,
            "status": "available" if local else "unavailable",
        })

    status_counts = Counter(item["status"] for item in entries)
    preferred_count = sum(item["preferred_suffix_available"] for item in entries)
    report = {
        "schema_version": 1,
        "input": str(args.input.resolve()),
        "xsdir": str(args.xsdir.resolve()),
        "preferred_suffix": args.preferred_suffix.lower(),
        "summary": {
            "unique_zaids": len(entries),
            "available_locally": status_counts["available"],
            "unavailable_locally": status_counts["unavailable"],
            "available_with_preferred_suffix": preferred_count,
        },
        "interpretation": (
            "This is an availability audit, not an authorization to substitute "
            "nuclear data. Any mapped or omitted nuclide must be documented and "
            "the resulting calculation treated as a separately qualified case."
        ),
        "nuclides": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
