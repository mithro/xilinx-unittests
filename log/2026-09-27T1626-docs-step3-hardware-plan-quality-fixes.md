# 2026-09-27: step 3 plan — PR #11 code-quality review fixes

## What changed

**Must-fix 1: one judging step.**
- New `runners.sim.judge_trace` covers the samples → trace → compare → `mismatches.txt` step. It keeps ruling S15: an empty expected trace is an `error`.
- `vector_check` is refactored onto it.
- `hwsim.sim_case` now uses it and returns `ConfigResult`; `CfgOutcome` is removed.
- The hw runner uses it too:
  - `run_config` judges repeat 1;
  - nondeterminism is passed in as a problem;
  - headers are built with `trace_header(...) | {seed, rig}`.
- `raw_to_trace` and `samples_to_trace` now share `stimcompile.out_port_bits`/`port_values`.
- There is an S15 test on each path:
  - `xut hw sim`: `sim_case`, with `simulate` replaced by the emulator;
  - hw runner: the fake board.

**Must-fix 2: preflight.**
- The new `Transport.capture` keeps a command's stdout separate from its log.
- The preflight parses only that stdout: a `PREFLIGHT_OK` line, and an `openFPGALoader v…` line.
- The command is `openFPGALoader --Version && echo XUT_PREFLIGHT_OK`, so a failing `--Version` is no longer masked.
- The fake transport logs the `$ ssh …` line exactly as the real one does.
- New tests cover the reported version, a failing `--Version`, and quoting.
- `preflight_command` and `PI_TOOLS` are shared with `xut doctor`.

**Nits:**
- Shared helpers and existing code:
  - `scope.run_in_group` and `scope.cached_version` replace the copies in `xsim.run_script` and `xsim_version`; the Vivado version uses `cached_version`;
  - the step-2 `ToyDff` replaces `HwToyFf`;
  - the session layout (`Step`, `session_steps`, `split_replies`, `slot_replies`, `run_replies`) moves to a stdlib-only `xut.hw.steps`. This also removes the function-level import in the session.
- Magic numbers become names: `TestPlan.dut_slot`, `PASS_SLOT`/`COUNT_SLOT`, `STATUS_CODE`/`.get`, and named UART timeout constants.
- Dead code is gone:
  - `OP_NAMES` is removed;
  - `CPB` now reaches the testbench through `host.vh`;
  - `RC_TTL` is now used;
  - the `_check_fits` alias is removed;
  - the `--fake` mention is removed.
- `check_fits` returns its `validate` report, so the stimulus is validated only once.
- `pool.run_job` runs each attempt through a `with`-based `_attempt` helper.
- Long functions are split:
  - `ensure_bitstream` → `_run_vivado`, `_post_route_checks`, `_manifest`;
  - `HwRunner._batch` → `_group`.
- Rigs config:
  - no fallback key: a rig without `identity_file` is a config error;
  - `Rig` and `Jump` are built with keywords.
- `xut hw sim --jobs` is capped by `max_sim_jobs`: PR #10's `container.max_jobs()` for Icarus, and budget ÷ 16G = 6 for xsim.
- `xut hw build` exits 4 on a planning error.
- The backend is keyed by `(root, rigs)`.
- The fake raises instead of asserting.
- Tests:
  - the lock tests poll instead of using fixed sleeps;
  - the hwsim tests moved to `test_hw_rtl.py`;
  - `PATTERNS.groupindex` replaces `_FIELD`;
  - the doctor, `run_tests` and crosscheck tests are now code (the old masking test is replaced).
- Task 12 and 13 stage only unit-owned paths.

## Test results

- Planning only; nothing heavy was run.
- `ruff format --check` passes on all 55 parseable code blocks.
- `ruff check` (E, F, W, I, B, UP, SIM, plus ANN on the tool modules) passes. The only findings left are undefined or unused names in fragments that extend existing files.
- `xut lint --branch` passes (run in a 4G scope before the push).

## Next steps

- Re-review PR #11.
