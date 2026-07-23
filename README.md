# MCGeoBridge

MCGeoBridge converts a documented MCNP geometry subset into ordinary GDML that
can be read by an unmodified Geant4 installation. Its central design goal is
preservation of MCNP cell-region membership within an explicit finite conversion
domain. Transport sources, tallies, physics settings and nuclear-data libraries
are outside the GDML output.

**Release 1.0.2.** The source is distributed under the BSD-3-Clause license.
Use the tagged release and the accompanying validation records for reproducible
work; the development branch may change after a release is issued.

## Requirements

- Python 3.10 or newer for the converter and its core tests (standard library)
- Geant4 only for independent destination-geometry checks

No installation step is required for the command-line converter.  From the
repository root:

```text
python src/mcnp2gdml.py INPUT.i OUTPUT.gdml
```

For example, the seven-hole disk used to explain AST lowering in the paper can be converted and sampled
with:

```text
python src/mcnp2gdml.py examples/seven_hole_disk/seven_hole_disk.i out/quickstart.gdml --validate 120 --validate-local 240 --validate-boundary 10 --validate-seed 20260718 --validate-out out/quickstart.validate.json
```

Run the Python regression suite with:

```text
python -m unittest discover -s test -p "test_*.py"
```

## Scope and qualification

The current implementation supports signed analytic surfaces, implicit
intersection, union, parentheses, selected complements and macrobodies, plus a
qualified subset of universes, fills, transforms and square/hexagonal
lattices.  A generated file is not automatically an equivalence proof.
MCGeoBridge distinguishes:

- **exact-path** results: supported, fully resolved geometry for which the
  declared finite-domain construction has no recorded approximation;
- **structural checks**: reported GDML loading, navigation, or overlap evidence
  that does not by itself establish complete point-membership agreement; and
- **approximate** results: an identified discretization, fallback, or unsupported
  semantic detail, excluded from exact-path claims.

Read the English [user manual](doc/MCGeoBridge_user_manual.md) before applying
the converter to a new model. `REPRODUCIBILITY.md` gives the commands and
evidence boundaries for the released validation records.

## Repository layout

- `src/`: converter, MCNP parser/IR and GDML model
- `test/`: unit tests, regression decks and benchmark manifests
- `tools/`: validation and corpus-summary utilities
- `out/`: generated validation records; not all development outputs belong in
  the eventual release archive

## Citation and license

MCGeoBridge is distributed under the BSD-3-Clause license. Citation metadata
are provided in `CITATION.cff`; cite the release version used for a calculation.
The archived v1.0.1 record is available at
https://doi.org/10.5281/zenodo.21511720. Third-party benchmark inputs retain
their own notices and are distributed only when their licenses permit it; see
`THIRD_PARTY_NOTICES.md`.
