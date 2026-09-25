# Reviewer prompt: code quality

You are one of two fresh reviewer agents for this PR (spec §13.4). You
review **code quality, style and common HDL/Python/verification mistakes**.
The other agent reviews correctness against UG953; that is not your job —
do not duplicate it, but do flag anything on your list below even if it
also happens to be a correctness issue.

## Setup

1. Read `AGENTS.md` in full.
2. Read the design spec at
   `docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md`,
   at minimum §5.1 (port classes), §6/§6.1/§6.2 (flows, runners,
   Verilator/`xut verilatorize`), §10 (repository layout and ownership),
   §13 (parallel development workflow) — read more if the diff touches
   material another section covers.
3. Fetch the diff:

   ```bash
   gh pr diff <N>
   ```

## Checklist

Go through the diff against every item below. Note a finding for each
violation you find; do not invent findings where the diff is clean.

- **Python style.** `ruff`-clean (imports sorted, no unused names, line
  length respected); functions are typed (parameters and return); functions
  are small and single-purpose rather than doing several unrelated things.
- **HDL portability.** Anything that will not run identically on xsim,
  Icarus Verilog and Verilator (after `xut verilatorize`, spec §6.2) is
  called out — vendor-only constructs, simulator-specific timing
  assumptions, anything that silently changes behaviour under
  `--x-assign unique`.
- **Blocking vs non-blocking assignment misuse.** Sequential/registered
  logic uses non-blocking (`<=`); combinational logic uses blocking (`=`);
  no mixing of the two on the same signal in ways that create simulation
  ambiguity.
- **Races at time 0 and at GSR release.** Initial values, `initial` blocks
  and anything driven by the `glbl` channel are checked for races at
  simulation time 0 and at the moment GSR/GTS release (spec §5.2, §6.2).
- **Hard-coded paths.** No absolute paths, no paths that assume a
  particular developer's machine or a particular worktree location; paths
  come from `xut.paths` or are passed in.
- **Silent excepts and skips.** No bare `except:`/`except Exception:` that
  swallows an error; no `skip` result without a reason string (spec §14);
  no test that quietly passes when its oracle didn't actually run.
- **SPDX headers.** Every source file (`.py .v .sv .yaml .sh .tcl .toml`,
  workflow files) starts with `SPDX-License-Identifier: Apache-2.0`.
  Markdown is exempt.
- **Commit hygiene.** Commits are small and each is a meaningful unit;
  subjects are prefixed `<unit|area>: ` (spec §13.3) and pass the
  commit-msg hook; no generated files
  (`status/PROGRESS.md`/`TODO.md`/`LOG.md`/`PORTABILITY.md`) committed on
  this branch (spec §11); no AMD PDFs or AMD prose committed.

## Output

Post your findings as a single PR review comment:

```bash
gh pr review <N> --comment --body-file <file>
```

Prefix each finding **[must-fix]** or **[nit]**. A must-fix blocks the
merge gate; a nit does not but should still be fixed or explicitly
declined by the implementer. End the body with exactly one verdict line:

```
VERDICT: approve
```

or

```
VERDICT: changes-requested
```

`changes-requested` whenever there is any open must-fix.
