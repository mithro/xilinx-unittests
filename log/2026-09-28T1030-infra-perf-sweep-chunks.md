# infra/perf-sweep: the lint sweep in chunks

## What changed

- The sweep test in `tools/tests/test_vz_rewrite.py` is now two tests.
  - **`test_sweep_transforms_every_model_it_can[source]`** holds the
    manifest assertions, once per source: the transformed count, the refused
    set and their reasons, and the FD* triggers and rewrites.
  - **`test_sweep_every_transformed_model_lints[source-chunk]`** is split
    into 4 chunks per source, each taking every 4th transformed model. The
    lint assertions are unchanged; each chunk writes `summary-<k>.txt`.
- `test_sweep_chunks_cover_every_transformed_model_once` checks that the
  chunks partition the models.
- `ci_shards` (stacked on #23) splits the old `sweep` shard into
  `sweep0` .. `sweep3`, one chunk of both sources per runner. The manifest
  test goes with `sweep0`, and `rest` deselects both tests.
- `test_ci_shards` checks the partition, each chunk shard's node ids, and
  that the shard constants match the test module.

## Results

- **Local**, 2025.2 only, because the submodule is not checked out here:
  6 passed, 5 skipped (the gh-2020.1 tests), 328 s serial.
  - The manifest test took 189 s: the first `verilatorize` in a fresh
    worktree, most of it the prescan that #26 speeds up.
  - The chunks took 46, 43, 27 and 23 s.
- `test_ci_shards`, `test_ci_select` and the partition unit test: 32 passed.
- CI timing: pending, in the PR.
