# infra/perf-xsim-slots: a separate xsim slot pool (ruling S60)

## What changed

- `tools/xut/slots.py` has two slot kinds:
  - `vivado`: `XUT_VIVADO_SLOTS`, default 4, for synthesis and
    implementation. It is unchanged.
  - `xsim`: `XUT_XSIM_SLOTS`, default 12. Its lock directory is
    `$XDG_RUNTIME_DIR/xut-xsim/`.
- `vivado_slot(kind=...)` selects the pool. `xsim.run_script`, used by the
  runner and the verilatorize oracle, and `xsim_version` take `kind="xsim"`.
- AGENTS.md §10.1 describes both pools and the measured xsim memory. xsim
  runs inside the caller's scope and budget.
- `tools/tests/test_slots.py` adds a separate-pool test. The spy test checks
  that the runner asks for the xsim kind.

## Results

- Benchmark: `xut run '7series.FDRE.*' --model-source unisim-2025.2 --runner
  xsim --jobs 16`, clean `build/rtl`, detached worktree at flops 9cc4eb9,
  32G scope under the heavy lock.
  - main (4 slots): 258 s.
  - This branch (12 xsim slots): 208 s (-19%).
  - With PR #17 as well: 115 s (-55%).
- The gain is capped because `xut run` runs one (test, runner) pair's
  configurations sequentially in one thread. The long L2 tests finish last.
  This is S60 item 2 (scheduling).
- The results are identical to main in both variants: 23 `result.json`
  (status, reason, per-configuration status, reason and trace sha256),
  154 `trace.xtr` and 65 `raw.txt`.
- Memory: the benchmark scope, twelve `xsim -R` at once, peaked at 3.4G.
- `pytest tools/tests/test_slots.py tools/tests/test_runner_xsim.py -m 'not
  vivado'`: 40 passed. ruff is clean.

## Next steps

S60 item 2: xsim-first, longest-first scheduling. That is also where the 12
slots pay off fully.

## Rebase onto main (#18 merged), then the code-quality review

- **Rebase.** Rebased onto 6a66bd6. The only conflict was AGENTS.md §10.1,
  where #18 had rewritten the same paragraph, and I merged the two texts by
  hand. They now say which pool a run takes by where it runs:
  - **The Vivado pool** is for runs in a 16G scope of their own: `hw build`
    and `hw sim`'s xsim, counted by `--vivado N`.
  - **The xsim pool** is for xsim inside the caller's scope: the runner and
    the oracle, counted by `--mem`.
- **`slots.py`.** The docstring says the same.
- **Validation.** `vivado_slot` validates `kind` up front, and `KINDS` is a
  `NamedTuple`.
- **Tests.** The slot test is split into four.
- **§10.1 table.** A 3.4G row for twelve xsim at once.
- **History note.** The benchmark in the entry above ran under the old
  `flock` mutex and predates `xut heavy`. Do not copy that command.
