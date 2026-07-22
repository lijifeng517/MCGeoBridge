# MCGeoBridge user manual

## Purpose and scope

MCGeoBridge converts a documented subset of MCNP constructive-solid geometry
into ordinary GDML that can be loaded by an unmodified Geant4 application. The
program preserves supported cell-region membership only within the declared
finite conversion domain. It does not transfer MCNP sources, tallies, KCODE,
physics settings, variance-reduction cards, or nuclear-data libraries.

The converter reports three evidence categories:

- **exact-path**: a supported, fully resolved finite-domain construction with
  no recorded approximation;
- **structural check**: a loading, navigation, or overlap result that does not
  alone establish full point-membership agreement; and
- **approximate**: a result with an identified fallback, discretisation, or
  unsupported semantic detail. Such a result is excluded from exact-path use.

Always inspect the conversion manifest and validation report before using an
output geometry in a new workflow.

## Requirements

- Python 3.10 or later for conversion and core tests; the converter uses only
  the Python standard library.
- Geant4 is optional and is required only for independent destination checks.

Run commands from the package root. No installation step is required:

```text
python src/mcnp2gdml.py INPUT.i OUTPUT.gdml
```

## Comprehensive sample run

The seven-hole disk is a complete, redistributable example. Run:

```text
python -m unittest discover -s test -p "test_*.py"
python src/mcnp2gdml.py examples/seven_hole_disk/seven_hole_disk.i out/quickstart.gdml --validate 120 --validate-local 240 --validate-boundary 10 --validate-seed 20260718 --validate-out out/quickstart.validate.json --write-manifest out/quickstart.manifest.json
python tools/gdml_integrity.py out/quickstart.gdml
```

The test suite must finish without failures. The sample creates a GDML file, a
conversion manifest, and a sampled-membership report. Inspect the JSON report:
the `mismatches` count must be zero for the supported cells, and skipped
boundary probe forms must be understood before drawing a conclusion.

## Main command-line arguments

| Argument | Meaning |
|---|---|
| `--top-cells 1,2` | Place only the listed cell IDs in the GDML world. |
| `--bbox x0,x1,y0,y1,z0,z1` | Declare a finite MCNP-coordinate conversion domain in cm. |
| `--bbox-margin 0.1` | Relative expansion used for an automatically inferred domain. |
| `--dump-geom [FILE]` | Write the parsed geometry AST as JSON. |
| `--write-manifest FILE` | Write conversion metadata, including domain and coordinate translation. |
| `--validate N` | Generate `N` uniform global points per selected cell. |
| `--validate-local N` | Generate `N` cell-local points per selected cell. |
| `--validate-boundary N` | Generate `N` near-boundary point pairs for supported surfaces. |
| `--validate-cells 1,2` | Limit point checks to the listed cells. |
| `--validate-seed N` | Fix the pseudo-random validation seed. |
| `--validate-eps X` | Set the inside/outside comparison tolerance. |
| `--validate-out FILE` | Write the validation report as JSON. |
| `--validate-g4-points FILE` | Write local points for an independent Geant4 `Inside()` check. |

For example, to declare an explicit 200 cm by 200 cm by 100 cm domain and
perform layered point checks:

```text
python src/mcnp2gdml.py INPUT.i out/model.gdml --bbox -100,100,-100,100,-50,50 --validate 120 --validate-local 240 --validate-boundary 10 --validate-seed 20260723 --validate-out out/model.validate.json --write-manifest out/model.manifest.json
```

## Supported geometry and hierarchy

The implementation covers signed analytic surfaces, implicit intersection,
union, parentheses, selected complements and selected macrobodies. It supports
a qualified subset of universes, fills, rigid transforms, square lattices and
indexed RHP-based hexagonal lattices. The exact supported forms and limitations
are described in the accompanying manuscript and release notes.

An unbounded MCNP half-space is realised only after intersection with the
declared finite domain. For an explicit `--bbox`, verify that it contains the
region of interest. The domain changes clipping only; it is not a recovered
physical outer boundary.

## Validation interpretation

The built-in checker compares source-expression membership with the generated
solid evaluator at the same points. It is a deterministic regression check for
the sampled points, not a transport comparison, a global-partition proof, or a
replacement for Geant4 navigation validation.

For a destination-side check, build the checker under
`tools/geant4_validation/` against your Geant4 installation, record its version
and the GDML hash, and retain the command and raw log. Loading, overlap,
navigation, and `G4VSolid::Inside()` checks answer different questions; record
them separately.

## Troubleshooting

- **Non-zero mismatches:** retain the JSON examples, fix the validation seed,
  inspect the declared domain and cell selection, and rerun with logging.
- **Geometry missing from the world:** inspect `--top-cells`, universe/fill
  relations, and the conversion manifest.
- **A warning or approximation:** do not describe the result as exact-path.
  Either resolve the unsupported feature or retain an explicit approximation
  record.
- **Transport disagreement after conversion:** first establish the geometry,
  source, material, nuclear-data and estimator conditions independently; GDML
  conversion alone does not establish transport equivalence.

## Reproducibility and licensing

`REPRODUCIBILITY.md` describes the released validation records. External input
decks are retained only when their redistribution terms permit it; consult
`THIRD_PARTY_NOTICES.md`. MCGeoBridge source is BSD-3-Clause licensed. Cite the
release version recorded in `VERSION` and `CITATION.cff`.
