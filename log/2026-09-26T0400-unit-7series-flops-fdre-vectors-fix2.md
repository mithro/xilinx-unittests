# Task 21 fix round 2 (re-review: 1 Important, 1 Minor)

Commits `649021c`, `f0622fe` on top of `0bdf8e0`. Re-review approved all of
fix round 1 (I1, M2-M6) and raised N1 (Important) and N2 (Minor), both in
the shared reach-guard/recipe code.

- **N1**: `test_exercises_are_reach_confirmed` compared declared
  `exercises` against raw `reach.bins()`, missing the `polarity_bins`
  renaming `xut.runners.python.PythonRunner.run_config` applies. Async/gate
  bins stayed `rise`/`fall` there but `assert`/`release` in the runner and
  in `exercises`, so the test would fail on every correct async-kind
  declaration and could not catch I1 for the right reason. Fixed by
  reusing the runner's own (private) `_polarity_context` plus
  `xut.golden.polarity_bins`, via a minimal `TestCase`/`RunContext`
  wrapper — no `tools/` file edited. Logged an infra TODO (AGENTS §13):
  `_polarity_context` could be a small public `(family, prim, root)`
  helper instead.
  - Proved in a scratch copy (`git archive` + `PYTHONPATH` override,
    confirmed imports resolved to the copy) with throwaway, uncommitted
    FDSE/FDCE/FDPE `SdrFlop` subclasses: current declarations pass for
    FDRE/FDSE/FDCE, and FDPE fails only on the already-known N2 bug; with
    the I1 fix reverted, fails with exactly
    `FDCE.L0.smoke: ['port:CLR:assert']` and
    `FDPE.L0.smoke: ['port:PRE:assert']`.
- **N2**: `l1_recovery` set `D = 1 - k.forced` once, which for FDPE
  (`forced=1`) equals the builder's own tracked 0 default — a no-op
  `VecBuilder.set` never emits — so the declared bare `port:D` bin was
  never actually reached. Primed `D` to `k.forced` first (complementary to
  `1 - k.forced`, so one of the two is always a real transition). Checked
  the same pattern across every D-driving recipe for all four kinds via
  the corrected N1 test against the scratch models: nothing else affected.

## Test results

- `uv run pytest -v tests/7series/register/_shared/flops`: 32 passed, 1
  skipped.
- Regenerating FDRE's files: no diff (neither fix touches an FDRE
  declaration).
- `uv run xut run '7series.FDRE.*' --runner python`: 11 vector `pass`, 3
  sv/cocotb `skip`; zero missing bins.
- `uv run xut lint` / `--branch`: 0 errors, 42 warnings both times (same
  pre-existing FDSE/FDCE/FDPE set).
- `uv run ruff format`/`check`: clean outside the documented `ANN*` gap.
- `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: 1308 passed, 1
  skipped (unchanged count).

## Next steps

- Same as before: watch `test_exercises_are_reach_confirmed`'s runtime as
  FDSE/FDCE/FDPE join.
- The `_polarity_context` infra TODO stays open for whoever picks up an
  `infra/*` topic next.
