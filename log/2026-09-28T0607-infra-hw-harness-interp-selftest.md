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

## Fix round 1 (task-3-review.md minors 1–5)

- (1) New tests: multi-chunk in_vec with nin > 16. A 40-bit passthrough round-trips
  random vectors. On a 20-bit slot, a SET to chunk 1 is truncated to the partial top
  chunk, and a SET beyond the slot's chunks has no effect. That matches the RTL, which
  drops such a SET rather than raising an error.
- (2) `margin_violations` now runs on both real self-test programs, and it finds none.
- (3) Emulator hardening and docs:
  - `Harness` now checks every sample against `width(EmuSlot.nout)` and raises `EmuError`
    on a mismatch (tested).
  - A new test covers `ModelDut(two_state=True)`.
  - The module docstring documents that events are stamped at DECODE (change-to-capture
    gaps are overstated by one cycle) and that `cycles` leaves out S_SAMPLED and print time.
- (4) The skip text now says "hw unsupported" or "hw no" when the runner is declared that
  way, and "hw not declared" only when it is absent. Removed the unused `tmp_path`. The
  docstring now says the tested configurations are a superset of what the hw runner runs,
  and it notes the DutMap round-trip blind spot.
- (5) The S54 skip can no longer outlive S54. If `tests/7series/register/_shared/flops`
  or a `tests/7series/register/FD*` directory exists but no flops vector case is found,
  the test fails as `flops-cases-lost`. `test_s54_skip_only_while_the_flops_unit_is_absent`
  covers this.
- Minors (6) and (7) are left for later tasks, as the coordinator ruled.
- Results:
  - On this branch: 99 passed, 1 skipped (the S54 skip).
  - In the scratch flops merge: 57 passed, 10 skipped. The skipped cases are
    `hw unsupported`, each with its reason.
  - `ruff`: clean.
