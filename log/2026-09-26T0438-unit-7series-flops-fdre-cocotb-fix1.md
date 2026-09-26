# Task 23 fix round 1: claim:FDRE.C4 exercised only by luck

## What changed

- `tests/7series/register/_shared/flops/flops_cocotb.py`: added an explicit `check()`
  call right after `model.glbl("GSR", 0)`, before the main loop, so the
  power-on/GSR-release INIT value (claim `*.C4`/gsr_init) is always compared instead of
  being overwritten by the first random draw before anything sees it (review: only
  ≈17% of seeds happened to validate it; this task's seed `1265722429` passed by luck).
  Updated the module docstring to state the new per-trace sample count
  (`2 * cycles + 1`, i.e. 4001 for `cycles=2000`, not 4000).
- Commented the `exp.bits != "-"` don't-care guard in `check()`: dead code for the
  flops model (never emits `-`), kept because the session is shared by later
  primitives whose models may emit one (spec §5.3).
- Did **not** merge the `flop_recipes` import into one group with `xut`/`xut_models` as
  the review's other minor suggested (matching the brief's literal snippet): verified
  this reintroduces `ruff` `I001`, since `pyproject.toml`'s
  `[tool.ruff.lint.isort] known-first-party = ["xut", "xut_models"]` does not include
  `flop_recipes`, so ruff's isort always re-splits the group. `pyproject.toml` is
  infra-owned; left the import groups as ruff already requires (unchanged from the
  original commit).

## Test results

`uv run xut run 7series.FDRE.L2.cocotb_random --runner iverilog --runner xsim`:
`iverilog: pass`, `xsim: skip` (declared reason). All 4 configurations
(`default`, `init1`, `inv_all`, `init1_inv_c`) pass with 0 mismatches; each `trace.xtr`
now holds 4001 samples (confirmed by line count), up from 4000. Stimulus seed
unchanged: `1265722429`.

## Verification

- `uv run ruff format` on the two files: unchanged.
- `uv run ruff check` on the two files: 0 errors beyond the known ANN gap.
- `uv run xut lint --branch`: 0 errors, 42 pre-existing unrelated warnings.
- `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: 1308 passed, 1 skipped.

## Next steps

- None new. Task 24 (verilator/iverilog-vz) still pending per Ruling S36/S37.
