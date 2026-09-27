# 2026-09-27: step 3 (hardware) implementation plan

## What changed

- Added `docs/superpowers/plans/2026-09-27-step3-hardware.md`, the step 3 plan. It has 13 tasks in three stacked infra PRs, then the unit pilots:
  - **PR A** `infra/hw-harness`: the UART protocol and its generated message ROM, the `.xvec` → program-image compiler, the reference interpreter and emulator, the harness RTL and slot generator, and the harness under Icarus and xsim. The simulated harness must match the emulator byte for byte, and must reproduce FDRE's golden trace.
  - **PR B** `infra/hw-vivado`: capped `systemd-run` scopes, the Vivado batch build (generated constraints, deterministic build IDs, bitstream cache), and the first real builds.
  - **PR C** `infra/hw-runner`: the rigs config, the Pi-side scripts (rig lock, SRAM programming, UART), `BoardSession` with a fake transport, the board pool, `xut doctor`, the `hw` runner, and the LUT6 smoke design.
  - **PR D/E**: the flops pilot on a real board. The luts pilot is conditional on the luts unit having merged; otherwise the LUT6 smoke design stands in.
- Owner ruling applied while writing: no `/dev/null` anywhere in the plan, in any form. The only occurrence is the Global Constraints rule itself.

## Test results

- None run: this is a planning session. The plan was written against the infra code on `main` (crosscheck, status, provenance) and on `infra/verilatorize` (runners, container), both read-only.

## Decisions recorded in the plan

The plan's "Spec ambiguities resolved" section lists these, with a proposed spec rev 3.5:
- the stimulus is loaded over the UART, not baked into the bitstream;
- the harness streams raw samples, and the host writes the `.xtr`;
- `t0` becomes the harness flip-flops' INIT, with one run per slot per programming;
- the protocol is host-driven;
- `hw` runs flow `vivado` and records results under the reference model source only;
- DNA readback is deferred to the configuration unit;
- the lock mechanics, and N = 16 cycles at 100 MHz;
- 3 repeats;
- packing per test;
- the harness relies on BUFG and BRAM;
- `xut hw sim` is not a runner;
- the rig addresses beyond p9 are inferred.

## Next steps

- Review the plan (docs PR), and decide on the proposed spec rev 3.5 amendments.
- Prerequisites for Task 1: step-2 PRs C (verilatorize) and E (flops) merged.
- Board access (fpgas-online/fpgas.online-infra#124) gates only Task 12. Tasks 1–11 need no board.
