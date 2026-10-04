# infra/perf-xdist: per-file xdist groups, with two modules spread test by test

## What changed

- `tools/tests/conftest.py` gives every test an `xdist_group` named after its
  file, so `--dist loadgroup` keeps each module on one worker as `loadfile`
  does. The exception is `PER_TEST`: `test_runner_xsim.py` and
  `test_runner_verilator.py` get no group, so their tests are spread one by
  one.
  - The hook is `tryfirst`, so it runs before xdist's own loadgroup hook
    reads the marks.
  - With `--dist loadfile` the groups are ignored, and the behaviour is
    exactly as before.
- The CI tooling job uses `--dist loadgroup`. The container tests in the
  `sim` job are left for after #23, which rewrites that job.

## Why the two modules are safe to spread

Every test in them works under `tmp_path` (the `work` and `ctx` fixtures).
Neither module has module-scoped fixtures or module-level mutable state.
The only process-level caches are `xsim_version` and `sim_tool_versions`,
which are lock-guarded and per process.

## Results

Each run used `-n 8 -p no:randomly --junitxml`, under the heavy lock in a
32G scope.

| Files | `--dist loadfile` | `--dist loadgroup` | Outcomes |
|---|---|---|---|
| `test_runner_xsim.py` + `test_runner_verilator.py` | 266.1 s | **87.0 s** | 139 passed each; identical per node id |
| The other 32 non-heavy files (the chunk D set) | 60.6 s | 59.6 s | 1213 passed, 1 skipped each; identical per node id |

The node ids are compared after stripping xdist's `@<group>` suffix.

## How to verify

```bash
uv run xut heavy --mem 16G --containers 8 --name xdist-a -- uv run pytest -q -n 8 \
  --dist loadfile --junitxml=a.xml tools/tests/test_runner_xsim.py tools/tests/test_runner_verilator.py
uv run xut heavy --mem 16G --containers 8 --name xdist-b -- uv run pytest -q -n 8 \
  --dist loadgroup --junitxml=b.xml tools/tests/test_runner_xsim.py tools/tests/test_runner_verilator.py
```

Then compare the `(classname::name with @suffix stripped) -> outcome` maps
of `a.xml` and `b.xml`: they must be equal.
