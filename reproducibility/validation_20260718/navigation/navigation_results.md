# Global-navigation controls: recorded outcomes

The controls in this directory are evaluated by the optional seventh argument
of `tools/geant4_validation/mcnp2gdml_g4check`.  The expected logical-volume
field is a prefix because ordinary GDML placement expansion adds a unique
suffix.

## FRIDGe indexed RHP lattice

Input: `fridge_lat2_navigation_points.tsv`.

```text
MCGEOBRIDGE_NAVIGATION label=hex_0_0 logical=Vol_100_432 expected=Vol_100 match=1
MCGEOBRIDGE_NAVIGATION label=hex_1_0 logical=Vol_100_436 expected=Vol_100 match=1
MCGEOBRIDGE_NAVIGATION label=hex_0_1 logical=Vol_100_500 expected=Vol_100 match=1
MCGEOBRIDGE_RESULT navigation_queries=3 navigation_mismatches=0 navigation_unresolved=0
```

These are three source-derived, non-boundary basis placements after the
recorded MCNP-to-GDML translation.  They do not exhaust the indexed-hex map.

## PWR spent-fuel canister

Input: `spentfuel_navigation_points.tsv`.

```text
MCGEOBRIDGE_RESULT navigation_queries=4 navigation_mismatches=0 navigation_unresolved=0
```

The four source assembly-placement control points resolve to distinct
`Vol_1015_*` fuel-pellet logical volumes.  This tests placement composition
and transformed-surface ownership, not universal overlap freedom.
