# infra/hw-harness — Task 3: reference interpreter, harness emulator, self-test channels

## What changed

- `tools/xut/hw/interp.py` (stdlib only): `DutSim`, `CycleEvent`, `RunOutcome`,
  `run_program` (the xut_hw_ctrl cycle model: FETCH+DECODE per word, COMMIT/EDGE hold
  MARGIN+1, WAIT n holds n+1, SAMPLE in DECODE), `margin_violations`, `EmuSlot`, and
  `Harness.feed` (the UART protocol of `xut.hw.proto`, byte for byte).
- `tools/xut/hw/selftest.py` (stdlib only): slot 0 16-bit passthrough and slot 1 8-bit
  counter (CE, sync clear, wraps past 255), their programs, sims, expected samples and
  `check`.
- `tools/xut/hw/replay.py`: `ModelDut` (a golden model as a `DutSim`),
  `samples_to_trace`, `hw_replay`.
- `tools/xut/stimcompile.py`: `out_port_bits` / `port_values` lifted out of
  `raw_to_trace` (shared with `samples_to_trace`).
- Tests: `tools/tests/test_hw_interp.py`, `test_hw_selftest.py`, `test_hw_replay.py`,
  the `hw_toy.py` helper and the `fixtures/hw/TOYFF.v` toy.
- Ruling S54: `test_every_renderable_flops_configuration` discovers the flops vector
  tests when present and otherwise is one explicit skip (`no-flops-tests`, reason names
  the unmerged unit). Declared-unsupported cases skip with their `unsupported_reasons`.

## Test results

- This branch: `test_hw_{interp,selftest,replay,compile,image,proto}.py` and
  `test_stimcompile.py` (pytest -n 4, 8G scope): 92 passed, 1 skipped (the S54 skip).
  The step-2 `test_stimcompile.py` tests pass unchanged after the refactor.
- Proof against the flops unit: a scratch clone of `unit/7series/flops` (377b472)
  merged with this branch: `test_hw_replay.py` 38 passed (2 toy + 36 flops cases),
  10 skipped (hw unsupported: GSR tests, IS_D_INVERTED tests). 252 configurations
  compiled and interpreted, all equal to the golden trace; none was unrenderable.
- `ruff format` / `ruff check tools`: clean.

## Next steps

- Task 4: xut_hw_ctrl RTL, whose UART output must equal `Harness.feed` (Task 5 pins it).
- After flops merges and this branch is rebased, the flops replay test runs for real.
