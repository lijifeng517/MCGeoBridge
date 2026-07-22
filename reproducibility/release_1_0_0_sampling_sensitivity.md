# Sampling-density sensitivity check

This record supplements, but does not replace, the fixed validation suite
reported in the accompanying manuscript.  It concerns the converter's
source-expression versus emitted-solid membership comparison only; it is not
an additional Geant4 transport or independent-destination result.

The two representative inputs were re-run on 23 July 2026 with a fixed seed
of 20260723 and five times the baseline point budget in every stratum:

| Input | Validated cells | Points | Boundary pairs | Active boundary pairs | Mismatches |
|---|---:|---:|---:|---:|---:|
| Mixed CSG regression model (`CASE_10`) | 4 | 8,400 | 600 | 345 | 0 |
| ZPPR-20C fast-reactor model | 181 | 411,430 | 42,815 | 25,279 | 0 |

For each cell, the run used 600 global-domain points, 1,200 cell-local points,
and 50 point pairs per supported referenced surface at a normal offset of
`1e-5 cm`.  The complete machine-readable reports are retained in the
development record; the table above is the portable release summary.  The
result supports robustness of the source/internal membership result to this
fivefold sampling increase.  It does not constitute a proof of global
geometric equality.

