# infra/perf-ci-paths: docs/logs-only PRs skip the sim steps

## What changed

- `tools/xut/ci_select.py` is stdlib only. It decides whether the CI `sim`
  steps are needed, and it is fail-safe.
  - They are skipped only for a pull request whose changed files could be
    listed, whose list is non-empty, and whose every file is `log/*.md`,
    `docs/superpowers/*`, the top-level `README.md` or `AGENTS.md`.
  - Anything else runs everything: a push to main, a git error, an empty list,
    any other path including `docs/work-units.yaml`, `docs/templates`,
    `findings` and unknown paths.
  - It has a dry-run mode: `--files ...`.
- `.github/workflows/ci.yml`:
  - a new `changes` job runs the selector;
  - the `sim` job `needs: changes` and always runs, so its check is reported
    on every PR;
  - every sim step is gated on `needs.changes.outputs.sim == 'true'`;
  - a no-op step says when the sim steps are skipped;
  - the `tooling` job is unchanged and always runs in full.
- `tools/tests/test_ci_select.py` (26 tests):
  - docs-only paths skip, and 18 other kinds of path run everything;
  - doubt runs everything;
  - the dry run shows docs-only against tools changes;
  - a git failure runs everything;
  - the script is stdlib only;
  - a structural check of `ci.yml` (every sim step gated, the job always
    runs, the tooling job untouched).

## Measured (CI run 36353264166)

- tooling: 100 s.
- sim: 462 s, of which the container pytest took 424 s. The image build took
  19 s, so the gha layer cache hits.
- A docs-only PR's CI wall time drops from about 462 s, bound by sim, to about
  100 s, bound by tooling.

## Branch protection

`main` has no branch protection and no rulesets (`gh api .../branches/main/protection`:
404; rulesets: `[]`). The `sim` job still always runs and succeeds, so
a future required check named `sim` is satisfied.

## Next steps

- Shard the container pytest (424 s) across parallel jobs.
- xsim-first scheduling (S60 item 2).

## Rebase onto main after #19, and the correctness-review nits

- Rebased onto main at 6be838a, which includes #19. #19's new sim steps are
  now gated like the others: the `xut run` exit-code check and
  `crosscheck --strict --level L0 --level L1 --style vector`. The stale
  "selects nothing" comment went with #19's rewrite.
- **Gate.** Steps run unless `sim` is explicitly `false`: the condition is
  `!= 'false'`, so an empty output runs everything.
- **The sim job.** It has `if: !cancelled()`, so it still reports when
  `changes` failed. Its first step fails the job when `changes` did not
  succeed, so the sim check is never green without its steps.
- `test_ci_select.py` pins all three. 26 passed.
