# infra/ci-gate: CI gates on crosscheck

## What changed
- CI's `sim` job ran `xut run 'unit:flops' …` as a gating step. That command exits 1 on
  any `fail`, including the two GSR-vs-control doc-gap tests, whose disagreement is a listed
  `expected_divergence` of an open finding (spec §8). PR #16 (flops) went red on them.
- `xut run` now reports without gating, and `xut crosscheck` (the existing next step) is the
  gate:
  - exit 0 only when every disagreement is a listed known-divergence;
  - exit 3 on an unlisted finding;
  - exit 4 on errors, unexplained fails or missing comparisons.

  Nothing that crosscheck checks is lost.

## Tests
- Checked on the flops data: `xut crosscheck 'unit:flops'` exits 0 on both model sources
  (Task 27 and the PR #16 reviews).

## Next steps
- Merge this, then re-run PR #16's CI.
