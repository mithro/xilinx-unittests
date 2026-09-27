# infra/verilatorize — PR #10 fix round 3

Re-review of fix round 2; ruling S50a (round 3).

## What changed

- `crosscheck.verilator_unconfirmed` fails closed with `stale` when the
  iverilog-vz result, or the iverilog baseline it is compared against, differs
  from the Verilator result in `tree_hash` or `head`, or when either result is
  dirty or unstamped. `xut status record` then records the Verilator pass as
  `error` ("verilator pass not confirmed by iverilog-vz: stale").
- `test_a_verilator_pass_needs_its_iverilog_vz_companion` gains the `stale`,
  `stale-head`, `dirty`, `unstamped` and `stale-baseline` cases (the
  reviewer's `test_cx_stale.py` scenario is `stale`/`dirty`).

## Test results

- status record + crosscheck: 150 passed. Full suite: see the round-3 report.

## Next steps

- Re-run `xut portability` on main after merge; S51.5 smoke_attrs follow-up.
