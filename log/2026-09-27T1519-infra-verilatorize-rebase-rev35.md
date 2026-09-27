# infra/verilatorize: rebased onto main, spec rev 3.5 (orchestrator)

## What changed
- Rebased the branch's own commits onto `origin/main` (after PR B, the xvec-strings
  PR #8 and the memory-safety PR #9). Commits already on main were skipped.
- Four conflicts, each additive, resolved by keeping both sides:
  - the spec header (rev 3.3 notes and rev 3.4 notes);
  - `cli.py` (crosscheck, verilatorize and portability commands);
  - `status.py` (`record` and `render_portability`);
  - `test_lint.py`.

  The `lint()` docstring in `lint.py` was merged by hand.
- The post-rebase fixes (`_shared_dirs` moved into `TestCase.shared_dirs`, and the
  lint fixture's catalog) are in their own commits and log entry.
- Spec rev 3.5 records rulings S26, S28, S29, S31, S35, S38, S43, S45, S46 and S48 in §6.2.

## Tests
- Full suite after the fixes: 1778 passed (pytest -n 8 inside a 24G capped scope).
- `xut lint --branch`: 0 errors, 1 expected warning (PORTABILITY.md is generated on main).

## Next steps
- Portability re-run with capped containers at `--jobs 24`.
- PR C: two reviewers, CI, merge. Then regenerate status on main.
