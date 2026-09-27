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
