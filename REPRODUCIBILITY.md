# Reproducing MCGeoBridge validation evidence

This document is the single entry point for the released validation evidence.
Commands are run from the repository root. Record the release tag, operating
system, Python version and (where used) Geant4 version with every rerun.

Machine-readable geometry-validation artefacts are frozen in
`reproducibility/validation_20260718/`: the nine-case layered
regression records, the 70-case Geant4 load report, and source-derived PWR and
FRIDGe navigation controls. They are evidence records, not substitutes for a
fresh-copy rerun of the commands below.

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

## 5. Conversion-cost record

`reproducibility/release_1_0_2_conversion_performance.json` records ten
isolated cold-process conversions for a small mixed-CSG deck, the ZPPR-20C
assembly, and a public PWR spent-fuel canister. The timed interval covers
parsing, IR/CSG lowering, GDML construction and writing only; it is not a
Geant4 loading, navigation or transport benchmark. The record includes the raw
times, median, range, quartiles and IQR, together with Python, operating-system,
processor, logical-CPU, memory, output-filesystem and hardware/storage metadata.

## 6. Independent Geant4 checks

Geant4 checks require a separately configured Geant4 installation. The package
includes checker source and build instructions. For a new run, archive the
Geant4 version, GDML input hash, command and raw log with the result. Reported
checks distinguish XML/schema
integrity, GDML loading, sampled `G4VSolid::Inside()` classification, interior
overlap sampling and boundary navigation.  Passing one check must not be
reported as passing the others.

## Reuse checklist

Before publishing a derived result, confirm that third-party inputs may be
redistributed, retain their license notices, run the applicable workflow from a
fresh copy of the tagged release, and archive the resulting commands and logs.
The source license is BSD-3-Clause.
