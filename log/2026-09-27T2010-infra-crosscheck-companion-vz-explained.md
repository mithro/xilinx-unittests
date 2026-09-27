# infra/crosscheck-companion: an iverilog-vz fail explained by its iverilog companion

## What changed
- `crosscheck._companion_explained` treats an iverilog-vz `fail` as explained when:
  - iverilog failed the same flow and model source;
  - a value finding explains that iverilog fail;
  - no `transform-bug` finding separates the two.
- A `transform-bug` is never explained away by this path; it stays a finding.
- Why: the flops pilot (Task 24) found `L1.gsr_vs_{clear,preset}`, whose known
  divergences (doc-gap) list iverilog, verilator and xsim. Spec §8 classes are
  computed over the UNISIM simulators, so they never include iverilog-vz. Its identical
  trace was left as "fail not explained", and `xut crosscheck` exited 4.

## Tests
- 4 new unit tests: explained by the companion; a transform-bug is not explained this
  way; no explanation when iverilog passed; no explanation without views.
- `test_crosscheck.py` and `test_status_record.py`: 154 passed (8G scope, host lock).
- Real data: this branch's `xut crosscheck '7series.FD*'` on unit/7series/flops@84b2c74
  exits 0, with 56 agree and 2 known-divergence (previously exit 4).
- ruff check and format are clean.

## Next steps
- Merge PR #13, then rebase unit/7series/flops so Task 27's crosscheck exits 0.
- The code-quality nit about the long commit subject is left as is: rewriting a reviewed
  branch's history is not allowed (AGENTS.md §12).
