# flops: FDRE GSR mid-simulation and X-input sv testbenches (Task 22)

Branch `unit/7series/flops`, HEAD 201f9cb at the start of this session.

## What changed

- Added the two shared sv testbench bodies (spec §4.3 sv style), parameterised by
  `FLOP_TB`/`FLOP_PRIM`/`FLOP_CTRL`/`FLOP_FORCED`/`FLOP_ASYNC`:
  - `tests/7series/register/_shared/flops/flop_gsr_tb.svh`: two direct UNISIM instances
    (`INIT=1'b0`/`INIT=1'b1`), forces `glbl.GSR_int` mid-run while clocking, checks GSR ->
    INIT on Q (C4) and capture after release (C1). Clock edges taken while GSR is still
    active are recorded as checkpoints (`P<n>.gsr_edge`) only, since UG953 does not
    describe them.
  - `tests/7series/register/_shared/flops/flop_x_tb.svh`: drives `1'bx` on D, CE and the
    control in turn. Checks the two documented cases (CE Low holds Q with D=x, C2; an
    active control forces Q with D=CE=x, C3) and records the three undocumented cases
    (D=x with CE High, CE=x, control=x) as checkpoints only.
  - `tests/7series/register/FDRE/sv/tb_fdre_gsr.sv` and `tb_fdre_x.sv`: one-line includers
    that define `FLOP_PRIM=FDRE`, `FLOP_CTRL=R`, `FLOP_FORCED=1'b0`, `FLOP_ASYNC=0` (R is
    a synchronous control, UG953 p375-376) and include the shared body.
- Followed the brief in `task-22-brief.md` verbatim, with one deliberate deviation per
  ruling S36: `if (\`FLOP_ASYNC) \`XUT_CHECK(...)` is wrapped in an explicit `begin`/`end`
  in `flop_x_tb.svh`. This turned out to be belt-and-braces: `XUT_CHECK` in
  `tools/xut/hdl/xut_trace.svh` already expands to its own `begin ... end` block, so the
  bare `if (cond) \`XUT_CHECK(...)` (no `else` follows it) was already a single statement
  and safe either way. Keeping the explicit wrap makes that safety obvious to a future
  reader/editor without requiring them to expand the macro by hand.
- No test.yaml edits: both `7series.FDRE.L1.sv_gsr_midsim` and `.sv_x_inputs` were already
  declared (runners, `unsupported_reasons`, `configs`) by an earlier task.

## Tests

Per ruling S36, only `iverilog` and `xsim` were run — `verilator`/`iverilog-vz` aren't on
this branch yet (Task 15 is on `infra/verilatorize`); those expectations move to Task 24's
end-to-end run after that branch merges and this one rebases.

```
uv run xut run 7series.FDRE.L1.sv_gsr_midsim 7series.FDRE.L1.sv_x_inputs \
  --runner iverilog --runner xsim --jobs 8
```

- `7series.FDRE.L1.sv_gsr_midsim`: **pass** on iverilog and xsim. Checkpoints `P0`,
  `P1.gsr`, `P1.gsr_edge`, `P1.released`, `P1.after`, `P2.gsr`, `P2.gsr_edge`,
  `P2.released`, `P2.after` — identical trace.body on both simulators.
- `7series.FDRE.L1.sv_x_inputs`: **pass** on iverilog and xsim. Checkpoints `X1`, `X2a`,
  `X2`, `X3`, `X4`, `X5a`, `X5` — identical trace.body on both simulators (`X3  Q=x`,
  `X4  Q=0`, `X5a  Q=1`, `X5  Q=1` on both). No iverilog-vs-xsim divergence on any
  checkpoint, documented or undocumented, so there is nothing for `xut crosscheck` to
  flag as `sim-divergence` here; no finding filed.
- `uv run xut lint`: 0 errors (42 pre-existing warnings, all `related id ... does not
  exist` for sibling FDSE/FDCE/FDPE tests not yet written; unrelated to this change and
  present before it too).
- `uv run xut lint --branch`: 0 errors, same 42 pre-existing warnings; no branch-paths
  issues (the new files are all under the flops unit's owned paths).
- `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: 1308 passed, 1 skipped.

## Next steps

- Task 24: end-to-end run once `infra/verilatorize` (Task 15) merges and this branch
  rebases, to record the `verilator`/`iverilog-vz` results these two tests already
  declare in `test.yaml` ('yes' for `sv_gsr_midsim`, `unsupported` for `sv_x_inputs`).
