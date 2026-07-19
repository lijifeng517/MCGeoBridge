# KBS-3 public-reference criticality comparison: compatibility audit

## Purpose and scope

This record defines the interpretation boundary for the public PWR spent-fuel
canister comparison.  It is a geometry-sensitive, cross-code consistency
exercise: it tests whether a converted GDML model can support a stable Geant4
fission-source iteration whose result can be reported alongside the published
MCNP result.  It is **not** a same-library code-to-code verification unless
the items marked below as unresolved are brought under matched control.

The public source deck is
`test/engineering_cases/NormalOperation_SpentFuel_mcnp_v2`.  Its header records
an MCNP result of `0.19588 +/- 0.00002` using ENDF/B-VIII.0.  The deck specifies
`MODE N`, `KCODE 50000 1 300 3000`, and `KSRC 0 0 1` (MCNP centimetres).
These are source-deck facts, not a substitute for independently reproducing
the MCNP calculation.

## Configuration inventory

| Control | MCNP public deck | Current Geant4 run | Interpretation |
|---|---|---|---|
| Geometry | MCNP CSG with universes, fills, transforms and lattices | Converted `tmp/snf_v3_manifest.gdml` | The comparison is intended to be sensitive to this mapping. |
| Initial source | One `KSRC` point at `(0,0,1)` cm | 1,156 verified fuel-pin candidate points in the converted four-assembly lattice | Different initial sources are acceptable only after source convergence is demonstrated. |
| Criticality population | 50,000 histories/cycle; 300 inactive, 3,000 active cycles | 1,000 histories/cycle; 20 inactive, 30 active cycles in the current diagnostic run | The current run is a convergence study, not yet a precision replication. |
| Nuclear data | Deck header identifies ENDF/B-VIII.0; material cards use `.00c` suffixes | `Shielding` physics list with locally installed `G4NDL4.7.1` | Evaluated data are not demonstrated to be identical. A residual difference cannot be assigned uniquely to geometry. |
| Thermal scattering | The deck contains `MT` thermal-treatment cards, e.g. `fe-56.40t` | GDML stores no thermal-scattering card; Geant4 uses its installed neutron data and physics configuration | Unresolved transport-model difference; retain in all result tables. |
| Material compositions | Isotope-resolved MCNP material cards | Isotope/fraction and density conversion into GDML materials | Must be checked by material inventory; geometry conversion alone does not prove transport-material identity. |
| Estimator | Production MCNP `KCODE` implementation | Research helper using fixed population, Geant4 fission bank and systematic combing | Algorithmic uncertainty must be qualified with source diagnostics and independent seeds. |

The Geant4 data-path inventory was obtained from the local
`/home/ubuntu/geant4-build-11.4.1/geant4-config --datasets` command.  It reports
`G4NEUTRONHPDATA=/home/ubuntu/geant4-build-11.4.1/data/G4NDL4.7.1`.

## Required evidence before reporting a comparison value

1. Preserve the exact GDML hash, converter revision, source-point file and
   Geant4 data-path inventory with each run.
2. Verify every initial source point by Geant4 navigation.  For the current
   lattice source file, all 1,156 candidates were located in material
   `M00000099` in the converted fuel region.
3. Report the entire inactive/active cycle trace, fission-bank population,
   occupied spatial bins and source entropy; do not rely on the final mean
   alone.
4. Use at least one independent random seed after the first run has shown a
   stable source distribution.  Compare seed-to-seed estimates before forming
   a pooled statement.
5. Report the public MCNP value and the Geant4 value side by side, but label
   their difference as a cross-code consistency result unless nuclear data,
   thermal treatment and estimator settings are demonstrably matched.

## Exclusions

No result from this workflow may be described as a proof that MCNP and Geant4
are physically equivalent.  In particular, a statistically compatible
`k_eff` is necessary but not sufficient evidence for geometric equivalence;
the manuscript's bounded semantic and destination-navigation validation layers
remain separate evidence.
