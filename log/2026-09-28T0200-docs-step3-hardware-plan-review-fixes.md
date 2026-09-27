# 2026-09-28: step 3 plan — review fixes and spec rev 3.6

This session addressed the review ("ready after fixes") and orchestrator ruling S49.

## What changed

- **Spec rev 3.6**, in its own commit before the plan fixes. It changes:
  - §5.6: N = 3 repeats;
  - §6: the post-flow DUT check for `vivado`, and the `hw` fields;
  - §7.1: the stimulus is loaded over the UART; power-on `t0`; the host-driven protocol and raw samples; the margin, the constraints and the checked latency budget; the packing limits;
  - §7.5: SRAM only; the S49 lock rule; busy rigs; DNA deferred;
  - §8: a failed DUT check is a `flow-mismatch`.

  PR C (#10) brings rev 3.5 for §6.2, so the status lines need merging on rebase.
- **C1, the lock.** The lock file is never deleted, re-created or broken:
  - a held lock means 75 (busy), with `(stale)` when the owner record is past its TTL;
  - only a verified own holder is killed: same client owner and label, same host and boot id, a live pid in the recorded group, past its TTL. Both of its process groups are killed;
  - `BoardBusy` moves the job to the next rig without using the transport retry;
  - 124 and 137 are documented;
  - the test that asserted a second holder is replaced by never-broken, no-owner and own-holder-recovery tests.
- **I1:** the `run_tests` error and its test use one wording.
- **I2:** the Vivado slots are host-wide: `$XDG_RUNTIME_DIR/xut-vivado/slot{0..3}.lock`, a non-blocking scan, then a blocking wait. `vivado -version` also runs under a slot, cached per process.
- **I3:** a generated `post_route.tcl` writes every DUT cell's `REF_NAME` and configured attributes, and `check_dut_cells` compares them.
  - A mismatch raises `FlowMismatch`: the runner reports `flow-mismatch`, `hw.dut_check = fail`, and crosscheck classifies it as `flow-mismatch`.
  - It is tested with fake reports and a `FakeBuilder` option.
- **I5:** the 100G budget is stated for every command (96G at most):
  - `pytest -n 4` at 32G;
  - `xut run --jobs 16`;
  - `xut hw sim` at one cap, 16G, and its xsim runs go through `scoped_run`.
- **I6:** Task 5 is split into 5a (scopes, testbench, `simulate`, byte-exact) and 5b (`plan.py` with its interfaces and tests, `sim_case`, `xut hw sim`, golden reproduction). Task 9 is split into 9a (session, fake) and 9b (pool, doctor, `xut hw rigs`).
- **M1:** the DUT clock latency is measured after routing (`XUT_LATENCY`) and fails the build if over budget.
- **M2:** a 28-clock FDRE build is added to Task 7.
- **M3:** `ModelDut(two_state=True)` for the fake board.
- **M4:** every code block was extracted, run through `ruff format`, then `ruff check` (E, F, W, I, B, UP, SIM; line length 100), and written back:
  - 48 complete modules are format-clean;
  - the remaining findings are undefined or unused names in fragments that extend existing files, which is intended;
  - the lint steps now format before checking.
- **M5:** the SRAM test scans every tracked file.
- **M6:** "every Vivado run" wording.
- **M7:** 124 and 137.
- **M8:** doctor never raises, and gates `hw` on the key and Vivado.
- **M9:** the DNA reasoning is corrected; Task 12 checks for a DNA option.
- **M10:** the inferred rig addresses are commented.
- **M11:** the lost-byte behaviour is documented.
- **M12:** the simulated-harness output moves to `build/hwsim-runs/`, and a test checks that `gather` ignores it.
- **M13:** bitstream compression, and the staged `top.bit` is deleted after upload.
- **M14:** the stdlib wording.
- **M15:** only `FD*.overrides.yaml` is staged.
- **M16:** the toy's catalog entry is imported from the step-2 tests.
- **M17:** notes on the python re-run and on the backend cache.

## Test results

- Nothing heavy was run (planning only).
- `ruff format --check` passes on the 48 parseable code blocks extracted from the plan.
- `xut lint --branch` passes (run before the push).

## Next steps

- The PR "docs: step 3 hardware plan and spec rev 3.6" gets the review gate.
- Rev 3.6 must be on `main` before Task 1.
