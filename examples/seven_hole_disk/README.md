# Seven-hole disk example for Methods 2.3

This example is intended to illustrate the mixed conversion path used by MCGeoBridge. The MCNP cell expression

`-1 2 -3 4 5 6 7 8 9 10`

defines a finite disk bounded by `CZ 4.0` and `PZ +/-0.5`, removes the central `CZ 0.6` bore, and enforces the outside of six eccentric `C/Z` hole surfaces distributed uniformly on a 28 mm bolt circle close to the outer rim.

In semantic form, the converted solid is

`AnnularDisk(Rout=40 mm, Rin=6 mm, T=10 mm) - (Hole_1 U ... U Hole_6)`.

The lowering path is intentionally mixed:

1. The subgroup `-1 2 -3 4` satisfies the exact cylinder-shell template and is recovered as a single finite GDML `tube` with `rmin = 6 mm`, `rmax = 40 mm`, and `z = 10 mm`.
2. Surfaces `5`-`10` are eccentric `C/Z` cylinders placed at $(d\cos\theta, d\sin\theta)$ with $d=28$ mm and $\theta=k\pi/3$, $k=0,\ldots,5$. In the current lowering pass they are emitted as translated subtractive cylinders, so the resulting GDML solid is a direct Boolean subtraction chain rather than an intersection with clipped complements.
3. At the expression level this remains an intersection with six outside-hole constraints, but the GDML emission canonicalizes it to a subtraction chain, preserving the same point-membership semantics.
4. This makes the example more informative than a simple coaxial subtraction because it demonstrates exact primitive recovery and non-template lowering inside the same cell.
