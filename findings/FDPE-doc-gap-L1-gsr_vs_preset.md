# FDPE: doc-gap in 7series.FDPE.L1.gsr_vs_preset

- Class: doc-gap
- Test: 7series.FDPE.L1.gsr_vs_preset
- Flow / model source: rtl / unisim-2025.2
- Runners: iverilog, verilator, xsim
- First seen: 2026-09-28 (flops Task 24; pre-check run of the uncommitted test, then the full run)
- Status: open

## Evidence

Configurations with INIT=1'b0 (INIT differs from the value PRE forces, 1), with
IS_PRE_INVERTED both 0 and 1. The golden model's expected Q, against every UNISIM simulator:

- `(A)` GSR asserted, then PRE made active (samples S2), then one clock cycle under both
  (S3 after the rise, S4 after the fall): expected 1, got 0 on every simulator.
- `(B)` PRE made active first (Q = 1, agreed), then GSR asserted (S9): expected 1,
  got 0 on every simulator.
- Every other sample agrees, including S5 (GSR released while PRE is still active: Q = 1,
  `doc:372`) and S10 (PRE released while GSR is still active: Q = INIT, `doc:372`).
- Configurations with INIT=1'b1 agree throughout: GSR and PRE give the same value there.
- Every disagreeing bit carries the provenance
  `inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win`;
  no `doc:` bit disagrees.

The crosscheck points of the full run are in the pilot log entry
(`log/*-unit-7series-flops-pilot-run.md`) and in `build/crosscheck/7series.FDPE.L1.gsr_vs_preset.json`.

## Analysis

UG953 v2026.1 p372 gives two rules that conflict here and does not order them:

- "When PRE is asserted, it overrides all other inputs and presets the data output (Q) High", with the logic-table row
  PRE=1, CE=X, D=X, C=X giving Q=1.
- "When global set/reset (GSR) is active upon power-up or when GSR is asserted, the value of
  the INIT attribute is placed on the register's output" (and the p373 INIT description:
  "initial value of Q output after configuration or when GSR is asserted").

"All other inputs" lists the pins; GSR is a global signal and is not named. The page never
says what Q is while both are active with INIT different from the forced value. The golden
model resolves the conflict with an `inferred:` rule (ruling S30): the control wins. UNISIM,
on xsim and Icarus (unisim-2025.2) and on Icarus and Verilator (unisim-gh-2020.1), gives
INIT: GSR wins, whichever of the two was asserted first. Both simulators and both model
sources agree with each other, so this is not a simulator divergence.

Because the model's answer is `inferred:` and UG953 is silent, this is a `doc-gap`, not a
model bug (AGENTS.md §8: where UG953 is silent the model gives a definite inferred value, and
a disagreement becomes a doc-gap finding, never a mask). Per ruling S42 the model is kept
as it is, and it is not refitted to UNISIM. The expected bits stay defined; the test lists
this finding in `expected_divergence`, so crosscheck reports it as `known-divergence`.

Resolution needs evidence outside UG953: a hardware run (GSR on hardware needs the
GSR-immune harness state of spec §7.2) or documentation that orders GSR against PRE
(for example UG474). If silicon shows GSR winning, the S30 inference should be revised,
from the new evidence, with its provenance.
