# infra/perf-cfgpar: every configuration is a unit of work (ruling S61)

## What changed (three commits)

1. **Runner template split into three steps.** It is now `begin`, then
   `run_cfg` per configuration, then `end`. `Runner.run` is still the
   sequential loop, with the same results, logs and error semantics. An
   exception outside `run_config` still makes the whole pair an error,
   raised again in configuration order. `PythonRunner` keeps per-test state,
   so it sets `parallel_configs = False`.
2. **`ensure_model` concurrency.**
   - The per-model lock covers only loading or transforming the entry.
   - The descendant derivation and the equivalence check of each
     configuration key take a per-(model, key) lock, so each key is checked
     exactly once and different keys run at the same time.
   - The manifest is still written under `_MANIFEST_LOCK`, reloaded before
     every write.
3. **`xut run` scheduler.** Each pair is three kinds of task: a `begin` task,
   one task per configuration, and an `end` task. No task ever waits on
   another.
   - Configurations run in the main pool of `--jobs` workers, each holding
     at most one container, so the memory budget is unchanged.
   - xsim configurations run in a host pool of `min(jobs, xsim slots)`
     workers.
   - Pairs start highest level first.
   - `result.json`, `trace.xtr` and `run.log` are aggregated in
     configuration order, and the summary keeps selection order.
   - Runners with state, or that override `run`, run whole.
   - Ctrl-C cancels both pools, calls `kill_live` and writes an interrupted
     summary.

## Results

- **Benchmark.** `xut run '7series.FDRE.*' '7series.FDCE.*' --model-source
  unisim-2025.2 --jobs 16`, every runner, on flops head 9c11782 merged with
  main.
  - The warm-up is FDRE and FDCE `L2.exhaustive` on verilator.
  - Before: `infra/perf-xsim-slots`, #20. After: this branch.
  - Wall time: **331.6 s before, 197.6 s after (-40%)**. Both exit 1 because
    of the known flops fails.
  - The runs were under the heavy lock in a 32G scope.
- **Byte-identical.**
  - All 145 `result.json`: status, reason, seeds, x_dependence, and each
    configuration's status, reason, trace and stimulus sha256, and
    mismatches.
  - 1017 `trace.xtr`, 828 `raw.txt` and 148 `xdep.json`.
  - Every pair's `run.log` configuration sections, in the same order.
- **Full pytest** in four chunks, each under the heavy lock in a 32G scope
  with `-n 8 --dist loadfile`, releasing the lock between chunks:

  | Chunk | Tests | Result | Time |
  |---|---|---|---|
  | A | the verilator, iverilog and cocotb runners | 176 passed | 199 s |
  | B | the `vz_*` tests except `vz_rewrite` | 174 passed, 6 skipped | 176 s |
  | C | xsim (with Vivado), `vz_rewrite`, portability, crosscheck | 338 passed, 1 skipped | 339 s |
  | D | everything else | 1223 passed, 1 skipped | 65 s |

- **New tests.**
  - `test_run_parallel.py`, 9 tests, passed 5 runs out of 5. They cover:
    - configuration order, byte-equal to the sequential template;
    - peak concurrency equal to `--jobs`;
    - the size of the host pool;
    - stateful runners running whole;
    - level order;
    - a runner that cannot be constructed, and an exception outside
      `run_config`;
    - Ctrl-C.
  - `test_vz_driver.py`: 8 threads over 2 keys give one check per key, run
    concurrently. The test fails on the old code.

## Negative result: xsim-first scheduling (S60 item 2, no PR)

Ruled on in S61. Every run was FDRE with every runner at `--jobs 16`, warm,
with identical results throughout.

| Code | Variant | Wall |
|---|---|---|
| Old main (4 xsim slots) | as is | 242 s |
| Old main | xsim pairs submitted first, highest level first | **261 s (worse)** |
| Main + #17 + #20 | as is | 178 s |
| Main + #17 + #20 | xsim pairs in their own pool | 178 s (no change) |

- **Why xsim-first was worse:** up to 16 workers sat waiting for 4 xsim
  slots while the container runners had none.
- **Why the separate pool did not help:** with #17 and #20 in, the tail was
  the Verilator L2 pairs, each running 16 configurations one after another,
  about 130 s. Reordering whole pairs cannot shorten that. This PR can,
  because each configuration is now its own unit of work.

The branch `infra/perf-sched` stays local and unpushed.

## Next steps

- Profile the pytest suite: chunk C and `test_runner_xsim` are about 1 s per
  test (wait-time report 006).
- Split the sweep test (CI's critical path).
