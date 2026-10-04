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

## Fix round 1: rebase onto main (#19, #21), then the correctness review

- **Rebase.** Rebased onto main at d97eca2.
  - `sim-shard` takes #21's `needs: changes` and `if: ${{ !cancelled() }}`.
  - Its first step fails when `changes` did not succeed.
  - Every other step is gated on `needs.changes.outputs.sim != 'false'`.
  - #19's flops steps also carry `&& matrix.shard == 'rest'`.
  - The `sim` gate job uses `!cancelled()`, like #21.
  - #21's structural test now checks `sim-shard` and the gate.
- **[must-fix] Flops steps pinned to one shard.** `ci_shards.FLOPS_SHARD =
  "rest"`. The new `test_flops_steps_run_in_exactly_one_shard` asserts two
  things:
  - both flops steps name exactly that one shard, and it exists in `SHARDS`;
  - no other step is shard-conditional.

  Mutation check: renaming the shard to `rset` in one step fails the test.
- **[nit] Shard arguments.** The workflow writes `ci_shards.py`'s output to
  `$RUNNER_TEMP/pytest-args` as a plain command, so bash -e sees a failure,
  then runs `mapfile` from that file. The shard name comes in through
  `env: SHARD`. The test pins both.
- **[nit] How the "149 node ids, same outcomes" claim was checked.**
  1. Fetch the job logs:

     ```bash
     gh run view 36353909339 -R mithro/xilinx-unittests --log --job <sim job id> > sim-log.txt
     gh run view 36354963868 -R mithro/xilinx-unittests --log --job <each sim-shard job id> > shardlog-<id>.txt
     ```

  2. In each log, keep every `-v` result line that matches
     `(PASSED|SKIPPED|FAILED|ERROR|XFAIL|XPASS) (tools/tests/\S+::\S+)`, as a
     node id → outcome map.
  3. Compare the before map with the union of the three shard maps, both as
     sets of node ids and as outcomes per node id.

  Result: 149 = 149 (139 passed, 10 skipped), with no id on only one side and
  no differing outcome.
- **Tests.** `test_ci_shards`, `test_ci_select` and the non-container
  `test_container`: 113 passed, in a capped scope. ruff is clean.
