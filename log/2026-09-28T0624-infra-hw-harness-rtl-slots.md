# infra/hw-harness: harness RTL and slot generator (Step 3, Task 4)

## What changed

- `tools/xut/hdl/hw/`: the harness RTL, verbatim from the plan. It holds
  `xut_hw_uart_tx.sv` and `xut_hw_uart_rx.sv` (8N1), `xut_hw_crc32.vh` (the zlib CRC-32),
  `xut_hw_print.sv` (the message-ROM printer), `xut_hw_ctrl.sv` (the parser, loader,
  stimulus BRAM and sequencer, with the `S_WAITM` MARGIN+1 hold) and `xut_hw_top.sv`
  (Arty A7 top: one sysclk BUFG and a 128-cycle power-on reset).
- `tools/xut/hw/slots.py`: `SlotBuild` and its digest, the self-test slots, `pack`
  (digest order, a 28-BUFG DUT budget, `MAX_SLOTS`), and `render_slots`. It also has
  `render_cfg_vh` and `timing_tcl`, where every object query goes through `xut_must`.
- `tools/tests/test_hw_slots.py`: 8 tests, including the Icarus elaboration of the whole
  harness with two toy DUTs.

## Test results

- Red first: `No module named 'xut.hw.slots'`.
- `test_hw_slots.py`: 8 passed (`-n 4`, 16G scope). This includes the container
  elaboration test on `xut-sim:1`.
- A manual Icarus `-g2012 -Wall` elaboration of the same harness produced no warnings.
- All `test_hw_*.py` files: 66 passed and 1 skipped. The skip is the S54 flops skip.
- `ruff format` and `ruff check`: clean. `xut lint --branch`: 0 errors. The one warning
  is the existing orchestrator-only PORTABILITY.md warning.

## Next steps

- Task 5a: the testbench, then the byte-exact comparison of the RTL against
  `Harness.feed()` on Icarus and xsim. Task 5a also has to handle the controller dropping
  host bytes that arrive while it prints or runs.

## Fix round 1 (task-4-review.md, rulings S59)

### What changed

- **Critical: timing.tcl.**
  - The out-of-DUT max-delay was `-datapath_only -to cur_out` with no `-from`, which
    Vivado rejects (Constraints 18-540). It is now
    `-from [xut_must dclk [get_clocks dclk_s*]] -to [xut_must cur_out ...]`. The self-test
    counter guarantees that at least one `dclk_s*` exists.
  - The in_vec constraint keeps `-from in_s` with no `-to`, so that it times every path out
    of in_vec: DUT flops, async pins, latch gates, and `cur_out` through combinational
    DUTs. Adding a `-to` would only narrow it.
  - The new test asserts that every `-datapath_only` delay has a `-from`, and that the
    capture delay has both `-from` and `-to`.
  - The plan's Task 4 code block (line ~2812) has the same bug. The orchestrator will fix
    it in a docs follow-up.
- **Vivado probe.** A Vivado 2025.2 synthesis of the self-test slots, two toy FFs and a
  20-bit two-chunk DUT (`xc7a35ticsg324-1L`) ran under `vivado_slot()`, in a 16G scope,
  with the heavy lock. Results:
  - `source timing.tcl` gives rc=0: no error and no critical warning.
  - `report_exceptions` shows both constraints as `max_dpo=140`.
  - DUT Q→`cur_out` and counter→`cur_out` paths have a requirement of 140 ns, with hold
    false-pathed.
  - All constraints are met (WNS 3.659 ns, WHS 0.045 ns).
- **Important 1: one command in flight.**
  - The rule is stated in the `proto.py` docstring and the `xut_hw_ctrl` header.
  - `Harness.feed()` raises `EmuError` on a byte that follows a complete command in the
    same call. A frame split across several calls is still legal.
  - Tests cover `II`, `IR`, `ZI` and L+R, plus the legal pacing.
- **Important 2: fail-closed packing.**
  - `pack()` refuses any primitive outside `PACKABLE`: FD*, LD*, LUT*, CFGLUT5, CARRY4,
    MUXF7/8, SRL*, RAM32/64/128/256* and ROM*. The refusal reads "hw packing: <PRIM> needs
    resource budgeting (BUFG/MMCM/BRAM/DSP/IO/region) — not yet supported".
  - `slots.py` carries a TODO listing the resources to budget.
- **Minors.**
  - Stronger tests:
    - the Icarus elaboration runs with `-Wall`, adds a two-chunk DUT, and requires no
      diagnostic line at all (no "error" substring check);
    - the `MAX_SLOTS` split (62 per bitstream);
    - a non-DUT refusal;
    - validation of the slot list, `maxwords`, `margin` and `t0`;
    - `maxin` rounding.
  - The 2-cycle `sample_take` offset is documented in the `xut_hw_ctrl` header and the
    interp docstring.
  - The generators validate their inputs: the exact self-test slots, DUT-only slots from
    slot 2 on, the clock budget, `MAX_SLOTS`, `maxwords` in 1..65535, `margin` in 3..255,
    and a 32-bit build id.
  - `pack` places identical digests once.
  - UART RX waits for an idle line after a framing error. A new Icarus test fails on the
    old RX, which emits a garbage 0xf0 byte after a break.

### Test results

- `test_hw_*` and `test_stimcompile.py`: 164 passed, 1 skipped (the S54 skip).
- `ruff` is clean.
- `xut lint --branch`: 0 errors.

### Next steps (Task 5a/6)

- **Task 5a testbench.**
  - Flag X or Z on `cur_out` at `sample_take`.
  - Measure change-to-capture as `sample_take - 2`.
  - Pace one command in flight.
  - Include a multi-chunk slot.
- **Task 6 `board.xdc`.**
  - Add `set_false_path` for `uart_txd_in`, `uart_rxd_out` and `led[*]` (asynchronous
    ports).
  - Consider a vivado-marked test asserting both exceptions in `report_exceptions`.
