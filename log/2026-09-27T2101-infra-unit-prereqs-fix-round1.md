# infra/unit-prereqs — PR #14 fix round 1 (ruling S57)

This round addresses the PR #14 correctness review, following the coordinator's ruling S57. The reviewer's two scratch counterexamples are now regression tests.

## What changed

1. **Don't-care bits (S57.1).** `unitkit._doc_diffs` counts a documented bit only where golden and mutant are both defined (0/1) and differ. A `-`, x or z on either side never counts: that is the least-observable semantics of `xtr.compare` against a 2-state runner. Tests cover both directions for `-`, x and z, and include the reviewer's counterexample (`compare` passes where the old guard counted a catch).
2. **Pure crediting per declaring test (S57.2).** The pure-crediting guard used to pool pure configurations across tests. Now every bin a vector test declares needs a pure configuration within a test that declares it. The regression test covers two cases: a pure configuration in a non-declaring test fails the guard, and one in the declaring test passes it.
3. **AGENTS.md §10.1 (S57.3).**
   - The budget is now `scope cap + jobs × container cap ≤ 96G`, so the usable `--jobs` is `(96 − scope)/4`: 16 in a 32G scope.
   - After PR C, 24 is only xut's hard limit.
   - Direct Vivado/xsim runs are on the heavy-command list.
   - The 4 Vivado slots count inside the lock holder's budget.
   - The lock is described as per-user under `$XDG_RUNTIME_DIR`, shared by every session of this user on the host. The "never deleted" claim is dropped.
4. **Nits (S57.4).**
   - **AGENTS.md §7:**
     - `status init` may create stubs. A unit removes the ones it does not own with `git clean -f -- <path>` and reports them.
     - An infra PR that changes `coverage_bins` may carry the refreshed stubs as an exception stated in its body, until the orchestrator refreshes them on main after the merge.
     - The stub-invariant test comment points to this rule.
   - **`attr_bins` docstring:** an explicit default value reaches `attr:<A>` too, and value spread is `attr_sampling`'s job.
   - **Seed:** `xut status record` now warns when it credits a generated vector test's python run made with a non-default `--seed`. There are TODOs in `status._warn_non_default_seed` and `unitkit.vector_reach` to refuse such a run once `xut freeze-seed` exists.

## Test results

- Focused runs (single process): `test_unitkit.py` and `test_status_record.py` give 78 passed.
- Full suite: 1851 passed, 5 skipped in 181 s. It ran under the heavy lock in a 16G scope with `-n 4 --dist loadfile -m "not slow"`.
- `ruff check .` is clean. `ruff format --check tools` is clean.
- `xut lint --branch` reports 0 errors and 0 warnings.
- `ruff format --check .` flags two docs plan markdown files that were already unformatted on main. They are not touched here.

## Next steps

- Re-review of PR #14.
- The flops migration to `xut.unitkit` is still an open TODO (see the unitkit log entry).
