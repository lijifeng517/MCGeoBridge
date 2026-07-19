"""Generate candidate pin-centre source locations for four PWR 17x17 assemblies."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--pitch-mm", type=float, default=12.5984)
    parser.add_argument("--assembly-centre-mm", type=float, default=180.0)
    parser.add_argument("--z-mm", type=float, default=0.0)
    args = parser.parse_args()
    if args.pitch_mm <= 0 or args.assembly_centre_mm <= 0:
        parser.error("pitch and assembly centre must be positive")

    centres = (-args.assembly_centre_mm, args.assembly_centre_mm)
    rows = ["# Candidate PWR lattice pin centres in GDML millimetres.\n"]
    for cx in centres:
        for cy in centres:
            for ix in range(17):
                for iy in range(17):
                    rows.append(
                        f"{cx + (ix - 8) * args.pitch_mm:.6f} "
                        f"{cy + (iy - 8) * args.pitch_mm:.6f} {args.z_mm:.6f}\n"
                    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
