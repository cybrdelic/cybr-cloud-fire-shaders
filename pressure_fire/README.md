# Pressure-driven reactive volume

This directory contains a reproducible CPU reference for a persistent three-dimensional explosion volume. The state evolves through conservative compressible flow. There is no time-dependent radius, animated signed-distance shape, prescribed outward velocity, or continuously spherical emitter.

## What is simulated

Each cell stores eight conservative quantities, in this order:

`rho, rho*u, rho*v, rho*w, E, rho*Yfuel, rho*Yoxygen, rho*Ysoot`

The first five obey the compressible Euler equations. Gas pressure comes from internal energy:

`p = (gamma - 1) * (E - |momentum|² / (2*rho))`

Pressure enters the momentum flux and does pressure work in the total-energy flux. A localized initial internal-energy deposit and later fuel consumption create pressure gradients, which accelerate gas. Fuel, oxygen and soot travel with the computed flow. Curl can arise from shear, buoyancy and misaligned pressure/density gradients; there is no imposed curl-noise velocity.

The oil initial condition consists of six connected irregular fuel pockets and two adjacent compact ignition-energy pockets. This geometry is used once, at initialization. Every subsequent frame reads the evolved state.

## Numerical method

- Primitive-variable MUSCL reconstruction with generalized minmod limiting, theta = 1.5.
- HLLC approximate Riemann flux, using the minimum/maximum left/right acoustic signal speeds. An invalid HLLC star state falls back to the more diffusive HLLE flux.
- Unsplit SSPRK2 time integration, with a source half-step before and after the flow step.
- Adaptive timestep based on the **sum** of directional acoustic/advective speeds. Target CFL is 0.35. A stage that exceeds the bound or develops nonfinite/nonpositive gas state is rejected and retried with a smaller timestep.
- Transmissive ghost cells at all six boundaries. These are zero-gradient open boundaries, not a perfectly absorbing characteristic boundary condition.
- Density and total energy are never silently floored. Only tiny negative passive-scalar roundoff is clipped, and that correction is recorded separately.

The solver measures all six boundary fluxes and all source increments. `diagnostics.jsonl` reports the conservation residual as:

`current - initial + cumulative_outflow - cumulative_sources - roundoff_correction`

`--max-dt 0.0025` imposes an additional cap for a fixed-timestep GPU implementation. It does not replace the CPU's acoustic CFL test.

## Chemistry and buoyancy closures

The model deliberately uses nondimensional, scaled thermodynamics and acoustics. Ambient density, pressure and temperature are one; gamma is 1.3. Length and time are simulation units. These values do not constitute a calibrated real-world oil-explosion calculation.

One-step combustion consumes fuel and oxidizer, limited by the available amount of each. Activation smoothly rises between temperature 1.3 and 2.0. For an activated cell:

`burn = min(fuel, oxygen/3) * (1 - exp(-rate * activation * dt))`

`fuel -= burn; oxygen -= 3*burn; soot += yield*burn; E += Q*burn`

Gas mass is unchanged: the consumed reactants become implicit combustion products. The tracked species need not sum to one; the remainder is inert gas/products. This is a visual one-step mixture model, not detailed oil chemistry. There is no resolved spray, molecular diffusion, flame-thickness model, soot oxidation, or compressible combustion-chemistry calibration. Fuel/oxidizer mixing at unresolved scales is numerical. This limitation matters when interpreting burning at a coarse grid.

Hot internal energy relaxes toward the ambient-temperature state over a configured cooling time. This represents unresolved heat loss; it is not a solved radiative transfer/energy coupling. Buoyancy is the explicit background-subtracted force `f_y = g*(rho_ambient-rho)`. Its momentum impulse and corresponding kinetic-energy work are both added to the conserved state. It preserves a uniform ambient state at rest but is an approximation to a hydrostatic atmosphere.

The first irregular oil trial used heat release 220, rate 3.5, soot yield 0.22, cooling time 8 and buoyancy 0.35. The hotter trial uses heat release 500 and vorticity-confinement strength 2. The original validation case uses smaller values; each snapshot's JSON stores its actual parameters.

### Explicit subgrid vorticity force

When `--confinement 2` is enabled, the solver estimates omega = curl(velocity) by centered differences and adds:

`acceleration = epsilon*h * cross(normalize(gradient(length(omega))), omega)`

Here h is the smallest cell width. The corresponding force density `rho*acceleration` enters the momentum RHS at both RK stages, and `dot(force,velocity)` enters the total-energy RHS. Both are included in the measured source budget. This is an explicit artistic subgrid closure that counters loss of resolved swirl on a coarse grid; it is not a claim of resolved small-scale turbulence. It uses only the evolving flow and vanishes when curl is zero. It adds no random velocity and no prescribed expanding geometry.

## Reproduce

Requires Python with NumPy and a C++17 compiler supporting OpenMP. `run.py` builds the C++ core when necessary.

```bash
python fields.py init checkpoints/oil96_initial --shape 96 112 96 --profile oil
python run.py checkpoints/oil96_initial checkpoints/oil96 --end 3 --output-dt 1 --threads 8 --heat 500 --confinement 2
python validate.py
```

The approved production command is:

```bash
python run.py checkpoints/oil96_initial production_oil96 --end 4.775 --output-dt .025 --threads 2 --heat 500 --confinement 2 --no-convert
```

It writes **192 independently evolved states**, from time 0 through 4.775 in increments of 0.025. Displaying those states at 24 frames per second produces an eight-second clip, with 0.6 nondimensional simulation units per playback second. No state interpolation or duplicated frames is needed. The camera/volume renderer is separate from the solver.

Each raw checkpoint is first written to `.raw.partial`, closed, then renamed to `.raw`. JSON metadata is likewise published by an atomic rename after the raw volume is complete. A renderer should wait for `state_NNNN.json` before reading the corresponding `.raw`. Production does not create redundant NPZ copies.

To continue a simulation, pass a checkpoint as the input stem and an absolute final time:

```bash
python run.py checkpoints/oil96/state_0003 checkpoints/oil96_late --end 8 --output-dt 1 --threads 8
```

## Snapshot contract

Every checkpoint has a `.raw`, `.json` and optionally `.npz` file. Raw storage is little-endian float32, C-contiguous **[nz, ny, nx, 8]**, with x changing fastest. The JSON gives dimensions in **[nx, ny, nz]** order and bounds in **[[xmin,xmax],[ymin,ymax],[zmin,zmax]]** order. y is vertical. Samples are located at cell centers.

Current bounds are x,z from -6 to 6 and y from -1 to 13. A 96 by 112 by 96 grid therefore has cubic cells of width 0.125. The `time` field is the physical simulation time in nondimensional units, not a frame index.

NPZ fields include `U`, `rho`, `velocity` (last dimension x,y,z), `pressure`, `temperature` (`p/rho`), `internal_energy`, `fuel`, `oxygen`, `soot`, `bounds`, `time`, `gamma` and JSON `metadata`. Fuel, oxygen and soot are **mass densities**, not fractions. Divide each by rho for mass fractions.

## Causality and conservation checks

`validate.py` checks a quiescent uniform volume, positivity/finite state, mass and energy budgets, and a pressure-coupling ablation. In the ablation, both cases start with the same density, chemical fields and internal energy, have zero initial velocity, and disable buoyancy. The ablated case replaces pressure in the flow flux with a spatially constant ambient value while retaining chemical/thermal evolution. This intentionally nonphysical control isolates the pressure force.

The normal case gains outward momentum and kinetic energy. The ablated case remains motionless. This is a causal check that pressure actually drives expansion, rather than merely coloring an independently expanding shape. The test is not a claim of quantitative blast validation.

The final hot-model checks are reproducible with:

```bash
python fields.py init checkpoints/oil48_initial --shape 48 56 48 --profile oil
python validate.py --initial checkpoints/oil48_initial --output validation/hot --threads 2 --heat 500 --confinement 2
```

At time 0.5 the normal hot case has kinetic energy 9.9903 and outward radial momentum 21.3480; the pressure-off control has exactly zero of both. Its material RMS radius remains 0.8018, while the normal case reaches 1.1254. The maximum acoustic CFL is 0.34910 with no rejected steps. Relative mass and total-energy budget residuals are about 1.08e-8 and 5.15e-9. A uniform ambient volume remains exactly unchanged in float32. These numbers refer to the 48 by 56 by 48 test grid, not a convergence study.

The completed production audit checked all 192 volumes, including a complete finite-value scan and SHA256 hashes. All 192 hashes are distinct. There are 1,483 accepted physical timesteps and no rejected timesteps; maximum observed acoustic CFL is 0.34946. Maximum relative mass and total-energy budget residuals are 4.40e-7 and 1.86e-7. The detailed records are in `production_audit.json` (also retained as `production_oil96/audit.json`).

## Visual quality status

The pressure/advection correction is implemented and tested. **Photorealism is not solved by that numerical correction.** The final 96 by 112 by 96 volume still has visibly soft large forms and grid-aligned bands in some views; it does not resolve the fine billows of a photographed oil explosion. The final frame sequence preserves the approved simulation and rendering settings consistently.

Separate optical experiments found that interpolating premultiplied emissivity (`j = extinction * source_radiance`) is a cleaner transport reconstruction than independently interpolating source radiance and extinction. The corresponding ray integral uses `j*(1-exp(-extinction*ds))/extinction`. That correction did not materially restore missing fine detail. Cubic reconstruction or mild spatial filtering suppresses some lattice bands at the cost of further softness. These experiments are **not integrated into the finalized frame sequence or delivered shader transport**, and must not be presented as a completed visual fix. No procedural density detail, new motion or additional physics was added during these optical experiments.

## Numerical references

- Clawpack's *Riemann Problems and Jupyter Solutions*, Euler approximate solvers: https://www.clawpack.org/riemann_book/html/Euler_approximate.html
- E. F. Toro, *The HLLC Riemann Solver*, SUM 2012: https://www.prague-sum.com/download/2012/Toro_2-HLLC-RiemannSolver.pdf
- R. Fedkiw, J. Stam and H. W. Jensen, *Visual Simulation of Smoke*, SIGGRAPH 2001 (vorticity confinement): https://www.graphics.stanford.edu/papers/smoke/

The implementation is an original compact reference following the standard conservative equations and HLLC construction.
