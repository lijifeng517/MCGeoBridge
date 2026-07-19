# GDML off-screen renderer

This helper loads a converted GDML model with Geant4 and renders it to a JPEG
using Geant4's built-in RayTracer. It requires no interactive OpenGL or Qt
window, which makes it suitable for reproducible paper figures and batch
rendering on WSL or a server.

```sh
cmake -S tools/gdml_render -B build/gdml_render \
  -DGeant4_DIR=/path/to/Geant4Config-directory
cmake --build build/gdml_render -j
mcgeobridge_gdml_render model.gdml model.jpeg 1200 900
```

For an internal three-quarter view, remove the camera-facing quadrant.  This
operates on the in-memory Geant4 solids used for rendering and does not modify
the source GDML.  It is intended for origin-centred radial models whose
displayed volumes share a common local coordinate system:

```sh
mcgeobridge_gdml_render model.gdml model-cutaway.jpeg 1200 900 --cutaway-quarter
```

One or more logical volumes can be hidden by name.  The renderer prints the
available logical-volume and material names while loading the model:

```sh
mcgeobridge_gdml_render model.gdml model-inner.jpeg --hide Vol_25_4
```

For generated lattice models, a repeated logical-volume family can be hidden
by its name prefix, for example `--hide-prefix Vol_103_`.

Air cells are hidden by default so that void partitions do not obscure the
material geometry.  Add `--show-air` only when visualising an air region is
itself the purpose of the figure.

Material-consistent colours are used by default. For component libraries in
which many independent parts share one material, `--colour-by-volume` assigns
distinct colours from logical-volume names so that part boundaries remain
visible.

Large auxiliary or graveyard cells can make geometry-aware camera fitting too
conservative.  For consistent paper figures, the optional Pillow-based helper
reframes the non-white foreground while preserving the original canvas size:

```sh
python autocrop.py model.jpeg model-framed.jpeg --occupancy 0.86
```
