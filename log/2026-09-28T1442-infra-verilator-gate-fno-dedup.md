# infra/verilator-gate: -fno-dedup for the V3Gate internal error on constant LUTs

## What changed

- `tools/xut/runners/verilator.py`: every Verilator build (vector and sv) adds
  `OPT_FLAGS = ("-fno-dedup",)` after `--x-initial unique`. The module docstring explains why.
- `tools/xut/hdl/cocotb_run.py`: cocotb Verilator builds use the same flags. A test pins the
  two copies as equal.
- Tests:
  - `test_every_build_disables_the_v3gate_dedupe` (hermetic);
  - `test_constant_output_lut4_builds_and_simulates[unisim-2025.2, unisim-gh-2020.1]`
    (container). It builds the real UNISIM LUT4 with INIT=16'h0000 through
    `verilator_argv` and checks that O is 0 for all 16 inputs. A control build without
    `OPT_FLAGS` must still hit the internal error, so this test flags when a Verilator
    upgrade makes the flag unnecessary.

## Root cause and minimal repro

Verilator 5.048 (`xut-sim:1`) fails with `%Error: Internal Error: .../LUT4.v:61:12:
../V3Gate.cpp:974: Consumer doesn't match lhs of assign`. Minimal input: the plain
`verilator --binary --timing -y <unisims>` command, with none of the runner's other flags,
on this module:

```verilog
module tb2;
  reg [3:0] i;  wire o;
  LUT4 dut (.O(o), .I0(i[0]), .I1(i[1]), .I2(i[2]), .I3(i[3]));  // INIT default 0
  initial begin i = 4'd0; repeat (16) begin #10; $display("%b %b", i, o); i = i + 1; end $finish; end
endmodule
```

With `reg [3:0] i = 4'd0` (a declaration initialiser instead of the initial block) the
error does not occur.

LUT4, LUT5, LUT6 and LUT6_2 compute O with nested calls of a mux function over INIT
slices. A constant INIT makes those calls identical, and V3Gate's dedupe sub-pass trips
over the merged logic. LUT1–LUT3 use a UDP instead and are unaffected.

## Flags tried

These were tried on the failing luts config `7series.LUT4.L0.smoke cfg-default`, using the
runner's exact command plus one flag each.

- **Fix the build:** only `-fno-gate` and `-fno-dedup`. `-fno-dedup` is the narrower: it
  turns off only the gate dedupe sub-pass.
- **Still fail with the same error:** `-fno-` followed by each of `dfg`, `dfg-pre-inline`,
  `dfg-post-inline`, `dfg-scoped`, `dfg-peephole`, `const`, `const-bit-op-tree`,
  `const-before-dfg`, `const-eager`, `inline`, `inline-funcs`, `subst`, `subst-const`,
  `table`, `expand`, `life`, `life-post`, `localize`, `func-opt`, `dead-assigns`,
  `dead-cells`, `case`, `slice`, `lift-expr`, `reorder`, `merge-cond`, `split`,
  `var-split`, `acyc-simp`, `assemble`, `combine`, `reloop` and `merge-const-pool`.

No newer Verilator was needed, and the container image is unchanged.

## Identical-outcome evidence (A = without, B = with -fno-dedup)

A and B were fresh `xut run <sel> --runner verilator --jobs 8` runs (iverilog-vz runs as
the companion) in separate worktrees. A comparison script checked, per test:

- `result.json` status, reason, seeds and x_dependence;
- every configuration's status, reason, stimulus/trace sha256 and mismatches;
- the sha256 of every `trace.xtr`, `raw.txt`, `xdep.json` and `mismatches.txt`, including
  the per-X-seed files.

| selection | runner | model source | configs | differences | A errors fixed in B |
|---|---|---|---|---|---|
| luts (805ac58) | verilator | 2025.2 | 606 | 0 | 87 |
| luts (805ac58) | verilator | gh-2020.1 | 606 | 0 | 87 |
| luts | iverilog-vz | both | 606 each | 0 | 0 |
| flops (main 6a66bd6) | verilator | 2025.2 | 296 | 0 | 0 |
| flops (main 6a66bd6) | verilator | gh-2020.1 | 296 | 0 | 0 |
| flops | iverilog-vz | both | 296 each | 0 | 0 |

- **luts, fixed configurations.** The 87 configurations fixed in B are exactly the V3Gate
  errors in A. Each is now a pass:
  - LUT4/5/6: L0.smoke ×2, L1.default_init ×1 and L2.init_sweep ×2 each;
  - LUT6_2: L0.smoke ×2, L1.default_init ×1, L1.o5_lower_half ×1, L1.projections ×2 and
    L2.init_sweep ×66.
- **luts, other configurations.** All other 519 are byte-identical passes on both sources.
- **flops.** A and B both have the same 4 fails per source: FDCE.gsr_vs_clear and
  FDPE.gsr_vs_preset, the known open doc-gap findings. Everything else passes and is
  byte-identical.
- **tools/tests.** This covered `test_runner_verilator`, `test_runner_cocotb` and
  `test_vz_*` (container included, `-n 8`). Main gave 393 passed. The branch gave 396
  passed: the same 393 plus the 3 new tests. There were no failures and no skips.

## Build time

Build time was measured with an interleaved A/B benchmark: the runner's exact command,
with and without the flag, 5 repetitions each. The five configurations were LUT3, LUT4
and LUT6 `rand`, FDRE `init0` and FDCE (transformed models), all on unisim-2025.2.

- **Overall median:** 4.57 s without the flag and 4.74 s with it (+3.7%).
- **Per configuration:** from −5.5% to +10%, which is noise on a shared host.
- **Full runs:** median test durations were about the same, e.g. luts verilator 2025.2
  10.3 s → 9.9 s.

## Test results

- `ruff check` and `ruff format --check` are clean.
- `xut lint --branch` passes.

## Next steps

- After merge, the luts unit can drop its pending Verilator decision. It can then re-run
  and close the four `findings/LUT{4,5,6,6_2}-sim-divergence-verilator-constant-output.md`
  findings (they are unit-owned; this branch did not touch them).
- When the image's Verilator is upgraded, the control half of
  `test_constant_output_lut4_builds_and_simulates` shows whether the flag is still needed.
