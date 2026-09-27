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

- the INIT bit CDI enters: (to be recorded)
- the INIT bit on CDO: (to be recorded)

## Analysis

The golden model infers that CDI enters INIT[0], that each shift moves INIT[i] to
INIT[i+1], and that INIT[31] drives CDO. The inference is tagged `inferred:`. Rulings S52
and S53: an output whose value depends on it credits no claim; CFGLUT5.C3/C5/C7 are
credited only where the contents are known to be uniform whatever the direction (uniform
since power-on with equal bits shifted in, or after 32 equal shifts). This finding stays open until the documentation
states the direction, whatever UNISIM shows.
