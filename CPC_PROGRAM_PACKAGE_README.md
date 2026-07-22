# MCGeoBridge CPC Program Package

This package accompanies the manuscript *MCGeoBridge: Bounded
Semantics-Preserving Conversion from MCNP CSG Models to Geant4 GDML*.
It is prepared for a Computer Programs in Physics (CPiP) submission to
*Computer Physics Communications*.

## Requirements

- Python 3.10 or newer for conversion and core tests. The converter uses the
  Python standard library only.
- A separately configured Geant4 installation is optional for the independent
  destination-geometry checks recorded under `reproducibility/`.

## Package layout

- `src/` -- MCNP reader, semantic geometry compiler, GDML writer, and command
  line entry point.
- `test/` -- unit and regression tests, including published FRIDGe input
  covered by its accompanying third-party notice.
- `examples/seven_hole_disk/` -- complete example input, generated GDML, and
  explanatory image.
- `reproducibility/validation_20260718/` -- frozen layered-validation,
  Geant4-load, and navigation records cited by the manuscript.
- `tools/` -- validation, integrity, corpus-summary, and figure utilities.
- `doc/mcnp2gdml_user_manual_zh.md` -- user manual.
- `LICENSE` and `THIRD_PARTY_NOTICES.md` -- licensing information.

## Installation and comprehensive sample run

No installation step is required. Run the following commands at the package
root:

```text
python -m unittest discover -s test -p "test_*.py"
python src/mcnp2gdml.py examples/seven_hole_disk/seven_hole_disk.i out/quickstart.gdml --validate 120 --validate-local 240 --validate-boundary 10 --validate-seed 20260718 --validate-out out/quickstart.validate.json --write-manifest out/quickstart.manifest.json
python tools/gdml_integrity.py out/quickstart.gdml
```

The test suite must finish without failures. The sample conversion writes a
GDML file, a conversion manifest, and a sampled-membership report with zero
mismatches for the supported cells. The integrity checker reports one valid
GDML root volume.

## Scope

MCGeoBridge converts the documented MCNP geometry subset into ordinary GDML.
It does not transfer MCNP sources, tallies, physics settings, variance
reduction, or nuclear-data libraries. The conversion claim is conditional on
the supported syntax and the declared finite conversion domain; see the user
manual and `REPRODUCIBILITY.md` for qualifications.
