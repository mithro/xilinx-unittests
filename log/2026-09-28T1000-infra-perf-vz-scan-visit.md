# infra/perf-vz-scan: has_procedural_assign walks the syntax tree in C++

## What changed

- `xut.verilatorize.analyze.has_procedural_assign` is the prescan that every
  verilatorize and portability run calls on every model file, and that
  `test_vz_analyze` calls over all of UNISIM.
  - It now uses pyslang's C++ `visit` with a `lookup_table`. It stops at the
    first `ProceduralAssign`/`ProceduralDeassign` statement.
  - It skips whole the subtrees that cannot hold a statement: every
    expression, the plain declarations, and continuous assigns.
  - The answer is unchanged.
- New tests:
  - one procedural assign nested in a task, a function, a generate block, a
    case, a fork and a named block is found, and continuous assigns alone
    are not;
  - every fixture gives the same answer as a full Python walk;
  - a `slow` test does the same over the whole submodule.

## Measurements (capped scopes)

- **Old full Python walk against the new visit**, over 1438 files (both
  model sources and every fixture): 122.3 s → 11.1 s, with the same answer
  on every file (92 contain one). Parsing takes about 3 s of either figure.
  - Script: `scratchpad/perf/prof_scan4.py`
  - Log: `prof_scan4.log`
- **`test_vz_analyze.py::test_every_forced_model[unisim-2025.2]`:**
  173.1 s → 78.9 s. The rest of that time is `analyze()` itself: DSP48E1
  18 s, PLLE2_ADV 12 s, 70 s in total.
- **`test_vz_analyze.py`:** 70 passed, 7 skipped. The skips are the
  gh-2020.1 tests; the submodule is not checked out in this worktree, and CI
  runs them.

## Next steps

- `analyze()` spends most of its 70 s in the same Python syntax walks. It is
  a candidate for the same technique, with the same equivalence proof.
