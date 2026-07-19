# Reproducing MCGeoBridge validation evidence

This document is the single entry point for the project's validation evidence.
Commands are run from the repository root. The public release will pin the
repository revision, operating-system image and Geant4 version.

Machine-readable geometry-validation artefacts are frozen in
`reproducibility/validation_20260718/`: the nine-case layered
regression records, the 70-case Geant4 load report, and source-derived PWR and
FRIDGe navigation controls.  They are evidence records, not substitutes for a
clean-clone rerun of the commands below.

## 1. Core regression tests

```text
python -m unittest discover -s test -p "test_*.py"
```

These tests exercise parsing, AST normalization, geometry lowering and summary
logic.  They are necessary but do not replace the end-to-end geometry checks.

## 2. Minimal end-to-end conversion

```text
python src/mcnp2gdml.py examples/seven_hole_disk/seven_hole_disk.i out/quickstart.gdml --validate 120 --validate-local 240 --validate-boundary 10 --validate-seed 20260718 --validate-out out/quickstart.validate.json --write-manifest out/quickstart.manifest.json
python tools/gdml_integrity.py out/quickstart.gdml
```

Expected artifacts are a GDML file, a schema-v2 sampled-membership record and a
conversion manifest containing the finite domain and coordinate translation.
The validation record must be inspected for mismatches and skipped boundary
probe forms; successful XML generation alone is not sufficient.

## 3. Coverage table

The fixed, geometry-deduplicated corpus is described by
`test/benchmark_corpus/selection.json`.  Regenerate the JSON and Markdown
summaries with:

```text
python tools/summarize_corpus_coverage.py test/benchmark_corpus/selection.json --json-out out/coverage_summary.json --markdown-out out/coverage_summary.md
```

The manifest records source repositories, revisions, hashes and license
metadata.  External decks are not automatically republished by this project.

## 4. Layered membership table

Given the archived per-case `*.validate.json` records:

```text
python tools/summarize_layered_validation.py out/layered_validation_20260718 --output out/layered_validation_20260718/layered_validation_summary.regenerated.json
```

The output keeps global, cell-local and boundary-directed point counts
separate, including active boundary pairs and skipped surface references.

## 5. Independent Geant4 checks

Geant4 checks require a separately configured Geant4 installation.  The
release archive will include the checker source, build instructions, Geant4
version, GDML input hash and raw log.  Reported checks distinguish XML/schema
integrity, GDML loading, sampled `G4VSolid::Inside()` classification, interior
overlap sampling and boundary navigation.  Passing one check must not be
reported as passing the others.

## Release blockers

Before a public archival release is frozen, the authors must confirm
authorship/citation metadata, replace working paths with a versioned public
release/DOI, audit redistribution rights for every third-party input and run
the complete workflow from a clean clone. The source license is BSD-3-Clause.
