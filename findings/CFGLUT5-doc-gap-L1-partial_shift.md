# CFGLUT5: doc-gap in 7series.CFGLUT5.L1.partial_shift

- Class: doc-gap
- Test: 7series.CFGLUT5.L1.partial_shift
- Flow / model source: rtl / (none yet: written by hand before the first run, ruling S52)
- Runners: xsim, iverilog
- First seen: UG953 v2026.1 review, before any simulation
- Status: open

## Evidence

UG953 v2026.1 p348 says a new INIT is shifted in serially through CDI while CE is High,
and that CDO cascades to the next CFGLUT5's CDI (32 bits per LUT). It gives no shift
direction: which INIT bit CDI enters, and which INIT bit drives CDO.

The order UNISIM shows is recorded here by Task B6 of the unit playbook, for each model
source (`unisim-2025.2`, `unisim-gh-2020.1`):

- the INIT bit CDI enters: UNISIM unisim-2025.2 on iverilog and xsim, and
  unisim-gh-2020.1 on iverilog: INIT[0], each shift moving INIT[i] to INIT[i+1], as
  inferred. `xut crosscheck unit:luts` (run at 59252e3, 2026-09-28) reports no
  disagreement on L1.projections, L1.partial_shift, L1.cdo_cascade or L2.init_sweep
  (every one `agree`, python, xsim and iverilog all `pass`).
- the INIT bit on CDO: the same runs: INIT[31], as inferred (L1.cdo_cascade agrees on
  every one of its 64 per-shift CDO samples).

## Analysis

The golden model infers that CDI enters INIT[0], that each shift moves INIT[i] to
INIT[i+1], and that INIT[31] drives CDO. The inference is tagged `inferred:`. Rulings S52
and S53: an output whose value depends on it credits no claim; CFGLUT5.C3/C5/C7 are
credited only where the contents are known to be uniform whatever the direction (uniform
since power-on with equal bits shifted in, or after 32 equal shifts). This finding stays open until the documentation
states the direction, whatever UNISIM shows.

Known blind spot (luts B1-B5 review, Minor 1): because CDO is order-dependent whenever the
contents are not known-uniform, nothing checks CDO *during* a run of shifts; only the
value after a full 32-shift run is documented. A simulator that shifts two bits per
active edge therefore passes every documented bit. One reading of p348's "32 bits per
LUT" cascade is that CDO keeps the old uniform value for the first 31 shifts of an
opposite-valued run, whatever the direction; that reading would catch it, but it goes
beyond what the page states, so it is not modelled. It is a candidate C5 strengthening
for Tier 2 if the documentation, or an orchestrator ruling, settles the latency.
