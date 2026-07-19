"""Prepare a documented, non-reference MCNP library-compatibility variant.

This utility exists solely to make local run-chain screening reproducible when
the original deck's named nuclear-data library is unavailable.  It never
changes the source deck.  A generated variant must not be reported as an
original-library reference calculation.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from audit_mcnp_xs_libraries import xsdir_zaids


ZAID_TOKEN = re.compile(r"(?<![A-Za-z0-9])(\d{4,6})\.(\d{2}c)\b", re.IGNORECASE)
FALLBACK_SUFFIX = {"6012": "42c", "6013": "42c", "10020": "42c"}


def normalized_zaid(value: str) -> str:
    return str(int(value))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("xsdir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--preferred-suffix", default="81c")
    parser.add_argument(
        "--omit-unavailable",
        action="store_true",
        help="Omit material-card lines whose ZAID has no local continuous-energy library",
    )
    args = parser.parse_args()
    available = xsdir_zaids(args.xsdir)
    preferred = args.preferred_suffix.lower()
    changes: list[dict[str, str]] = []
    output_lines = []
    in_material_cards = False

    for line_no, line in enumerate(args.input.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip().lower()
        if stripped.startswith("m") and len(stripped) > 1 and stripped[1].isdigit():
            in_material_cards = True
        match = ZAID_TOKEN.search(line) if in_material_cards else None
        if not match:
            output_lines.append(line)
            continue
        zaid_text, original_suffix = match.groups()
        zaid = normalized_zaid(zaid_text)
        local_suffixes = available.get(zaid, set())
        if preferred in local_suffixes:
            target_suffix = preferred
        elif FALLBACK_SUFFIX.get(zaid) in local_suffixes:
            target_suffix = FALLBACK_SUFFIX[zaid]
        else:
            target_suffix = None
        if target_suffix is None:
            changes.append({
                "line": str(line_no), "zaid": zaid, "original_suffix": original_suffix.lower(),
                "action": "omitted" if args.omit_unavailable else "unresolved",
            })
            if args.omit_unavailable:
                output_lines.append("c MCGEOBRIDGE_LIBRARY_VARIANT omitted: " + line.strip())
            else:
                output_lines.append(line)
            continue
        replacement = f"{zaid_text}.{target_suffix}"
        output_lines.append(line[:match.start()] + replacement + line[match.end():])
        changes.append({
            "line": str(line_no), "zaid": zaid, "original_suffix": original_suffix.lower(),
            "replacement_suffix": target_suffix, "action": "mapped",
        })

    unresolved = [item for item in changes if item["action"] == "unresolved"]
    if unresolved:
        raise SystemExit(
            "unresolved local ZAIDs; rerun with --omit-unavailable only for a non-reference screening case"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "c MCGEOBRIDGE_LIBRARY_VARIANT: non-reference local compatibility deck",
        "c Do not use as an original-library keff reference; see companion JSON report.",
    ]
    # MCNP treats physical line one as the title card, even when it starts
    # with ``c``.  Preserve the source title in that position.
    if not output_lines:
        raise ValueError("input deck is empty")
    args.output.write_text(
        "\n".join([output_lines[0], *header, *output_lines[1:]]) + "\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": 1,
        "source": str(args.input.resolve()),
        "output": str(args.output.resolve()),
        "xsdir": str(args.xsdir.resolve()),
        "preferred_suffix": preferred,
        "classification": "non-reference local library-compatibility screening",
        "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mapped": sum(item["action"] == "mapped" for item in changes),
                      "omitted": sum(item["action"] == "omitted" for item in changes)}, indent=2))


if __name__ == "__main__":
    main()
