# Visualization protocol for showcase cases

## Reference and converted views

For every showcase case, retain both of the following:

1. **MCNP reference**: render the original deck with MCNP PLOT or MCNP Visual
   Editor. Record the MCNP version and any plot commands.
2. **GDML result**: load the generated file through Geant4's GDML parser and
   render it with the Qt/OpenGL stored viewer. Record the Geant4 version,
   visualization macro, and converter command.

ROOT `TGeoManager::Import` may be used as a second, independent GDML import
check. It is not a replacement for loading through Geant4 because Geant4 is the
target application.

## Required views

Each primary showcase model should have:

- one isometric 3-D overview;
- one orthogonal section or clipping-plane view through important internals;
- one detail view when repeated structures or small components are otherwise
  hidden.

Use the same physical view centre, extent, projection, clipping plane, material
colour mapping, background, and image dimensions for the source and converted
figures. Prefer a light, neutral background and colour-blind-safe colours.

## Reproducible capture record

Store a machine-readable record beside each image containing:

- case ID and input/output SHA-256;
- converter command and commit;
- MCNP, Geant4, and optional ROOT versions;
- camera centre, direction, up vector, zoom/scale, and projection type;
- clipping plane or section coordinates;
- cell/physical-volume visibility rules and colour mapping;
- screenshot resolution.

Do not use manually adjusted screenshots as the only publication artifact.
Create MCNP plot commands and Geant4 visualization macros so figures can be
regenerated.

## Interpretation

Images are qualitative evidence of recognisable geometry and presentation
quality. They do not establish geometric equivalence. The validation section
must separately report independent point-membership agreement, near-boundary
sampling, missing/extra volume estimates, Geant4 load/overlap checks, and all
converter warnings.
