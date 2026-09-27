# unit/7series/luts — intake and claims (Task B1)

Branch `unit/7series/luts`, cut from `main` at f6986bb (P1 / PR #14's `xut.unitkit` merged).
This is Task B1 of the unit playbook (`2026-09-28-unit-playbook`, Part B), transcribed from the
reviewed plan.

## Intake

- **UG953 v2026.1 pages** (checked against the page footers of the text export):
  CFGLUT5 pp. 348-349, LUT1 pp. 488-489, LUT2 pp. 491-492, LUT3 pp. 494-495,
  LUT4 pp. 497-499, LUT5 pp. 500-502, LUT6 pp. 504-507, LUT6_2 pp. 509-512.
- **What is documented.** LUT1-LUT6 have a complete logic table (O = INIT[{I<n-1>..I0}]) and a
  zero INIT default ("a ground"). LUT6_2's table gives O6 = INIT[{I5..I0}] and
  O5 = INIT[{I4..I0}] (lower 32 bits; I5 does not reach O5), with the p509 OR example
  64'hFFFFFFFFFFFFFFFE. CFGLUT5 (p348) documents the serial reload through CDI while CE
  (active-High) is High, the O6/O5 outputs, the CDO cascade (32 bits per LUT), the all-zeroes
  INIT default and IS_CLK_INVERTED (p349).
- **What is not documented.** CFGLUT5 p348 cites O5/O6 tables that the 2026.1 section does not
  contain, and gives no shift direction and no CDO bit. The golden model will infer them
  (decision D5, `inferred:`), and two `doc-gap` findings record the gap before any run
  (ruling S52). No LUT has GSR text (decision D6: inferred, credits nothing).
- **Portability** (`status/PORTABILITY.md`, both model sources): LUT1-LUT6 and LUT6_2 are
  `yes`/`yes`, verilatorize `unchanged`. CFGLUT5 is iverilog `yes`, verilator
  `no: verilatorize: ... (ruling S28)`, so every CFGLUT5 test will declare
  `verilator: "unsupported"` (CFG_VL).
- **Hardware class.** No pad, inout, `clock_out` or `drp` port. CFGLUT5's CLK is a stepped
  clock. Every vector test is renderable except the GSR tests (`HW_GSR`) and the reject tests
  (`HW_REJ`).
- **Legality.** Every INIT value of the declared width is legal; the only illegal value tried is
  an INIT with x digits (`L0.illegal_init`).
- **Not claims.** LUT1-LUT5's statements on grouping several LUTs into one LUT6 are Vivado
  packing rules for several instances; each override records that as a comment.
- **Doc notes.** LUT5's p501 table labels the output "LO" (the port is O); CFGLUT5's VHDL
  template (p349) spells the generic INT.
- **Configuration estimate** (from the plan): 88 tests (64 vector, 16 sv, 8 cocotb),
  706 vector configurations, 23 sv and 32 cocotb configurations.

## Claims

| Primitive | Claims |
|---|---|
| LUT1-LUT6 | C1 logic table (table page), C2 zero default (Introduction page) |
| LUT6_2 | C1 O6 table (p510), C2 O5 lower half (p510), C3 zero default (p509), C4 OR example (p509) |
| CFGLUT5 | C1 O6, C2 O5, C3 CE-High shift, C4 CE-Low hold, C5 CDO cascade (p348); C6 INIT at start-up, C7 IS_CLK_INVERTED (p349) |

Validation (`load_entry` + `coverage_bins`): LUT1 2 claims / 7 bins, LUT2 2/10, LUT3 2/13,
LUT4 2/16, LUT5 2/19, LUT6 2/22, LUT6_2 4/25, CFGLUT5 7/36, as the plan predicted.

`xut status init --refresh-bins` refreshed exactly the eight luts stubs (the new claim bins);
no other file changed.

## Commits

- `luts: add catalog overrides with behavioural claims for LUT1-LUT6, LUT6_2, CFGLUT5`
- `luts: add doc-gap findings for CFGLUT5's undocumented bit order (ruling S52)`

## Next steps

Task B2 (clean-room golden models), then B3 (recipes, file generator, guards).
