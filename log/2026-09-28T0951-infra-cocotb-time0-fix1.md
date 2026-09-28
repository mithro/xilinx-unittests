# infra/cocotb-time0: review fix round 1 (M8 must-fix, clk keeps its declaration initialiser)

## What changed

Correctness review (rev8/review-24.md) found a must-fix: the previous commit removed
`clk`'s declaration initialiser along with `in_vec`'s, so `clk` gained an x-to-0 event at
time 0 on Icarus (iverilog and iverilog-vz) — a spurious negedge, and a posedge on an
`IS_*_INVERTED` internal clock — while the data inputs were still x. GSR masks this for
flops (INIT holds through it), but not for clocked storage without GSR, and it has no
counterpart in `xut_vector_tb.sv` or the golden replay.

- `tools/xut/wrap.py` (`render_cocotb_top`): `clk` now keeps its declaration initialiser
  (`reg [...] clk = {...{1'b0}};`), exactly as `xut_vector_tb.sv`'s `clk_step`,
  `clk_free` and `free_en` keep theirs, so it has no event at time 0 there either. Only
  `in_vec` goes through the time-0 non-blocking-update barrier now. Rewrote the docstring:
  it no longer claims `clk` uses "the barrier of `xut_vector_tb.sv`" (it never did; only
  `in_vec` does), and it now states plainly that `clk` must not be barriered, and why.
  It also documents the pre-existing, unrelated Verilator behaviour below (nit).
- `tools/tests/test_runner_cocotb.py`:
  - `test_cocotb_top_drives_inputs_by_a_time0_nonblocking_update` split into
    `test_cocotb_top_drives_in_vec_by_a_time0_nonblocking_update` (in_vec only, plus an
    explicit `"clk <=" not in text` check) and `test_cocotb_top_gives_clk_no_time0_edge`
    (pins that clk's declaration keeps its `= 0` initialiser: review's must-fix, direct).
  - New container test `test_cocotb_top_has_no_time0_clock_edge_on_icarus`
    (`iverilog`, `iverilog-vz`), behavioural: a new toy model `TOYNEG`
    (`always @(negedge C) f <= 1;`, `tools/tests/fixtures/cocotb/cocotb_toyneg.py`) samples
    `F` once at S0 with no session write to `C`. `F` must stay 0 (no time-0 clock edge).
    Not parametrized over `verilator`: it already has an unrelated time-0 negedge on clk
    (2-state `--x-initial unique` reset), which this fix does not touch (review nit).
  - `TOYCOMB` lost its `P`/`C` half (`P = ~C`, event-driven off `clk`'s barrier): with
    `clk` no longer barriered, `always @(C)` never fires and `P` would stay x forever,
    which is not what that half was pinning. TOYCOMB now only checks `O = ~(A | B)`,
    driven purely by `in_vec`'s barrier; the clock-edge behaviour moved to TOYNEG above,
    which is the right fixture for it.
- Reworded the PR body: dropped the "barrier of `xut_vector_tb.sv`" claim for clk; added
  the nit that Verilator already saw a time-0 negedge on clk before this PR, unrelated to
  this fix.

## Verification of the must-fix (sanity check on the un-fixed code)

Before restoring the corrected `wrap.py`, ran only the new
`test_cocotb_top_has_no_time0_clock_edge_on_icarus` against the buggy pre-fix
`render_cocotb_top` (clk barriered, matching the review's finding): both `iverilog` and
`iverilog-vz` failed with `F was set: a time-0 clock edge fired ({'F': '1'})`. Restored
the corrected `wrap.py` (clk keeps its initialiser) and re-ran: both pass (`F: '0'`).
This confirms the new test actually pins the must-fix rather than passing vacuously.

Commands (capped scope, `xut-heavy.lock` held):
```
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice \
  --unit=xut-p24fix-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run pytest "tools/tests/test_runner_cocotb.py::test_cocotb_top_has_no_time0_clock_edge_on_icarus" -n 8
```

## Test results

- `uv run ruff check tools`: 0 errors. `uv run ruff format --check tools`: 104 files
  already formatted.
- Full suite, capped scope, `-n 8`:
  ```
  flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice \
    --unit=xut-p24fix-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
    uv run pytest tools/tests/test_runner_cocotb.py tools/tests/test_runner_iverilog.py \
      tools/tests/test_runner_verilator.py tools/tests/test_runner_sim.py \
      tools/tests/test_runner_base.py tools/tests/test_wrap.py -n 8
  ```
  351 passed (349 from the prior commit + 2 new: `test_cocotb_top_gives_clk_no_time0_edge`
  and `test_cocotb_top_has_no_time0_clock_edge_on_icarus[iverilog-vz]`/`[iverilog]` counted
  with the existing parametrizations).
- luts branch, re-verified against the **corrected** fix, in a fresh detached worktree
  off the current unit branch HEAD (`ddb369f`, unchanged), with only `tools/xut/wrap.py`
  copied over from this branch:
  ```
  flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice \
    --unit=xut-p24fix-luts-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
    uv run xut run '7series.*.L2.cocotb*' --runner iverilog --runner verilator --jobs 8
  ```
  All 8 LUT primitives pass on `iverilog`, `verilator` and `iverilog-vz` (CFGLUT5 is the
  pre-existing declared Verilator skip, ruling S28). The luts x-first-sample fix still
  holds with `clk` restored to its declaration initialiser.
- flops branch, same treatment, off the current unit branch HEAD (`9c11782`, further
  along than the review's `264efe4` but the same wrap.py-only diff applies cleanly):
  ```
  flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice \
    --unit=xut-p24fix-flops-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
    uv run xut run '7series.*.L2.cocotb*' --runner iverilog --runner verilator --jobs 8
  ```
  All 12 results pass on `iverilog`, `verilator` and `iverilog-vz` (GSR still masks the
  clk-barrier difference for flops either way, as the review found).
- `xut lint --branch`: see below.

## Disagreements with the review

None on substance. The review's suggested fixture design (drop TOYCOMB's `P`/`C` half,
add a dedicated negedge-pinning toy) is exactly what was implemented; the "sanity check
on the un-fixed code" step above was added on top of the brief to make sure the new
pinning test isn't vacuously true.

## Next steps

- None outstanding from this review round; awaiting re-review.
