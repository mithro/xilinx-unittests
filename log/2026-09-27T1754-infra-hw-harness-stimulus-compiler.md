# Step 3, Task 2: the stimulus compiler — `.xvec` → harness program image

## What changed

- `tools/xut/hw/image.py` (new, standard library only): the harness program-image
  model — opcodes `OP_SET/OP_COMMIT/OP_EDGE/OP_WAIT/OP_SAMPLE/OP_END`, `CHUNK`,
  `MAX_CHUNKS`, `MAX_CLOCKS`, `MAX_WAIT`, the harness defaults `MAXWORDS`/`MARGIN`,
  `width`, `chunks`, the `w_*`/`decode` word codec, the frozen `HwProgram`, and
  `ImageBuilder` (`set_bits`, `edge`, `wait`, `sample`, `end`), `HwImageError`.
- `tools/xut/hw/compile.py` (new): `t0_bits` (the power-on in_vec from the `t=0 set`
  lines) and `compile_program` (an `.xvec` + `DutMap` → `HwProgram`), `HwCompileError`
  (invalid stimulus) and `HwUnrenderable` (valid but not stepped-harness renderable;
  message is `validate`'s `hw_reasons`, or the `expect=reject` reason).
- `tools/xut/stimcompile.py`: `_check_fits` renamed to the public `check_fits`, which
  now returns the `validate` `Report` it computes (`-> Report`) instead of `None`;
  its one in-module caller (`compile_vec`) updated. No other caller existed.
- `tools/tests/test_hw_image.py`, `tools/tests/test_hw_compile.py` (new): the task
  brief's test files, copied verbatim.

TDD followed as specified: wrote both test files first, confirmed collection failed
with `ImportError: cannot import name 'image' from 'xut.hw'`, then implemented
`image.py` and `compile.py` (and the `check_fits` rename) verbatim per the brief, and
reran.

## Test results

`uv run pytest tools/tests/test_hw_image.py tools/tests/test_hw_compile.py
tools/tests/test_stimcompile.py -v -n 4`, scoped (`systemd-run ... -p MemoryMax=8G -p
MemorySwapMax=0`): **55 passed**, 0 failed, 0 skipped — 8 new (`test_hw_image.py` 6 +
`_hw_compile.py` 5, one parametrized into 4 cases) plus the 47 pre-existing
`test_stimcompile.py` tests, which still pass unchanged after the `check_fits` rename
(including the Icarus/Verilator replay tests).

`ruff format tools`: 105 files left unchanged. `ruff check tools`: all checks passed.

`xut lint --branch` (scoped `MemoryMax=4G`): see report for the result recorded at
push time.

## Next steps

Task 3 (per the plan) builds on this program image: the reference interpreter
(`xut.hw.interp`) that replays an `HwProgram` and the harness RTL that must match it
byte-for-byte in simulation.
