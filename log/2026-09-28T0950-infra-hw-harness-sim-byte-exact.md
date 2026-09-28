# infra/hw-harness: Task 5a, capped scopes and the harness in simulation

## What changed

- `tools/xut/scope.py` (new): `scope_argv`, `scoped_run` (refuses without systemd-run),
  `run_in_group` (process group plus timeout, the one copy), `cached_version` (the one
  per-process version cache), `VIVADO_MEMORY_MAX`, `OOM_RCS`.
- `tools/xut/runners/xsim.py`: `run_script` and `xsim_version` use `run_in_group` and
  `cached_version`. PR #17's standalone `axsim` script is unchanged, and PR #10's
  `vivado_slot()` still wraps both the run and the version probe. A module-level
  `vivado_slot()` resolves `xut.slots.vivado_slot` at call time, so a test can patch
  either name.
- `tools/xut/hw/steps.py` (new): `Step`, `session_steps`, `split_replies`,
  `slot_replies`, `run_replies`. The docstring states the one-command-in-flight
  precondition.
- `tools/xut/hw/hwsim.py` (new): `simulate` on Icarus (in the 4g container) or on xsim
  (`scoped_run` at 16G inside `vivado_slot()`), plus `render_host`, `max_sim_jobs`,
  `HwSimError` and `SimResult`. `SimResult` gains `x_samples`, and `simulate` gains
  `monitor_margin`. An OOM-killed xsim run is an error.
- `tools/xut/hdl/hw/xut_hw_tb.sv` (new): the testbench. How it checks:
  - The host waits for each whole reply before it sends the next command.
  - The margin monitor times captures at the physical `cur_out` capture
    (`sample_take` − 2).
  - `XUT_X_SAMPLE` reports an X or Z in the sampled bits.
  - `XUT_X_TX` reports an X or Z in a transmitted byte, which is a harness error.
- `tools/xut/hw/interp.py`: `Harness.feed` clears its buffer before it raises
  `EmuError`, so the harness stays usable (Task 4 re-review, Minor 1).

## Test results

- `test_hw_rtl.py`: 8 passed.
  - The byte-exact comparison against the emulator passes on Icarus and on xsim. It
    covers every error path, the self-test slots, two toy FF slots, and a 20-bit
    two-chunk slot, including chunk truncation and a SET to a missing chunk.
  - The monitor test on Icarus, with a bound of MARGIN+2: every capture gap it flags is
    exactly MARGIN+1 (17). One X sample is flagged.
- `test_scope.py`: 6 passed. `test_hw_steps.py`: 2 passed. `test_hw_interp.py`: 19
  passed.
- Full suite (`pytest -n 8`, 16G scope, host lock): 2105 passed, 18 skipped.
- `ruff check` and `ruff format --check` are clean.
- `xut lint --branch`: 0 errors. There are 4 pre-existing `portability-agreement`
  warnings from the flops unit on main.

## Next steps

- Task 5b: `sim_case` against the golden flop traces.
- Task 6: the build test should assert both exceptions in `report_exceptions`.
