# CFGLUT5: doc-gap in 7series.CFGLUT5.L1.projections

- Class: doc-gap
- Test: 7series.CFGLUT5.L1.projections
- Flow / model source: rtl / (none yet: written by hand before the first run, ruling S52)
- Runners: xsim, iverilog
- First seen: UG953 v2026.1 review, before any simulation
- Status: open

## Evidence

UG953 v2026.1 p348 says O5 and O6 can be used as two 4-input functions, or as a 5-input
and a 4-input function, "see the following tables". The CFGLUT5 section (pp. 348-349) has
no table, so it does not say which INIT bit an I4..I0 value selects on O6, or which bits
and inputs O5 uses.

The order UNISIM shows is recorded here by Task B6 of the unit playbook, for each model
source (`unisim-2025.2`, `unisim-gh-2020.1`):

- O6 index order: UNISIM unisim-2025.2 on iverilog and xsim, and unisim-gh-2020.1 on
  iverilog: O6 = INIT[{I4..I0}], as inferred. `xut crosscheck unit:luts` (run at 59252e3,
  2026-09-28) reports no disagreement on L1.projections, L1.partial_shift, L1.cdo_cascade
  or L2.init_sweep (every one `agree`, python, xsim and iverilog all `pass`).
- O5 bits and inputs: the same runs: O5 = INIT[{I3..I0}], the lower 16 bits, as inferred;
  the same four tests agree on every O5 sample.

## Analysis

The golden model infers O6 = INIT[{I4..I0}], as in the LUT5 logic table (p501), and
O5 = INIT[{I3..I0}], the lower half, as for LUT6_2's O5 (p509). Both are tagged
`inferred:`. Rulings S52 and S53: a read whose value depends on this order credits no
claim; only contents known to be uniform whatever the order (all 0 or all 1) credit
CFGLUT5.C1/C2, and L1.edge_polarity credits every claim from such reads alone. This finding stays open until the
documentation gives the tables, whatever UNISIM shows. The model is not changed to follow
a simulator (AGENTS.md §8).
