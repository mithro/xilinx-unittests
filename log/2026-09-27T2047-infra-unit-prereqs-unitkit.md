# infra/unit-prereqs — unit playbook Task P1

Branch `infra/unit-prereqs`, cut from `main` at f1fa432. It carries the
infrastructure every work unit after flops needs
(`docs/superpowers/plans/2026-09-28-unit-playbook.md`, Task P1).

## What changed

- **Coverage bins named like `coverage_bins`.** `xut.golden.attr_bins` and
  `xut.golden.coverage_reach` add the single `attr:<A>` bin for every
  explicitly set attribute whose catalog `allowed` list is not enumerated. Before
  this, a vector test could never be credited with `attr:<A>` (every LUT INIT,
  BRAM `INIT_xx` and DSP/MMCM integer attribute). The python runner now records
  its bins through one function, `xut.runners.python.replay_config`, which
  `xut.unitkit.vector_reach` also uses. `_polarity_context` has no caller in
  the runner any more. It stays only because the flops reach guard imports it.
- **`xut.unitkit`** (ruling S53) is the shared code for units:
  - the standard runner reasons, `runners`, `claims`, `class_bins` and `entry`;
  - the no-alias `dump_test_yaml`, `cell`, `run_block` and `render_readme`
    (the "How to run" block runs under the heavy lock);
  - `vector_reach`, `doc_mismatches`, `mutant_fails`, `Mutant` and `cases`;
  - the `Unit` / `UnitGuards` guard set, including the S55/S55a mutant guard.
- **`tools/tests/test_status_schema.py`** removes the TEMPORARY `pre_s19` and
  `REGENERATED_ON_BRANCH` allowances. Every never-recorded stub now has to hold
  exactly `coverage_bins(entry)`.
- **`pyproject.toml`** adds `tests/**/test_*.py` to the ruff `ANN` exemption.
- **AGENTS.md**:
  - §7: a unit branch may refresh its own never-recorded stubs (D16).
  - §10.1: one host-wide `$XDG_RUNTIME_DIR/xut-heavy.lock` around every heavy
    command (S53).

## Test results

- Focused run, single process: `test_golden_reach.py`, `test_unitkit.py` and
  `test_runner_base.py` give 66 passed. Before the implementation the first two
  failed at collection with `ImportError`, as the plan expects.
- Full suite, under the heavy lock in a 16G scope with
  `-n 4 --dist loadfile -m "not slow"`: **1840 passed, 5 skipped** in 219 s,
  container tests included.
- `ruff format --check tools` and `ruff check .` are clean.
- `xut lint --branch` reports 0 errors and 0 warnings.

## Next steps / TODO

- **TODO (follow-up PR, not this one):** migrate the flops unit to
  `xut.unitkit`: its `flop_tests.py` helpers, and the reach guard's private
  `_polarity_context` import. Then delete `_polarity_context` from
  `tools/xut/runners/python.py`.
- Next is the luts unit (Part B), stacked on this branch while this PR is open.
