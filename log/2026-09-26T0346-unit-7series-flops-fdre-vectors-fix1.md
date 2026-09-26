# Task 21 fix round 1 (review: 1 Important, 6 Minor)

Commits `b2b531f`, `0401dc3`, `13d6f10` on top of `11fac40`.

FDRE's own committed deliverables were confirmed correct by the review
(every `exercises` bin reached, mutants killed); the findings were all in
the shared `tests_for()`/model code.

- **I1 + M2**: `L0.smoke` never calls `.ctrl()`, so it must not credit the
  control's class bins — `Flop.__init__`'s initial (inactive) control value
  is not an intending test, and for an async control (FDCE/FDPE) the
  `:assert` bin it would have declared is not even reachable that way.
  Dropped `_reach_all(k, c)` from smoke; both bins stay accounted for FDRE
  via `reset_over_ce`, `is_r_inverted` and the L2 tests. Corrects this
  progress log's own prior claim (2026-09-26T0326 entry) that FDSE/FDCE/FDPE
  "need no new code in `tests_for()`" — they do: the async-only
  `{w}_async`/`{w}_recovery` tests now carry `_reach_all(k, c)` too, since
  they *do* call `.ctrl()` for real, in both directions.
- **M1**: added `test_exercises_are_reach_confirmed` (replays every vector
  test's real generator through `xut.golden.replay`, per-test seeded the
  way `xut run` would, for every primitive with a registered model) —
  exactly the check that would have caught I1 mechanically. ~6.6s for FDRE
  today; worth revisiting as `@pytest.mark.slow` once FDSE/FDCE/FDPE join.
- **M3**: `glbl()`/`outputs()` now also refuse to run before `power_on()`.
- **M4**: `render_test_yaml` uses a no-alias `yaml.SafeDumper` subclass; the
  regenerated `test.yaml` has no `&id001`-style anchors/aliases.
- **M5**: added `test_expected_files_are_present` (`EXPECTED_PRESENT =
  ("FDRE",)`), so a missing/renamed `test.yaml` fails instead of silently
  emptying the drift/generator/schema parametrizes.
- **M6**: `l1_capture` samples once before its first capture, so INIT is
  actually observed (matching its own "for both INIT values" claim).

## Test results

- `uv run pytest -v tests/7series/register/_shared/flops`: 32 passed, 1
  skipped.
- `uv run xut run '7series.FDRE.*' --runner python`: 11 vector `pass`, 3 sv/
  cocotb `skip` as declared; zero missing bins on the reach check.
- `uv run xut lint` / `--branch`: 0 errors, 42 warnings both times (same
  pre-existing FDSE/FDCE/FDPE `related`-id set); no new branch-ownership or
  generated-file issues.
- `uv run ruff format`/`check`: clean outside the documented `ANN*` gap on
  `tests/` files.
- `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: 1308 passed, 1
  skipped (+4 over the prior round, matching the 4 new tests).
- Reviewer's `mutate2.py` (N1-N9, M1-M9): all 18 mutants still killed.

## Next steps

- Same as before: Tasks 25/26 reuse `flop_recipes.py`/`flop_tests.py`
  unchanged; the async-only tests' new `_reach_all(k, c)` and `test_
  exercises_are_reach_confirmed`'s per-model parametrize both apply to
  FDSE/FDCE/FDPE automatically once those land.
- Watch `test_exercises_are_reach_confirmed`'s runtime as more primitives
  get models; mark it `slow` if it stops being cheap.
