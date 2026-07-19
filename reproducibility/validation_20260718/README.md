# Archived geometry-validation records

This directory freezes the machine-readable records that support the geometry
claims in the manuscript.  It deliberately contains validation artefacts and
their input point sets, rather than third-party MCNP decks whose redistribution
terms differ by source.

## Contents

- `layered/`: the nine GDML files, source-expression point sets, per-case
  validation summaries, the aggregate summary, and the independent Geant4
  `Inside()` report used for the 420-cell layered regression.
- `geant4_load_70.json`: isolated Geant4 11.4.1 load results for the fixed
  70-case coverage corpus.  Each of 70 files loaded and closed successfully;
  this is a loadability record, not an overlap or membership certificate.
- `navigation/`: source-derived global-navigation control points for the PWR
  spent-fuel and FRIDGe indexed-hex examples.  The exact generated GDML file,
  Geant4 schema path, software version and command are recorded in the linked
  manuscript/reproduction documentation.

The raw point sets are in the GDML local frame for `G4VSolid::Inside()` checks.
Navigation controls are in the GDML global frame after the recorded placement
transform.  A zero mismatch in these records is finite regression evidence;
it does not establish a global partition or transport equivalence claim.
