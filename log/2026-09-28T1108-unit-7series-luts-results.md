# luts B6: full run and crosscheck (partial: two decisions pending)

Branch `unit/7series/luts`, rebased onto main 6a66bd6. Local time (ACST), as main's
recent entries use.

## What changed

- `5159693` regenerated the 8 READMEs after the rebase. The only diff is the "How to run"
  block, which now uses `xut heavy` (main 504198e).
- `f1a7559` B6 prep (b), review Minor 4: the CFGLUT5.C6 mutant now loads the complement
  of INIT instead of all zeros, and it is declared `event=True`, so it must fail every
  C6-crediting configuration. The old mutant passed L0.smoke, L1.default_init and
  L1.edge_polarity, which the guard confirmed when temporarily pointed at it.
- `59252e3` B6 prep (a), review Minor 1: the CFGLUT5 two-bits-per-edge blind spot is noted
  in `findings/CFGLUT5-doc-gap-L1-partial_shift.md`.
- `aa93fce` recorded the order UNISIM shows in both CFGLUT5 doc-gap findings. Both are
  still open.
- `e0cd240` filed four open findings, `findings/LUT{4,5,6,6_2}-sim-divergence-verilator-constant-output.md`,
  and regenerated the READMEs that link them.
- There is no cocotb harness-error finding to close, because B5 never filed one (see the
  2204 log). After PR #24, every cocotb test passes: LUT1-LUT6 and LUT6_2 on iverilog and
  verilator, and CFGLUT5 on iverilog, for both sources.

## Runs

- Before the run, each command was estimated at 45-60 min, reported every 5 min.
- `xut heavy --mem 8G --containers 12 -- xut run unit:luts --model-source unisim-2025.2 --jobs 12`
  took 1510 s (about 25 min) for 440 results.
- `xut heavy --mem 8G --containers 8 -- xut run unit:luts --model-source unisim-gh-2020.1 --runner python --runner iverilog --runner verilator --jobs 8`
  took 1313 s for 352 results.
- The two runs ran together within the 96G budget (56G + 40G). Both first waited about
  3 min behind old-style `flock` holders from other sessions.
- The long tail was Verilator on the L2.init_sweep tests of LUT6 and LUT6_2 (130
  configurations each).

## Crosscheck (`xut crosscheck unit:luts`, both sources): 65 agree, 22 incomplete, 1 uncompared, exit 4

- **Every documented and inferred comparison agrees.** No doc-vs-model, doc-gap,
  sim-divergence (trace), x-dependence or transform-bug disagreement was found on either
  source. This covers the CFGLUT5 order tests, L1.edge_polarity, the GSR tests
  (L1.gsr_transparent and L1.gsr_after_reconfig, so the D6 inferences hold), all the sv
  tests (the x and GSR checkpoints agree between iverilog and xsim) and all the cocotb
  tests.
- **CFGLUT5 bit order:** UNISIM follows the D5 inference on both sources. See the two
  findings.
- **Incomplete (a), 8 tests: `L0.illegal_init` of every primitive.**
  - The xsim and iverilog runs of unisim-2025.2, and the iverilog run of
    unisim-gh-2020.1, accept `INIT=<w>'bx..x` ("expected rejection, got acceptance").
  - Task A6's reject-test rule (and the flops precedent) says to remove the reject test
    and recipe and add a gap to L0.smoke.
  - **Not done: the edit was refused by the session's permission classifier** as the
    removal of a test. It needs the user's or orchestrator's approval.
- **Incomplete (b), 14 tests on Verilator, both sources: a Verilator 5.048 internal error**
  (`V3Gate.cpp:974: Consumer doesn't match lhs of assign`). It hits every LUT4, LUT5,
  LUT6 and LUT6_2 configuration in which an output is constant (INIT all 0/1; for LUT6_2,
  a uniform lower half). The same configurations pass on python, xsim, iverilog and
  iverilog-vz.
  - The findings are filed.
  - Crosscheck has no class for a simulator that cannot build a legal configuration
    (D13).
  - Clearing it at unit level would need a per-configuration
    `config_exclusions.verilator` entry citing the findings. That is also a test-scope
    reduction, so it was left for the orchestrator to decide.
- **Uncompared: CFGLUT5.L2.cocotb_random.** It has only one trace (iverilog), because
  Verilator is declared unsupported (S28). This is expected.

## Not done (blocked on the decisions above)

- `xut status record` for either source. Resolving (a) or (b) changes tree-hashed inputs,
  so the unit must be re-run and re-recorded after the decision in any case.
- The B7 PR.

## Checks

- `pytest tests/7series/clb`: 167 passed. The brief's "188" does not match the unit's
  historical count of 167, which B1-B5 also reported.
- `xut lint --branch`: 0 errors and 18 warnings, the known D12 portability-agreement ones
  on sv_x_inputs and illegal_init.

## Next steps

1. Orchestrator or user: approve removing the 8 `L0.illegal_init` reject tests. This
   touches `luts_tests.py`, `luts_recipes.py` and the L0.smoke gap, with the wording the
   flops unit uses.
2. Orchestrator: rule on the Verilator constant-output error: per-configuration
   `config_exclusions.verilator` citing the findings, or an infra fix (Verilator flag or
   version).
3. Then regenerate, commit, re-run both sources, crosscheck until exit 0, record status
   for both sources, log, and open the PR (B7).
