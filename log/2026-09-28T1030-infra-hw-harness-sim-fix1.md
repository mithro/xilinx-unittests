# infra/hw-harness: Task 5a review fix round 1

## What changed

- **Important 1, a short reply hung the simulation.**
  - Each host wait in `xut_hw_tb.sv` is now bounded. When the harness has been idle for
    16 byte-times, the testbench prints `XUT_SHORT_REPLY` and ends the run. Idle means
    the controller is in S_IDLE and no byte is being received from it.
  - `harness_tx.txt` is flushed after every byte.
  - `simulate` raises `HwSimError` naming the step. The error carries the partial reply
    as `.tx`, plus `split_replies`' "truncated" message.
  - New test: a mis-counted `Step(b"I", 2)` fails in about 1 s with the `id` line
    attached. It used to hang until the outer timeout.
- **Monitor test.** It now runs the counter self-test with a bound of MARGIN+4, which
  shows both branches firing:
  - capture gaps: the minimum is exactly MARGIN+1;
  - change gaps: exactly {MARGIN+3}, from the back-to-back EDGEs.
- **vvp OOM.** An exit code of 137 or -9 from `vvp`, or the container's OOM mark in the
  log, is now `HwSimError`, not "did not finish". There is a test for it.
- **Documentation.**
  - `cached_version`'s docstring warns that its lock is held across a probe that waits
    for a Vivado slot. Callers must not call it while holding a slot, and Task 6's
    builder probe must follow that too.
  - `_KILL_GRACE_S` now has a comment. The xsim runner's timeout path used 10 s before
    the Task 5a move into `xut.scope`; it now uses 30 s, matching the container kill
    timeout.
  - `slots.py`'s docstring lists `hwsim._xsim` as a slot holder.
- **Correction to the first session.** The byte-exact stream is 2796 bytes (106 lines),
  not 4194 as the Task 5a report said.

## Test results

- `test_hw_rtl.py`: 10 passed, on Icarus and xsim.
- Full suite (`-n 8`, 16G scope, host lock): 2107 passed, 18 skipped.
- `ruff check` and `ruff format --check` are clean.
- `xut lint --branch` has 0 errors. The 4 pre-existing flops portability warnings remain.

## Next steps

Task 5b.
