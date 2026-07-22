# Release 1.0.0 verification record

This record describes checks run on the released source tree on 23 July 2026.
It distinguishes executable regression evidence from the broader fixed-corpus
records that accompany the manuscript.

## Python regression suite

Command:

```text
python -m unittest discover -s test -p test_*.py -v
```

Result: **33 tests passed**.

The suite includes parser, Boolean lowering, hierarchy/transform, material,
validation-report and serialization regressions.  In particular,
`test_general_plane_far_from_explicit_domain_preserves_retained_bbox` verifies
negative-axis, positive-axis and oblique general-plane (`P`) half-spaces whose
retained side contains the complete explicit conversion domain.

## Direct finite-domain regression

A two-cell deck with `P 1 0 0 2000` and explicit domain
`[-10,10]^3 cm` was converted and classified at 200 random points per cell.
The released source produced zero source-versus-emitted-solid mismatches for
both the retained and excluded half-spaces.  This test specifically guards
against accidentally shrinking a retained full-domain half-space during
finite clipping.

## Scope

These executable checks concern geometry conversion and its bounded membership
contract.  They do not establish transport equivalence, nuclear-data
equivalence, or the validity of unsupported MCNP syntax.

