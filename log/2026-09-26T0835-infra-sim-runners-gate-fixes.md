# 2026-09-26: PR B gate-review fix wave

## What changed
- `xut.runners.sim` holds the runner-neutral simulator code (M2): the checks, the cocotb command, and one post-run ladder (`classify_run`).
- Zero evidence is never a pass (S15):
  - validate errors on a non-reject stimulus without samples;
  - sv needs at least one executed `XUT_CHECK` and at least one checkpoint (`XUT_CHECKS <n>`).
- Reject evidence (S13b) must be an error/fatal line that names a declared illegal attribute (`illegal=`). `XUT_ERROR` in the run gives error.
- A don't-care `-` bit needs `doc:<page>` provenance (S14).
- Model error lines fail vector and cocotb runs. Every cocotb fail/error reason ends with `[seed N]`.
- validate refuses events within `async_sep_ps` of glbl's GSR release. xsim refuses `XIL_*` defines.
- sv testbenches receive `XUT_SEED` (the recorded seed).
- `xut run` changes:
  - an unmatched selector exits non-zero;
  - skip reasons are printed;
  - the summary file is `summary-<model-source>.json`.
- The watchdog starts no thread after the deadline. `NoPythonRun` and `ModelContractError` replace bare exceptions.
- Tests: pytest-xdist, a `slow` marker, and shared fixtures in `conftest.py`.

## Tests
- Full suite (container + vivado), `-n auto --dist loadfile`: 1114 passed in 10m33s.
- ruff format/check are clean. `xut lint --branch --base infra/sim-formats`: 0 issues.

## Next
- Deferred per the brief:
  - real-UNISIM agreement beyond FDRE (PR E);
  - `xut freeze-seed`;
  - the Verilator x/z skip hook (Task 15).
