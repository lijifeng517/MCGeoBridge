# Geant4 destination-geometry checker

`mcnp2gdml_g4check` loads an emitted GDML file with Geant4 and can perform
three complementary checks: point classification against a TSV oracle,
interior-overlap sampling, and optional global-navigation control points.
It is a destination-side regression aid, not a transport calculation and not
a proof that a model is globally overlap-free.

## Optional navigation controls

Pass a whitespace-separated file as the eighth program argument:

```text
label x_cm y_cm z_cm expected_logical_substring
fuel_00 0.0 0.0 -30.25 Vol_100
```

Coordinates are in the GDML global frame, in centimetres.  The checker uses a
fresh `G4Navigator` rooted at the parsed world volume and reports one
`MCGEOBRIDGE_NAVIGATION` line per control point.  A result matches when the
resolved logical-volume name contains the requested substring; the suffix
added by GDML placement expansion is intentionally ignored.  A missing volume
or a non-matching name makes the checker return a non-zero status.

Controls must be derived from a documented source point and all applied
MCNP-to-GDML placement transforms.  They are suitable for checking salient
hierarchy and placement relations (for example, a representative lattice
basis or an assembly placement), but a finite set of controls does not prove
complete lattice membership, global partition equivalence, or transport
equivalence.
