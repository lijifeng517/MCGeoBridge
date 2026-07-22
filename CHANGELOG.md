# Changelog

## 1.0.0 — 2026-07-23

First archival release of MCGeoBridge.

- Converts the supported MCNP CSG subset to standard Geant4 GDML within a
  declared finite domain.
- Records exact-path, structural-check, and documented-approximation outcomes
  separately.
- Includes 33 Python regression tests, a Geant4-independent-validation helper,
  representative inputs and a fixed public-corpus coverage record.
- Corrects bounded clipping for a general `P` plane whose retained half-space
  contains the complete conversion domain; the regression suite covers axis
  aligned and oblique forms.
- Adds an English user manual, citation metadata, reproducibility notes and a
  release-specific conversion-cost record.

