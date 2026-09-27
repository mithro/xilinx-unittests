# unit/7series/luts — sv testbenches and the cocotb session (Tasks B4, B5)

These are Tasks B4 and B5 of the unit playbook, transcribed verbatim from the plan by extraction, not retyped. The generated LUT wrappers and cocotb modules from Task B3 already matched the plan's examples byte for byte.

## What changed

- **B4**:
  - Shared bodies `tests/7series/clb/_shared/luts/luts_x_tb.svh` and `luts_gsr_tb.svh`, which the 14 generated LUT wrappers include.
  - Hand-written `tests/7series/clb/CFGLUT5/sv/tb_cfglut5_x.sv` and `tb_cfglut5_gsr.sv`.
- **B5**: the shared session `tests/7series/clb/_shared/luts/luts_cocotb.py`, which the 8 generated cocotb modules import.

## Test results

- `ruff check` and `ruff format --check` over `tests` and `models`: clean.
- `pytest tests/7series/clb/_shared/luts`: 167 passed.
- `xut lint`: 0 errors. The warnings are the same 14 D12 ones as before.
- **sv on iverilog.** `xut run 'unit:luts' --style sv --runner iverilog --jobs 16` ran under the heavy lock in a 32G scope.
  - Result: exit 0, and all 16 sv tests pass. That is 23 configurations.
  - `XUT_CHECKS` per configuration is exactly what the plan expects: LUTn `sv_x_inputs` 2^n, LUT6_2 128; LUTn `sv_gsr_midsim` 2 × 2^n, LUT6_2 256; CFGLUT5 192 (x) and 160 (gsr).
  - I read only pass/fail and the check counts, never a checkpoint value (clean room).
- **cocotb on iverilog.** `xut run 'unit:luts' --style cocotb --runner iverilog --jobs 16` ran under the heavy lock in a 32G scope. It exited 1:
  - CFGLUT5 and LUT1-LUT3 pass (2001 samples per LUT configuration, 2578 per CFGLUT5 configuration).
  - **LUT4, LUT5, LUT6 and LUT6_2 fail** in all 4 configurations each. The failure is the same everywhere: the DUT output is `x` at the power-on comparison S0 (LUT6, LUT6_2), or at S0 and S1 (LUT4, LUT5). The golden model expects a defined, documented bit there. Every later sample matches, so each configuration has 1 or 2 mismatches out of 2001 samples.

## Classification: harness-error (infra-owned)

The cocotb top that `xut wrap --cocotb-top` generates (`tools/xut/wrap.py`, line 611) gives `in_vec` a declaration initialiser, `reg [..] in_vec = {..{1'b0}}`, and `XutDut` also writes 0 at construction. On Icarus that time-0 value raises no event that a combinational UNISIM LUT model sees. This is exactly decision D7:

- The vector testbench (`tools/xut/hdl/xut_vector_tb.sv`) avoids it with the time-0 barrier: `in_vec` stays x until a time-0 non-blocking update.
- The luts sv testbenches avoid it in the same way, and pass.

The cocotb top has no such barrier. The session drives 0 again (`x.set(**idle)`), but the value does not change, so no event occurs. The output stays x until an input really changes.

I did not change the session to hide this (AGENTS.md §9), and I did not touch the infra path (AGENTS.md §3, §13).

**TODO (infra):** the cocotb top should leave `in_vec` (and `clk`) undriven at declaration and give them their first value with a time-0 non-blocking update, as `xut_vector_tb.sv` does. After that, re-run the LUT4-LUT6/LUT6_2 cocotb tests. Whether to also file `harness-error` findings for them is for the coordinator to decide. They would be `findings/<PRIM>-harness-error-L2-cocotb_random.md`.

I have not run xsim or verilator yet; that is Task B6.

## Next steps

- The infra fix above, then the full unit run on every runner (Task B6).
