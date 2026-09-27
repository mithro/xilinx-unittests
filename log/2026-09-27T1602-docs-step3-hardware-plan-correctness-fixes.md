# 2026-09-27: step 3 plan — PR #11 correctness re-review fixes

## What changed

- **Must-fix 1 (lock recovery).** `xut_lock.sh` kills a stale holder only if two more checks pass:
  - the recorded pid's `/proc/<pid>/cmdline` is `xut_lock.sh` for this lock;
  - its start time (`/proc/<pid>/stat` field 22, plus `btime`) is at or before the record's `since`.

  Otherwise the rig is busy. New tests:
  - an unrelated reused pid (`sleep`) survives;
  - a lock script that started after the record survives.
- **Exit codes.** 75 now means busy and nothing else. A lock file that cannot be created or opened exits 93, which the session raises as a `BoardError` naming the lock fault. There is a test, and a fake fault.
- **Must-fix 2 (Vivado slots).** The plan's `VivadoSlots` and `slots_dir` are deleted. Every Vivado or xsim invocation (builds, `vivado -version`, and `xut hw sim`'s xsim runs) takes PR #10's `xut.slots.vivado_slot()`:
  - it appears in the consumes list and in the Step 0 import check;
  - there are tests that the hw-sim xsim runs, `vivado -version` and builds all run inside a slot.
- **Must-fix 3 (masking).** The crosscheck `hw` branch no longer uses `continue`, either after `flow-mismatch` or after `harness-error`. There are crosscheck tests for both combinations, and a runner test with two bitstream groups: one fails its DUT check, the other shows a silicon mismatch, and both are reported.
- **Must-fix 4 (staging).** I scanned every task's Files list against its `git add` lines:
  - Task 5b now stages `test_hw_plan.py`;
  - Task 10 stages `crosscheck.py` and `test_crosscheck.py`;
  - Task 7 has explicit build and log commits;
  - the log commits in 5b, 11, 12 and 13 are explicit commands.
- **Nits:**
  - the second lock wait is bounded to 30 s, and the host timeout is `wait + ttl + 180`;
  - the kill path is documented as a near-unreachable last resort;
  - a failed DUT check is cached (`flow_mismatch.json`), with a test;
  - reals are compared numerically;
  - the stale Task 6 reference and the Task 5b commit subject are fixed;
  - the spec wording for busy (a retryable `error`, not `harness-error`), for "the same client" and for the 28-clock note is fixed;
  - the doctor fragment's missing `VIVADO_SETTINGS` import is added.

## Test results

- Planning only; nothing heavy was run.
- The plan's 48 complete Python blocks are `ruff format`-clean, with no E/W/I/B/UP/SIM findings. The only findings left are undefined or unused names in fragments that extend existing files.
- `xut lint --branch` was run before the push, in a 4G scope.

## Next steps

- Re-review of PR #11.
- Once PR #10 lands, confirm that `xut.slots.vivado_slot()` matches the name and behaviour this plan assumes.
