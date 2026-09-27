# FDPE: UG953 gives two different INIT defaults

- Class: doc-gap (a documentation inconsistency; no simulator disagrees with the golden model)
- Test: 7series.FDPE.L1.capture (configuration `default`, which sets no attribute)
- Flow / model source: rtl / unisim-2025.2 and unisim-gh-2020.1
- Runners: none disagree
- First seen: 2026-09-26 (flops Task 26 log), filed 2026-09-28 (flops Task 24, ruling S42)
- Status: open

## Evidence

UG953 v2026.1, FDPE section:

- p373, Available Attributes table: `INIT`, allowed values `1'b1, 1'b0`, default `1'b1`.
- p374, VHDL instantiation template: `INIT => '0'`; Verilog instantiation template:
  `.INIT(1'b0)`.

A template shows a starting value for the user to edit, so it is not a formal default. It
still contradicts the table, and every other flop in the group (FDCE p370/p371, FDRE,
FDSE) uses the same value in its table and its templates.

## Analysis

The golden model (`models/xut_models/7series/fdpe.py`) follows the attribute table:
`INIT_DEFAULT = 1`, cited `doc:373`. `7series.FDPE.L1.capture` has a `default`
configuration that sets no attribute at all, so the model's documented default meets
UNISIM's own default there. It passes on every simulator of both model sources, so UNISIM's
default is `1'b1` too, in agreement with the table.

The risk is to users and flows, not to simulation: a design copied from the p374 template
gets INIT=0, a preset flop that powers up Low, while the table (and UNISIM) say an FDPE
with no INIT powers up High. Nothing in the test suite needs to change. The finding stays
open until UG953 makes the template agree with the table; it is not listed in any
`expected_divergence`, because no trace disagrees.
