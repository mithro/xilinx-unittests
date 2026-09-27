# infra/cocotb-time0: the cocotb top drives its inputs at time 0 by a non-blocking update

## What changed
- `tools/xut/wrap.py` (`render_cocotb_top`): `clk` and `in_vec` have no declaration
  initialiser. They are x until an `initial` block's time-0 non-blocking update drives
  them to 0. This is the same barrier as `xut_vector_tb.sv` (unit playbook decision D7).
  The old initialiser set 0 before any process ran. An `always @(inputs)` model (a
  behavioural LUT) on Icarus therefore never saw that value as an event, and the
  session's idle writes of the same 0 made no event either. LUT4–LUT6 and LUT6_2 cocotb
  outputs stayed x for the first 1–2 samples. This was the luts branch's B4–B5
  harness-error.
- `tools/tests/test_runner_cocotb.py` has two new regression tests:
  - The first is hermetic: the generated top declares `clk` and `in_vec` without an
    initialiser and drives them with a non-blocking update.
  - The second runs in the container on `iverilog`, `verilator` and `iverilog-vz`. It
    uses a toy model `TOYCOMB` whose outputs are regs written by `always @(A or B)` and
    `always @(C)` (written for this test, not UNISIM text). The fixture session in
    `tools/tests/fixtures/cocotb/cocotb_toycomb.py` re-drives the idle 0s and checks that
    S0 and S1 are already defined.
  - Before the fix, the container test failed on iverilog and iverilog-vz
    (`S0: ('x', 'x')`) and passed on Verilator (2-state).

## Test results
- New tests: 1 hermetic and 3 container tests. They failed before the fix (3 failed,
  Verilator passed) and all 4 pass after it.
- `test_runner_cocotb`, `test_runner_iverilog`, `test_runner_verilator`, `test_runner_sim`,
  `test_runner_base` and `test_wrap` (`-n 8`, container tests included): 348 passed,
  0 skipped.
- luts branch (ddb369f, a detached scratch copy with only this wrap.py change applied),
  `xut run '7series.*.L2.cocotb*' --runner iverilog`:
  - Before: LUT4, LUT5, LUT6 and LUT6_2 fail (x at S0, or at S0 and S1); CFGLUT5 and
    LUT1–LUT3 pass.
  - After: all 8 pass.
  - The traces differ only in those x samples, which now hold the golden value.
  - The LUT1–LUT3 and CFGLUT5 traces are byte-identical.
  - With `--runner verilator` after the fix, LUT1–LUT6 and LUT6_2 pass on both verilator
    and iverilog-vz. CFGLUT5 is a declared skip (ruling S28).
- flops branch (264efe4, a scratch copy), `xut run '7series.*.L2.cocotb*' --runner
  iverilog --runner verilator`: all 12 results pass both before and after the fix, and
  all 92 `trace.xtr` files are byte-identical.

## Next steps
- The luts branch re-runs its cocotb tests once this merges. No
  `findings/*-harness-error-*` file is needed if it merges before the luts results are
  recorded.
