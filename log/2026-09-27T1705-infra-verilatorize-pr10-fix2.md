# infra/verilatorize — PR #10 fix round 2

Correctness re-review of fix round 1 (rounds 1's must-fixes all confirmed fixed);
orchestrator ruling S50a (fail closed).

## What changed

- **Must-fix: a Verilator pass needs its iverilog-vz companion.**
  `crosscheck.companion_gap` confirms a Verilator pass only by an iverilog-vz
  result for the same test, flow and model source that is a pass (no trace
  difference against iverilog when both traces exist) or a fail with both
  traces and no difference. Otherwise: `missing`, `error` (error, skip, a
  z-refused cocotb run, an uncomparable fail) or `transform-bug`.
  `xut status record` records such a pass as `error` with the warning
  "verilator pass not confirmed by iverilog-vz: <why>"; `xut crosscheck`
  lists it as an issue (verdict incomplete).
- **Nit: `config`** only when every error line is a model legality message and
  nothing crashed (rc or a logged exit >= 128); otherwise the first non-config
  error decides. The reviewer's cls.py is now `other: %Error: ... $stop`.
- **Nit: `deps_sha256`** covers every model of the hierarchy, unchanged
  intermediates included, so `dep_configs` and kept verdicts are discarded when
  an intermediate changes.

## Test results

- Targeted: status record (missing / error / z-refused / trace difference /
  confirming pass and fail), crosscheck companion_gap and the incomplete issue,
  portability classification, the hierarchy re-key test: all pass.
- Re-classifying the S50 full-run logs: counts unchanged.
- Full suite: see the fix-round-2 report line.

## Next steps

- Re-run `xut portability` on main after merge.
- S51.5 legal smoke configurations from units' `smoke_attrs` (follow-up).
