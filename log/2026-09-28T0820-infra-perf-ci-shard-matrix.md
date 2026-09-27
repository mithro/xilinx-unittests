# infra/perf-ci-shard: container tests in three parallel CI shards

## What changed

- `tools/xut/ci_shards.py` (stdlib only) defines three shards of
  `-m container`:
  - `sweep`: the verilatorize lint sweep test (358 s on CI).
  - `verilator`: `test_runner_verilator.py`, spread test by test (`--dist
    load`); in sequence it took 323 s on one worker.
  - `rest`: everything else, with `--dist loadfile` as before, plus the flops
    runs.
- `ci.yml`:
  - a `sim-shard` matrix job, with `fail-fast: false`;
  - a `sim` job (`if: always()`) that is green only when every shard passed,
    so the check name is unchanged.
- `tools/tests/test_ci_shards.py`:
  - it collects every shard and the whole `-m container` set, and asserts
    each test is in exactly one shard;
  - it also checks the CLI and the workflow structure.
- `tools/tests/test_container.py::test_ci_builds_the_current_sim_image` now
  reads the `sim-shard` job.

## Measured on GitHub

- Before, run 36353909339: 449 s wall. The sim job took 440 s, and its
  container pytest 424 s.
- After, run 36354963868: 270 s wall.

  | Job | Time | pytest step |
  |---|---|---|
  | sweep | 251 s | 215 s |
  | verilator | 108 s | 62 s |
  | rest | 126 s | 91 s |
  | tooling | 128 s | – |

  The image build took 15–18 s per shard, so the gha cache hits.
- Same tests, same outcomes: 149 container tests (139 passed, 10 skipped),
  node for node identical to the before run.

## Next steps

- The critical path is now the sweep test, 215 s on its own runner.
- After #19 and #21 merge, the orchestrator rebases; the sim steps they touch
  move into `sim-shard`.
