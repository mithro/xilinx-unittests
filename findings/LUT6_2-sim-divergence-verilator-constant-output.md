# LUT6_2: Verilator internal error when an output is constant

- Class: sim-divergence (a Verilator compile failure; see Analysis for why this class)
- Tests and configurations (the same on both model sources):
  - `7series.LUT6_2.L0.smoke (default, ones)`
  - `7series.LUT6_2.L1.default_init (default)`
  - `7series.LUT6_2.L1.projections (p5, n5)`
  - `7series.LUT6_2.L1.o5_lower_half (lo_zero_hi_ones)`
  - `7series.LUT6_2.L2.init_sweep (zeros, ones, w0_32..w0_63, w1_32..w1_63: 66 of 130)`
- Flow / model source: rtl / unisim-2025.2 and unisim-gh-2020.1
- Runners: verilator (errors); python, xsim, iverilog and iverilog-vz pass the same
  configurations
- First seen: luts Task B6 full run, 2026-09-28, at 59252e3
- Status: open

## Evidence

`xut run unit:luts` on both model sources: every configuration in which an output is constant: INIT's lower 32 bits are all zeros or all ones, so O5 is constant (O6 as well when all 64 bits are)
fails to compile on Verilator 5.048 (container `xut-sim:1`) with

```
%Error: Internal Error: <model>/LUT6_2.v:<line>:15: ../V3Gate.cpp:974: Consumer doesn't match lhs of assign
```

(line 84 of the unisim-2025.2 file, line 95 of the unisim-gh-2020.1 file; the
UNISIM source was not opened, per the clean-room rule). Every other configuration of the
same tests passes on Verilator, and every configuration listed above passes on python,
xsim, iverilog and iverilog-vz, so the traces that exist agree. LUT1, LUT2 and LUT3 compile
their constant configurations (INIT all zeros, all ones) without the error. `xut crosscheck`
reports these results as `error` issues and exits 4 (incomplete evidence).

## Analysis

UG953 allows every one of these INIT values (a constant function is a legal LUT; the
default INIT is all zeros, a ground). The failure is an internal error of Verilator's gate
optimiser (V3Gate) on a UNISIM model elaborated with a constant function, not a
disagreement with the golden model or with UG953: no trace is produced, so there is
nothing to compare. It is not `x-dependence` (the build fails before any X-seed run) and
not `transform-bug` (the error is in Verilator's compile, and iverilog-vz, Icarus on the
transformed model, passes). Crosscheck has no class for a simulator that fails to build a
UG953-legal configuration (decision D13); `sim-divergence` is the nearest: one UNISIM
simulator of the source does not reproduce what the others do.

Not yet handled: the unit has not declared these configurations unsupported on Verilator
(a per-configuration `config_exclusions.verilator` entry citing this finding) nor changed
any test. That is an orchestrator decision (see the luts B6 log). Possible infra
follow-ups: a Verilator option that avoids the V3Gate path, a newer Verilator, or an
upstream Verilator bug report with a minimal reproducer.
