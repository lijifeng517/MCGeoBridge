# ORSphere Case 2: geometry and criticality-driver calibration record

## Scope

This record separates three questions that must not be conflated:

1. whether the public MCNP Case-2 deck was transcribed and converted correctly;
2. whether the local MCNP installation reproduces the expected criticality
   scale for that geometry; and
3. whether the experimental Geant4 fission-source driver is qualified for a
   cross-code comparison.

The first two are supported by the evidence below. A Geant4 11.4.1
ParticleHP multiplicity lookup defect has now been isolated and corrected
locally, and a post-fix short calculation returns to the expected criticality
scale. A precision calculation and independent-seed reproduction are still
required before the third question can be answered affirmatively.

## Public reference and conversion checks

The source fixture `test/engineering_cases/ORSphere_Case2_simple_public.i`
transcribes Table 4-2 (simple Case 2) in INL/EXT-13-28721.  The source has a
single uranium-alloy sphere of radius 8.72995881 cm and atom density
4.82842E-02 atoms/(barn cm).  The report's evaluated experimental value is
`k_eff = 0.9966 +/- 0.0007`.

The converted `tmp/orsphere_case2.gdml` has one fuel sphere of the same radius
and a converted material mass density of 18.77848006 g/cm3.  The value follows
directly from the atom density and isotope-weighted molar mass.  `g4check`
reported one world, two physical volumes, two logical volumes, nine solids,
two materials, and no invalid surface volumes.

An isotope-by-isotope back-conversion of the GDML density and mass fractions
reconstructs a total atom density of `0.0482842000000` atoms/(barn cm), exactly
the cell-card density to the printed precision.  The individual reconstructed
densities reproduce the MCNP material entries (for example U-235
`0.044838288849` versus `0.0448383`, and U-238 `0.002738999319` versus
`0.00273900`).  Material fraction conversion is therefore excluded as a
plausible source of the multi-percent k deficit.

## Independent local MCNP control

`test/engineering_cases/ORSphere_Case2_simple_public_endf71_local.i` retains
the geometry and atom densities but uses the locally available ENDF/B-VII.1
`.80c` ACE tables and reduced `KCODE 5000 1.0 20 80` controls.  This is not a
same-library reproduction of the report's `.70c` calculation.

The local MCNP6 run (`tmp/orsphere_mcnp_endf71.out`) completed 60 active cycles
and reports combined `k_eff = 0.99742 +/- 0.00125`; its source-entropy check
passed.  This overlaps the published evaluation and is evidence that the
transcribed geometry/material model is on the expected criticality scale.

## Geant4 driver audit

The earlier Geant4 run (`tmp/orsphere_case2_keff.json`; population 5000,
30 inactive and 100 active cycles) gave `0.934896 +/- 0.002387`.  Its source
entropy and occupied-bin diagnostics were stable late in the run, but this is
a statistically distinct deficit from both MCNP values and cannot be described
as a conversion result.

The driver now explicitly propagates source-particle weights through
`G4ParticleGun`, evaluates each cycle as total fission-bank weight divided by
the fixed population, and emits fission-weight diagnostics.  A short post-fix
smoke calculation (`tmp/orsphere_case2_weight_smoke.json`) recorded zero
non-unit fission-neutron weights in all six cycles; its count and total-weight
estimators were therefore identical.  The smoke calculation has only four
active cycles and is **not** a criticality estimate.

A larger corrected run (`tmp/orsphere_case2_keff_weighted.json`; population
2000, 25 inactive and 60 active cycles) gave `0.923358 +/- 0.004350`.
All 85 cycles reported zero non-unit fission-neutron weights, so the weighted
and count estimators were identical for this physics configuration.  Its final
ten-cycle k trend is still downward (`-0.00514` per cycle), although source
entropy and occupied-bin diagnostics are comparatively stable.  It confirms
the material deficit persists after the weight correction, but the late-cycle
trend means it is not a qualified precision estimate.

At this stage of the audit, the leading explanations were the different
neutron-data/physics implementation (`Shielding` with G4NDL4.7.1 versus MCNP
ACE data) and unqualified details of the custom fission-source iteration. The
event-level diagnostics below subsequently isolated a ParticleHP multiplicity
lookup defect. These pre-fix values remain useful negative controls but must
not be reported as conversion results.

### Shielding fission-fragment setting

The Geant4 11.4.1 `Shielding` reference list explicitly calls
`G4ParticleHPManager::SetProduceFissionFragments(true)` for its HP neutron
variant.  The run log confirms `Produce fission fragments 1` for U-234,
U-235, U-236 and U-238.  In the same Geant4 source path,
`G4ParticleHPFissionFS` warns that this mode precludes delayed-neutron
production and sets the sampled delayed multiplicity to zero.  This is a
confirmed difference from MCNP's total-nubar criticality treatment.  Its
expected magnitude alone is not assumed to explain the full deficit; a
controlled fragments-off diagnostic is required before assigning causality.

A matched short diagnostic used the same seed, 1000 histories per cycle,
15 inactive cycles and 30 active cycles.  The reference-list default
(fragments on) gave `0.93463 +/- 0.00892`; explicitly disabling fragments gave
`0.94567 +/- 0.00774`.  The observed increase is about 0.0110, but the short
runs are too noisy to estimate that effect precisely.  More importantly, the
fragments-off result remains about 0.0509 below the evaluated benchmark, over
six combined standard errors for this diagnostic.  Suppression of delayed
neutrons is therefore a confirmed configuration mismatch but cannot by itself
account for the full deficit.

### G4NDL multiplicity and provenance

The installed G4NDL4.7.1 README records that its non-thermal neutron cross
sections and final states are inherited from G4NDL4.6, which was generated
from JEFF-3.3.  The local MCNP control instead uses ENDF/B-VII.1 `.80c` data.
Thus the comparison is not same-library.  Direct inspection of the compressed
U-235 G4NDL fission final-state file gives total mean neutron multiplicities
of about 2.583 at 1.4585 MeV and 2.646 at 2 MeV.  The local MCNP output reports
an average of 2.598 neutrons per fission and an average fission-causing energy
of 1.4585 MeV.  The average multiplicity values are close; a missing
multi-percent total-nubar contribution is not supported by these data.

### Fission-event and source-bank accounting

The criticality executable was instrumented at every neutron `nFission` step.
It records the incident energy, target isotope, number and weight of neutron
secondaries reported by the step, and the same quantities after the stacking
action has populated the next-generation bank. In all diagnostic runs, the
step-level neutron count and weight equalled the bank count and weight exactly.
Consequently, neither the stacking filter nor the source-bank representation is
discarding fission neutrons.

In a two-cycle, 10,000-history-per-cycle probe with fission fragments disabled,
the first cycle recorded 5,248 fissions and 12,840 emitted/banked neutrons
(`nu = 2.4466`), with a mean incident fission energy of 1.399 MeV. The second
recorded 4,523 fissions and 10,839 neutrons (`nu = 2.3964`) at 1.366 MeV.
More than 97% of the events were U-235 fissions. These values reveal an emitted
multiplicity near 2.42, materially below the approximately 2.57--2.58 prompt
plus delayed multiplicity encoded by the installed U-235 data in this energy
range.

### Independent first-interaction multiplicity probe

`mcgeobridge_fission_probe` provides a control independent of fission-source
iteration. It launches monoenergetic neutrons from the ORSphere centre, records
only the primary neutron's first hadronic interaction, counts the secondaries
if that interaction is fission, and aborts the event before any descendant can
be transported. This follows the diagnostic principle of the Geant4 Hadr03
example without depending on its analysis-library target.

A 50,000-event run at exactly 1.4585 MeV produced 8,034 first-interaction
fissions. Of these, 7,858 (97.8%) were on U-235. The overall multiplicity was
`2.4114 +/- 0.0175` (standard error of the event mean), and the U-235-only mean
was `2.4089`. Two separate 20,000-event seeds gave `2.4188 +/- 0.0274` and
`2.4554 +/- 0.0280`, consistent with the larger run and with the criticality
driver's direct fission-step observation.

An energy scan gives the following descriptive results:

| Source energy | U-235 mean neutrons/fission | U-235 fission events |
|---:|---:|---:|
| 0.0253 eV | 2.4286 | 16,643 |
| 1.4585 MeV | 2.4089 | 7,858 |
| 2 MeV | 2.4332 | 3,181 |
| 5 MeV | 2.4746 | 2,535 |

The sampled multiplicity therefore fails to reproduce the strong energy trend
present in the installed U-235 G4NDL table. Static source inspection excludes
the HP `DoNotAdjustFinalState` setting: that adjustment is used by inelastic and
capture final states, whereas the fission path samples prompt and delayed
multiplicities directly.

### Root cause and corrected controls

The defect is an unintended C++ overload selection in
`G4ParticleHPParticleYield.hh`. Its `GetMean(double)`, `GetPrompt(double)` and
`GetDelayed(double)` functions are declared `const`, but the energy-based
`G4ParticleHPVector::GetY(double)` overload is not. In that const context the
compiler instead selects `GetY(int) const`, converting an incident energy such
as 1.4585 MeV to integer index 1. Direct temporary instrumentation confirmed
that the HP fission routine received 1.4585 MeV internally and that the prompt
vector stored its energy grid in the correct units, while the lookup returned
the index-1 (near-thermal) value `2.4091`.

The minimal local correction removes the inappropriate `const` qualifier from
the three yield accessors; the reproducible source patch is archived as
`tools/physics_validation/patches/geant4-11.4.1-particlehp-yield-energy.patch`.
The official Geant4 master, v11.4.0 and v11.3.2 source snapshots inspected on
2026-07-19 contain the same accessor signatures, so this is not treated as a
project-specific source modification.

After applying the correction, the 50,000-event 1.4585-MeV first-interaction
control recorded 7,982 fissions and `2.5897 +/- 0.0181` neutrons per fission;
the U-235-only value was `2.5868`. This agrees with the approximately 2.583
value read from the installed G4NDL table and independently verifies the
correction at the final-state level.

A corrected short criticality smoke calculation used 1,000 histories per
cycle, 15 inactive cycles and 30 active cycles, with fission fragments disabled.
It returned `k_eff = 0.99457 +/- 0.01264`, statistically compatible with the
evaluated `0.9966 +/- 0.0007` and sharply different from the matched pre-fix
short result `0.94567 +/- 0.00774`. Because the post-fix calculation is short
and the Geant4 and MCNP nuclear-data libraries remain unmatched, it demonstrates
successful defect correction but is not yet a precision cross-code equivalence
result.

A first corrected precision run (`orsphere_case2_keff_constfix_precision.json`)
used 5,000 histories per cycle, 30 inactive cycles, 100 active cycles and seed
24681357. It gave `k_eff = 0.998018 +/- 0.001879`. The difference from the
evaluated value is 0.001418, or about 0.71 combined standard deviations when
the reported statistical errors are combined in quadrature. Late-cycle source
diagnostics remained stable: 369--400 occupied 20-mm bins and entropy between
5.65 and 5.73. All cycles retained equality between step-level and banked
fission-neutron weights, with zero non-unit-weight bank entries. This is a
successful first calibration realization, not yet an independent replication.

A second corrected precision run (`orsphere_case2_keff_constfix_precision_seed2.json`)
used the same population and cycle controls with independent seed 97531864. It
gave `k_eff = 1.001794 +/- 0.002428`. The two corrected realizations differ by
0.003776, corresponding to approximately 1.23 combined standard errors; their
inverse-variance weighted center is approximately 1.000. Both runs retained
zero non-unit fission-neutron weights and stable source diagnostics (roughly
370--400 occupied 20-mm bins with entropy about 5.65--5.73). This independent
replication supports stability of the patched driver at the descriptive level.
The comparison remains limited by the unmatched G4NDL4.7.1 and ENDF/B-VII.1
nuclear-data libraries, so it is not presented as a same-data cross-code
equivalence test.

ORSphere and KBS-3 values must remain out of the manuscript's physical-
equivalence claims until the independent seed and nuclear-data limitation
analysis are complete.
