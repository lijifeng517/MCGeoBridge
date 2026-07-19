# MCGeoBridge

MCGeoBridge converts the geometry subset of an MCNP input deck into ordinary
GDML that can be read by an unmodified Geant4 installation.  Its central
design goal is preservation of MCNP cell-region membership within an explicit
finite conversion domain.  Transport sources, tallies, physics settings and
nuclear-data libraries are outside the GDML output.

> **Pre-release status.** This working tree is being prepared for submission
> to *Computer Physics Communications*.  The source is released under the
> BSD-3-Clause license; a versioned archival release and DOI are still pending.

## Requirements

- Python 3.10 or newer for the converter and its core tests (standard library)
- Geant4 only for independent destination-geometry checks
- PySide6 and VTK only for the optional desktop GUI

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

The optional GUI is started on Windows with `run_gui.bat`; its dependencies are
listed in `requirements-gui.txt`.

## Scope and qualification

The current implementation supports signed analytic surfaces, implicit
intersection, union, parentheses, selected complements and macrobodies, plus a
qualified subset of universes, fills, transforms and square/hexagonal
lattices.  A generated file is not automatically an equivalence proof.
MCGeoBridge distinguishes:

- **strict** results, for supported exact geometry with resolved references and
  an accepted finite domain;
- **qualified** results, which pass stated structural or Geant4 checks but lack
  complete point-membership evidence; and
- **degraded** results containing a reported approximation or fallback.

See `doc/mcnp2gdml_user_manual_zh.md` for the current user manual and
`REPRODUCIBILITY.md` for the commands that regenerate manuscript evidence.

## Repository layout

- `src/`: converter, MCNP parser/IR, GDML model and optional GUI
- `test/`: unit tests, regression decks and benchmark manifests
- `tools/`: validation, corpus-summary and figure-generation utilities
- `doc/MCGeoBridge_paper_draft/`: manuscript source, figures and PDF build
- `out/`: generated validation records; not all development outputs belong in
  the eventual release archive

## Citation and license

MCGeoBridge is distributed under the BSD-3-Clause license. Citation metadata
and the archival release DOI will be added when the author list is confirmed.
Third-party benchmark inputs retain their own notices and are distributed only
when their licenses permit it; see `THIRD_PARTY_NOTICES.md`.
