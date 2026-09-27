# FDPE: UG953 gives two different INIT defaults

- Class: doc-gap (a documentation inconsistency; no simulator disagrees with the golden model)
- Test: 7series.FDPE.L1.capture (configuration `default`, which sets no attribute)
- Flow / model source: rtl / unisim-2025.2
- Also seen: rtl / unisim-gh-2020.1 (2026-09-27 at b3ffb16)
- Runners: none disagree
- First seen: 2026-09-26 (flops Task 26 log), filed 2026-09-27 at b3ffb16 (flops Task 24, ruling S42)
- Status: open

The id uses the level token `doc` (`<PRIM>-doc-gap-doc-<name>`, ruling S56a): no trace
produces this finding, so it has no test level.

## Evidence

UG953 v2026.1, FDPE section:

- p373, Available Attributes table: `INIT`, allowed values `1'b1, 1'b0`, default `1'b1`.
- p374, VHDL instantiation template: `INIT => '0'`; Verilog instantiation template:
  `.INIT(1'b0)`.

A template shows a starting value for the user to edit, so it is not a formal default. It
still contradicts the table. The same table-versus-template contradiction exists for
FDSE (p379 table `1'b1`, p380 templates 0): see `findings/FDSE-doc-gap-doc-init_default.md`.
FDRE (p376 table `1'b0`, p377 templates 0) and FDCE (p370 table `1'b0`, p371 templates 0)
are consistent. The two flops whose control forces Q High, and whose table default is
`1'b1`, are the two whose templates disagree.

## Analysis

The golden model (`models/xut_models/7series/fdpe.py`) follows the attribute table:
`INIT_DEFAULT = 1`, cited `doc:373`. `7series.FDPE.L1.capture` has a `default`
configuration that sets no attribute at all, so the model's documented default meets
UNISIM's own default there. It passes on every simulator of both model sources
(unisim-2025.2: xsim, iverilog, verilator; unisim-gh-2020.1: iverilog, verilator), so
UNISIM's default is `1'b1` too, in agreement with the table.

The risk is to users and flows, not to simulation: a design copied from the p374
template gets INIT=0, a flop that powers up Low, while the table (and UNISIM) say a
FDPE with no INIT powers up High. Nothing in the test suite needs to change. The
finding stays open until UG953 makes the template agree with the table; it is not listed
in any `expected_divergence`, because no trace disagrees.
