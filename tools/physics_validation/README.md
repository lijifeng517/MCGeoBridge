# MCGeoBridge fixed-source transport validation

This small Geant4 application loads a converted GDML model and runs a
monoenergetic, monodirectional neutron source. It is intended for controlled
MCNP/Geant4 consistency experiments, not as a general-purpose transport input
replacement.

The JSON result contains per-source-particle estimates of:

- neutron track length and track-length fluence in each logical volume;
- deposited energy in each logical volume;
- neutron capture and fission event counts;
- neutron and energy leakage through the world boundary;
- standard errors computed from event histories for additive estimators.

Scores are reported both for individual GDML logical volumes and aggregated by
the original MCNP cell number encoded in `Vol_<cell>_<instance>`. Cell-level
standard errors are accumulated per event and therefore retain correlations
between repeated lattice instances. The aggregate reports track-length
integrals rather than a volume-normalized flux because evaluating the volumes
of every unvisited complex Boolean solid can dominate the transport runtime.

Build with a configured Geant4 installation:

```sh
cmake -S tools/physics_validation -B build/physics_validation \
  -DGeant4_DIR=/path/to/Geant4Config-directory
cmake --build build/physics_validation -j
```

Example:

```sh
mcgeobridge_transport model.gdml result.json \
  --events 10000 --seed 1234567 --physics Shielding \
  --energy-mev 2.0 --position-mm 0 0 0 --direction 0 0 1
```

Add `--compute-volumes` when volume-normalized per-volume fluence is required.
It is disabled by default because Geant4's numerical volume calculation for
hundreds of complex Boolean solids can take longer than a small transport run.

The repository wrapper discovers and exports the Geant4 dataset variables and
also checks that the output is complete:

```sh
python tools/run_transport_validation.py model.gdml result.json \
  --executable build/physics_validation/mcgeobridge_transport \
  --geant4-config /path/to/geant4-config --events 10000
```

## Criticality pilot workflow

`mcgeobridge_criticality` performs fixed-population fission-source iterations.
It accepts either a single GDML-coordinate source point (`--position-mm`) or a
whitespace-delimited file of source points (`--source-points-mm`).  The latter
is intended for a mapped MCNP `KSRC` distribution.

The converter can write the coordinate mapping used to centre the GDML world:

```sh
python src/mcnp2gdml.py --write-manifest model.manifest.json model.i model.gdml
```

Use the criticality wrapper to map one or more MCNP source positions in cm to
GDML coordinates in mm.  Repeating `--mcnp-position-cm` preserves a discrete
multi-point initial source distribution:

```sh
python tools/run_criticality_validation.py model.gdml criticality.json \
  --executable build/physics_validation/mcgeobridge_criticality \
  --geant4-config /path/to/geant4-config \
  --manifest model.manifest.json \
  --mcnp-position-cm 0 0 0 --mcnp-position-cm 6 6 0
```

The current Geant4 criticality implementation is a research-validation helper,
not a replacement for a production criticality code.  Before interpreting a
MCNP/Geant4 difference as evidence about geometry conversion, establish that
the GDML source is in the intended fuel region, and separately qualify the
physics list, neutron data, thermal-scattering treatment, and fission-neutron
banking algorithm.

The conversion manifest also lists explicit MCNP reflecting (`*`) and white
(`+`) surface boundaries.  These are transport conditions rather than GDML
geometry.  The present helper does not implement them, so a model containing
such a boundary is ineligible for a criticality comparison until an equivalent,
separately qualified Geant4 boundary treatment is provided.

For a defensible comparison, use identical source definitions and isotopic
material specifications in both codes. Nuclear data libraries, material
temperatures, and thermal-scattering treatments must be recorded separately;
they are not encoded completely by GDML.
