"""Run a GDML criticality pilot with MCNP-source coordinates mapped by a manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from run_transport_validation import geant4_dataset_environment


def load_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("conversion manifest must contain a JSON object")
    return manifest


def mapped_source_points(points_cm: list[list[float]], manifest: dict) -> list[list[float]]:
    transform = manifest.get("coordinate_transform", {})
    translation = transform.get("translation_cm")
    if not isinstance(translation, list) or len(translation) != 3:
        raise ValueError("manifest does not contain a three-component coordinate translation")
    return [
        [10.0 * (point[axis] + float(translation[axis])) for axis in range(3)]
        for point in points_cm
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gdml")
    parser.add_argument("output")
    parser.add_argument("--executable", required=True)
    parser.add_argument("--geant4-config", required=True)
    parser.add_argument("--population", type=int, default=1000)
    parser.add_argument("--inactive", type=int, default=30)
    parser.add_argument("--active", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1234567)
    parser.add_argument("--physics", default="Shielding")
    parser.add_argument(
        "--disable-hp-fission-fragments",
        action="store_true",
        help="Override a reference list that enables ParticleHP fission-fragment production",
    )
    parser.add_argument("--energy-mev", type=float, default=2.0)
    parser.add_argument("--source-bin-mm", type=float, default=20.0)
    parser.add_argument("--locate-only", action="store_true", help="Report source locations and exit before transport")
    parser.add_argument("--manifest")
    parser.add_argument(
        "--allow-unimplemented-boundaries",
        action="store_true",
        help="Acknowledge that MCNP special boundaries listed in the manifest are not reproduced by this helper",
    )
    parser.add_argument("--mcnp-position-cm", type=float, nargs=3, action="append")
    parser.add_argument("--position-mm", type=float, nargs=3)
    parser.add_argument("--source-points-mm", help="Existing whitespace-delimited GDML-mm source-point file")
    parser.add_argument("--log")
    parser.add_argument("--stream", action="store_true", help="Stream Geant4 output instead of capturing it")
    args = parser.parse_args()
    if args.population <= 0 or args.inactive < 0 or args.active <= 1:
        parser.error("population and active cycles must be positive; inactive cycles non-negative")
    if args.source_bin_mm <= 0:
        parser.error("--source-bin-mm must be positive")
    source_modes = sum(bool(value) for value in (
        args.mcnp_position_cm, args.position_mm, args.source_points_mm
    ))
    if source_modes != 1:
        parser.error("provide exactly one of --mcnp-position-cm, --position-mm, or --source-points-mm")
    if args.mcnp_position_cm and not args.manifest:
        parser.error("--manifest is required with --mcnp-position-cm")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        args.executable, args.gdml, str(output),
        "--population", str(args.population),
        "--inactive", str(args.inactive),
        "--active", str(args.active),
        "--seed", str(args.seed),
        "--physics", args.physics,
        "--energy-mev", str(args.energy_mev),
        "--source-bin-mm", str(args.source_bin_mm),
    ]
    if args.disable_hp_fission_fragments:
        command.append("--disable-hp-fission-fragments")
    if args.locate_only:
        command.append("--locate-only")
    source_point_count = 1
    if args.mcnp_position_cm:
        manifest = load_manifest(Path(args.manifest))
        boundary_info = manifest.get("transport_boundary_conditions", {})
        special_boundaries = boundary_info.get("surfaces", []) if isinstance(boundary_info, dict) else []
        if special_boundaries and not args.allow_unimplemented_boundaries:
            surface_ids = ", ".join(str(item.get("surface_id", "?")) for item in special_boundaries)
            parser.error(
                "manifest lists MCNP transport boundaries on surface(s) " + surface_ids
                + "; GDML does not encode them and this helper does not reproduce them"
            )
        points_mm = mapped_source_points(args.mcnp_position_cm, manifest)
        source_file = output.with_suffix(".initial-source-mm.txt")
        source_file.write_text(
            "# GDML millimetres; generated from MCNP centimetres and conversion manifest.\n"
            + "".join("{:.12g} {:.12g} {:.12g}\n".format(*point) for point in points_mm),
            encoding="utf-8",
        )
        command.extend(("--source-points-mm", str(source_file)))
        source_point_count = len(points_mm)
    elif args.source_points_mm:
        source_file = Path(args.source_points_mm)
        if not source_file.is_file():
            parser.error(f"source-point file not found: {source_file}")
        command.extend(("--source-points-mm", str(source_file)))
        source_point_count = sum(
            bool(line.strip()) and not line.lstrip().startswith("#")
            for line in source_file.read_text(encoding="utf-8").splitlines()
        )
    else:
        command.extend(("--position-mm", *(str(value) for value in args.position_mm)))

    environment = os.environ.copy()
    environment.update(geant4_dataset_environment(args.geant4_config))
    if args.stream:
        completed = subprocess.run(command, env=environment)
        combined = ""
    else:
        completed = subprocess.run(command, capture_output=True, text=True, env=environment)
        combined = "\n".join((completed.stdout, completed.stderr))
    if args.log:
        Path(args.log).write_text(combined, encoding="utf-8")
    if completed.returncode != 0:
        sys.stderr.write(combined)
        raise SystemExit(completed.returncode)
    if args.locate_only:
        for line in combined.splitlines():
            if line.startswith("MCGEOBRIDGE_CRITICALITY_LOCATION"):
                print(line)
        return
    result = json.loads(output.read_text(encoding="utf-8"))
    if result.get("status") != "complete":
        raise RuntimeError("criticality result is incomplete")
    print(json.dumps({
        "status": result["status"],
        "keff": result["keff"],
        "source_point_count": source_point_count,
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
