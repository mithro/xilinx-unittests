# flops: Task 20 fix round 1 (ruling S32)

Branch `unit/7series/flops`, resuming after review of 12ce3dd/79be854
(`task-20-review.md`): 3 Important, 8 Minor, no Critical.

## What changed

- `models/xut_models/7series/_common/flops.py`: `_ctrl_active()` is now a pure
  predicate (no hit); `inv_ctrl` (C6) is hit only inside `_force()`, i.e. only where
  the active-Low control actually forces Q -- never from the bare probe inside
  `_under_gsr()`'s GSR path. `inv_c` (C5) is hit only beside a real capture or a
  synchronous control's force, not on an edge GSR or CE Low would ignore anyway.
  `_force()` and the capture branch now pass `ATTR_PAGE` when an inversion attribute
  shaped the output (Important 3), so IS_D_INVERTED/IS_C_INVERTED captures and
  inversion-driven control forces cite p376 (FDRE), not p375. The GSR edge retag
  (`_GSR_EDGE`) no longer touches Q when CE Low or an inactive control already make
  the edge a no-op (Minor 7). `set_input`/`clock_edge` reject a port outside
  `inputs()`/`CLOCKS` with `ModelContractError` (Minor 5). A clock edge no longer
  redundantly re-forces (or re-hits C3/C5/C6 for) an async control that a prior
  `set_input`/`glbl` already forced -- that edge decides nothing new, verified by
  direct probing of scratch FDCE/FDPE subclasses (Task 26 isn't implemented yet, so
  this has no test in this branch, but is checked by inspection and by probe against
  the reviewer's own async scratch classes).
- `tests/7series/register/_shared/flops/test_flop_models.py`: added
  `test_power_on_hits_only_gsr_init` (kills the "all claims at power-on" mutant),
  `test_c3_not_hit_while_control_stays_inactive`, `test_c5_not_hit_when_ce_low`,
  `test_free_running_clock_under_gsr_hits_nothing` (the reviewer's exact false-C5-hit
  scenario), `test_unknown_port_is_rejected`; added negative (`not in claims_hit`)
  assertions for C1-C3 and C7 to existing tests; added a literal, model-independent
  `_PAGES` dict and pinned exact `doc:<page>` provenance in the C1/C5/C6/C7 tests
  (kills a `PAGE = 999` mutant); reworked `test_c6_control_active_low` to load a real
  pre-force value first (Minor 1); added a same-tick sample right after GSR release in
  `test_gsr_midrun_and_inferred_edge` (Minor 3, kills a resample-to-INIT mutant); added
  the C3-hit assertion to the S30 disagreeing case (Minor 4); `forced()` and the C4
  default now read `KINDS[prim].forced`/`.init_default` directly (Minor 8, no
  duplicated literals).

## Verification

- Hand-simulated every new/changed assertion against the new model logic before
  running pytest (documented port-by-port in the session, not repeated here); all
  passed on the first run.
- Re-ran the reviewer's `mutate.py` (scratchpad `t20review/`) against the fixed
  model. Its harness's `except Exception` doesn't catch `pytest.raises`' `Failed`
  (which is a bare `BaseException` in this pytest version), so I ran a copy
  (`t20fix/mutate_rerun.py`) with that widened to `except BaseException` (still
  re-raising `KeyboardInterrupt`/`SystemExit`) -- a harness fix only, no change to
  the mutants themselves. Result: all 9 mutants killed, including the three that
  previously survived (M4 all-claims-at-power-on, M6 `PAGE=999`, M7
  resets-to-INIT-on-release). `test_unknown_port_is_rejected` also happens to "kill"
  M1 via the widened-exception path, for a reason unrelated to M1's actual bug (M1's
  hand-written `clock_edge` override returns before ever calling `super()` for its
  CE-Low branch, so it never reaches the new port check); the real, intended kill of
  M1 is still `test_c3_control_overrides{'ce': 0}`, unaffected.
- Re-ran the reviewer's `probe.py`: P1/P2 (false C5 hits) now show only C4/C2+C4 as
  appropriate; P3 (IS_D_INVERTED capture) now cites `doc:376`; P4 (GSR edge retag
  after release) is unchanged (still correctly preserved); P5 (unknown port) now
  raises `ModelContractError` (the script itself then exits non-zero, since it isn't
  wrapped in a `try`/`except` -- expected, it was written to demonstrate the old bug).
- Extra direct probe (not committed) of the reviewer's scratch FDCE/FDPE subclasses
  confirms C6 is no longer hit in the GSR "agree" case (Minor 6), is hit (with
  `doc:370`/`doc:373`, i.e. `ATTR_PAGE`) exactly where the inverted control actually
  forces on release, and that a clock edge arriving while an async control is already
  asserted adds no new claims and leaves Q's provenance untouched.
- `tests/7series/register/_shared/flops`: 17 passed, 1 skipped (up from 12/1; the one
  skip is still the async-only S30 test, empty for `PRIMS = ["FDRE"]`).
- `uv run ruff format`: both changed files already formatted.
- `uv run ruff check` on the four flops files: clean on the two model files and
  `flop_recipes.py`; `test_flop_models.py` has 44 ANN findings (up from 34,
  proportional to the new test functions) -- same infra-owned gap noted in the Task
  20 report (`pyproject.toml`'s ANN per-file-ignore covers `tools/tests/**` only, not
  `tests/**`); not re-flagged as a new issue.
- `uv run xut lint`: 0 issues. `uv run xut lint --branch`: 0 issues.
- Fast suite, `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: **1293
  passed, 1 skipped** in 116.92s (up from 1288/1; +5 net new test functions across
  their prim/init/ce parametrizations).

## Next steps

- Same as before: Task 21 (stimulus recipes), Tasks 25/26 (FDSE, then FDCE/FDPE --
  where the async-control claim crediting and the skip-redundant-force behaviour
  checked here by probe finally gets real test coverage), and the still-open infra
  TODO to widen ruff's ANN per-file-ignore to `tests/**`.
