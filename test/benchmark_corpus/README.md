# MCNP geometry benchmark corpus

This corpus deliberately separates two questions that should not be conflated
in the CPC manuscript:

1. **Showcase set** -- a small set of recognisable, medium-complexity nuclear or
   engineering models used for MCNP/GDML render comparisons and figure panels.
2. **Coverage set** -- a mechanically selected, geometry-deduplicated set used
   to report parser/converter success, warnings, XML validity, syntax coverage,
   and later geometric equivalence.

The first downloaded snapshot contains 518 candidate files and 384 normalized
geometries. The fixed coverage rule retains 70 unique medium-complexity
geometries (8--500 cells and 8--1000 surfaces). The current v21 development
baseline converts all 70 cases, produces well-formed XML with internally valid
GDML references for all 70, passes the official Geant4 GDML schema for all 70,
and is loaded and closed successfully by Geant4 11.4.1 for all 70. Sixty-eight
cases are free of geometry-degradation warnings; two horn/spindle torus cases
use an explicitly reported 720-segment generic-polycone approximation. Five
geometry-only source decks omit their MCNP material cards; those cases receive
explicitly labelled Air-composition placeholder materials and remain flagged
as incomplete for material-fidelity statistics. Overlap and independent
geometric-equivalence checks remain separate validation stages.

## Reproducibility and licensing

`sources.json` records the repository URL, exact commit, and repository license.
External input decks are not copied into this directory because the licenses
span MIT, BSD, EUPL, LGPL, and GPL. They remain in
`tmp/corpus_discovery/repos` during development. Before publishing a benchmark
archive, each selected deck's own notices and redistribution terms must be
reviewed; otherwise publish the manifest, hashes, and fetch instructions only.

`selection.json` is generated from the inventory and smoke report with:

```text
python tools/build_corpus_selection.py \
  --inventory tmp/corpus_discovery/inventory.json \
  --smoke-report tmp/corpus_discovery/smoke_report_v21.json \
  --output test/benchmark_corpus/selection.json
```

## Intended paper outputs

- Showcase figures: MCNP reference rendering, converted GDML rendering, and a
  matched section/cutaway view using the same camera and colours.
- Coverage table: per-syntax presence and success rate, including warnings.
- Correctness table: GDML schema/load result plus independent point-membership
  and near-boundary agreement, not merely successful file generation.
- Performance table: conversion time and GDML size versus cells/surfaces.

The showcase list is a target list. Models that fail a later validation stage
remain in the list because they define meaningful converter-development
milestones.
