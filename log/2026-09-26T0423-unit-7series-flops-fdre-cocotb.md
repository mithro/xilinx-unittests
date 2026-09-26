# Task 23: FDRE cocotb constrained-random session

## What changed

- `tests/7series/register/_shared/flops/flops_cocotb.py`: `random_session(dut, prim,
  cycles=2000)`, the constrained-random cocotb session shared by the flops unit (spec
  §4.3 cocotb style). Drives random CE/D/control and clock edges through `XutDut`,
  applies the same events to the golden model (`xut_models.registry.get`), and compares
  `Q` after every clock edge and every async control change, sampling every comparison
  point into `trace.xtr`.
- `tests/7series/register/FDRE/cocotb/cocotb_fdre_random.py`: the
  `7series.FDRE.L2.cocotb_random` cocotb test, `fdre_random` -> `random_session(dut,
  "FDRE", cycles=2000)`.

Followed the Task 23 brief verbatim except for Ruling S37, which overrides it:

1. Ran only `--runner iverilog --runner xsim` (verilator and iverilog-vz are not on
   this branch yet; they move to Task 24, per Ruling S36 carried forward). `xsim`
   skips with its declared reason (test.yaml already declares it `unsupported`: "cocotb
   has no xsim backend").
2. The model (`models/xut_models/7series/_common/flops.py` `set_input`) refuses any
   input value other than 0/1. The brief's `for p in ("CE", "D", k.ctrl): model.set_input(p,
   x.value(p))` runs right after only the control port has been driven
   (`await x.set(**{k.ctrl: inv_ctrl})`), reading CE and D's shadow implicitly rather
   than through an explicit drive. Changed to `await x.set(CE=0, D=0, **{k.ctrl:
   inv_ctrl})` first, so every port fed to `model.set_input` was explicitly driven to a
   defined value by this session before being read back with `x.value()`.
3. No mismatch occurred, so the "never mask, freeze instead" rule (S37(3)) was not
   exercised this task.

## Test results

`uv run xut run 7series.FDRE.L2.cocotb_random --runner iverilog --runner xsim`:

```
progress: done=1 total=2 elapsed_s=9.6  7series.FDRE.L2.cocotb_random iverilog: pass
progress: done=2 total=2 elapsed_s=9.6  7series.FDRE.L2.cocotb_random xsim: skip

test                           iverilog  xsim
7series.FDRE.L2.cocotb_random  pass      skip
skip: declared unsupported: cocotb has no xsim backend (spec §4.3) (1 result)
```

- iverilog: pass, all 4 declared configurations (`default`, `init1`, `inv_all`,
  `init1_inv_c`), 0 mismatches each. Each config's `trace.xtr` holds exactly 4000
  samples (2000 cycles × 2 edges), confirmed by line count.
- xsim: skip, declared reason, as expected.
- python: not run this task (already recorded `skip`, "declared unsupported: the
  cocotb test compares against the golden model itself" — the test.yaml declaration).
- verilator: deferred to Task 24 per Ruling S37(1).

No disagreements between UNISIM (iverilog) and the golden model were observed for any
seed, so no finding was filed and no seed needs freezing.

## Verification

- `uv run ruff format` on the new files: unchanged.
- `uv run ruff check` on the new files: 0 errors beyond the known ANN gap on `tests/`
  (`ANN001`/`ANN201` for the untyped `dut` cocotb argument — matches the existing
  `tools/tests/fixtures/.../cocotb_toyff.py` style).
- `uv run xut lint`: 0 errors (42 pre-existing warnings, all `tests-documented`
  `related id ... does not exist` for FDSE/FDCE/FDPE ids not yet implemented; unrelated
  to this change).
- `uv run xut lint --branch`: 0 errors, same 42 warnings.
- `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: 1308 passed, 1 skipped.

## Next steps

- Task 24: rerun with `--runner verilator` (and `iverilog-vz`) once those runners land
  on this branch, per Ruling S36/S37.
- If a future seed disagrees, classify and record the finding, freeze the seed into
  `vectors/frozen/<seed>.xvec` (S37(3)) — never mask by weakening the session.
