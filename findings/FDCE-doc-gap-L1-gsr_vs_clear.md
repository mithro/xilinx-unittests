# FDCE: doc-gap in 7series.FDCE.L1.gsr_vs_clear

- Class: doc-gap
- Test: 7series.FDCE.L1.gsr_vs_clear
- Flow / model source: rtl / unisim-2025.2
- Runners: iverilog, verilator, xsim
- First seen: 2026-09-27 at b3ffb16
- Also seen: rtl / unisim-gh-2020.1 (2026-09-27 at b3ffb16)
- Status: open

## Evidence

`xut crosscheck '7series.FD*'` at b3ffb16 (results of the full runs of both model
sources), verbatim. rtl / unisim-2025.2, runners iverilog, verilator, xsim:

- init1_clrinv0/S2 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv0/S3 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv0/S4 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv0/S9 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S2 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S3 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S4 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S9 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)

rtl / unisim-gh-2020.1, runners iverilog, verilator (no xsim for this source):

- init1_clrinv0/S2 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv0/S3 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv0/S4 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv0/S9 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S2 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S3 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S4 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)
- init1_clrinv1/S9 Q[0]: expected 0, got 1 (inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win)

Sample map, per configuration (INIT=1'b1; IS_CLR_INVERTED 0 and 1):

- (A) S1 GSR on; S2 CLR on; S3, S4 after the rise and fall of one clock cycle
  under both; S5 GSR off, CLR still on (agrees: Q=0, `doc:`).
- (B) S8 CLR on (agrees: Q=0); S9 GSR on; S10 CLR off, GSR still on
  (agrees: Q=INIT, `doc:`).
- Configurations with INIT=1'b0 agree throughout; no `doc:` bit disagrees.

## Analysis

UG953 v2026.1 p369 gives two rules that conflict here and does not order them:

- "When CLR is active, it overrides all other inputs and resets the data output (Q) Low", with the logic-table row
  CLR=1, CE=X, D=X, C=X giving Q=0.
- "When global set/reset (GSR) is active upon power-up or when GSR is asserted, the value of
  the INIT attribute is placed on the register's output" (and the p370 INIT description:
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
GSR-immune harness state of spec §7.2) or documentation that orders GSR against CLR
(for example UG474). If silicon shows GSR winning, the S30 inference should be revised,
from the new evidence, with its provenance.
