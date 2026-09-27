# Step 3 — Hardware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the suite's vector tests on real silicon and cross-check the results:

- a stimulus compiler: `.xvec` → a program image of harness operations (spec §7.1), with a Python reference interpreter and a byte-exact emulator of the harness, so everything up to the UART is testable without hardware;
- the stepped fabric harness RTL for the Arty A7-35T (`xc7a35ticsg324-1L`):
  - a sequencer whose DUT clocks are harness flip-flops routed through BUFGs, with an N-cycle margin after every change;
  - multi-DUT packing, selected by a harness register;
  - the self-test passthrough and counter channels;
  - a UART dumper whose output carries the build ID, the slot and a CRC;
- the harness simulated under xsim and Icarus against the reference emulator, and the simulated harness reproducing the golden `.xtr` for FDRE;
- a Vivado batch build flow run in a capped scope, with generated-clock and max-delay constraints, deterministic build IDs and a bitstream cache;
- a `BoardSession` adapter (spec §7.5) for SSH through a jump host: SRAM-only programming with `openFPGALoader -b arty`, the UART session, a per-rig `flock` lock with a TTL, one transport retry, and boards marked bad on a self-test failure. It is fully testable with a fake transport;
- the `hw` runner, plugged into the existing `Runner`/`RunResult`/crosscheck/status machinery exactly like the xsim runner;
- the pilot: the `flops` unit on hardware (plus the `luts` unit if it has merged, otherwise a LUT6 smoke design), run on a real board, cross-checked and recorded.

**Architecture:**

- **Order, not time.** The stepped harness renders the *order* of a stimulus's events (spec §5.1 ruling S8′). `xut.hw.compile` drops the picosecond times and emits one operation word per action: `SET` a 16-bit chunk of the next input vector, `COMMIT` it, `EDGE` one DUT clock, `SAMPLE`, `END`. The harness itself (not the program) holds `MARGIN` system cycles after every `COMMIT` and `EDGE`, so correctness holds by construction whatever the program says.
- **Stimulus over the UART, DUTs in the bitstream.** A bitstream holds the harness plus a set of DUT *slots* (one per test configuration). The programs are loaded over the UART at run time, so a bitstream depends only on its slots, never on the stimulus. Identical slot sets from different tests share one cached bitstream.
- **Power-on state.** Each slot's input register powers up as the stimulus's `t=0` values (the flip-flops' INIT, baked into the bitstream), and each DUT clock powers up low. That is the hardware equivalent of simulation's "inputs at their `t=0` values while glbl holds GSR". A slot runs once per configuration of the FPGA (the harness refuses a second run of a used slot), so every repeat reprograms the FPGA.
- **One protocol definition.** `xut.hw.proto.MESSAGES` is the single definition of the harness's replies. It generates the harness's message ROM (`xut_hw_msgs.vh`, committed and pinned by a test), the host parser and the reference emulator. `tools/tests/test_hw_rtl.py` pins that the RTL transmits byte-for-byte what `xut.hw.interp.Harness` predicts, on Icarus and on xsim.
- **Board access** is one `BoardSession` per rig (spec §7.5). One SSH job per programming: `scp` the bitstream and three small Pi-side scripts, then run them under the rig lock, then `scp` the results back. A `Transport` protocol separates the session logic from `ssh`/`scp`, so a `FakeTransport` backed by the emulator tests all of it: retry, busy locks, CRC corruption, self-test failure and bad-board fallback.
- **The `hw` runner** runs flow `vivado` (spec §6: "bitstream on hw"; `xut.testspec.runner_flows` already maps `hw` to the non-`rtl` flows). It writes `build/vivado/hw/unisim-2025.2/<test-id>/`, beside the golden model's `build/rtl/python/unisim-2025.2/<test-id>/`, so `xut crosscheck` finds both in one model-source group. Its `result.json` `hw` object carries `selftest`, `repeats` and `repeats_differ`, which crosscheck already reads for `harness-error` and `nondeterminism`.

**Tech Stack:**

- Everything from steps 1–2: Python ≥ 3.12, uv, click, PyYAML, jsonschema, pytest (+ xdist), ruff, the `xut-sim:1` container (Icarus 12, Verilator 5.048), Vivado 2025.2 xsim.
- Vivado 2025.2 synthesis and implementation (`vivado -mode batch`), always inside a `systemd-run --user --scope` with `MemoryMax=16G`.
- On each rig's Raspberry Pi: `openFPGALoader`, `flock`, `timeout` (util-linux, coreutils) and `python3` (standard library only). `xut doctor` and `xut hw rigs` check for all four.

**Spec:** `docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md` (rev 3.6, which this plan's docs PR brings: it records the decisions below and ruling S49). Read §§4, 5 (especially 5.1 ruling S8′ and 5.3), 6, 7 (binding for this step), 8, 11, 13, 14, 15 and 16 step 3.

**Prerequisites:** the step-2 PRs are merged into `main`: A (#4), B (#6), D (#7), the xvec-strings PR (#8), **C** (`infra/verilatorize`: the verilator runner and `xut.runners.sim`) and **E** (`unit/7series/flops`: the FDRE/FDSE/FDCE/FDPE models and tests). This plan consumes:

- `xut.formats.xvec`: `Vec`, `Event`, `load`, `check_structure`; `xut.formats.xtr`: `Trace`, `load`, `dump`, `compare`, `diff`, `XtrError`;
- `xut.validate.validate` (`Report.errors`, `.hw_reasons`), `xut.stimcompile` (`StimCompileError`, `_check_fits`, `raw_to_trace`), `xut.stimgen.VecBuilder`;
- `xut.wrap`: `DutMap`, `spec_from_catalog`, `build_map`, `write_dut`; `xut.catalog.model.load_entry`;
- `xut.golden.replay`; `xut_models.base.Model`/`Out`; `xut_models.registry.get`;
- `xut.runners.base`: `Runner`, `RunContext`, `RunResult`, `ConfigResult`, `workdir`, `python_dir`, `load_generated`, `expected_trace`, `NoExpectedTrace`, `sha256_file`, `error_reason`;
- `xut.runners.xsim`: `render_script`, `run_script`, `settings_available`, `xsim_version`, `LIBRARY_PATH_GUARD`;
- `xut.container`: `executor_for`, `RunTimeout`; `xut.modelsrc.resolve`;
- `xut.slots.vivado_slot` (PR #10, ruling S50 CQ2): the host-wide Vivado/xsim slot every Vivado or xsim invocation in this plan takes;
- `xut.testspec`: `TestCase`, `declared`, `exclusions_for`, `runner_flows`; `xut.run.run_tests`; `xut.crosscheck` (reads `result.json` `hw.selftest`, `hw.repeats`, `hw.repeats_differ`);
- `xut.doctor`: `Check`, `Probe`, `run_checks`, `_safe`;
- the pytest markers `container`, `vivado`, `slow` and `tools/tests/conftest.py`.

- [ ] **Step 0 (before Task 1): verify the prerequisites on `main`**

```bash
cd /home/tim/github/f4pga/xilinx-unittests && git fetch origin && git checkout main && git pull --ff-only
mkdir -p .cache
uv run python -c "from xut.runners.sim import vector_check; from xut.runners.verilator import VerilatorRunner; from xut.runners.xsim import render_script, run_script; from xut.stimcompile import _check_fits, raw_to_trace; from xut.crosscheck import classify; from xut.slots import vivado_slot; from xut_models.registry import get; print('step-2 interfaces OK', get('7series','FDRE').PRIM)" > .cache/step3-step0.log 2>&1
ls tests/7series/register/FDRE/test.yaml tests/7series/register/_shared/flops/flop_tests.py >> .cache/step3-step0.log 2>&1
grep -n "revision 3.6" docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md >> .cache/step3-step0.log 2>&1
cat .cache/step3-step0.log
```

Expected: `step-2 interfaces OK FDRE`, both paths listed, and the spec's `Status: revision 3.6` line. Spec rev 3.6 (§5.6, §6, §7.1, §7.5, §8; ruling S49) lands with this plan's docs PR, and **must be on `main` before Task 1**: AGENTS.md §1 makes the spec on `main` win over a plan, and rev 3.4's §7.1/§7.5 text contradicts this plan (the stimulus in the bitstream, a dumped `.xtr`, a lock broken past its TTL). If PR C or E has not merged, stop and report: Tasks 1–11 need C (the shared simulator code), and Task 5b's FDRE proof and Task 12 need E. If a name differs, adapt this plan's calls to the merged code (not the semantics), and note the mapping in the first log entry.

## Global Constraints

- **SPDX headers.** Every source file (`.py .v .sv .svh .vh .yaml .sh .tcl .toml .xdc`, workflow files) starts with an `SPDX-License-Identifier: Apache-2.0` comment in its syntax (`#`, `//`). Generated files (`xut_hw_msgs.vh`, `xut_hw_slots.v`, `xut_hw_cfg.vh`, `timing.tcl`, `build.tcl`, `build.sh`) carry it too. Markdown and JSON (no comment syntax; the existing schemas carry none) are exempt.
- **Never `2>/dev/null`** (or any `/dev/null` redirection).
- **Never pipe command output into `grep`/`tail`.** Log to a file (`cmd > .cache/x.log 2>&1`), then inspect the log file.
- **Small commits.** Commit after every meaningful change. Subjects are prefixed `<area>: ` (`infra: `, `hw: `, `runners: `, `flops: `, `luts: `, `docs: `). Every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`, passed as a second `-m` as the commit commands below do.
- **MEMORY SAFETY:** every heavy command (Vivado, `pytest -n`, `xut run`) runs inside `systemd-run --user --scope --slice=vivado.slice --unit=xut-<what>-$(date +%s) -p MemoryMax=<cap> -p MemorySwapMax=0 -- <cmd>`. Every docker container gets `--memory=4g --memory-swap=4g` (the infra now does this). Vivado jobs are at most 4 in parallel, and each Vivado scope is capped at 16G. `pytest -n` is at most 8, never `-n auto`.
  - `xut` itself launches every Vivado synthesis/implementation run, and `vivado -version`, through `xut.scope.scoped_run` (Task 5a), which builds exactly that `systemd-run` line with `MemoryMax=16G`, inside PR #10's host-wide `xut.slots.vivado_slot()` (`XUT_VIVADO_SLOTS`, default 4, flock files `$XDG_RUNTIME_DIR/xut-vivado/slot{N}.lock`). It refuses to run Vivado when `systemd-run` is missing: it never falls back to an unscoped Vivado. Every xsim or Vivado invocation takes a slot, including those under `xut hw sim`, whose xsim runs go through `scoped_run` at the same `HW_SIM_MEMORY_MAX = "16G"` that its command scope uses (one value throughout).
  - **The budget** (ruling S49 I5): the project's share of `vivado.slice` is 100G, and the caps of everything that can run at once must sum to at most that. Vivado children and containers run in their own scopes, outside the command's cap, so both count:
    - Vivado and xsim: at most 4 × 16G = 64G, host-wide (PR #10's `XUT_VIVADO_SLOTS`, default 4; never raise it).
    - `pytest`: at most `-n 4` in a 32G scope. Each worker runs at most one capped child (a 4G container or a 16G Vivado), so the worst case is 32G + 4 × 16G = **96G**. Never run `pytest -n` above 4 while Vivado builds can run.
    - `xut run` (simulators): a 32G scope plus `--jobs 16` × 4G containers = **96G**. `xut run --flow vivado --runner hw`: 32G + 64G of Vivado = **96G**.
    - `xut hw build` and `xut hw smoke`: an 8G scope + 64G of Vivado = **72G**.
    - `xut hw sim`: a 16G scope plus Icarus `--jobs 8` × 4G containers = **48G**, or xsim `--jobs 2` × 16G = **48G**.
    - Do not run two of these at once.
  - Commands in this plan that run `pytest -n`, `xut run`, `xut hw build`, `xut hw sim` or `xut hw smoke` are written out in full with their scope and the caps above.
  - An OOM kill is a retryable failure: lower the parallelism and re-run. Never raise a cap.
- **SRAM-only programming.** The only programming command anywhere is `openFPGALoader -b arty <bitstream>`, which writes the FPGA's SRAM. Never pass `-f`, `--write-flash`, `--external-flash`, `--bulk-erase` or any other flash option, and never use openocd's `program`. The flash keeps whatever the lab put there. `xut.hw.session.PROGRAM_ARGV` is the one definition; a test pins it, and the Pi-side script `hw/pi/xut_work.sh` has no other `openFPGALoader` line (a test greps for it).
- **The flock rule** (spec §7.5, ruling S49). Programming the FPGA, and any reboot of a rig, happen only while holding that rig's lock: `flock` on `/run/lock/<lock>` (per rig, from `hw/rigs.yaml`), taken by `hw/pi/xut_lock.sh`.
  - The holder writes an owner record (label `xut.session`, owner, host, boot id, pid, process groups, since, TTL) and runs under `timeout -k 10 <ttl>`, so a holder of ours never outlives its TTL.
  - **The lock file is never deleted, re-created or unlinked, and a lock is never broken.** A held lock, even one whose owner record looks stale, is waited for up to the rig's `lock_wait_s`. Then the rig is reported `busy`: the job is a retryable `error` (not a result, not a `harness-error`) and moves to the next rig.
  - The only recovery allowed is killing a holder verified as our own: our label and client owner, the same host and boot id, a live pid in the recorded process group, and past its TTL.
  - xut never reboots a Raspberry Pi unless the rig's config names a `reboot_command`, and even then only through the same lock.
- **Transport errors are retried once** (spec §7.5, §14). An error is never retried into a pass: a retry re-runs the whole job, and a second failure is an `error` result.
- **No hard-coded board access.** Board names, addresses, jump host, key path, UART device and lock names come from `hw/rigs.yaml` (or the file named by `XUT_HW_CONFIG`). No secret is ever committed: the rigs file names the key *path* (`~/.ssh/keys/xilinx-unittests_ed25519`), never key material. SSH runs with a generated `.cache/hw/ssh_config` (`IdentitiesOnly yes`, `BatchMode yes`), so no agent key or user config leaks in.
- **Vivado** is only ever sourced in a subshell: `bash -c 'source /opt/xilinx/Vivado/2025.2/settings64.sh && ...'`, and never with `XIL_TIMING` (spec §2: timing is out of scope).
- **Stdlib-only modules.** `hw/pi/xut_uart.py` is self-contained (standard library only, and it must not import `xut.*`): only the three `hw/pi` scripts are copied to a Pi. `tools/xut/hw/{proto,image,interp,selftest}.py` are standard library only too, so that the emulator and the tests can use them without xut's dependencies.
- **Generated files** `status/PROGRESS.md`, `status/TODO.md`, `status/LOG.md` and `status/PORTABILITY.md` are never committed on a branch; only the orchestrator regenerates them on `main` (`status: regenerate`).
- **Coordination.** Before any real-board step, check board availability with the fpgas.online sessions (ten64.welland.mithis.com, desktop.buddy.mithis.com), and confirm the shared lock name they use. Board access (keys on the Pis, the jump-host account) is fpgas-online/fpgas.online-infra#124. Route any infra request there. Never touch a repo outside github.com/mithro or github.com/fpgas-online.
- **Long runs** follow the global progress-reporting rule: run in the background, log to a file, watch with a Monitor that reads the log's `progress: done=N total=M elapsed_s=E` lines (`xut run`, `xut hw build`, `xut hw sim` all print them), and report the remaining time and the finish clock-time at the stated cadence.
- **Code in this plan is `ruff format`-clean at line length 100.** Every complete Python module in it was extracted and checked with `ruff format --check` and `ruff check` (E, F, W, I, B, UP, SIM) when the plan was written; fragments that extend an existing file (a CLI command, an import list, a few lines in a function) were checked for line length only. Each lint step runs `ruff format` before `ruff check`; if the formatter still changes something, keep its version: it may differ from the plan's text.
- Worktrees live under `../xilinx-unittests-worktrees/<branch-with-dashes>`. **One PR per branch, always.**

### Branches and PRs

| Branch | Branched from | Worktree | Tasks | PR (base) |
|---|---|---|---|---|
| `infra/hw-harness` | `origin/main` | `infra-hw-harness` | 1–4, 5a, 5b | **PR A** "infra: hw harness — program compiler, reference interpreter, harness RTL and simulation" (base `main`) |
| `infra/hw-vivado` | `infra/hw-harness` | `infra-hw-vivado` | 6–7 | **PR B** "infra: hw Vivado flow — scoped builds, constraints, build IDs, bitstream cache" (base `infra/hw-harness` until A merges, then `main`) |
| `infra/hw-runner` | `infra/hw-vivado` | `infra-hw-runner` | 8, 9a, 9b, 10, 11 | **PR C** "infra: hw runner — rigs, BoardSession, hw runner, doctor, LUT6 smoke" (base `infra/hw-vivado` until B merges, then `main`) |
| `unit/7series/flops` (a fresh branch; the step-2 one has merged) | `origin/main` after A–C merge | `unit-7series-flops` | 12 | **PR D** "flops: hardware pilot" (base `main`) |
| `unit/7series/luts` | `origin/main` after A–C and the luts unit merge | `unit-7series-luts` | 13 (conditional) | **PR E** "luts: hardware pilot" (base `main`) |

- **Merge order** is A → B → C → D (→ E).
- **Stacked PRs.** A child PR's base is its parent branch while the parent's PR is open (`gh pr create --base <parent-branch>`). After the parent merges, only the **orchestrator** rebases the child onto `main`, re-runs its tests, pushes with `git push --force-with-lease` and retargets the PR (`gh pr edit <N> --base main`).
- **Push after every task** (a remote backup of all work): `git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/mithro/xilinx-unittests.git <branch>`.
- **Two review levels**, as in step 2. After each task, a per-task reviewer checks that task's commits and writes a report file; must-fix items are addressed before the next task. When the branch's PR opens, the §13.4 gate runs: two fresh reviewers with the `docs/review/` prompts, posting `gh pr review`.
- **Two-agent limit** (spec §13.5). With one implementer running, reviewers (a) and (b) run **sequentially**.
- **Ownership.** PRs A–C touch only infra paths (`tools/`, `hw/`, `.github/`, `AGENTS.md`, `pyproject.toml`). Nothing in them touches a unit's tests, models, overrides, status files or findings. The pilot branches touch only their unit's paths.

## Review Focus

1. **SRAM only, and the lock.**
   - `PROGRAM_ARGV` is exactly `("openFPGALoader", "-b", "arty")` plus the bitstream; a test refuses every flash option.
   - `hw/pi/xut_work.sh` programs only inside `xut_lock.sh`, and has exactly one `openFPGALoader` programming line.
   - The lock is taken around programming *and* around `reboot()`. The TTL is enforced by `timeout -k 10` on our own holder. Nothing ever deletes or re-creates the lock file; a held lock means `busy` (move to the next rig), and only a verified own holder may be killed.
2. **Correctness by construction** (spec §7.1).
   - The margin is enforced in RTL (`xut_hw_ctrl` `S_WAITM`), not only by the compiler. `xut_hw_tb.sv`'s margin monitor and `xut.hw.interp.margin_violations` both check it.
   - Every constraint in the generated `timing.tcl` goes through `xut_must`, so a constraint that matches no object stops the build (exit 4) instead of silently constraining nothing.
   - Timing must close (`WNS >= 0`, `WHS >= 0`) or the build is an error.
   - The DUT clock latency (flip-flop → BUFG → global net) is measured after routing and must fit the 2 periods the margin leaves (Task 6).
   - The post-flow DUT check (spec §6) confirms every DUT cell's `REF_NAME` and configured attributes after implementation; a mismatch is a `flow-mismatch`, never a DUT result.
   - Every in_vec bit and every DUT clock is driven straight from a harness flip-flop (no logic in between), so nothing glitches, async CLR/PRE included.
3. **Byte-exact reference.** The RTL harness's UART output equals `Harness.feed()` byte for byte on Icarus and on xsim (Task 5a), including the error paths (`noload`, `used`, `badcrc`, `badcmd`). The message ROM is generated from `proto.MESSAGES` and pinned by a test.
4. **No silent skips and no masking** (spec §14, §8).
   - A configuration that is not hardware-renderable is a `skip` whose reason is the validator's `hw_reasons`.
   - A harness self-test failure is an `error` with `hw.selftest = "fail"` (crosscheck: `harness-error`), never a DUT `fail`.
   - Repeats that differ fail the configuration and set `hw.repeats_differ` (crosscheck: `nondeterminism`).
   - A transport error is retried once, never into a pass.
   - An `expected_divergence` never masks a silicon result.
5. **Power-on semantics.** A slot's in_vec INIT is its stimulus's `t0`. A slot runs once per programming, and every repeat reprograms. A `t0` difference is a different slot, so it is part of the bitstream key.
6. **Memory safety.** Every Vivado or xsim run (and `vivado -version`) goes through `scoped_run` with `MemoryMax=16G` inside PR #10's `vivado_slot()`, and never falls back to an unscoped run; `xut hw sim`'s xsim runs are scoped the same way at one cap value. Containers keep the infra's `--memory=4g`. Every command's stated sum stays within the 100G share.

---

## File Structure

```
tools/xut/hw/__init__.py
tools/xut/hw/proto.py            UART protocol: MESSAGES, render/parse, load frames, ROM generator (stdlib)
tools/xut/hw/image.py            program words, ImageBuilder, HwProgram, decode (stdlib)
tools/xut/hw/compile.py          .xvec + DutMap -> HwProgram (t0 vector, order-only rendering)
tools/xut/hw/interp.py           DutSim, run_program, margin_violations, Harness emulator (stdlib)
tools/xut/hw/selftest.py         passthrough + counter channels: sims, programs, expected samples (stdlib)
tools/xut/hw/replay.py           ModelDut (golden model as a DutSim), samples_to_trace, hw_replay
tools/xut/hw/slots.py            SlotBuild, packing, xut_hw_slots.v / xut_hw_cfg.vh / timing.tcl generation
tools/xut/hw/hwsim.py            the harness under Icarus / xsim (5a); `sim_case`, `xut hw sim` (5b)
tools/xut/hw/plan.py             plan_case: a test's configurations compiled, settled or packed (5b)
tools/xut/scope.py               scoped_run (systemd-run --user --scope) (Task 5a); slots come from PR #10's xut.slots
tools/xut/hw/vivado.py           build inputs, build key and ID, batch build, bitstream cache, VivadoBuilder
tools/xut/hw/rigs.py             Rig / RigsConfig from hw/rigs.yaml, ssh_config rendering
tools/xut/hw/session.py          Transport, SshTransport, HwJob, JobResult, BoardSession, SshBoardSession
tools/xut/hw/pool.py             BoardPool, run_job (retry once, self-test, bad boards)
tools/xut/hw/fake.py             FakeTransport, FakeBuilder (tests and `--fake` dry runs)
tools/xut/hw/smoke.py            LUT6 smoke design, Lut6Sim; `xut hw smoke`
tools/xut/runners/hw.py          HwRunner
tools/xut/hdl/hw/xut_hw_top.sv   board top: sysclk BUFG, power-on reset, ctrl + slots
tools/xut/hdl/hw/xut_hw_ctrl.sv  command parser, loader, stimulus BRAM, sequencer
tools/xut/hdl/hw/xut_hw_print.sv message printer (ROM-driven)
tools/xut/hdl/hw/xut_hw_uart_tx.sv, xut_hw_uart_rx.sv
tools/xut/hdl/hw/xut_hw_crc32.vh CRC-32 (zlib) byte step
tools/xut/hdl/hw/xut_hw_msgs.vh  GENERATED message ROM (committed; pinned by a test)
tools/xut/hdl/hw/xut_hw_tb.sv    simulation testbench (UART host model, margin monitor)
tools/xut/schemas/rigs.schema.json
tools/xut/schemas/result.schema.json        (modified: the hw object)
hw/rigs.yaml                     the fpgas.online Welland rigs (no secrets)
hw/boards/arty_a7_35t/board.xdc  pins and the sysclk
hw/pi/xut_lock.sh                rig lock wrapper (flock, owner record, TTL)
hw/pi/xut_work.sh                inside the lock: program (SRAM) + UART session
hw/pi/xut_uart.py                UART session runner (stdlib; runs on the Pi)
hw/README.md                     operators: rigs, the lock, how to reboot under it
tools/tests/test_hw_*.py         tool tests; fixtures under tools/tests/fixtures/hw/
```

Run and cache layout (never committed):

```
build/vivado/hw/unisim-2025.2/<test-id>/{result.json,trace.xtr,run.log}   the hw runner (spec §6 layout)
build/vivado/hw/unisim-2025.2/<test-id>/cfg-<cfg>/{trace.xtr,trace-r<k>.xtr,mismatches.txt,run.log}
build/vivado/hw/unisim-2025.2/<test-id>/jobs/g<g>-r<k>/attempt-<n>/       staged files + fetched results
build/hwsim-runs/<sim>/<model-source>/<test-id>/                                `xut hw sim`
.cache/hw/bit/<key>/{top.bit,manifest.json,build.log,timing.rpt,utilization.rpt,drc.rpt,sources/}
.cache/hw/locks/build-<key>.lock                                       per-key build lock (per worktree)
$XDG_RUNTIME_DIR/xut-vivado/slot{N}.lock                                the host-wide Vivado/xsim slots (PR #10's xut.slots)
.cache/hw/ssh_config, .cache/hw/known_hosts
```

---

## PR A: the harness (branch `infra/hw-harness`)

### Task 1: The harness UART protocol and its message ROM

**Files:**
- Create: `tools/xut/hw/__init__.py`, `tools/xut/hw/proto.py`, `tools/xut/hdl/hw/xut_hw_msgs.vh` (generated), `tools/tests/test_hw_proto.py`
- Modify: `tools/xut/cli.py` (a `hw` group with `gen-rtl`)

**Interfaces:**
- Produces (`xut.hw.proto`, standard library only):
  - `PROTO = 1`; `CMD_ID = b"I"`, `CMD_LOAD = b"L"`, `CMD_RUN = b"R"`
  - `STATUS: dict[int, str]` (`0 ok, 1 used, 2 noload, 3 badop, 4 badslot, 5 badcrc, 6 toolong, 7 badcmd`) and `STATUS_CODE` (the inverse)
  - `FIELDS: dict[str, tuple[int, int]]` (name → ROM token, hex digits; `bits` has 0 digits: it is binary, `max(1, nout)` wide)
  - `MESSAGES: dict[str, str]` (`id`, `load`, `run`, `sample`, `end`, `err`; the order is the ROM's message numbering)
  - `render(name, **values) -> bytes`, `parse(name, line: bytes) -> dict`
  - `IdReply(build, slots, maxwords, margin)`, `LoadReply(slot, words, crc, status)`, `RunReply(build, slot, words, samples, status, crc)` (frozen dataclasses)
  - `load_frame(slot, words) -> bytes`, `parse_id(data) -> IdReply`, `parse_load(data) -> LoadReply`, `parse_run(data) -> RunReply`
  - `rom() -> tuple[list[int], dict[str, int]]`, `render_rom_vh() -> str`
  - `ProtoError(ValueError)`: a malformed, truncated or CRC-failing reply. It is a *transport* error for the host.
- CLI: `xut hw gen-rtl` rewrites `tools/xut/hdl/hw/xut_hw_msgs.vh` from `MESSAGES`.

- [ ] **Step 1: Create the worktree and branch**

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git fetch origin && git worktree add ../xilinx-unittests-worktrees/infra-hw-harness -b infra/hw-harness origin/main
cd ../xilinx-unittests-worktrees/infra-hw-harness
mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
git config core.hooksPath tools/hooks
```

- [ ] **Step 2: Write the failing tests** — `tools/tests/test_hw_proto.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import struct
import zlib
from pathlib import Path

import pytest

from xut.hw import proto
from xut.hw.proto import ProtoError

VH = Path(__file__).resolve().parents[1] / "xut/hdl/hw/xut_hw_msgs.vh"


def test_render_is_fixed_width_lower_hex():
    got = proto.render("id", build=0xDEADBEEF, slots=3, maxwords=8192, margin=16)
    assert got == b"# xut-hw 1 id build=deadbeef slots=03 maxwords=2000 margin=10\n"
    assert proto.render("sample", sidx=10, bits="0101") == b"S 000a 0101\n"


def test_render_refuses_what_the_rtl_cannot_print():
    with pytest.raises(ProtoError, match="does not fit"):
        proto.render("load", slot=256, words=1, crc=0, status=0)
    with pytest.raises(ProtoError, match="0/1"):
        proto.render("sample", sidx=0, bits="01x")


@pytest.mark.parametrize("name", list(proto.MESSAGES))
def test_parse_round_trips_every_message(name):
    values = {f: (1 if f != "bits" else "10") for f in proto.FIELDS}
    fields = set(proto._FIELD.findall(proto.MESSAGES[name]))
    values = {k: v for k, v in values.items() if k in fields}
    assert proto.parse(name, proto.render(name, **values)) == values


def test_load_frame_layout_and_crc():
    f = proto.load_frame(2, [0x12345678, 0xF0000000])
    assert f[:1] == b"L"
    body = f[1:-4]
    assert body == struct.pack("<BHII", 2, 2, 0x12345678, 0xF0000000)
    assert f[-4:] == struct.pack("<I", zlib.crc32(body))


@pytest.mark.parametrize("slot,words", [(256, [0]), (-1, [0]), (0, [])])
def test_load_frame_refuses(slot, words):
    with pytest.raises(ProtoError):
        proto.load_frame(slot, words)


def _run_block(samples, status=0, slot=2, crc_delta=0):
    body = proto.render("run", build=0xABCD0123, slot=slot, words=5)
    body += b"".join(proto.render("sample", sidx=i, bits=b) for i, b in enumerate(samples))
    end = proto.render(
        "end", slot=slot, samples=len(samples), status=status, crc=zlib.crc32(body) ^ crc_delta
    )
    return body + end


def test_parse_run_ok():
    r = proto.parse_run(_run_block(["1", "0"]))
    assert r == proto.RunReply(0xABCD0123, 2, 5, ("1", "0"), 0, r.crc)


def test_parse_run_crc_mismatch_is_a_proto_error():
    with pytest.raises(ProtoError, match="CRC"):
        proto.parse_run(_run_block(["1"], crc_delta=1))


def test_parse_run_refuses_truncation_reordering_and_err_lines():
    good = _run_block(["1", "0"])
    with pytest.raises(ProtoError, match="truncated"):
        proto.parse_run(good[:-1])
    swapped = good.replace(b"S 0000 1\nS 0001 0\n", b"S 0001 0\nS 0000 1\n")
    with pytest.raises(ProtoError, match="sample"):
        proto.parse_run(swapped)
    with pytest.raises(ProtoError):
        proto.parse_run(proto.render("err", cmd=0x5A, status=7))


def test_rom_expands_back_to_the_templates():
    data, start = proto.rom()
    assert len(data) <= 512  # the printer's 9-bit ROM address
    tok = {t: n for n, (t, _) in proto.FIELDS.items()}
    for name, tpl in proto.MESSAGES.items():
        a, text = start[name], ""
        while data[a]:
            text += f"{{{tok[data[a]]}}}" if data[a] & 0x80 else chr(data[a])
            a += 1
        assert text == tpl


def test_committed_rom_is_current():
    assert VH.read_text() == proto.render_rom_vh(), "run: uv run xut hw gen-rtl"
```

Run `uv run pytest tools/tests/test_hw_proto.py > .cache/pytest.log 2>&1; cat .cache/pytest.log`. Expected: collection fails (`No module named 'xut.hw'`).

- [ ] **Step 3: Implement `tools/xut/hw/__init__.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The hardware harness (spec §7): program images, the reference interpreter, the
harness RTL generators, the Vivado flow and board access."""
```

- [ ] **Step 4: Implement `tools/xut/hw/proto.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The stepped harness's UART protocol (spec §7.1 "UART dumper"). Standard library only:
the host (xut.hw.session), the reference emulator (xut.hw.interp) and the generator of
the harness's message ROM (``tools/xut/hdl/hw/xut_hw_msgs.vh``) all use this module.

Host -> harness, raw bytes::

    "I"                                    identify
    "L" slot:u8 nwords:u16le word:u32le*nwords crc:u32le
                                           load one slot's program; crc = zlib.crc32 of
                                           the bytes from slot through the last word
    "R"                                    run the loaded program on the loaded slot

Harness -> host: ASCII lines ending in "\\n" (``MESSAGES``); every number is fixed-width
lower-case hex. A run answers with a ``run`` line, one ``sample`` line per SAMPLE and an
``end`` line whose ``crc`` is zlib.crc32 of every byte from the ``run`` line's ``#``
through the ``\\n`` before the ``end`` line. The harness streams raw samples (``S <n>
<out_vec bits>``), not ``.xtr``: port names live in the wrapper's map, which the host
applies (``xut.hw.replay.samples_to_trace``).

The same templates generate the harness's message ROM (``render_rom_vh``), so the host
parser, the emulator and the RTL cannot drift apart.
"""

from __future__ import annotations

import re
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass

PROTO = 1
CMD_ID, CMD_LOAD, CMD_RUN = b"I", b"L", b"R"

STATUS = {
    0: "ok",
    1: "used",  # the slot already ran since the FPGA was configured
    2: "noload",  # R without a successful L
    3: "badop",  # an unknown opcode, or the program ran past its last word
    4: "badslot",  # L named a slot the bitstream does not have
    5: "badcrc",  # L's CRC did not match the bytes received
    6: "toolong",  # L with 0 words or more than the harness's maxwords
    7: "badcmd",  # an unknown command byte
}
STATUS_CODE = {v: k for k, v in STATUS.items()}

#: field -> (ROM token, hex digits). ``bits`` is binary: max(1, nout) chars of 0/1.
FIELDS: dict[str, tuple[int, int]] = {
    "build": (0x81, 8),
    "slots": (0x82, 2),
    "maxwords": (0x83, 4),
    "margin": (0x84, 2),
    "slot": (0x85, 2),
    "words": (0x86, 4),
    "crc": (0x87, 8),
    "status": (0x88, 2),
    "samples": (0x89, 4),
    "sidx": (0x8A, 4),
    "bits": (0x8B, 0),
    "cmd": (0x8C, 2),
}
#: message -> template. The dict order is the ROM's message numbering (XUT_MSG_*).
MESSAGES: dict[str, str] = {
    "id": "# xut-hw 1 id build={build} slots={slots} maxwords={maxwords} margin={margin}\n",
    "load": "# xut-hw 1 load slot={slot} words={words} crc={crc} status={status}\n",
    "run": "# xut-hw 1 run build={build} slot={slot} words={words}\n",
    "sample": "S {sidx} {bits}\n",
    "end": "# xut-hw 1 end slot={slot} samples={samples} status={status} crc={crc}\n",
    "err": "# xut-hw 1 err cmd={cmd} status={status}\n",
}
_FIELD = re.compile(r"\{(\w+)\}")
ROM_SIZE = 512  # the printer's 9-bit ROM address


class ProtoError(ValueError):
    """A reply that is malformed, truncated or fails its CRC. For the host this is a
    transport error (retried once, spec §7.5)."""


def render(name: str, **values: int | str) -> bytes:
    """Message ``name`` exactly as the RTL prints it."""

    def sub(m: re.Match[str]) -> str:
        f = m.group(1)
        if f == "bits":
            bits = str(values["bits"])
            if not bits or set(bits) - {"0", "1"}:
                raise ProtoError(f"bits {bits!r} must be one or more 0/1")
            return bits
        digits = FIELDS[f][1]
        v = int(values[f])
        if not 0 <= v < 16**digits:
            raise ProtoError(f"{f}={v} does not fit {digits} hex digits")
        return f"{v:0{digits}x}"

    return _FIELD.sub(sub, MESSAGES[name]).encode("ascii")


def _pattern(name: str) -> re.Pattern[str]:
    tpl, out, pos = MESSAGES[name], [], 0
    for m in _FIELD.finditer(tpl):
        out.append(re.escape(tpl[pos : m.start()]))
        f = m.group(1)
        out.append(f"(?P<{f}>[01]+)" if f == "bits" else f"(?P<{f}>[0-9a-f]{{{FIELDS[f][1]}}})")
        pos = m.end()
    out.append(re.escape(tpl[pos:]))
    return re.compile("".join(out))


PATTERNS = {n: _pattern(n) for n in MESSAGES}


def parse(name: str, line: bytes) -> dict[str, int | str]:
    """The fields of one ``name`` line (with its ``\\n``); hex fields as ints."""
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError as e:
        raise ProtoError(f"expected a {name} line, got non-ASCII bytes {line[:60]!r}") from e
    m = PATTERNS[name].fullmatch(text)
    if not m:
        raise ProtoError(f"expected a {name} line, got {text[:120]!r}")
    return {k: (v if k == "bits" else int(v, 16)) for k, v in m.groupdict().items()}


@dataclass(frozen=True)
class IdReply:
    build: int
    slots: int
    maxwords: int
    margin: int


@dataclass(frozen=True)
class LoadReply:
    slot: int
    words: int
    crc: int
    status: int


@dataclass(frozen=True)
class RunReply:
    build: int
    slot: int
    words: int
    samples: tuple[str, ...]
    status: int
    crc: int


def load_frame(slot: int, words: Sequence[int]) -> bytes:
    """The ``L`` command for ``words`` into ``slot``."""
    if not 0 <= slot < 256:
        raise ProtoError(f"slot {slot} is not 0..255")
    if not 0 < len(words) < 1 << 16:
        raise ProtoError(f"{len(words)} words: a load carries 1..65535")
    if any(not 0 <= w < 1 << 32 for w in words):
        raise ProtoError("a program word is not 32 bits")
    body = struct.pack("<BH", slot, len(words)) + b"".join(struct.pack("<I", w) for w in words)
    return CMD_LOAD + body + struct.pack("<I", zlib.crc32(body))


def _lines(data: bytes) -> list[bytes]:
    if not data.endswith(b"\n"):
        raise ProtoError(f"truncated reply (no final newline): {data[-60:]!r}")
    return [ln + b"\n" for ln in data[:-1].split(b"\n")]


def parse_id(data: bytes) -> IdReply:
    (line,) = _one(data)
    return IdReply(**parse("id", line))  # type: ignore[arg-type]


def parse_load(data: bytes) -> LoadReply:
    (line,) = _one(data)
    return LoadReply(**parse("load", line))  # type: ignore[arg-type]


def _one(data: bytes) -> list[bytes]:
    lines = _lines(data)
    if len(lines) != 1:
        raise ProtoError(f"expected one line, got {len(lines)}: {data[:120]!r}")
    return lines


def parse_run(data: bytes) -> RunReply:
    """A whole ``R`` reply: header, samples in order, end line with a matching CRC."""
    lines = _lines(data)
    if len(lines) < 2:
        raise ProtoError(f"run reply has {len(lines)} line(s): {data[:120]!r}")
    head, end = parse("run", lines[0]), parse("end", lines[-1])
    samples = []
    for i, ln in enumerate(lines[1:-1]):
        s = parse("sample", ln)
        if s["sidx"] != i:
            raise ProtoError(f"sample {s['sidx']} out of order (expected {i})")
        samples.append(str(s["bits"]))
    calc = zlib.crc32(b"".join(lines[:-1]))
    if calc != end["crc"]:
        raise ProtoError(f"run CRC {end['crc']:08x} does not match the bytes ({calc:08x})")
    if end["samples"] != len(samples) or end["slot"] != head["slot"]:
        raise ProtoError(f"end line {end} does not match the {len(samples)} samples received")
    return RunReply(
        int(head["build"]),
        int(head["slot"]),
        int(head["words"]),
        tuple(samples),
        int(end["status"]),
        int(end["crc"]),
    )


def rom() -> tuple[list[int], dict[str, int]]:
    """The message ROM: each template as ASCII bytes with a field's token in place of
    the field, ended by 0x00; plus each message's start address."""
    data: list[int] = []
    start: dict[str, int] = {}
    for name, tpl in MESSAGES.items():
        start[name] = len(data)
        pos = 0
        for m in _FIELD.finditer(tpl):
            data += list(tpl[pos : m.start()].encode("ascii"))
            data.append(FIELDS[m.group(1)][0])
            pos = m.end()
        data += [*tpl[pos:].encode("ascii"), 0]
    if len(data) > ROM_SIZE:
        raise ProtoError(f"message ROM is {len(data)} bytes; the printer addresses {ROM_SIZE}")
    return data, start


def render_rom_vh() -> str:
    """``xut_hw_msgs.vh``: message numbers, field tokens, field widths and the ROM, as
    localparams and functions for inclusion inside a module."""
    data, start = rom()
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// GENERATED by `uv run xut hw gen-rtl` from xut.hw.proto.MESSAGES. Do not edit.",
        f"// Message ROM: {len(data)} bytes.",
    ]
    for i, name in enumerate(MESSAGES):
        out.append(f"localparam [2:0] XUT_MSG_{name.upper()} = 3'd{i};")
    for name, (tok, _) in FIELDS.items():
        out.append(f"localparam [3:0] XUT_F_{name.upper()} = 4'h{tok & 0xF:x};")
    out += ["function [8:0] xut_hw_msg_start(input [2:0] msg);", "  case (msg)"]
    out += [f"    3'd{i}: xut_hw_msg_start = 9'd{start[n]};" for i, n in enumerate(MESSAGES)]
    out += ["    default: xut_hw_msg_start = 9'd0;", "  endcase", "endfunction"]
    out += [
        "function [15:0] xut_hw_field_digits(input [3:0] f, input [15:0] nbits);",
        "  case (f)",
    ]
    for name, (tok, digits) in FIELDS.items():
        value = "nbits" if name == "bits" else f"16'd{digits}"
        out.append(f"    4'h{tok & 0xF:x}: xut_hw_field_digits = {value};")
    out += ["    default: xut_hw_field_digits = 16'd1;", "  endcase", "endfunction"]
    out += ["function [7:0] xut_hw_msg_rom(input [8:0] a);", "  case (a)"]
    out += [f"    9'd{a}: xut_hw_msg_rom = 8'h{b:02x};" for a, b in enumerate(data)]
    out += ["    default: xut_hw_msg_rom = 8'h00;", "  endcase", "endfunction"]
    return "\n".join(out) + "\n"
```

- [ ] **Step 5: Add `xut hw gen-rtl`** to `tools/xut/cli.py` (after the `vec` group):

```python
@main.group("hw")
def hw_grp() -> None:
    """The hardware harness (spec §7)."""


@hw_grp.command("gen-rtl")
def hw_gen_rtl_cmd() -> None:
    """Regenerate tools/xut/hdl/hw/xut_hw_msgs.vh from xut.hw.proto.MESSAGES."""
    from xut.hw.proto import render_rom_vh

    out = Path(__file__).resolve().parent / "hdl" / "hw" / "xut_hw_msgs.vh"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_rom_vh())
    click.echo(f"wrote {out}")
```

- [ ] **Step 6: Generate the ROM and run the tests**

```bash
uv run xut hw gen-rtl > .cache/gen-rtl.log 2>&1; cat .cache/gen-rtl.log
uv run pytest tools/tests/test_hw_proto.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
```

Expected: `wrote .../xut_hw_msgs.vh`; every test passes; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add tools/xut/hw tools/xut/hdl/hw/xut_hw_msgs.vh tools/xut/cli.py tools/tests/test_hw_proto.py
git commit -m "hw: harness UART protocol, message templates and generated message ROM" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The stimulus compiler — `.xvec` → harness program image

**Files:**
- Create: `tools/xut/hw/image.py`, `tools/xut/hw/compile.py`, `tools/tests/test_hw_image.py`, `tools/tests/test_hw_compile.py`
- Modify: `tools/xut/stimcompile.py` (`_check_fits` becomes the public `check_fits`; the old name stays as an alias for one release)

**Interfaces:**
- Produces (`xut.hw.image`, standard library only):
  - opcodes `OP_SET=0x1, OP_COMMIT=0x2, OP_EDGE=0x3, OP_WAIT=0x4, OP_SAMPLE=0x5, OP_END=0xF`; `CHUNK=16`, `MAX_CHUNKS=4096`, `MAX_CLOCKS=4096`, `MAX_WAIT=2**28-1`; the harness defaults `MAXWORDS=8192`, `MARGIN=16`
  - `width(n) -> int` (`max(1, n)`: the wrapper's vector width), `chunks(bits) -> list[int]`
  - `w_set(chunk, data)`, `w_commit()`, `w_edge(idx, level)`, `w_wait(n)`, `W_SAMPLE`, `W_END`, `decode(word) -> tuple[int, int, int]`
  - `HwProgram(nin, nclk, noutw, t0, words, labels)` (frozen)
  - `ImageBuilder(nin, nclk, noutw, t0)` with `set_bits(bits)`, `edge(idx, level)`, `wait(n)`, `sample(label)`, `end(maxwords=MAXWORDS) -> HwProgram`
  - `HwImageError(ValueError)`
- Produces (`xut.hw.compile`): `t0_bits(vec, m) -> str`, `compile_program(vec, m, maxwords=MAXWORDS) -> HwProgram`, `HwCompileError` (an invalid stimulus), `HwUnrenderable` (not hardware-renderable; its message is the reason)
- Consumes: `xut.stimcompile.check_fits`, `xut.validate.validate`, `xut.formats.xvec`, `xut.wrap.DutMap`

Word format (one 32-bit word per operation, op in `[31:28]`):

| op | fields | action |
|---|---|---|
| `SET` 0x1 | `[27:16]` chunk c, `[15:0]` data | `in_nxt[16c+15:16c] = data` |
| `COMMIT` 0x2 | — | the selected slot's in_vec takes `in_nxt` in one clock; then `MARGIN` cycles |
| `EDGE` 0x3 | `[12]` level, `[11:0]` clock i | the slot's clock flip-flop i takes `level`; then `MARGIN` cycles |
| `WAIT` 0x4 | `[27:0]` n | n + 1 more cycles |
| `SAMPLE` 0x5 | — | capture out_vec, print `S <n> <bits>` |
| `END` 0xF | — | finish with status `ok` |

- [ ] **Step 1: Write the failing tests.** `tools/tests/test_hw_image.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.hw import image
from xut.hw.image import HwImageError, ImageBuilder


def test_chunks_lsb_first():
    bits = "1" + "0" * 15 + "0000000000000011"  # 32 bits: bit 31 and bits 1:0
    assert image.chunks(bits) == [0x0003, 0x8000]
    assert image.chunks("101") == [0b101]


def test_word_encoding_round_trips():
    assert image.decode(image.w_set(3, 0xBEEF)) == (image.OP_SET, 3, 0xBEEF)
    assert image.decode(image.w_edge(7, 1)) == (image.OP_EDGE, 7, 1)
    assert image.decode(image.w_wait(1000)) == (image.OP_WAIT, 1000, 0)
    assert image.decode(image.W_SAMPLE) == (image.OP_SAMPLE, 0, 0)
    assert image.decode(image.W_END) == (image.OP_END, 0, 0)


def test_set_bits_writes_only_changed_chunks_then_commits():
    b = ImageBuilder(20, 1, 1, "0" * 20)
    b.set_bits("0" * 20)  # no change: no words
    b.set_bits("1" + "0" * 19)  # bit 19 = chunk 1, bit 3
    p = b.end()
    assert p.words == (image.w_set(1, 0x8), image.w_commit(), image.W_END)


def test_edges_samples_and_labels():
    b = ImageBuilder(1, 2, 1, "0")
    b.edge(1, 1)
    b.sample("a")
    b.edge(1, 0)
    b.sample("b")
    p = b.end()
    assert p.labels == ("a", "b")
    assert p.words == (
        image.w_edge(1, 1),
        image.W_SAMPLE,
        image.w_edge(1, 0),
        image.W_SAMPLE,
        image.W_END,
    )


@pytest.mark.parametrize(
    "call,match",
    [
        (lambda b: b.edge(2, 1), "clock 2"),
        (lambda b: b.set_bits("01"), "1 char"),
        (lambda b: b.set_bits("x"), "0/1"),
        (lambda b: b.wait(image.MAX_WAIT + 1), "WAIT"),
    ],
)
def test_builder_refuses(call, match):
    b = ImageBuilder(1, 2, 1, "0")
    with pytest.raises(HwImageError, match=match):
        call(b)


def test_capacity():
    b = ImageBuilder(1, 1, 1, "0")
    for _ in range(10):
        b.sample(f"s{_}")
    with pytest.raises(HwImageError, match="11 words"):
        b.end(maxwords=10)
```

`tools/tests/test_hw_compile.py` uses a two-input toy map and the step-2 `VecBuilder`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.hw import image
from xut.hw.compile import HwUnrenderable, compile_program, t0_bits
from xut.stimgen import VecBuilder
from xut.wrap import Bit, DutMap


def _map(nin=2, clk=True, cls="data") -> DutMap:
    bits = [Bit("in", 0, "D", 0, "data"), Bit("in", 1, "R", 0, cls), Bit("out", 0, "Q", 0, "data")]
    if clk:
        bits.insert(0, Bit("clk", 0, "C", 0, "clock"))
    return DutMap("TOYFF", "7series", "c0", {}, int(clk), nin, 1, bits)


def test_t0_is_the_initialisation_and_order_is_kept():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.init(R=1)
    b.set(D=1)
    b.cycle("C")  # rise, sample, fall
    b.set(D=0, R=0)
    b.sample("s2")
    vec = b.build()
    assert t0_bits(vec, m) == "10"  # R=1 (bit 1), D=0
    p = compile_program(vec, m)
    assert p.t0 == "10"
    ops = [image.decode(w)[0] for w in p.words]
    assert ops[:2] == [image.OP_SET, image.OP_COMMIT]  # D=1
    assert image.OP_EDGE in ops and ops[-1] == image.OP_END
    assert list(p.labels) == [e.target for e in vec.events if e.op == "sample"]


def test_co_timed_disjoint_sets_are_one_commit():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.set(D=1, R=1)
    b.sample("s")
    p = compile_program(b.build(), m)
    assert [image.decode(w)[0] for w in p.words].count(image.OP_COMMIT) == 1


def test_unrenderable_reasons_are_the_validators():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.set(D="x")
    b.sample("s")
    with pytest.raises(HwUnrenderable, match="x/z"):
        compile_program(b.build(), m)


def test_glbl_is_unrenderable():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.glbl("GSR", 1)
    b.glbl("GSR", 0)
    b.sample("s")
    with pytest.raises(HwUnrenderable, match="GSR"):
        compile_program(b.build(), m)


def test_expect_reject_is_unrenderable():
    m = _map()
    b = VecBuilder(m, seed=1, expect="reject", illegal=["INIT"])
    b.sample("s")
    with pytest.raises(HwUnrenderable, match="reject"):
        compile_program(b.build(), m)
```

(The validator's GSR reason reads "glbl GSR on hardware needs the GSR-immune harness (spec §7.2; step 3)". If the merged wording differs, match it: the test pins that the validator's reason reaches `HwUnrenderable`, and that a `glbl` event never compiles.)

Run both files; expected: `No module named 'xut.hw.image'`.

- [ ] **Step 2: Make `check_fits` public.** In `tools/xut/stimcompile.py`, rename `_check_fits` to `check_fits`, update its callers in the module, and add `_check_fits = check_fits  # step-2 name; remove in step 4`. Its docstring: "Structure, sizes, primitive/configuration and `validate` errors (ruling S11): the checks every compiler of an `.xvec` applies."

- [ ] **Step 3: Implement `tools/xut/hw/image.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Harness program images (spec §7.1): the operation words the stepped harness's
sequencer executes from its stimulus BRAM. Standard library only.

One 32-bit word per operation, op in [31:28]::

    0x1 SET     [27:16] chunk c, [15:0] data   in_nxt[16c+15:16c] = data
    0x2 COMMIT                                 the slot's in_vec = in_nxt; then MARGIN cycles
    0x3 EDGE    [12] level, [11:0] clock i     the slot's clock i = level; then MARGIN cycles
    0x4 WAIT    [27:0] n                       n + 1 more cycles
    0x5 SAMPLE                                 print "S <n> <out_vec>" (n counts from 0)
    0xF END

The harness, not the program, holds MARGIN system cycles after every COMMIT and EDGE:
an in_vec change, the next DUT clock edge and the next capture are always at least
MARGIN cycles apart, whatever the program says (correctness by construction). A slot's
in_vec powers up as its program's ``t0`` (the harness flip-flops' INIT, baked into the
bitstream), and its clocks power up low.
"""

from __future__ import annotations

from dataclasses import dataclass

OP_SET, OP_COMMIT, OP_EDGE, OP_WAIT, OP_SAMPLE, OP_END = 0x1, 0x2, 0x3, 0x4, 0x5, 0xF
OP_NAMES = {
    OP_SET: "SET",
    OP_COMMIT: "COMMIT",
    OP_EDGE: "EDGE",
    OP_WAIT: "WAIT",
    OP_SAMPLE: "SAMPLE",
    OP_END: "END",
}
CHUNK = 16
MAX_CHUNKS = 1 << 12
MAX_CLOCKS = 1 << 12
MAX_WAIT = (1 << 28) - 1
#: The harness's defaults (xut_hw_ctrl parameters). A bitstream reports its own in `I`.
MAXWORDS = 8192
MARGIN = 16


class HwImageError(ValueError):
    """An operation the harness cannot express, or a program too long for it."""


def width(n: int) -> int:
    """A wrapper vector's width: ``max(1, n)`` (spec §5.2 wrappers never have 0 bits)."""
    return max(1, n)


def chunks(bits: str) -> list[int]:
    """MSB-first ``bits`` as 16-bit chunks, chunk 0 = bits[15:0]."""
    lsb = bits[::-1]
    return [int(lsb[i : i + CHUNK][::-1], 2) for i in range(0, len(lsb), CHUNK)]


def w_set(chunk: int, data: int) -> int:
    if not (0 <= chunk < MAX_CHUNKS and 0 <= data < 1 << CHUNK):
        raise HwImageError(f"SET chunk={chunk} data={data:#x} does not fit")
    return (OP_SET << 28) | (chunk << 16) | data


def w_commit() -> int:
    return OP_COMMIT << 28


def w_edge(idx: int, level: int) -> int:
    if not (0 <= idx < MAX_CLOCKS and level in (0, 1)):
        raise HwImageError(f"EDGE clock={idx} level={level} does not fit")
    return (OP_EDGE << 28) | (level << 12) | idx


def w_wait(n: int) -> int:
    if not 0 <= n <= MAX_WAIT:
        raise HwImageError(f"WAIT {n} does not fit 28 bits")
    return (OP_WAIT << 28) | n


W_SAMPLE = OP_SAMPLE << 28
W_END = OP_END << 28


def decode(w: int) -> tuple[int, int, int]:
    """``(op, a, b)``: SET (chunk, data), EDGE (clock, level), WAIT (n, 0), else (0, 0)."""
    op = (w >> 28) & 0xF
    if op == OP_SET:
        return op, (w >> 16) & 0xFFF, w & 0xFFFF
    if op == OP_EDGE:
        return op, w & 0xFFF, (w >> 12) & 1
    if op == OP_WAIT:
        return op, w & MAX_WAIT, 0
    return op, 0, 0


@dataclass(frozen=True)
class HwProgram:
    nin: int
    nclk: int
    noutw: int  # max(1, nout): the width of every sample
    t0: str  # MSB-first width(nin) chars of 0/1: the slot's power-on in_vec
    words: tuple[int, ...]
    labels: tuple[str, ...]  # sample labels, in sample order


def _check_bits(bits: str, n: int, what: str) -> None:
    if len(bits) != n:
        raise HwImageError(f"{what} {bits!r} is not {n} char(s)")
    if set(bits) - {"0", "1"}:
        raise HwImageError(f"{what} {bits!r} must be 0/1 (the harness is 2-state)")


class ImageBuilder:
    """Builds one slot's program. ``set_bits`` takes the whole next in_vec (MSB first)
    and emits a SET per changed chunk plus one COMMIT: one atomic input change."""

    def __init__(self, nin: int, nclk: int, noutw: int, t0: str) -> None:
        self.nin, self.nclk, self.noutw = nin, nclk, noutw
        w = width(nin)
        _check_bits(t0, w, "t0")
        if (w + CHUNK - 1) // CHUNK > MAX_CHUNKS or nclk > MAX_CLOCKS:
            raise HwImageError(f"nin={nin} nclk={nclk} exceed the harness's operand fields")
        self.t0 = t0
        self._cur = t0
        self._words: list[int] = []
        self._labels: list[str] = []

    def set_bits(self, bits: str) -> None:
        _check_bits(bits, width(self.nin), "in_vec")
        old, new = chunks(self._cur), chunks(bits)
        changed = [i for i, (a, b) in enumerate(zip(old, new, strict=True)) if a != b]
        if not changed:
            return
        self._words += [w_set(i, new[i]) for i in changed] + [w_commit()]
        self._cur = bits

    def edge(self, idx: int, level: int) -> None:
        if not 0 <= idx < self.nclk:
            raise HwImageError(f"clock {idx} out of range (nclk={self.nclk})")
        self._words.append(w_edge(idx, level))

    def wait(self, n: int) -> None:
        self._words.append(w_wait(n))

    def sample(self, label: str) -> None:
        self._words.append(W_SAMPLE)
        self._labels.append(label)

    def end(self, maxwords: int = MAXWORDS) -> HwProgram:
        words = [*self._words, W_END]
        if len(words) > maxwords:
            raise HwImageError(f"{len(words)} words > the harness's maxwords={maxwords}")
        return HwProgram(
            self.nin, self.nclk, self.noutw, self.t0, tuple(words), tuple(self._labels)
        )
```

- [ ] **Step 4: Implement `tools/xut/hw/compile.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Compile an .xvec into a harness program (spec §7.1).

Only a hardware-renderable stimulus compiles (spec §5.1, ruling S8'): no free-running
clock, no glbl event, no pad/inout port, no x/z, no ``simultaneous`` group, and at least
max(async_sep_ps, min_event_gap_ps) between distinct event times. ``validate`` decides;
its ``hw_reasons`` become the ``HwUnrenderable`` message, which the hw runner records as
the configuration's skip reason.

The stepped harness renders the ORDER of events, so times are dropped:

- the ``t=0 set`` lines are the slot's power-on in_vec (``t0``). The bitstream bakes it
  into the harness flip-flops' INIT, so the DUT already sees it during the configuration
  start-up (GSR), as it does while glbl holds GSR in simulation;
- each later time step becomes, in file order, its ``set``s as one COMMIT (co-timed
  disjoint sets are one atomic change, ruling S6), then its edges, then its samples. The
  validator makes an edge or a sample lonely at its time, so a step never mixes kinds;
- ``end`` (or the end of the file) becomes END.
"""

from __future__ import annotations

from itertools import groupby

from xut.errors import XutError
from xut.formats.xvec import Vec
from xut.hw.image import MAXWORDS, HwImageError, HwProgram, ImageBuilder, width
from xut.stimcompile import StimCompileError, check_fits
from xut.validate import validate
from xut.wrap import DutMap

REJECT_REASON = (
    "an expect=reject configuration checks the simulation model's attribute check; "
    "a bitstream has no such check"
)


class HwCompileError(XutError, ValueError):
    """An invalid stimulus (structure, sizes or class rules): never compiled."""


class HwUnrenderable(XutError, ValueError):
    """A valid stimulus the stepped harness cannot render; the message is the reason."""


def t0_bits(vec: Vec, m: DutMap) -> str:
    """The in_vec before ``settle_ps`` (0 plus the ``t=0 set`` lines), MSB first."""
    bits = ["0"] * width(m.nin)
    for e in vec.events:
        if e.t >= vec.settle_ps:
            break
        for i, ch in enumerate(reversed(e.value)):  # check_structure: only t=0 sets here
            bits[e.lsb + i] = ch
    return "".join(reversed(bits))


def compile_program(vec: Vec, m: DutMap, maxwords: int = MAXWORDS) -> HwProgram:
    if vec.expect == "reject":  # first: whatever else is wrong, it never reaches hardware
        raise HwUnrenderable(REJECT_REASON)
    try:
        check_fits(vec, m)
    except StimCompileError as e:
        raise HwCompileError(str(e)) from e
    report = validate(vec, m)
    if report.hw_reasons:
        raise HwUnrenderable("; ".join(report.hw_reasons))
    t0 = t0_bits(vec, m)
    b = ImageBuilder(m.nin, m.nclk, width(m.nout), t0)
    bits = list(reversed(t0))  # bits[i] = in_vec[i]
    body = [e for e in vec.events if e.t >= vec.settle_ps]
    for _t, group in groupby(body, key=lambda e: e.t):
        events = list(group)
        sets = [e for e in events if e.op == "set"]
        for e in sets:
            for i, ch in enumerate(reversed(e.value)):
                bits[e.lsb + i] = ch
        if sets:
            b.set_bits("".join(reversed(bits)))
        for e in events:
            if e.op == "set":
                continue
            if e.op == "edge":
                b.edge(vec.clock(e.target).index, 1 if e.value == "r" else 0)
            elif e.op == "sample":
                b.sample(e.target)
            elif e.op != "end":  # validate already refuses these; stay loud regardless
                raise HwUnrenderable(f"t={e.t}: {e.op} has no stepped-harness rendering")
    try:
        return b.end(maxwords)
    except HwImageError as e:
        raise HwUnrenderable(f"harness capacity: {e}") from e
```

- [ ] **Step 5: Run the tests, lint and commit**

```bash
uv run pytest tools/tests/test_hw_image.py tools/tests/test_hw_compile.py tools/tests/test_stimcompile.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/hw/image.py tools/xut/hw/compile.py tools/xut/stimcompile.py tools/tests/test_hw_image.py tools/tests/test_hw_compile.py
git commit -m "hw: compile .xvec stimuli into harness program images (order-only rendering, t0 power-on vector)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: all pass (the step-2 `test_stimcompile.py` still passes after the rename).

---

### Task 3: The reference interpreter, the harness emulator and the self-test channels

**Files:**
- Create: `tools/xut/hw/interp.py`, `tools/xut/hw/selftest.py`, `tools/xut/hw/replay.py`, `tools/tests/hw_toy.py`, `tools/tests/fixtures/hw/TOYFF.v`, `tools/tests/test_hw_interp.py`, `tools/tests/test_hw_selftest.py`, `tools/tests/test_hw_replay.py`
- Modify: `tools/xut/stimcompile.py` (`out_port_bits`, `port_values`: the one out_vec → port grouping, shared by `raw_to_trace` and `samples_to_trace`)

**Interfaces:**
- Produces (`xut.hw.interp`, standard library only):
  - `DutSim` (Protocol): `reset(t0: str)`, `drive(in_bits: str, clk_bits: str)`, `out_bits() -> str`. Bits are MSB-first strings; `clk_bits` is `"0"` for a slot without clocks.
  - `CycleEvent(cycle, kind, detail)` with `kind` one of `commit | edge | sample`
  - `RunOutcome(samples: list[str], status: int, events: list[CycleEvent], cycles: int)`
  - `run_program(words, nin, nclk, dut, t0, *, margin=MARGIN, max_cycles=2**40) -> RunOutcome`
  - `margin_violations(events, margin=MARGIN) -> list[str]`
  - `EmuSlot(nin, nout, nclk, t0, dut)`, `Harness(build_id, slots, *, margin=MARGIN, maxwords=MAXWORDS)` with `feed(data: bytes) -> bytes`
- Produces (`xut.hw.selftest`, standard library only): `PASS_SLOT = 0`, `COUNT_SLOT = 1`, `PassthroughSim`, `CounterSim`, `passthrough_program()`, `counter_program()`, `selftest_programs() -> dict[int, HwProgram]`, `selftest_sims() -> dict[int, DutSim]`, `expected_samples(slot) -> list[str]`, `check(slot, reply) -> str | None`
- Produces (`xut.hw.replay`): `ModelDut(model_cls, attrs, m)` (a golden model as a `DutSim`), `samples_to_trace(samples, labels, m, header, kind="actual") -> Trace`, `hw_replay(model_cls, vec, m) -> Trace`

The cycle model mirrors `xut_hw_ctrl` (Task 4): FETCH and DECODE take one cycle each per word; `COMMIT` and `EDGE` then hold `MARGIN + 1` cycles (`S_WAITM` counts `MARGIN` down to 0); `WAIT n` holds `n + 1`; `SAMPLE` captures in DECODE. The printing time is not modelled, because the DUT is static while the harness prints. The emulator's replies must equal the RTL's byte for byte (Task 5 pins it).

- [ ] **Step 1: The toy fixture.** `tools/tests/fixtures/hw/TOYFF.v`:

```verilog
// SPDX-License-Identifier: Apache-2.0
// Toy D flip-flop for the harness tests (tools/tests only; not a UNISIM model):
// Q powers up as INIT and takes D 100 ps after a rising C.
`timescale 1ps / 1ps
module TOYFF #(parameter [0:0] INIT = 1'b0) (output reg Q, input wire C, input wire D);
  initial Q = INIT;
  always @(posedge C) Q <= #100 D;
endmodule
```

`tools/tests/hw_toy.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A toy flip-flop for the hardware tests: fixtures/hw/TOYFF.v, with the step-2 toy's
catalog entry (``TOY_ENTRY``) and golden model (``ToyDff``): one definition of each."""

from pathlib import Path

from test_golden import ToyDff
from test_runner_base import TOY_ENTRY as TOY_HW_ENTRY

from xut.wrap import DutMap, DutSpec, build_map, spec_from_catalog

__all__ = ["TOYFF_V", "TOY_HW_ENTRY", "ToyDff", "toy_map", "toy_spec"]

FIX = Path(__file__).parent / "fixtures" / "hw"
TOYFF_V = FIX / "TOYFF.v"


def toy_spec(cfg: str, init: int) -> DutSpec:
    return spec_from_catalog(TOY_HW_ENTRY, cfg, {"INIT": f"1'b{init}"})


def toy_map(cfg: str, init: int) -> DutMap:
    return build_map(toy_spec(cfg, init))
```

- [ ] **Step 2: Write the failing tests.** `tools/tests/test_hw_interp.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import zlib

from xut.hw import image, proto
from xut.hw.image import ImageBuilder
from xut.hw.interp import EmuSlot, Harness, margin_violations, run_program
from xut.hw.selftest import PassthroughSim


class Recorder:
    def __init__(self):
        self.log = []

    def reset(self, t0):
        self.v = t0

    def drive(self, in_bits, clk_bits):
        self.log.append((in_bits, clk_bits))
        self.v = in_bits

    def out_bits(self):
        return self.v[-1:]


def _prog():
    b = ImageBuilder(2, 1, 1, "00")
    b.set_bits("01")
    b.edge(0, 1)
    b.sample("a")
    b.edge(0, 0)
    b.wait(5)
    b.sample("b")
    return b.end()


def test_run_program_drives_one_change_at_a_time_and_keeps_margins():
    p, r = _prog(), Recorder()
    r.reset(p.t0)
    out = run_program(p.words, p.nin, p.nclk, r, p.t0, margin=16)
    assert out.status == 0 and out.samples == ["1", "1"]
    assert r.log == [("01", "0"), ("01", "1"), ("01", "0")]
    assert margin_violations(out.events, 16) == []
    # SET, COMMIT(+17), EDGE(+17), SAMPLE, EDGE(+17), WAIT 5(+6), SAMPLE, END: 2 cycles/word
    assert out.cycles == 2 * 8 + 3 * 17 + 6


def test_margin_violations_catch_a_short_gap():
    from xut.hw.interp import CycleEvent

    ev = [CycleEvent(10, "commit", "1"), CycleEvent(20, "sample", "1")]
    assert margin_violations(ev, 16) == [
        "sample at cycle 20 is 10 cycle(s) after the commit at cycle 10"
    ]


def test_running_off_the_end_and_unknown_ops_are_badop():
    r = Recorder()
    r.reset("0")
    assert run_program([image.W_SAMPLE], 1, 0, r, "0").status == proto.STATUS_CODE["badop"]
    assert run_program([0x7 << 28], 1, 0, r, "0").status == proto.STATUS_CODE["badop"]


def test_edge_on_a_missing_clock_changes_nothing_but_still_waits():
    r = Recorder()
    r.reset("0")
    out = run_program([image.w_edge(3, 1), image.W_END], 1, 1, r, "0", margin=4)
    assert r.log == [] and out.cycles == 2 + 5 + 2


def _harness():
    return Harness(0xABCD0001, [EmuSlot(16, 16, 0, "0" * 16, PassthroughSim())], maxwords=64)


def test_identify():
    assert _harness().feed(b"I") == proto.render(
        "id", build=0xABCD0001, slots=1, maxwords=64, margin=16
    )


def test_load_run_and_used():
    h = _harness()
    b = ImageBuilder(16, 0, 16, "0" * 16)
    b.set_bits("0000000000000101")
    b.sample("s")
    p = b.end()
    load = proto.parse_load(h.feed(proto.load_frame(0, p.words)))
    assert load.status == 0 and load.words == len(p.words)
    run = proto.parse_run(h.feed(b"R"))
    assert run.samples == ("0000000000000101",) and run.status == 0
    again = proto.parse_run(h.feed(b"R"))
    assert again.status == proto.STATUS_CODE["used"] and again.samples == ()


def test_error_paths():
    h = _harness()
    assert proto.parse_run(h.feed(b"R")).status == proto.STATUS_CODE["noload"]
    bad = bytearray(proto.load_frame(0, [image.W_END]))
    bad[-1] ^= 1
    assert proto.parse_load(h.feed(bytes(bad))).status == proto.STATUS_CODE["badcrc"]
    assert proto.parse_load(h.feed(proto.load_frame(3, [image.W_END]))).status == 4
    assert proto.parse_load(h.feed(proto.load_frame(0, [image.W_END] * 65))).status == 6
    assert h.feed(b"Z") == proto.render("err", cmd=0x5A, status=7)


def test_bytes_may_arrive_in_pieces():
    h, frame = _harness(), proto.load_frame(0, [image.W_END])
    assert h.feed(frame[:3]) == b""
    assert proto.parse_load(h.feed(frame[3:])).status == 0


def test_load_reply_crc_is_the_computed_one():
    h = _harness()
    frame = proto.load_frame(0, [image.W_END])
    assert proto.parse_load(h.feed(frame)).crc == zlib.crc32(frame[1:-4])
```

`tools/tests/test_hw_selftest.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from xut.hw import proto, selftest


def test_passthrough_expected_is_the_pattern_list():
    exp = selftest.expected_samples(selftest.PASS_SLOT)
    assert exp[0] == "0000000000000001" and exp[15] == "1000000000000000"
    assert exp[16] == "1111111111111110" and exp[-2:] == ["0000000000000000", "1111111111111111"]


def test_counter_counts_wraps_holds_and_clears():
    exp = dict(zip(selftest.counter_program().labels, selftest.expected_samples(1), strict=True))
    assert exp["c0"] == "00000000" and exp["c1"] == "00000001" and exp["c255"] == "11111111"
    assert exp["c256"] == "00000000" and exp["c257"] == "00000001"
    assert exp["hold"] == exp["c260"] == format(260 % 256, "08b")
    assert exp["clear"] == "00000000"


def test_check_names_the_first_difference():
    good = proto.RunReply(0, 0, 1, tuple(selftest.expected_samples(0)), 0, 0)
    assert selftest.check(0, good) is None
    bad = proto.RunReply(0, 0, 1, ("0" * 16, *good.samples[1:]), 0, 0)
    assert "p0" in selftest.check(0, bad)
    assert "status" in selftest.check(0, proto.RunReply(0, 0, 1, (), 3, 0))
```

`tools/tests/test_hw_replay.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The harness rendering of a stimulus, interpreted against the golden model, gives the
golden trace: the compiler and the interpreter preserve every behaviour the stepped
harness claims to preserve (spec §5.1 ruling S8')."""

import pytest
from hw_toy import ToyDff, toy_map

from xut.golden import replay
from xut.hw.compile import HwUnrenderable, compile_program
from xut.hw.replay import hw_replay
from xut.paths import repo_root
from xut.runners.base import RunContext
from xut.runners.python import generate
from xut.stimgen import VecBuilder
from xut.testspec import declared, discover, select
from xut.wrap import build_map
from xut_models.registry import get


@pytest.mark.parametrize("init", [0, 1])
def test_toy(init):
    m = toy_map(f"init{init}", init)
    b = VecBuilder(m, seed=3)
    b.sample("start")
    for d in (1, 0, 1):
        b.set(D=d)
        b.cycle("C")
    vec = b.build()
    assert hw_replay(ToyDff, vec, m).samples == replay(ToyDff, vec, m)[0].samples


def _flops_vector_cases():
    root = repo_root()
    return [c for c in select(discover(root), ["unit:flops"]) if c.style == "vector"]


@pytest.mark.parametrize("case", _flops_vector_cases(), ids=lambda c: c.id)
def test_every_renderable_flops_configuration(case, tmp_path):
    """Every flops vector configuration the hw runner would run (declared hw "yes"): the
    interpreted harness program reproduces the golden trace exactly, '-' bits included."""
    if not declared(case, "hw")[0]:
        pytest.skip(f"hw not declared for {case.id}")
    from xut.modelsrc import resolve

    ctx = RunContext(repo_root(), "rtl", resolve("auto"))
    model = get(case.family, case.prim)
    ran = 0
    for vec, spec in generate(case, ctx):
        m = build_map(spec)
        try:
            compile_program(vec, m)
        except HwUnrenderable:
            continue
        assert hw_replay(model, vec, m).samples == replay(model, vec, m)[0].samples, vec.cfg
        ran += 1
    assert ran, "no renderable configuration: the test proves nothing"
```

Run the three files; expected: `No module named 'xut.hw.interp'`.

- [ ] **Step 3: Implement `tools/xut/hw/interp.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Reference interpreter of harness programs and emulator of the harness (spec §7.1).
Standard library only.

``run_program`` executes a program exactly as xut_hw_ctrl's sequencer does, against a
``DutSim``, and returns the samples plus a cycle-stamped log of every in_vec change,
clock change and capture. ``Harness`` wraps it in the protocol of ``xut.hw.proto``: fed
the host's bytes, it returns byte for byte what the RTL harness transmits
(tools/tests/test_hw_rtl.py pins that on Icarus and xsim). So the compiler, the
protocol and the host code are all testable without hardware.

Cycle model (xut_hw_ctrl): FETCH and DECODE take one cycle each per word; COMMIT and
EDGE then hold MARGIN + 1 cycles (S_WAITM counts MARGIN down to 0); WAIT n holds n + 1;
SAMPLE captures in DECODE. Printing time is not modelled: the DUT is static meanwhile.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Protocol

from xut.hw import proto
from xut.hw.image import (
    MARGIN,
    MAXWORDS,
    OP_COMMIT,
    OP_EDGE,
    OP_END,
    OP_SAMPLE,
    OP_SET,
    OP_WAIT,
    chunks,
    decode,
    width,
)


class DutSim(Protocol):
    def reset(self, t0: str) -> None:
        """Power-on: in_vec = ``t0`` (MSB first), every clock low."""

    def drive(self, in_bits: str, clk_bits: str) -> None:
        """New pin levels (MSB first). The harness changes in_vec or one clock, never both."""

    def out_bits(self) -> str:
        """out_vec now: max(1, nout) chars of 0/1, MSB first."""


@dataclass(frozen=True)
class CycleEvent:
    cycle: int
    kind: str  # commit | edge | sample
    detail: str


@dataclass
class RunOutcome:
    samples: list[str]
    status: int
    events: list[CycleEvent]
    cycles: int


def _clk(clk: list[str]) -> str:
    return "".join(reversed(clk)) if clk else "0"


def _from_chunks(ch: list[int], w: int) -> str:
    lsb = "".join(format(c, "016b")[::-1] for c in ch)
    return lsb[:w][::-1]


def run_program(
    words: list[int] | tuple[int, ...],
    nin: int,
    nclk: int,
    dut: DutSim,
    t0: str,
    *,
    margin: int = MARGIN,
    max_cycles: int = 1 << 40,
) -> RunOutcome:
    """Execute ``words`` on a slot whose DUT is ``dut`` (already reset to ``t0``)."""
    w = width(nin)
    nxt = chunks(t0)  # in_nxt starts as the slot's current in_vec (xut_hw_ctrl S_RUN_GO)
    cur = t0
    clk = ["0"] * nclk
    samples: list[str] = []
    events: list[CycleEvent] = []
    cyc = pc = 0
    ok, badop = proto.STATUS_CODE["ok"], proto.STATUS_CODE["badop"]
    while True:
        if pc >= len(words):
            return RunOutcome(samples, badop, events, cyc)
        cyc += 2  # FETCH, DECODE
        op, a, b = decode(words[pc])
        if op == OP_SET:
            if a < len(nxt):  # the RTL has no such chunk, or truncates it on COMMIT
                nxt[a] = b
        elif op == OP_COMMIT:
            cur = _from_chunks(nxt, w)
            events.append(CycleEvent(cyc, "commit", cur))
            dut.drive(cur, _clk(clk))
            cyc += margin + 1
        elif op == OP_EDGE:
            if a < nclk:  # no flip-flop for a missing clock: nothing changes
                clk[a] = str(b)
                dut.drive(cur, _clk(clk))
            events.append(CycleEvent(cyc, "edge", f"{a}={b}"))
            cyc += margin + 1
        elif op == OP_WAIT:
            cyc += a + 1
        elif op == OP_SAMPLE:
            bits = dut.out_bits()
            events.append(CycleEvent(cyc, "sample", bits))
            samples.append(bits)
        elif op == OP_END:
            return RunOutcome(samples, ok, events, cyc)
        else:
            return RunOutcome(samples, badop, events, cyc)
        pc += 1
        if cyc > max_cycles:
            raise RuntimeError(f"program still running after {max_cycles} cycles")


def margin_violations(events: list[CycleEvent], margin: int = MARGIN) -> list[str]:
    """Every operation closer than ``margin`` cycles to the last in_vec or clock change."""
    out: list[str] = []
    last: CycleEvent | None = None
    for e in events:
        if last is not None and e.cycle - last.cycle < margin:
            out.append(
                f"{e.kind} at cycle {e.cycle} is {e.cycle - last.cycle} cycle(s) after the "
                f"{last.kind} at cycle {last.cycle}"
            )
        if e.kind in ("commit", "edge"):
            last = e
    return out


@dataclass
class EmuSlot:
    nin: int
    nout: int
    nclk: int
    t0: str
    dut: DutSim


class Harness:
    """The harness as seen from its UART: ``feed`` the host's bytes, get its replies.
    Construction is "configuring the FPGA": every slot's DUT is reset to its ``t0``."""

    def __init__(
        self,
        build_id: int,
        slots: list[EmuSlot],
        *,
        margin: int = MARGIN,
        maxwords: int = MAXWORDS,
    ) -> None:
        self.build_id, self.slots, self.margin, self.maxwords = build_id, slots, margin, maxwords
        for s in slots:
            s.dut.reset(s.t0)
        self._buf = bytearray()
        self._mem = [0] * maxwords
        self._loaded, self._lslot, self._lwords = False, 0, 0
        self._used = [False] * len(slots)

    def feed(self, data: bytes) -> bytes:
        self._buf += data
        out = bytearray()
        while self._buf:
            n = self._step(out)
            if n == 0:
                break
            del self._buf[:n]
        return bytes(out)

    def _step(self, out: bytearray) -> int:
        """Handle the command at the head of the buffer; the bytes it used (0: need more)."""
        buf, c = self._buf, self._buf[0]
        if c == ord(proto.CMD_ID):
            out += proto.render(
                "id",
                build=self.build_id,
                slots=len(self.slots),
                maxwords=self.maxwords,
                margin=self.margin,
            )
            return 1
        if c == ord(proto.CMD_LOAD):
            if len(buf) < 4:
                return 0
            slot, n = buf[1], buf[2] | buf[3] << 8
            total = 4 + 4 * n + 4
            if len(buf) < total:
                return 0
            body = bytes(buf[1 : 4 + 4 * n])
            calc = zlib.crc32(body)
            for i in range(min(n, self.maxwords)):  # the RTL writes whatever it can
                self._mem[i] = int.from_bytes(buf[4 + 4 * i : 8 + 4 * i], "little")
            if slot >= len(self.slots):
                status = proto.STATUS_CODE["badslot"]
            elif n == 0 or n > self.maxwords:
                status = proto.STATUS_CODE["toolong"]
            elif int.from_bytes(buf[4 + 4 * n : total], "little") != calc:
                status = proto.STATUS_CODE["badcrc"]
            else:
                status = proto.STATUS_CODE["ok"]
            self._loaded = status == proto.STATUS_CODE["ok"]
            if self._loaded:
                self._lslot, self._lwords = slot, n
            out += proto.render("load", slot=slot, words=n, crc=calc, status=status)
            return total
        if c == ord(proto.CMD_RUN):
            body = proto.render("run", build=self.build_id, slot=self._lslot, words=self._lwords)
            samples: list[str] = []
            if not self._loaded:
                status = proto.STATUS_CODE["noload"]
            elif self._used[self._lslot]:
                status = proto.STATUS_CODE["used"]
            else:
                s = self.slots[self._lslot]
                self._used[self._lslot] = True
                r = run_program(
                    self._mem[: self._lwords], s.nin, s.nclk, s.dut, s.t0, margin=self.margin
                )
                samples, status = r.samples, r.status
            body += b"".join(proto.render("sample", sidx=i, bits=b) for i, b in enumerate(samples))
            out += body + proto.render(
                "end", slot=self._lslot, samples=len(samples), status=status, crc=zlib.crc32(body)
            )
            return 1
        out += proto.render("err", cmd=c, status=proto.STATUS_CODE["badcmd"])
        return 1
```

- [ ] **Step 4: Implement `tools/xut/hw/selftest.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The self-test channels every bitstream carries (spec §7.1 "Self-test"). Standard
library only.

Slot 0 is a 16-bit passthrough: out_vec = in_vec, no primitive in between. Slot 1 is an
8-bit counter clocked through its own harness flip-flop and BUFG (in[0] = count
enable, in[1] = synchronous clear). Their programs run first after every programming;
any mismatch is a harness error, never a DUT result.
"""

from __future__ import annotations

from xut.hw import proto
from xut.hw.image import HwProgram, ImageBuilder
from xut.hw.interp import DutSim, run_program

PASS_SLOT, COUNT_SLOT = 0, 1
PASS_WIDTH = 16
COUNT_NIN, COUNT_NCLK, COUNT_NOUT = 2, 1, 8
COUNT_EDGES = 260  # wraps past 255


class PassthroughSim:
    def reset(self, t0: str) -> None:
        self._v = t0

    def drive(self, in_bits: str, clk_bits: str) -> None:
        self._v = in_bits

    def out_bits(self) -> str:
        return self._v


class CounterSim:
    def reset(self, t0: str) -> None:
        self._in, self._clk, self._n = t0, "0", 0

    def drive(self, in_bits: str, clk_bits: str) -> None:
        if self._clk == "0" and clk_bits == "1":  # rising edge: the inputs before it count
            if self._in[-2] == "1":
                self._n = 0
            elif self._in[-1] == "1":
                self._n = (self._n + 1) % 256
        self._in, self._clk = in_bits, clk_bits

    def out_bits(self) -> str:
        return format(self._n, "08b")


def passthrough_program() -> HwProgram:
    b = ImageBuilder(PASS_WIDTH, 0, PASS_WIDTH, "0" * PASS_WIDTH)
    pats = [1 << i for i in range(16)] + [0xFFFF ^ (1 << i) for i in range(16)]
    pats += [0xA5A5, 0x5A5A, 0x0000, 0xFFFF]
    for i, p in enumerate(pats):
        b.set_bits(format(p, "016b"))
        b.sample(f"p{i}")
    return b.end()


def counter_program() -> HwProgram:
    b = ImageBuilder(COUNT_NIN, COUNT_NCLK, COUNT_NOUT, "00")
    b.sample("c0")
    b.set_bits("01")  # CE
    for k in range(1, COUNT_EDGES + 1):
        b.edge(0, 1)
        b.edge(0, 0)
        if k in (1, 2, 255, 256, 257) or k % 20 == 0:
            b.sample(f"c{k}")
    b.set_bits("00")  # hold
    b.edge(0, 1)
    b.edge(0, 0)
    b.sample("hold")
    b.set_bits("10")  # clear
    b.edge(0, 1)
    b.edge(0, 0)
    b.sample("clear")
    return b.end()


def selftest_programs() -> dict[int, HwProgram]:
    return {PASS_SLOT: passthrough_program(), COUNT_SLOT: counter_program()}


def selftest_sims() -> dict[int, DutSim]:
    return {PASS_SLOT: PassthroughSim(), COUNT_SLOT: CounterSim()}


def expected_samples(slot: int) -> list[str]:
    prog, sim = selftest_programs()[slot], selftest_sims()[slot]
    sim.reset(prog.t0)
    return run_program(prog.words, prog.nin, prog.nclk, sim, prog.t0).samples


def check(slot: int, reply: proto.RunReply) -> str | None:
    """None when self-test ``slot`` answered as expected; otherwise what differed."""
    if reply.status != proto.STATUS_CODE["ok"]:
        return f"slot {slot}: status {proto.STATUS.get(reply.status, reply.status)}"
    labels = selftest_programs()[slot].labels
    exp = expected_samples(slot)
    if len(reply.samples) != len(exp):
        return f"slot {slot}: {len(reply.samples)} samples, expected {len(exp)}"
    for label, got, want in zip(labels, reply.samples, exp, strict=True):
        if got != want:
            return f"slot {slot} sample {label}: got {got}, expected {want}"
    return None
```

- [ ] **Step 5: Share the port grouping.** In `tools/xut/stimcompile.py`, lift `raw_to_trace`'s grouping into two functions and have `raw_to_trace` use them (its step-2 tests must pass unchanged):

```python
def out_port_bits(m: DutMap) -> dict[str, list[Bit]]:
    """Each out_vec port's bits, MSB first (map order of ports)."""
    return {
        p: sorted((b for b in m.of("out") if b.port == p), key=lambda b: -b.index)
        for p in m.out_ports()
    }


def port_values(ports: dict[str, list[Bit]], bits: str) -> dict[str, str]:
    """One out_vec sample (MSB first) as per-port values (MSB first)."""
    by_index = bits[::-1]  # by_index[i] is out_vec[i]
    return {p: "".join(by_index[b.bit] for b in pb) for p, pb in ports.items()}
```

(`raw_to_trace` then builds `ports = out_port_bits(m)` once and adds `port_values(ports, bits)` per line; import `Bit` from `xut.wrap`.)

- [ ] **Step 6: Implement `tools/xut/hw/replay.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Golden models as harness DUTs, and harness samples as traces.

``ModelDut`` drives a golden model (xut_models) with the harness's pin levels, with the
semantics of ``xut.golden.replay``: power-on, every input 0 and then the ``t0`` values
as one change, then GSR released before the first stepped operation. ``hw_replay``
compiles a stimulus, interprets it against that model and returns the trace; Task 3's
tests pin that it equals ``replay``'s for every renderable configuration.
"""

from __future__ import annotations

from collections.abc import Mapping

from xut.errors import XutError
from xut.formats.xtr import Trace
from xut.formats.xvec import Vec
from xut.hw.compile import compile_program
from xut.hw.image import width
from xut.hw.interp import run_program
from xut.stimcompile import out_port_bits, port_values
from xut.wrap import DutMap
from xut_models.base import Model


class SampleError(XutError, ValueError):
    """Harness samples that do not fit the wrapper's out_vec or the labels."""


class ModelDut:
    """``two_state``: report a golden don't-care (``-``) bit as ``0``, as 2-state silicon
    would. The harness emulator (``xut.hw.fake``) needs it, because the protocol carries
    only 0/1; ``hw_replay`` keeps ``-``, which ``compare`` masks."""

    def __init__(
        self, model_cls: type[Model], attrs: Mapping[str, str], m: DutMap, two_state: bool = False
    ) -> None:
        self.cls, self.attrs, self.m, self.two_state = model_cls, dict(attrs), m, two_state

    def _set(self, in_bits: str) -> None:
        new, old = in_bits[::-1], self._in[::-1]  # index = in_vec bit
        for p in self.m.in_ports():
            pb = self.m.port_bits("in", p)
            if any(new[b.bit] != old[b.bit] for b in pb):
                self.model.set_input(p, int("".join(new[b.bit] for b in reversed(pb)), 2))
        self._in = in_bits

    def reset(self, t0: str) -> None:
        self.model = self.cls(self.attrs)
        self.model.power_on()
        for p in self.m.in_ports():
            self.model.set_input(p, 0)
        self._in, self._clk = "0" * width(self.m.nin), "0" * width(self.m.nclk)
        self._set(t0)
        self.model.glbl("GSR", 0)

    def drive(self, in_bits: str, clk_bits: str) -> None:
        if in_bits != self._in:
            self._set(in_bits)
        new, old = clk_bits[::-1], self._clk[::-1]
        for b in self.m.of("clk"):
            if new[b.bit] != old[b.bit]:
                self.model.clock_edge(b.port, new[b.bit] == "1")
        self._clk = clk_bits

    def out_bits(self) -> str:
        outs = self.model.outputs()
        by_bit = ["0"] * width(self.m.nout)
        for b in self.m.of("out"):
            bits = outs[b.port].bits  # MSB first
            by_bit[b.bit] = bits[len(bits) - 1 - b.index]
        out = "".join(reversed(by_bit))
        return out.replace("-", "0") if self.two_state else out


def samples_to_trace(
    samples: list[str] | tuple[str, ...],
    labels: list[str] | tuple[str, ...],
    m: DutMap,
    header: dict[str, str],
    kind: str = "actual",
) -> Trace:
    """out_vec samples (MSB first) as a trace grouped by port, with the port grouping
    ``raw_to_trace`` uses (``stimcompile.out_port_bits``/``port_values``)."""
    if len(samples) != len(labels):
        raise SampleError(f"{len(samples)} samples for {len(labels)} labels")
    t = Trace({**header, **({"kind": kind} if kind != "actual" else {})})
    ports = out_port_bits(m)
    for label, bits in zip(labels, samples, strict=True):
        if len(bits) != width(m.nout):
            raise SampleError(f"sample {label}: {len(bits)} bits, out_vec is {width(m.nout)}")
        t.add(label, port_values(ports, bits))
    return t


def hw_replay(model_cls: type[Model], vec: Vec, m: DutMap) -> Trace:
    """``vec`` compiled for the harness and interpreted against ``model_cls``."""
    prog = compile_program(vec, m)
    dut = ModelDut(model_cls, vec.attrs, m)
    dut.reset(prog.t0)
    out = run_program(prog.words, prog.nin, prog.nclk, dut, prog.t0)
    if out.status != 0:
        raise SampleError(f"{vec.prim}/{vec.cfg}: program ended with status {out.status}")
    header = {"runner": "hw-replay", "flow": "rtl", "model": "golden", "seed": str(vec.seed)}
    return samples_to_trace(out.samples, prog.labels, m, header, kind="expected")
```

- [ ] **Step 7: Run the tests, lint and commit**

```bash
uv run pytest tools/tests/test_hw_interp.py tools/tests/test_hw_selftest.py tools/tests/test_hw_replay.py tools/tests/test_stimcompile.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/hw/interp.py tools/xut/hw/selftest.py tools/xut/hw/replay.py tools/xut/stimcompile.py tools/tests/hw_toy.py tools/tests/fixtures/hw tools/tests/test_hw_interp.py tools/tests/test_hw_selftest.py tools/tests/test_hw_replay.py
git commit -m "hw: reference interpreter, harness emulator, self-test channels and golden-model DUTs" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: all pass. `test_every_renderable_flops_configuration` runs once per flops vector test and skips (with the reason) the ones declared `hw: unsupported`. A failure there is a compiler or interpreter bug, or a stimulus whose behaviour depends on event *times* rather than order. That would contradict ruling S8′, so stop and report it; never loosen the comparison.

---

### Task 4: The harness RTL and the slot generator

**Files:**
- Create: `tools/xut/hdl/hw/xut_hw_uart_tx.sv`, `xut_hw_uart_rx.sv`, `xut_hw_crc32.vh`, `xut_hw_print.sv`, `xut_hw_ctrl.sv`, `xut_hw_top.sv`; `tools/xut/hw/slots.py`; `tools/tests/test_hw_slots.py`

**Interfaces:**
- Produces (RTL):
  - `xut_hw_top #(CLKS_PER_BIT=868)` with ports `CLK100MHZ`, `uart_txd_in`, `uart_rxd_out`, `led[3:0]`. It includes the generated `xut_hw_cfg.vh` and instantiates `xut_hw_ctrl u_ctrl` and the generated `xut_hw_slots u_slots`.
  - `xut_hw_ctrl #(BUILD_ID, NSLOTS, MAXIN, MAXOUT, MAXWORDS, MARGIN, CLKS_PER_BIT)`, whose strobes `commit`, `edge_we` and `sample_take` are also what the testbench's margin monitor watches.
- Produces (`xut.hw.slots`):
  - `SlotBuild(kind, nin, nout, nclk, t0, wrapper="", label="", map_json="")` (frozen) with `digest() -> str`
  - `SELFTEST_SLOTS` (the passthrough and the counter), `DUT_BUFG_BUDGET = 28`, `MAX_SLOTS = 64`, `SYS_PERIOD_NS = 10.0`
  - `SlotError`, `normalize_wrapper(text)`, `dut_slot(m, wrapper_text, t0) -> SlotBuild`, `pack(slots) -> list[list[int]]`
  - `maxin(slots)`, `maxout(slots)`, `render_slots(slots) -> str`, `render_cfg_vh(slots, build_id, maxwords, margin) -> str`, `timing_tcl(slots, margin) -> str`
  - `HW_HDL` (the `tools/xut/hdl/hw` directory), `HW_SOURCES` (the five `.sv` files), `HW_INCLUDES` (the two `.vh` files)

Design rules the RTL follows (Review Focus 2):

- The system clock is the Arty's 100 MHz oscillator through one BUFG. The harness logic is shallow; the margin covers the DUT paths.
- In each slot, every in_vec bit is a flip-flop output (`in_s<k>`) and every DUT clock is a flip-flop (`dclk_s<k>_<i>`) driving a BUFG. Nothing combinational sits between the harness and a DUT pin, so no DUT input glitches, async CLR/PRE included.
- `xut_hw_ctrl` holds `MARGIN + 1` cycles after every COMMIT and EDGE (`S_WAITM`), so by construction an in_vec change, the next DUT edge and the next capture are ≥ `MARGIN` cycles apart.
- `cur_out` is re-registered every cycle from the selected slot's out_vec, and a SAMPLE takes it ≥ `MARGIN` cycles after the last change. The value is long settled, and a metastable first capture has been overwritten many times.
- A slot's registers change only while it is selected, so an unselected DUT keeps its power-on state until its turn.

- [ ] **Step 1: Write the failing generator tests** — `tools/tests/test_hw_slots.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import re
import shutil

import pytest
from hw_toy import TOYFF_V, toy_map, toy_spec

from xut.hw.slots import (
    DUT_BUFG_BUDGET,
    HW_HDL,
    HW_INCLUDES,
    HW_SOURCES,
    SELFTEST_SLOTS,
    SlotBuild,
    SlotError,
    dut_slot,
    normalize_wrapper,
    pack,
    render_cfg_vh,
    render_slots,
    timing_tcl,
)
from xut.wrap import render_wrapper


def _toy_slot(init: int, cfg: str | None = None, t0: str = "0") -> SlotBuild:
    cfg = cfg or f"init{init}"
    m = toy_map(cfg, init)
    return dut_slot(m, render_wrapper(toy_spec(cfg, init), m), t0)


def test_normalized_wrappers_do_not_depend_on_the_cfg_name():
    a, b = _toy_slot(1, "x"), _toy_slot(1, "y")
    assert a.wrapper == b.wrapper and a.digest() == b.digest()
    assert _toy_slot(0).digest() != a.digest()
    assert _toy_slot(1, t0="1").digest() != a.digest()  # t0 is baked into the bitstream


def test_normalize_refuses_a_file_without_exactly_one_wrapper():
    with pytest.raises(SlotError):
        normalize_wrapper("module other (); endmodule\n")


def test_render_slots():
    text = render_slots((*SELFTEST_SLOTS, _toy_slot(0), _toy_slot(1, t0="1")))
    assert "module xut_dut_s2 (" in text and "module xut_dut_s3 (" in text
    assert "module xut_dut (" not in text
    assert "reg [0:0] in_s3 = 1'b1;" in text  # t0 as the flip-flops' INIT
    assert len(re.findall(r"\bBUFG u_bufg_s", text)) == 3  # counter + two toy clocks
    assert (
        "8'd2: begin cur_in <= {15'd0, in_s2}; cur_out <= {15'd0, out_s2}; cur_noutw <= 16'd1; end"
        in text
    )
    assert "if (edge_we && sel == 8'd3 && edge_idx == 12'd0) dclk_s3_0 <= edge_val;" in text


def test_render_slots_requires_the_self_test_first():
    with pytest.raises(SlotError, match="self-test"):
        render_slots((_toy_slot(0), *SELFTEST_SLOTS))


def test_pack_respects_the_clock_budget_and_is_order_independent():
    slots = [_toy_slot(i % 2, f"c{i}", t0=str(i // 2 % 2)) for i in range(DUT_BUFG_BUDGET + 2)]
    groups = pack(slots)
    assert [len(g) for g in groups] == [DUT_BUFG_BUDGET, 2]
    shuffled = list(reversed(slots))
    assert [[shuffled[i].digest() for i in g] for g in pack(shuffled)] == [
        [slots[i].digest() for i in g] for g in groups
    ]
    fat = SlotBuild("dut", 1, 1, DUT_BUFG_BUDGET + 1, "0", "module xut_dut (\n", "X")
    with pytest.raises(SlotError, match="clocks"):
        pack([fat])


def test_timing_tcl_guards_every_object_query():
    tcl = timing_tcl((*SELFTEST_SLOTS, _toy_slot(0)), margin=16)
    assert tcl.count("create_generated_clock") == 2
    for line in tcl.splitlines():
        if "[get_" in line and not line.startswith("proc"):
            assert "xut_must" in line, line
    assert "set xut_margin_ns 140.000" in tcl


def test_cfg_vh():
    vh = render_cfg_vh((*SELFTEST_SLOTS, _toy_slot(0)), 0x1234ABCD, 8192, 16)
    assert "`define XUT_HW_BUILD_ID 32'h1234abcd" in vh and "`define XUT_HW_NSLOTS 3" in vh
    assert "`define XUT_HW_MAXIN 16" in vh and "`define XUT_HW_MAXOUT 16" in vh


@pytest.mark.container
def test_harness_elaborates_on_icarus(tmp_path):
    from xut.container import executor_for
    from xut.modelsrc import resolve

    ms = resolve("auto")
    d = tmp_path / "elab"
    d.mkdir()
    slots = (*SELFTEST_SLOTS, _toy_slot(0), _toy_slot(1, t0="1"))
    (d / "xut_hw_slots.v").write_text(render_slots(slots))
    (d / "xut_hw_cfg.vh").write_text(render_cfg_vh(slots, 0x12345678, 64, 16))
    for f in (*HW_SOURCES, *HW_INCLUDES):
        shutil.copy(HW_HDL / f, d / f)
    shutil.copy(TOYFF_V, d / "TOYFF.v")
    ex = executor_for(ms, tmp_path)
    libs = [a for p in ms.search for a in ("-y", ex.guest(p))]
    files = [ex.guest(d / f) for f in (*HW_SOURCES, "xut_hw_slots.v", "TOYFF.v")]
    argv = [
        "iverilog",
        "-g2012",
        "-tnull",
        "-s",
        "xut_hw_top",
        "-I",
        ex.guest(d),
        *libs,
        "-Y",
        ".v",
        *files,
    ]
    rc = ex.run(argv, cwd=d, log=d / "elab.log", timeout_s=300)
    text = (d / "elab.log").read_text()
    assert rc == 0 and "error" not in text.lower(), text
```

Run `uv run pytest tools/tests/test_hw_slots.py > .cache/pytest.log 2>&1; cat .cache/pytest.log`. Expected: `No module named 'xut.hw.slots'`.

- [ ] **Step 2: Write the UART and CRC RTL.**

`tools/xut/hdl/hw/xut_hw_uart_tx.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 8N1 UART transmitter: start bit, 8 data bits LSB first, stop bit.
// A byte is accepted in the cycle where valid && ready.
`timescale 1ps / 1ps
module xut_hw_uart_tx #(
  parameter integer CLKS_PER_BIT = 868
) (
  input  wire       clk,
  input  wire       rst,
  input  wire [7:0] data,
  input  wire       valid,
  output wire       ready,
  output reg        tx = 1'b1
);
  localparam integer CW = $clog2(CLKS_PER_BIT + 1);
  reg [CW-1:0] cnt = {CW{1'b0}};
  reg [3:0]    bitn = 4'd0;       // 0 idle; 1 start; 2..9 data; 10 stop
  reg [8:0]    shreg = 9'h1FF;    // {stop, d7..d0}
  assign ready = (bitn == 4'd0);
  always @(posedge clk) begin
    if (rst) begin
      tx <= 1'b1;
      bitn <= 4'd0;
      cnt <= {CW{1'b0}};
    end else if (bitn == 4'd0) begin
      if (valid) begin
        shreg <= {1'b1, data};
        tx <= 1'b0;
        bitn <= 4'd1;
        cnt <= CLKS_PER_BIT - 1;
      end
    end else if (cnt != {CW{1'b0}}) begin
      cnt <= cnt - 1'b1;
    end else if (bitn == 4'd10) begin
      bitn <= 4'd0;
    end else begin
      tx <= shreg[0];
      shreg <= {1'b1, shreg[8:1]};
      bitn <= bitn + 4'd1;
      cnt <= CLKS_PER_BIT - 1;
    end
  end
endmodule
```

`tools/xut/hdl/hw/xut_hw_uart_rx.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 8N1 UART receiver: a two-flop synchroniser, then mid-bit sampling. A byte with a bad
// stop bit is dropped; the host then times out and retries the whole job (spec §7.5).
`timescale 1ps / 1ps
module xut_hw_uart_rx #(
  parameter integer CLKS_PER_BIT = 868
) (
  input  wire       clk,
  input  wire       rst,
  input  wire       rx,
  output reg  [7:0] data = 8'h00,
  output reg        valid = 1'b0
);
  localparam integer CW = $clog2(CLKS_PER_BIT + 1);
  (* ASYNC_REG = "TRUE" *) reg [1:0] sync = 2'b11;
  wire r = sync[1];
  reg [CW-1:0] cnt = {CW{1'b0}};
  reg [3:0]    bitn = 4'd0;       // 0 idle; 1 start; 2..9 data; 10 stop
  reg [7:0]    sh = 8'h00;
  always @(posedge clk) begin
    sync <= {sync[0], rx};
    valid <= 1'b0;
    if (rst) begin
      bitn <= 4'd0;
    end else if (bitn == 4'd0) begin
      if (!r) begin
        bitn <= 4'd1;
        cnt <= CLKS_PER_BIT / 2 - 1;   // to the middle of the start bit
      end
    end else if (cnt != {CW{1'b0}}) begin
      cnt <= cnt - 1'b1;
    end else begin
      cnt <= CLKS_PER_BIT - 1;
      if (bitn == 4'd1) begin
        bitn <= r ? 4'd0 : 4'd2;       // high at mid-start: a glitch, not a start bit
      end else if (bitn <= 4'd9) begin
        sh <= {r, sh[7:1]};
        bitn <= bitn + 4'd1;
      end else begin
        if (r) begin
          data <= sh;
          valid <= 1'b1;
        end
        bitn <= 4'd0;
      end
    end
  end
endmodule
```

`tools/xut/hdl/hw/xut_hw_crc32.vh` (included inside a module):

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// One byte of CRC-32 (IEEE 802.3, reflected, polynomial 0xEDB88320): the same CRC as
// Python's zlib.crc32. Keep the state starting at 32'hFFFFFFFF; the CRC is ~state.
function [31:0] xut_crc32_byte(input [31:0] crc, input [7:0] b);
  integer i;
  reg [31:0] c;
  begin
    c = crc ^ {24'h000000, b};
    for (i = 0; i < 8; i = i + 1)
      c = c[0] ? ((c >> 1) ^ 32'hEDB88320) : (c >> 1);
    xut_crc32_byte = c;
  end
endfunction
```

- [ ] **Step 3: Write the printer** — `tools/xut/hdl/hw/xut_hw_print.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// Prints one message of xut.hw.proto.MESSAGES from the generated ROM (xut_hw_msgs.vh):
// ASCII bytes are sent as they are; a field token is replaced by its value, in fixed-width
// lower-case hex, or in binary (MSB first, f_nbits wide) for `bits`. `sent` pulses once
// per byte the UART accepted (the controller's run CRC); `done` pulses at the end.
// Field values must stay stable until `done`.
`timescale 1ps / 1ps
module xut_hw_print #(
  parameter integer MAXOUT = 16
) (
  input  wire              clk,
  input  wire              rst,
  input  wire              start,
  input  wire [2:0]        msg,
  output reg               done = 1'b0,
  output reg               sent = 1'b0,
  input  wire [31:0]       f_build,
  input  wire [7:0]        f_slots,
  input  wire [15:0]       f_maxwords,
  input  wire [7:0]        f_margin,
  input  wire [7:0]        f_slot,
  input  wire [15:0]       f_words,
  input  wire [31:0]       f_crc,
  input  wire [7:0]        f_status,
  input  wire [15:0]       f_samples,
  input  wire [15:0]       f_sidx,
  input  wire [MAXOUT-1:0] f_bits,
  input  wire [15:0]       f_nbits,
  input  wire [7:0]        f_cmd,
  output reg  [7:0]        tx_data = 8'h00,
  output reg               tx_valid = 1'b0,
  input  wire              tx_ready
);
  `include "xut_hw_msgs.vh"
  localparam [1:0] S_IDLE = 2'd0, S_TOK = 2'd1, S_FIELD = 2'd2, S_OUT = 2'd3;
  reg [1:0]  st = S_IDLE;
  reg [8:0]  pc = 9'd0;
  reg [3:0]  fld = 4'd0;
  reg [15:0] d = 16'd0;          // the digit (or bit) being printed, counting down
  reg        in_field = 1'b0;
  wire [7:0] tok = xut_hw_msg_rom(pc);

  reg [31:0] fv;
  always @* begin
    case (fld)
      XUT_F_BUILD:    fv = f_build;
      XUT_F_SLOTS:    fv = {24'd0, f_slots};
      XUT_F_MAXWORDS: fv = {16'd0, f_maxwords};
      XUT_F_MARGIN:   fv = {24'd0, f_margin};
      XUT_F_SLOT:     fv = {24'd0, f_slot};
      XUT_F_WORDS:    fv = {16'd0, f_words};
      XUT_F_CRC:      fv = f_crc;
      XUT_F_STATUS:   fv = {24'd0, f_status};
      XUT_F_SAMPLES:  fv = {16'd0, f_samples};
      XUT_F_SIDX:     fv = {16'd0, f_sidx};
      XUT_F_CMD:      fv = {24'd0, f_cmd};
      default:        fv = 32'd0;
    endcase
  end
  wire [3:0] nib = fv[4 * d[2:0] +: 4];
  wire [7:0] hexc = (nib < 4'd10) ? (8'h30 + {4'h0, nib}) : (8'h57 + {4'h0, nib});

  always @(posedge clk) begin
    done <= 1'b0;
    sent <= 1'b0;
    if (rst) begin
      st <= S_IDLE;
      tx_valid <= 1'b0;
    end else case (st)
      S_IDLE: if (start) begin
        pc <= xut_hw_msg_start(msg);
        st <= S_TOK;
      end
      S_TOK: begin
        if (tok == 8'h00) begin
          done <= 1'b1;
          st <= S_IDLE;
        end else if (tok[7]) begin
          fld <= tok[3:0];
          d <= xut_hw_field_digits(tok[3:0], f_nbits) - 16'd1;
          pc <= pc + 9'd1;
          st <= S_FIELD;
        end else begin
          tx_data <= tok;
          tx_valid <= 1'b1;
          in_field <= 1'b0;
          pc <= pc + 9'd1;
          st <= S_OUT;
        end
      end
      S_FIELD: begin
        if (fld == XUT_F_BITS) begin
          if (f_bits[d]) tx_data <= 8'h31;   // an x in simulation prints '0', as 2-state silicon would
          else tx_data <= 8'h30;
        end else begin
          tx_data <= hexc;
        end
        tx_valid <= 1'b1;
        in_field <= 1'b1;
        st <= S_OUT;
      end
      S_OUT: if (tx_ready) begin
        tx_valid <= 1'b0;
        sent <= 1'b1;
        if (in_field && d != 16'd0) begin
          d <= d - 16'd1;
          st <= S_FIELD;
        end else begin
          st <= S_TOK;
        end
      end
    endcase
  end
endmodule
```

- [ ] **Step 4: Write the controller** — `tools/xut/hdl/hw/xut_hw_ctrl.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// Stepped fabric harness controller (spec §7.1): UART command parser, program loader,
// stimulus BRAM, sequencer and message printer. Protocol: xut.hw.proto. Reference model:
// xut.hw.interp.Harness, which must predict this module's UART output byte for byte
// (tools/tests/test_hw_rtl.py).
//
// A lost or garbled host byte leaves the loader waiting in S_LD_* for bytes that never
// come; later command bytes are then taken as program data and the session times out.
// There is deliberately no inter-byte timeout: the host treats any timeout as a
// transport error, and every retry reprograms the FPGA, which resets this state.
//
// Correctness by construction: after every COMMIT (the selected slot's in_vec takes
// in_nxt) and every EDGE (one of its clock flip-flops changes), S_WAITM holds MARGIN + 1
// cycles before the next word, so no two changes and no change and capture are closer
// than MARGIN cycles, whatever the program says.
`timescale 1ps / 1ps
module xut_hw_ctrl #(
  parameter [31:0] BUILD_ID = 32'h00000000,
  parameter integer NSLOTS = 2,
  parameter integer MAXIN = 16,          // a multiple of 16
  parameter integer MAXOUT = 16,
  parameter integer MAXWORDS = 8192,
  parameter integer MARGIN = 16,
  parameter integer CLKS_PER_BIT = 868
) (
  input  wire              clk,
  input  wire              rst,
  input  wire              uart_rx,
  output wire              uart_tx,
  output reg  [7:0]        sel = 8'd0,
  output reg               commit = 1'b0,
  output reg  [MAXIN-1:0]  in_nxt = {MAXIN{1'b0}},
  output reg               edge_we = 1'b0,
  output reg  [11:0]       edge_idx = 12'd0,
  output reg               edge_val = 1'b0,
  output reg               sample_take = 1'b0,
  input  wire [MAXIN-1:0]  cur_in,
  input  wire [MAXOUT-1:0] cur_out,
  input  wire [15:0]       cur_noutw,
  output wire [3:0]        leds
);
  `include "xut_hw_crc32.vh"
  `include "xut_hw_msgs.vh"
  localparam integer AW = $clog2(MAXWORDS);
  localparam integer NCHUNK = MAXIN / 16;
  localparam [7:0]  NSLOTS8 = NSLOTS;
  localparam [15:0] MAXWORDS16 = MAXWORDS;
  localparam [7:0]  MARGIN8 = MARGIN;
  localparam [7:0] ST_OK = 8'd0, ST_USED = 8'd1, ST_NOLOAD = 8'd2, ST_BADOP = 8'd3,
                   ST_BADSLOT = 8'd4, ST_BADCRC = 8'd5, ST_TOOLONG = 8'd6, ST_BADCMD = 8'd7;

  // ---- UART
  wire [7:0] rx_data;
  wire       rx_valid;
  wire [7:0] tx_data;
  wire       tx_valid, tx_ready;
  xut_hw_uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
    .clk(clk), .rst(rst), .rx(uart_rx), .data(rx_data), .valid(rx_valid));
  xut_hw_uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
    .clk(clk), .rst(rst), .data(tx_data), .valid(tx_valid), .ready(tx_ready), .tx(uart_tx));

  // ---- printer and its fields (held stable while it prints)
  reg              p_start = 1'b0;
  reg  [2:0]       p_msg = 3'd0;
  reg  [7:0]       p_slot = 8'd0, p_status = 8'd0, p_cmd = 8'd0;
  reg  [15:0]      p_words = 16'd0, p_samples = 16'd0, p_sidx = 16'd0;
  reg  [31:0]      p_crc = 32'd0;
  reg  [MAXOUT-1:0] p_bits = {MAXOUT{1'b0}};
  wire             p_done, p_sent;
  xut_hw_print #(.MAXOUT(MAXOUT)) u_print (
    .clk(clk), .rst(rst), .start(p_start), .msg(p_msg), .done(p_done), .sent(p_sent),
    .f_build(BUILD_ID), .f_slots(NSLOTS8), .f_maxwords(MAXWORDS16), .f_margin(MARGIN8),
    .f_slot(p_slot), .f_words(p_words), .f_crc(p_crc), .f_status(p_status),
    .f_samples(p_samples), .f_sidx(p_sidx), .f_bits(p_bits), .f_nbits(cur_noutw),
    .f_cmd(p_cmd), .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready));

  // ---- stimulus memory: inferred block RAM, one write port, one registered read port
  reg [31:0]   mem [0:MAXWORDS-1];
  reg [31:0]   rdata = 32'd0;
  reg          mem_we = 1'b0;
  reg [AW-1:0] mem_wa = {AW{1'b0}};
  reg [31:0]   mem_wd = 32'd0;
  reg [15:0]   pc = 16'd0;
  always @(posedge clk) begin
    if (mem_we) mem[mem_wa] <= mem_wd;
    rdata <= mem[pc[AW-1:0]];
  end

  // ---- state
  localparam [4:0] S_IDLE = 5'd0, S_PRINT = 5'd1, S_LD_SLOT = 5'd2, S_LD_N0 = 5'd3,
                   S_LD_N1 = 5'd4, S_LD_W = 5'd5, S_LD_CRC = 5'd6, S_LD_DONE = 5'd7,
                   S_RUN = 5'd8, S_RUN_GO = 5'd9, S_FETCH = 5'd10, S_DECODE = 5'd11,
                   S_WAITM = 5'd12, S_SAMPLED = 5'd13, S_END = 5'd14;
  reg [4:0]  st = S_IDLE, after = S_IDLE;
  reg [31:0] crc = 32'hFFFFFFFF;        // load CRC state
  reg [31:0] rcrc = 32'hFFFFFFFF;       // run-output CRC state
  reg        rcrc_on = 1'b0;
  reg [7:0]  ld_slot = 8'd0;
  reg [15:0] ld_n = 16'd0, ld_i = 16'd0;
  reg [1:0]  ld_b = 2'd0;
  reg [31:0] ld_word = 32'd0;
  reg        loaded = 1'b0;
  reg [7:0]  lslot = 8'd0;
  reg [15:0] lwords = 16'd0;
  reg [NSLOTS-1:0] used = {NSLOTS{1'b0}};
  reg [15:0] samples = 16'd0;
  reg [27:0] wcnt = 28'd0;
  reg        err_seen = 1'b0;
  reg [25:0] hb = 26'd0;
  integer    c;
  wire [3:0] op = rdata[31:28];
  wire       ld_ok = (ld_slot < NSLOTS) && (ld_n != 16'd0) && (ld_n <= MAXWORDS) &&
                     (ld_word == ~crc);

  always @(posedge clk) hb <= hb + 26'd1;
  assign leds = {err_seen, st != S_IDLE, loaded, hb[25]};

  always @(posedge clk) begin
    p_start <= 1'b0;
    commit <= 1'b0;
    edge_we <= 1'b0;
    sample_take <= 1'b0;
    mem_we <= 1'b0;
    if (p_sent && rcrc_on) rcrc <= xut_crc32_byte(rcrc, tx_data);
    if (rst) begin
      st <= S_IDLE;
      loaded <= 1'b0;
      used <= {NSLOTS{1'b0}};
      rcrc_on <= 1'b0;
    end else case (st)
      S_IDLE: if (rx_valid) begin
        if (rx_data == 8'h49) begin                        // "I"
          p_msg <= XUT_MSG_ID; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
        end else if (rx_data == 8'h4C) begin               // "L"
          crc <= 32'hFFFFFFFF; st <= S_LD_SLOT;
        end else if (rx_data == 8'h52) begin               // "R"
          st <= S_RUN;
        end else begin
          p_cmd <= rx_data; p_status <= ST_BADCMD; err_seen <= 1'b1;
          p_msg <= XUT_MSG_ERR; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
        end
      end
      S_PRINT: if (p_done) st <= after;
      S_LD_SLOT: if (rx_valid) begin
        ld_slot <= rx_data; crc <= xut_crc32_byte(crc, rx_data); st <= S_LD_N0;
      end
      S_LD_N0: if (rx_valid) begin
        ld_n[7:0] <= rx_data; crc <= xut_crc32_byte(crc, rx_data); st <= S_LD_N1;
      end
      S_LD_N1: if (rx_valid) begin
        ld_n[15:8] <= rx_data; crc <= xut_crc32_byte(crc, rx_data);
        ld_i <= 16'd0; ld_b <= 2'd0;
        st <= ({rx_data, ld_n[7:0]} == 16'd0) ? S_LD_CRC : S_LD_W;
      end
      S_LD_W: if (rx_valid) begin
        crc <= xut_crc32_byte(crc, rx_data);
        ld_word <= {rx_data, ld_word[31:8]};              // little-endian
        ld_b <= ld_b + 2'd1;
        if (ld_b == 2'd3) begin
          if (ld_i < MAXWORDS) begin
            mem_we <= 1'b1; mem_wa <= ld_i[AW-1:0]; mem_wd <= {rx_data, ld_word[31:8]};
          end
          ld_i <= ld_i + 16'd1;
          if (ld_i + 16'd1 == ld_n) st <= S_LD_CRC;
        end
      end
      S_LD_CRC: if (rx_valid) begin
        ld_word <= {rx_data, ld_word[31:8]};
        ld_b <= ld_b + 2'd1;
        if (ld_b == 2'd3) st <= S_LD_DONE;
      end
      S_LD_DONE: begin
        p_slot <= ld_slot; p_words <= ld_n; p_crc <= ~crc;
        if (ld_slot >= NSLOTS) p_status <= ST_BADSLOT;
        else if (ld_n == 16'd0 || ld_n > MAXWORDS) p_status <= ST_TOOLONG;
        else if (ld_word != ~crc) p_status <= ST_BADCRC;
        else p_status <= ST_OK;
        loaded <= ld_ok;
        if (ld_ok) begin
          lslot <= ld_slot; lwords <= ld_n;
        end else begin
          err_seen <= 1'b1;
        end
        p_msg <= XUT_MSG_LOAD; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
      end
      S_RUN: begin
        sel <= lslot; p_slot <= lslot; p_words <= lwords;
        rcrc <= 32'hFFFFFFFF; rcrc_on <= 1'b1; samples <= 16'd0;
        p_msg <= XUT_MSG_RUN; p_start <= 1'b1; after <= S_RUN_GO; st <= S_PRINT;
      end
      S_RUN_GO: begin
        if (!loaded) begin
          p_status <= ST_NOLOAD; st <= S_END;
        end else if (used[lslot]) begin
          p_status <= ST_USED; st <= S_END;
        end else begin
          used[lslot] <= 1'b1; in_nxt <= cur_in; pc <= 16'd0; st <= S_FETCH;
        end
      end
      S_FETCH: st <= S_DECODE;                              // rdata <= mem[pc] at this edge
      S_DECODE: begin
        if (pc >= lwords) begin
          p_status <= ST_BADOP; st <= S_END;                // ran past the last word
        end else case (op)
          4'h1: begin                                       // SET
            for (c = 0; c < NCHUNK; c = c + 1)
              if (rdata[27:16] == c) in_nxt[16 * c +: 16] <= rdata[15:0];
            pc <= pc + 16'd1; st <= S_FETCH;
          end
          4'h2: begin                                       // COMMIT
            commit <= 1'b1; wcnt <= MARGIN; st <= S_WAITM;
          end
          4'h3: begin                                       // EDGE
            edge_we <= 1'b1; edge_idx <= rdata[11:0]; edge_val <= rdata[12];
            wcnt <= MARGIN; st <= S_WAITM;
          end
          4'h4: begin                                       // WAIT
            wcnt <= rdata[27:0]; st <= S_WAITM;
          end
          4'h5: begin                                       // SAMPLE
            sample_take <= 1'b1; p_bits <= cur_out; p_sidx <= samples;
            samples <= samples + 16'd1;
            p_msg <= XUT_MSG_SAMPLE; p_start <= 1'b1; after <= S_SAMPLED; st <= S_PRINT;
          end
          4'hF: begin                                       // END
            p_status <= ST_OK; st <= S_END;
          end
          default: begin
            p_status <= ST_BADOP; st <= S_END;
          end
        endcase
      end
      S_WAITM: begin
        if (wcnt == 28'd0) begin
          pc <= pc + 16'd1; st <= S_FETCH;
        end else begin
          wcnt <= wcnt - 28'd1;
        end
      end
      S_SAMPLED: begin
        pc <= pc + 16'd1; st <= S_FETCH;
      end
      S_END: begin
        rcrc_on <= 1'b0; p_crc <= ~rcrc; p_samples <= samples;
        if (p_status != ST_OK) err_seen <= 1'b1;
        p_msg <= XUT_MSG_END; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
      end
      default: st <= S_IDLE;
    endcase
  end
endmodule
```

Notes for the implementer:
- `p_sent` pulses in the cycle *after* the UART accepted a byte, while `tx_data` still holds it (the printer only loads the next byte one edge later). So `xut_crc32_byte(rcrc, tx_data)` sees the right byte.
- At `S_END`, every byte of the last sample line has been accounted for, because `p_done` comes at least one cycle after the last `p_sent`.
- The run header's `slot`/`words` are `lslot`/`lwords`, which change only on a successful load. The emulator does the same (`_lslot`, `_lwords`).

- [ ] **Step 5: Write the top** — `tools/xut/hdl/hw/xut_hw_top.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// Stepped fabric harness top for the Arty A7-35T (spec §7.1). The system clock is the
// board's 100 MHz oscillator through one BUFG; a power-on counter holds the controller
// in reset for 128 cycles after configuration. xut_hw_slots and xut_hw_cfg.vh are
// generated per bitstream by xut.hw.slots.
`timescale 1ps / 1ps
`include "xut_hw_cfg.vh"
module xut_hw_top #(
  parameter integer CLKS_PER_BIT = 868      // 100 MHz / 115200 baud
) (
  input  wire       CLK100MHZ,
  input  wire       uart_txd_in,            // host -> FPGA
  output wire       uart_rxd_out,           // FPGA -> host
  output wire [3:0] led
);
  localparam integer MAXIN = `XUT_HW_MAXIN;
  localparam integer MAXOUT = `XUT_HW_MAXOUT;
  wire clk;
  BUFG u_sysclk (.I(CLK100MHZ), .O(clk));
  reg [7:0] por = 8'd0;
  always @(posedge clk) if (!por[7]) por <= por + 8'd1;
  wire rst = !por[7];

  wire [7:0]        sel;
  wire              commit, edge_we, edge_val, sample_take;
  wire [11:0]       edge_idx;
  wire [MAXIN-1:0]  in_nxt, cur_in;
  wire [MAXOUT-1:0] cur_out;
  wire [15:0]       cur_noutw;
  xut_hw_ctrl #(
    .BUILD_ID(`XUT_HW_BUILD_ID), .NSLOTS(`XUT_HW_NSLOTS), .MAXIN(MAXIN), .MAXOUT(MAXOUT),
    .MAXWORDS(`XUT_HW_MAXWORDS), .MARGIN(`XUT_HW_MARGIN), .CLKS_PER_BIT(CLKS_PER_BIT)
  ) u_ctrl (
    .clk(clk), .rst(rst), .uart_rx(uart_txd_in), .uart_tx(uart_rxd_out),
    .sel(sel), .commit(commit), .in_nxt(in_nxt), .edge_we(edge_we), .edge_idx(edge_idx),
    .edge_val(edge_val), .sample_take(sample_take), .cur_in(cur_in), .cur_out(cur_out),
    .cur_noutw(cur_noutw), .leds(led));
  xut_hw_slots u_slots (
    .clk(clk), .sel(sel), .commit(commit), .in_nxt(in_nxt), .edge_we(edge_we),
    .edge_idx(edge_idx), .edge_val(edge_val), .cur_in(cur_in), .cur_out(cur_out),
    .cur_noutw(cur_noutw));
endmodule
```

- [ ] **Step 6: Implement `tools/xut/hw/slots.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Harness slots (spec §7.1 "Multi-DUT packing"): what one bitstream holds, and the
RTL and constraints generated for it.

Slot 0 is the self-test passthrough and slot 1 the self-test counter; slots 2.. are
DUTs, one per test configuration. Each slot k has:

- ``in_s<k>``: its in_vec register, INIT = the configuration's ``t0``, written only by a
  COMMIT while ``sel == k``;
- ``dclk_s<k>_<i>``: one flip-flop per clock, INIT 0, written only by an EDGE while
  ``sel == k``, driving a BUFG whose output is the DUT's clk[i];
- for a DUT, the configuration's ``xut_dut`` wrapper renamed ``xut_dut_s<k>``.

A slot's digest covers what reaches the bitstream (kind, sizes, ``t0``, normalised
wrapper) and never a configuration name, so identical slots from different tests share
cached bitstreams.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from xut.errors import XutError
from xut.hw.image import width
from xut.wrap import DutMap

HEADER = "// SPDX-License-Identifier: Apache-2.0"
HW_HDL = Path(__file__).resolve().parent.parent / "hdl" / "hw"
HW_SOURCES = (
    "xut_hw_top.sv",
    "xut_hw_ctrl.sv",
    "xut_hw_print.sv",
    "xut_hw_uart_tx.sv",
    "xut_hw_uart_rx.sv",
)
HW_INCLUDES = ("xut_hw_crc32.vh", "xut_hw_msgs.vh")
#: 7-series parts have 32 BUFGCTRL sites. The harness uses 2 (sysclk, the self-test
#: counter) and keeps 2 spare; DUT clocks get the rest.
DUT_BUFG_BUDGET = 28
MAX_SLOTS = 64
SYS_PERIOD_NS = 10.0
_GEN_LINE = re.compile(r"^// GENERATED by xut wrap:.*\n", re.MULTILINE)
_DECL = "module xut_dut ("


class SlotError(XutError, ValueError):
    """A slot set the harness cannot hold."""


@dataclass(frozen=True)
class SlotBuild:
    kind: str  # passthrough | counter | dut
    nin: int
    nout: int
    nclk: int
    t0: str  # MSB-first width(nin) chars of 0/1
    wrapper: str = ""  # dut: the normalised xut_dut.v
    label: str = ""  # dut: the primitive, for comments
    map_json: str = ""  # dut: the wrapper's map, for the manifest (not in the digest)

    def digest(self) -> str:
        h = hashlib.sha256()
        for part in (
            self.kind,
            str(self.nin),
            str(self.nout),
            str(self.nclk),
            self.t0,
            self.wrapper,
        ):
            h.update(part.encode())
            h.update(b"\0")
        return h.hexdigest()


SELFTEST_SLOTS = (
    SlotBuild("passthrough", 16, 16, 0, "0" * 16),
    SlotBuild("counter", 2, 8, 1, "00"),
)


def normalize_wrapper(text: str) -> str:
    """``xut_dut.v`` without its configuration-naming GENERATED line."""
    text = _GEN_LINE.sub("", text)
    if text.count(_DECL) != 1:
        raise SlotError(f"expected exactly one {_DECL!r} in the wrapper")
    return text


def dut_slot(m: DutMap, wrapper_text: str, t0: str) -> SlotBuild:
    if len(t0) != width(m.nin) or set(t0) - {"0", "1"}:
        raise SlotError(f"t0 {t0!r} is not {width(m.nin)} bits of 0/1")
    return SlotBuild(
        "dut", m.nin, m.nout, m.nclk, t0, normalize_wrapper(wrapper_text), m.prim, m.to_json()
    )


def pack(slots: Sequence[SlotBuild]) -> list[list[int]]:
    """Indices of DUT ``slots`` per bitstream: in digest order (so the same slot set packs
    the same way whichever test asks), greedily, until the next slot would exceed the
    DUT clock budget or MAX_SLOTS."""
    order = sorted(range(len(slots)), key=lambda i: (slots[i].digest(), i))
    groups: list[list[int]] = []
    cur: list[int] = []
    clocks = 0
    for i in order:
        s = slots[i]
        if s.kind != "dut":
            raise SlotError(f"slot {i} is a {s.kind}, not a DUT")
        if s.nclk > DUT_BUFG_BUDGET:
            raise SlotError(
                f"a slot with {s.nclk} clocks exceeds the {DUT_BUFG_BUDGET}-BUFG budget"
            )
        full = clocks + s.nclk > DUT_BUFG_BUDGET or len(cur) + len(SELFTEST_SLOTS) >= MAX_SLOTS
        if cur and full:
            groups.append(cur)
            cur, clocks = [], 0
        cur.append(i)
        clocks += s.nclk
    if cur:
        groups.append(cur)
    return groups


def maxin(slots: Sequence[SlotBuild]) -> int:
    w = max(width(s.nin) for s in slots)
    return -(-w // 16) * 16


def maxout(slots: Sequence[SlotBuild]) -> int:
    return max(width(s.nout) for s in slots)


def _pad(expr: str, w: int, total: int) -> str:
    return expr if w == total else f"{{{total - w}'d0, {expr}}}"


def _slot(k: int, s: SlotBuild) -> list[str]:
    wi, wo = width(s.nin), width(s.nout)
    what = f"{s.kind} {s.label}".strip()
    out = [
        f"  // ---- slot {k}: {what} (nin {s.nin}, nclk {s.nclk}, nout {s.nout})",
        f'  (* DONT_TOUCH = "TRUE" *) reg [{wi - 1}:0] in_s{k} = {wi}\'b{s.t0};',
        f"  always @(posedge clk) if (commit && sel == 8'd{k}) in_s{k} <= in_nxt[{wi - 1}:0];",
    ]
    gclk = []
    for i in range(s.nclk):
        out += [
            f'  (* DONT_TOUCH = "TRUE" *) reg dclk_s{k}_{i} = 1\'b0;',
            f"  always @(posedge clk) if (edge_we && sel == 8'd{k} && edge_idx == 12'd{i}) "
            f"dclk_s{k}_{i} <= edge_val;",
            f"  wire gclk_s{k}_{i};",
            f"  BUFG u_bufg_s{k}_{i} (.I(dclk_s{k}_{i}), .O(gclk_s{k}_{i}));",
        ]
        gclk.append(f"gclk_s{k}_{i}")
    if s.kind == "passthrough":
        out.append(f"  wire [{wo - 1}:0] out_s{k} = in_s{k};")
    elif s.kind == "counter":
        out += [
            f"  reg [7:0] cnt_s{k} = 8'd0;",
            f"  always @(posedge gclk_s{k}_0) if (in_s{k}[1]) cnt_s{k} <= 8'd0; "
            f"else if (in_s{k}[0]) cnt_s{k} <= cnt_s{k} + 8'd1;",
            f"  wire [7:0] out_s{k} = cnt_s{k};",
        ]
    else:
        clk = "{" + ", ".join(reversed(gclk)) + "}" if gclk else "1'b0"
        out += [
            f"  wire [{width(s.nclk) - 1}:0] clk_s{k} = {clk};",
            f"  wire [{wo - 1}:0] out_s{k};",
            f"  xut_dut_s{k} u_dut_s{k} (.clk(clk_s{k}), .in_vec(in_s{k}), .out_vec(out_s{k}));",
        ]
    return out


def render_slots(slots: Sequence[SlotBuild]) -> str:
    """``xut_hw_slots.v``: the slots module, then every DUT wrapper renamed per slot."""
    if tuple(s.kind for s in slots[:2]) != ("passthrough", "counter"):
        raise SlotError("slots 0 and 1 must be the self-test channels (SELFTEST_SLOTS)")
    if len(slots) > MAX_SLOTS:
        raise SlotError(f"{len(slots)} slots > MAX_SLOTS={MAX_SLOTS}")
    mi, mo = maxin(slots), maxout(slots)
    out = [
        HEADER,
        f"// GENERATED by xut.hw.slots: {len(slots)} slots. Do not edit.",
        "`timescale 1ps / 1ps",
        "module xut_hw_slots (",
        "  input  wire        clk,",
        "  input  wire [7:0]  sel,",
        "  input  wire        commit,",
        f"  input  wire [{mi - 1}:0] in_nxt,",
        "  input  wire        edge_we,",
        "  input  wire [11:0] edge_idx,",
        "  input  wire        edge_val,",
        f"  output reg  [{mi - 1}:0] cur_in = {mi}'d0,",
        f"  output reg  [{mo - 1}:0] cur_out = {mo}'d0,",
        "  output reg  [15:0] cur_noutw = 16'd1",
        ");",
    ]
    for k, s in enumerate(slots):
        out += _slot(k, s)
    out += ["  always @(posedge clk) begin", "    case (sel)"]
    for k, s in enumerate(slots):
        wi, wo = width(s.nin), width(s.nout)
        out.append(
            f"      8'd{k}: begin cur_in <= {_pad(f'in_s{k}', wi, mi)}; "
            f"cur_out <= {_pad(f'out_s{k}', wo, mo)}; cur_noutw <= 16'd{wo}; end"
        )
    out += [
        f"      default: begin cur_in <= {mi}'d0; cur_out <= {mo}'d0; cur_noutw <= 16'd1; end",
        "    endcase",
        "  end",
        "endmodule",
        "",
    ]
    for k, s in enumerate(slots):
        if s.kind == "dut":
            out.append(s.wrapper.replace(_DECL, f"module xut_dut_s{k} (", 1))
    return "\n".join(out) + "\n"


def render_cfg_vh(slots: Sequence[SlotBuild], build_id: int, maxwords: int, margin: int) -> str:
    return "\n".join(
        [
            HEADER,
            "// GENERATED by xut.hw.slots. Do not edit.",
            "`ifndef XUT_HW_CFG_VH",
            "`define XUT_HW_CFG_VH",
            f"`define XUT_HW_BUILD_ID 32'h{build_id:08x}",
            f"`define XUT_HW_NSLOTS {len(slots)}",
            f"`define XUT_HW_MAXIN {maxin(slots)}",
            f"`define XUT_HW_MAXOUT {maxout(slots)}",
            f"`define XUT_HW_MAXWORDS {maxwords}",
            f"`define XUT_HW_MARGIN {margin}",
            "`endif",
            "",
        ]
    )


def timing_tcl(slots: Sequence[SlotBuild], margin: int) -> str:
    """Constraints applied after synth_design (spec §7.1): a generated clock per DUT clock
    flip-flop, and max-delay (datapath only) of (MARGIN - 2) system periods on every path
    out of a slot's in_vec register and into the capture register. Every object query goes
    through ``xut_must``: a constraint that matches nothing stops the build (exit 4)."""
    out = [
        "# SPDX-License-Identifier: Apache-2.0",
        "# GENERATED by xut.hw.slots: sourced after synth_design by build.tcl. Do not edit.",
        "proc xut_must {what objs} {",
        '  if {[llength $objs] == 0} { puts "XUT_CONSTRAINT_EMPTY $what"; exit 4 }',
        "  return $objs",
        "}",
        "xut_must sysclk [get_clocks sysclk]",
    ]
    for k, s in enumerate(slots):
        for i in range(s.nclk):
            ff = f"u_slots/dclk_s{k}_{i}_reg"
            out.append(
                f"create_generated_clock -name dclk_s{k}_{i} "
                f"-source [xut_must {ff}/C [get_pins {ff}/C]] -divide_by 2 "
                f"[xut_must {ff}/Q [get_pins {ff}/Q]]"
            )
    out += [
        f"set xut_margin_ns {(margin - 2) * SYS_PERIOD_NS:.3f}",
        "set_max_delay -datapath_only $xut_margin_ns -from [xut_must in_s "
        "[get_cells -hierarchical -filter {NAME =~ u_slots/in_s*_reg*}]]",
        "set_max_delay -datapath_only $xut_margin_ns -to [xut_must cur_out "
        "[get_pins -hierarchical -filter {NAME =~ u_slots/cur_out_reg*/D}]]",
        "",
    ]
    return "\n".join(out)
```

- [ ] **Step 7: Run the tests** (the container test needs `xut-sim:1`; it elaborates the whole harness on Icarus):

```bash
uv run pytest tools/tests/test_hw_slots.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
```

Expected: all pass. If Icarus reports a construct it does not support, change the RTL to the common subset of xsim, Icarus `-g2012` and Vivado synthesis (for example, move a declaration to module scope). Never add a simulator-specific `ifdef`.

- [ ] **Step 8: Commit**

```bash
git add tools/xut/hdl/hw tools/xut/hw/slots.py tools/tests/test_hw_slots.py
git commit -m "hw: harness RTL (UART, printer, controller, top) and the per-bitstream slot generator" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5a: Capped scopes, and the harness in simulation — byte-exact against the emulator

**Files:**
- Create: `tools/xut/scope.py`, `tools/tests/test_scope.py`, `tools/xut/hdl/hw/xut_hw_tb.sv`, `tools/xut/hw/steps.py`, `tools/xut/hw/hwsim.py`, `tools/tests/test_hw_rtl.py`

**Interfaces:**
- Produces (`xut.scope`; here, not in PR B, because `xut hw sim` needs it first):
  - `scope_argv(argv, what, memory_max) -> list[str]`
  - `scoped_run(argv, *, what, memory_max, cwd, log, timeout_s) -> int`, which raises `ScopeError` when `systemd-run` is missing and `RunTimeout` on a timeout
  - `VIVADO_MEMORY_MAX = "16G"`, `OOM_RCS = (137, -9)`
- Consumes: `xut.slots.vivado_slot()` (PR #10, ruling S50 CQ2): a context manager that takes one of `XUT_VIVADO_SLOTS` (default 4) flock files `$XDG_RUNTIME_DIR/xut-vivado/slot{N}.lock`, with a non-blocking scan and then a wait. This plan has no slot mechanism of its own.
- Produces (`xut.hw.hwsim`):
  - `render_host(steps) -> tuple[str, int]`
- Produces (`xut.hw.steps`, standard library only; the simulator, `xut.hw.session`, the smoke design and the tests all import it):
  - `Step(send: bytes, lines: int)`, `RUN_FRAME_LINES = 2`
  - `session_steps(programs: dict[int, HwProgram]) -> list[Step]`: `I`, then per slot in order `L` (1 line) and `R` (`RUN_FRAME_LINES + len(labels)` lines)
  - `split_replies(data, steps) -> list[bytes]`, `slot_replies(replies, slots) -> dict[int, tuple[bytes, bytes]]` (the one owner of the reply indexing), `run_replies(replies, slots) -> dict[int, RunReply]`
  - `simulate(slots, steps, sim, workdir, *, model_source, work_root, extra_files=(), maxwords=MAXWORDS, margin=MARGIN, timeout_s=1800) -> SimResult` with `SimResult(tx: bytes, replies: list[bytes], log: Path, margin_violations: list[str])`
  - `SIM_BUILD_ID = 0x51AB0001`, `CPB = 4` (the testbench's UART clocks per bit), `HW_SIM_MEMORY_MAX = "16G"`, `HwSimError`

Every xsim run goes through `scoped_run` at `HW_SIM_MEMORY_MAX` (Global Constraints: one cap value) **inside `vivado_slot()`**, like every Vivado run; Icarus runs in the 4g-capped container.

- [ ] **Step 1: Write the scope tests** — `tools/tests/test_scope.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import shutil
import subprocess

import pytest

from xut import scope
from xut.scope import ScopeError, scope_argv


def test_scope_argv_is_the_agents_md_line():
    argv = scope_argv(["vivado", "-version"], "vivado-x", "16G")
    assert argv[:5] == ["systemd-run", "--user", "--scope", "--quiet", "--slice=vivado.slice"]
    assert argv[5].startswith("--unit=xut-vivado-x-")
    assert argv[6:11] == ["-p", "MemoryMax=16G", "-p", "MemorySwapMax=0", "--"]
    assert argv[11:] == ["vivado", "-version"]


def test_scoped_run_refuses_without_systemd_run(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ScopeError, match="systemd-run"):
        scope.scoped_run(
            ["true"], what="t", memory_max="1G", cwd=tmp_path, log=tmp_path / "l", timeout_s=5
        )


def _user_scopes_work() -> bool:
    if shutil.which("systemd-run") is None:
        return False
    r = subprocess.run(
        ["systemd-run", "--user", "--scope", "--quiet", "--", "true"], capture_output=True
    )
    return r.returncode == 0


@pytest.mark.skipif(
    not _user_scopes_work(), reason="no systemd user manager (CI runners have none)"
)
def test_scoped_run_runs_and_logs(tmp_path):
    rc = scope.scoped_run(
        ["bash", "-c", "echo hello; exit 3"],
        what="t",
        memory_max="256M",
        cwd=tmp_path,
        log=tmp_path / "l.log",
        timeout_s=60,
    )
    assert rc == 3 and "hello" in (tmp_path / "l.log").read_text()


def test_hw_sim_xsim_runs_inside_a_vivado_slot(tmp_path, monkeypatch):
    """Every xsim run of `xut hw sim` takes one of PR #10's host-wide slots."""
    from contextlib import contextmanager

    from xut.hw import hwsim

    held = []

    @contextmanager
    def slot():
        held.append(True)
        yield
        held.pop()

    def fake_run(argv, *, what, memory_max, cwd, log, timeout_s):
        assert held, "xsim ran outside a vivado_slot()"
        assert memory_max == hwsim.HW_SIM_MEMORY_MAX
        return 0

    monkeypatch.setattr(hwsim, "vivado_slot", slot)
    monkeypatch.setattr(hwsim, "scoped_run", fake_run)
    hwsim._xsim(tmp_path, ["a.sv"], 10)
```

- [ ] **Step 2: Implement `tools/xut/scope.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Capped scopes for heavy commands (AGENTS.md §10.1, memory safety).

``scoped_run`` runs a command in its own transient systemd user scope::

    systemd-run --user --scope --quiet --slice=vivado.slice --unit=xut-<what>-<t>-<pid>-<r>
        -p MemoryMax=<cap> -p MemorySwapMax=0 -- <argv>

so an OOM kill stays inside it. With no systemd-run it refuses: a heavy command never
falls back to an unscoped run. The host-wide bound on concurrent Vivado/xsim processes
is PR #10's ``xut.slots.vivado_slot()`` (ruling S50 CQ2); every caller takes a slot
around its ``scoped_run``.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

from xut.container import RunTimeout
from xut.errors import XutError

VIVADO_MEMORY_MAX = "16G"
#: A process killed by the OOM killer: bash reports 137, a direct child -9.
OOM_RCS = (137, -9)
_KILL_GRACE_S = 30


class ScopeError(XutError, RuntimeError):
    """A heavy command cannot run in a capped scope."""


def scope_argv(argv: Sequence[str], what: str, memory_max: str) -> list[str]:
    unit = f"xut-{what}-{int(time.time())}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--slice=vivado.slice",
        f"--unit={unit}",
        "-p",
        f"MemoryMax={memory_max}",
        "-p",
        "MemorySwapMax=0",
        "--",
        *argv,
    ]


def scoped_run(
    argv: Sequence[str],
    *,
    what: str,
    memory_max: str,
    cwd: Path,
    log: Path,
    timeout_s: int,
) -> int:
    """Run ``argv`` in a capped scope, appending its output to ``log``; its exit code."""
    if shutil.which("systemd-run") is None:
        raise ScopeError(
            "systemd-run not found: heavy commands run only in a capped scope "
            "(AGENTS.md §10.1); refusing to run unscoped"
        )
    with Path(log).open("a") as f:
        p = subprocess.Popen(
            scope_argv(argv, what, memory_max),
            cwd=cwd,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=_KILL_GRACE_S)
            raise RunTimeout(f"timeout after {timeout_s}s: {what}") from e
```

- [ ] **Step 3: Write the testbench** — `tools/xut/hdl/hw/xut_hw_tb.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// Simulation testbench of the stepped harness (tools/xut/hw/hwsim.py). Plays host.memh
// into the harness's UART, writes every byte the harness transmits to harness_tx.txt
// (two hex digits per line), and reports any operation closer than MARGIN cycles to the
// last in_vec or clock change (XUT_MARGIN_VIOLATION). Common subset of xsim and Icarus.
// The host side drives and samples on the falling clock edge, so it never races the
// harness's rising-edge logic.
//
// host.memh, one 32-bit word per line: 000000bb sends byte bb; 1nnnnnnn waits until the
// harness has sent nnnnnnn newlines in total; f0000000 ends the session.
`timescale 1ps / 1ps
`include "xut_hw_cfg.vh"
`include "host.vh"
module xut_hw_tb;
  localparam integer CPB = 4;
  localparam integer MARGIN = `XUT_HW_MARGIN;
  localparam integer NHOST = `XUT_HOST_WORDS;
  reg clk = 1'b0;
  always #5000 clk = ~clk;                     // 100 MHz
  reg  rx = 1'b1;
  wire tx;
  wire [3:0] led;
  xut_hw_top #(.CLKS_PER_BIT(CPB)) u_top (
    .CLK100MHZ(clk), .uart_txd_in(rx), .uart_rxd_out(tx), .led(led));

  reg [31:0] host [0:NHOST-1];
  reg [63:0] cyc = 64'd0;
  integer    fd;
  integer    nl = 0;
  always @(posedge clk) cyc <= cyc + 64'd1;

  // ---- the harness's transmitter, decoded mid-bit
  reg [7:0] rbyte;
  integer   rk;
  initial begin
    fd = $fopen("harness_tx.txt", "w");
    forever begin
      @(negedge tx);
      repeat (CPB / 2) @(negedge clk);
      for (rk = 0; rk < 8; rk = rk + 1) begin
        repeat (CPB) @(negedge clk);
        rbyte[rk] = tx;
      end
      repeat (CPB) @(negedge clk);
      $fwrite(fd, "%02x\n", rbyte);
      if (rbyte == 8'h0a) nl = nl + 1;
    end
  end

  // ---- the host
  task send_byte(input [7:0] v);
    integer j;
    begin
      @(negedge clk) rx = 1'b0;
      repeat (CPB) @(negedge clk);
      for (j = 0; j < 8; j = j + 1) begin
        rx = v[j];
        repeat (CPB) @(negedge clk);
      end
      rx = 1'b1;
      repeat (2 * CPB) @(negedge clk);
    end
  endtask

  integer i;
  initial begin : host_side
    $readmemh("host.memh", host);
    #(3_000_000);                              // 3 us: glbl's GSR and the harness's reset
    for (i = 0; i < NHOST; i = i + 1) begin
      if (host[i][31:28] == 4'h0) send_byte(host[i][7:0]);
      else if (host[i][31:28] == 4'h1) wait (nl >= host[i][27:0]);
    end
    repeat (8 * CPB) @(negedge clk);
    $fflush(fd);
    $display("XUT_DONE nl=%0d", nl);
    $finish;
  end

  // ---- a hung harness ends the run
  initial begin
    repeat (200_000_000) @(posedge clk);
    $display("XUT_TIMEOUT cycle=%0d nl=%0d", cyc, nl);
    $finish;
  end

  // ---- correctness by construction, observed (spec §7.1)
  reg [63:0] last_change = 64'd0;
  reg        have_change = 1'b0;
  always @(posedge clk) begin
    if (u_top.u_ctrl.commit || u_top.u_ctrl.edge_we || u_top.u_ctrl.sample_take) begin
      if (have_change && (cyc - last_change) < MARGIN)
        $display("XUT_MARGIN_VIOLATION cycle=%0d last_change=%0d", cyc, last_change);
      if (u_top.u_ctrl.commit || u_top.u_ctrl.edge_we) begin
        last_change <= cyc;
        have_change <= 1'b1;
      end
    end
  end
endmodule
```

- [ ] **Step 4: Write the failing byte-exact test** — `tools/tests/test_hw_rtl.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The RTL harness transmits byte for byte what the reference emulator predicts, on
Icarus (container) and on xsim (Vivado), error paths included (Task 5a); and the
simulated harness reproduces the golden traces of real flops (Task 5b)."""

import pytest
from hw_toy import TOYFF_V, ToyDff, toy_map, toy_spec

from xut.hw import proto
from xut.hw.compile import compile_program
from xut.hw.hwsim import SIM_BUILD_ID, simulate
from xut.hw.image import MARGIN, MAXWORDS, W_END
from xut.hw.interp import EmuSlot, Harness
from xut.hw.replay import ModelDut
from xut.hw.selftest import CounterSim, PassthroughSim, selftest_programs
from xut.hw.slots import SELFTEST_SLOTS, dut_slot
from xut.hw.steps import Step, run_replies, session_steps
from xut.modelsrc import resolve
from xut.stimgen import VecBuilder
from xut.wrap import render_wrapper

SIMS = [
    pytest.param("iverilog", marks=pytest.mark.container),
    pytest.param("xsim", marks=pytest.mark.vivado),
]


def _toy(init: int, d0: int):
    cfg = f"i{init}d{d0}"
    m = toy_map(cfg, init)
    b = VecBuilder(m, seed=5)
    if d0:
        b.init(D=1)
    b.sample("p")  # power-on: Q = INIT
    b.cycle("C")  # captures the power-on D (t0)
    for d in (0, 1, 1, 0):
        b.set(D=d)
        b.cycle("C")
    vec = b.build()
    prog = compile_program(vec, m)
    return m, prog, dut_slot(m, render_wrapper(toy_spec(cfg, init), m), prog.t0), vec


#: The error-path steps ``_steps`` puts before the normal session.
N_ERROR_STEPS = 4


def _steps(progs):
    """The normal session, preceded and followed by every error path."""
    t2 = progs[2]
    bad_crc = bytearray(proto.load_frame(2, t2.words))
    bad_crc[-1] ^= 0xFF
    pre = [
        Step(proto.CMD_RUN, 2),  # noload
        Step(b"Z", 1),  # badcmd
        Step(bytes(bad_crc), 1),  # badcrc
        Step(proto.load_frame(9, [W_END]), 1),  # badslot
    ]
    post = [Step(proto.load_frame(2, t2.words), 1), Step(proto.CMD_RUN, 2)]  # used
    assert len(pre) == N_ERROR_STEPS
    return pre + session_steps(progs) + post


@pytest.mark.parametrize("sim", SIMS)
def test_rtl_matches_the_emulator_byte_for_byte(sim, tmp_path):
    a, b = _toy(0, 1), _toy(1, 0)
    slots = (*SELFTEST_SLOTS, a[2], b[2])
    progs = {**selftest_programs(), 2: a[1], 3: b[1]}
    steps = _steps(progs)
    r = simulate(
        slots,
        steps,
        sim,
        tmp_path / "sim",
        model_source=resolve("auto"),
        work_root=tmp_path,
        extra_files=(TOYFF_V,),
    )
    emu = Harness(
        SIM_BUILD_ID,
        [
            EmuSlot(16, 16, 0, "0" * 16, PassthroughSim()),
            EmuSlot(2, 8, 1, "00", CounterSim()),
            EmuSlot(1, 1, 1, a[1].t0, ModelDut(ToyDff, a[3].attrs, a[0])),
            EmuSlot(1, 1, 1, b[1].t0, ModelDut(ToyDff, b[3].attrs, b[0])),
        ],
        margin=MARGIN,
        maxwords=MAXWORDS,
    )
    expected = b"".join(emu.feed(s.send) for s in steps)
    assert r.margin_violations == []
    assert r.tx == expected
    session = r.replies[N_ERROR_STEPS : N_ERROR_STEPS + len(session_steps(progs))]
    toy_run = run_replies(session, progs)[2]
    assert toy_run.status == 0 and toy_run.samples[0] == "0"  # power-on Q = INIT = 0
    assert toy_run.samples[1] == "1"  # the first edge captured the power-on D = t0 = 1
```

The last three asserts also pin the power-on semantics on the RTL: the toy slot with INIT=0 and `t0` D=1 samples Q=0 before any edge, and Q=1 after the first edge, with no `set` in between.

Run `uv run pytest tools/tests/test_scope.py tools/tests/test_hw_rtl.py > .cache/pytest.log 2>&1; cat .cache/pytest.log`. Expected: `No module named 'xut.scope'` (then, after Step 2, `xut.hw.hwsim`).

- [ ] **Step 5: Implement `tools/xut/hw/steps.py`** (standard library only: the session layout is protocol, and `xut.hw.session` and the Pi-side tests use it without the simulator):

```python
# SPDX-License-Identifier: Apache-2.0
"""The host's side of one harness session, independent of how the bytes travel
(simulation testbench, UART on a rig, the emulator). Standard library only.

A session is ``I``, then per slot in slot order ``L`` (one reply line) and ``R`` (the run
line, one line per sample, the end line). ``slot_replies`` owns that indexing; the
simulator, the board session and the tests all use it rather than re-deriving it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from xut.hw import proto
from xut.hw.image import HwProgram

#: Lines in an ``R`` reply besides its samples: the run line and the end line.
RUN_FRAME_LINES = 2


@dataclass(frozen=True)
class Step:
    send: bytes
    lines: int  # the lines of the harness's reply


def session_steps(programs: dict[int, HwProgram]) -> list[Step]:
    """``I``, then per slot in order: ``L`` (one line) and ``R`` (run, samples, end)."""
    steps = [Step(proto.CMD_ID, 1)]
    for slot, p in sorted(programs.items()):
        steps.append(Step(proto.load_frame(slot, p.words), 1))
        steps.append(Step(proto.CMD_RUN, RUN_FRAME_LINES + len(p.labels)))
    return steps


def split_replies(data: bytes, steps: Sequence[Step]) -> list[bytes]:
    """``data`` cut into one reply per step by line counts; leftovers are an error."""
    out, pos = [], 0
    for s in steps:
        end = pos
        for _ in range(s.lines):
            j = data.find(b"\n", end)
            if j < 0:
                raise proto.ProtoError(f"reply to {s.send[:1]!r} truncated: {data[pos:][:80]!r}")
            end = j + 1
        out.append(data[pos:end])
        pos = end
    if pos != len(data):
        raise proto.ProtoError(
            f"{len(data) - pos} unexpected trailing byte(s): {data[pos:][:80]!r}"
        )
    return out


def slot_replies(replies: Sequence[bytes], slots: Iterable[int]) -> dict[int, tuple[bytes, bytes]]:
    """The raw ``(L reply, R reply)`` per slot of a ``session_steps`` session."""
    return {s: (replies[1 + 2 * k], replies[2 + 2 * k]) for k, s in enumerate(sorted(slots))}


def run_replies(replies: Sequence[bytes], slots: Iterable[int]) -> dict[int, proto.RunReply]:
    """The parsed ``R`` reply per slot."""
    return {s: proto.parse_run(run) for s, (_, run) in slot_replies(replies, slots).items()}
```

- [ ] **Step 6: Implement `tools/xut/hw/hwsim.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The harness in simulation (spec §7.1): Icarus in the xut-sim container, or xsim on the
host (Vivado sourced only in a subshell, via xut.runners.xsim.render_script).

``simulate`` builds one harness with the given slots, plays a host script into its UART
(``xut_hw_tb.sv``) and returns what the harness transmitted. ``sim_case`` (Task 5b) runs
every hardware-renderable configuration of a vector test through the simulated harness,
with the golden expected traces as the reference: the proof, before any board is
involved, that the harness, its compiler and its protocol reproduce the golden ``.xtr``.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from xut.container import executor_for
from xut.errors import XutError
from xut.hw.image import MARGIN, MAXWORDS
from xut.hw.slots import HW_HDL, HW_INCLUDES, HW_SOURCES, SlotBuild, render_cfg_vh, render_slots
from xut.hw.steps import Step, split_replies
from xut.modelsrc import ModelSource
from xut.runners.xsim import render_script
from xut.scope import scoped_run
from xut.slots import vivado_slot

SIM_BUILD_ID = 0x51AB0001  # simulation has no bitstream; any fixed value
#: The one memory cap of `xut hw sim`: its command scope, and each xsim run (Global Constraints).
HW_SIM_MEMORY_MAX = "16G"
CPB = 4  # xut_hw_tb.sv's UART clocks per bit
TB = "xut_hw_tb.sv"


class HwSimError(XutError, RuntimeError):
    """The simulated harness did not compile, did not finish, or answered malformed."""


def render_host(steps: Sequence[Step]) -> tuple[str, int]:
    """``host.memh`` for ``steps`` and its word count."""
    words: list[int] = []
    nl = 0
    for s in steps:
        words += list(s.send)
        nl += s.lines
        words.append((1 << 28) | nl)
    words.append(0xF << 28)
    return "".join(f"{w:08x}\n" for w in words), len(words)


@dataclass
class SimResult:
    tx: bytes
    replies: list[bytes]
    log: Path
    margin_violations: list[str]


def _iverilog(d: Path, files: list[str], ms: ModelSource, work_root: Path, timeout_s: int) -> str:
    ex = executor_for(ms, work_root)
    libs = [a for p in ms.search for a in ("-y", ex.guest(p))]
    comp = ["iverilog", "-g2012", "-o", "sim.vvp", "-s", "xut_hw_tb", "-s", "glbl", "-I", "."]
    comp += [*libs, "-Y", ".v", *files, ex.guest(ms.glbl)]
    log = d / "run.log"
    if ex.run(comp, cwd=d, log=log, timeout_s=timeout_s) != 0:
        raise HwSimError(f"iverilog: the harness did not compile (see {log})")
    ex.run(["vvp", "-n", "sim.vvp"], cwd=d, log=log, timeout_s=timeout_s)
    return log.read_text(errors="replace")


def _xsim(d: Path, files: list[str], timeout_s: int) -> str:
    """xsim through ``scoped_run`` at ``HW_SIM_MEMORY_MAX``, inside a host-wide
    ``vivado_slot()`` (Vivado sourced only in ``xsim.sh``'s subshell, as in the xsim
    runner)."""
    (d / "xsim.sh").write_text(render_script(d, files, "xut_hw_tb", [], {}, {}))
    log = d / "run.log"
    log.write_text("")
    with vivado_slot():  # host-wide bound on Vivado/xsim processes (PR #10)
        scoped_run(
            ["bash", "xsim.sh"],
            what="hwsim-xsim",
            memory_max=HW_SIM_MEMORY_MAX,
            cwd=d,
            log=log,
            timeout_s=timeout_s,
        )
    return log.read_text(errors="replace")


def simulate(
    slots: Sequence[SlotBuild],
    steps: Sequence[Step],
    sim: str,
    workdir: Path,
    *,
    model_source: ModelSource,
    work_root: Path,
    extra_files: Sequence[Path] = (),
    maxwords: int = MAXWORDS,
    margin: int = MARGIN,
    timeout_s: int = 1800,
) -> SimResult:
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    for f in (*HW_SOURCES, *HW_INCLUDES, TB):
        shutil.copy(HW_HDL / f, workdir / f)
    for f in extra_files:
        shutil.copy(f, workdir / Path(f).name)
    (workdir / "xut_hw_slots.v").write_text(render_slots(slots))
    (workdir / "xut_hw_cfg.vh").write_text(render_cfg_vh(slots, SIM_BUILD_ID, maxwords, margin))
    memh, n = render_host(steps)
    (workdir / "host.memh").write_text(memh)
    (workdir / "host.vh").write_text(
        f"// SPDX-License-Identifier: Apache-2.0\n`define XUT_HOST_WORDS {n}\n"
    )
    files = [*HW_SOURCES, "xut_hw_slots.v", *(Path(f).name for f in extra_files), TB]
    if sim == "iverilog":
        text = _iverilog(workdir, files, model_source, work_root, timeout_s)
    elif sim == "xsim":
        text = _xsim(workdir, files, timeout_s)
    else:
        raise HwSimError(f"unknown simulator {sim!r} (iverilog or xsim)")
    if "XUT_DONE" not in text:
        why = "timed out" if "XUT_TIMEOUT" in text else "did not finish"
        raise HwSimError(f"{sim}: the harness testbench {why} (see {workdir / 'run.log'})")
    tx_file = workdir / "harness_tx.txt"
    tx = bytes(int(x, 16) for x in tx_file.read_text().split())
    viol = [ln.strip() for ln in text.splitlines() if "XUT_MARGIN_VIOLATION" in ln]
    return SimResult(tx, split_replies(tx, steps), workdir / "run.log", viol)
```

- [ ] **Step 7: Run the byte-exact tests on both simulators.** Expected under 10 minutes, so report every 60 s:

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwrtl-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run pytest tools/tests/test_hw_rtl.py -k byte_for_byte -v > .cache/pytest-hwrtl.log 2>&1; cat .cache/pytest-hwrtl.log
```

Expected: `test_rtl_matches_the_emulator_byte_for_byte[iverilog]` and `[xsim]` pass. On a mismatch, `r.tx` and `expected` differ at some byte. Find the first differing line (write both to `.cache/` and diff the files) and decide from the protocol spec which side is wrong. Fix the RTL or the emulator, never the test. Pay particular attention to the handling of `lslot`/`lwords` after a failed load, and to the CRC of the `load` reply.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/scope.py tools/tests/test_scope.py tools/xut/hdl/hw/xut_hw_tb.sv tools/xut/hw/steps.py tools/xut/hw/hwsim.py tools/tests/test_hw_rtl.py
git commit -m "hw: capped scopes; simulate the harness on Icarus and xsim, byte-exact against the emulator" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5b: The shared planner, `xut hw sim`, and FDRE's golden trace reproduced

**Files:**
- Create: `tools/xut/hw/plan.py`, `tools/tests/test_hw_plan.py`
- Modify: `tools/xut/runners/sim.py` (`judge_trace`; `vector_check` uses it), `tools/xut/hw/hwsim.py` (`sim_case`), `tools/tests/test_hw_rtl.py` (the golden-reproduction test), `tools/xut/cli.py` (`xut hw sim`)

**Interfaces:**
- Produces (`xut.hw.plan`; consumed by `xut hw sim` here, by `xut hw build` in Task 6, by the hw runner in Task 10 and by nothing else, so all three run exactly the same configurations):
  - `CfgPlan(cfg: str, m: DutMap, prog: HwProgram, slot: SlotBuild, expected: Trace, seed: int, stim_sha256: str)`
  - `TestPlan(case: TestCase, items: list[CfgPlan], settled: dict[str, tuple[str, str]], groups: list[list[int]])` with `dut_slot(j) -> int` (the slot of a group's `j`-th member), where `settled` maps a configuration that never reaches hardware to `(status, reason)` (`skip` for `config_exclusions` and not-renderable, `error` otherwise) and `groups` holds indices into `items`, one list per bitstream; methods `members(g) -> list[CfgPlan]`, `slots(g) -> tuple[SlotBuild, ...]` (self-test slots first), `programs(g) -> dict[int, HwProgram]` (keyed by slot)
  - `plan_case(case: TestCase, ctx: RunContext) -> TestPlan`
- Produces (`xut.runners.sim`): `judge_trace(cd, actual, expected, *, x_observable, stim_sha256, problems=()) -> ConfigResult` and `S15_REASON`: the one samples → trace → compare step, shared by `vector_check`, `sim_case` and the hw runner; `vector_check` is refactored onto it
- Produces (`xut.hw.hwsim`): `sim_case(case, ctx, sim) -> list[ConfigResult]`, writing `build/hwsim-runs/<sim>/<model-source>/<test-id>/`
- CLI: `xut hw sim SELECTORS... [--sim iverilog|xsim] [--model-source auto] [--jobs N]`. It runs the python runner first for the selected vector tests, then `sim_case` per test. It prints `progress:` lines and exits 3 on any mismatch (it wins, as in `xut crosscheck`), otherwise 4 on any error, otherwise 0.

`xut hw sim` is a verification tool, not a runner. It writes no `result.json` and nothing in `status/`, because simulating the harness is evidence about the harness, not about the primitive. Its output lives under `build/hwsim-runs/`, whose layout `xut.crosscheck.gather` (`build/*/*/*/<test>/`) never matches. The primitive's hardware evidence comes only from silicon (the `hw` runner).

- [ ] **Step 1: Write the failing planner tests** — `tools/tests/test_hw_plan.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import dataclasses

import pytest
from test_golden import ToyDff
from test_runner_base import _case

from xut.formats import xtr
from xut.hw import hwsim
from xut.hw.hwsim import SIM_BUILD_ID, SimResult
from xut.hw.interp import EmuSlot, Harness
from xut.hw.plan import plan_case
from xut.hw.replay import ModelDut
from xut.hw.selftest import CounterSim, PassthroughSim
from xut.hw.slots import SELFTEST_SLOTS
from xut.hw.steps import split_replies
from xut.modelsrc import ModelSource
from xut.runners.base import NoPythonRun, RunContext, python_dir
from xut.runners.python import PythonRunner
from xut.runners.sim import S15_REASON
from xut.wrap import DutMap


def _ctx(tmp_path):
    return RunContext(tmp_path, "rtl", ModelSource("unisim-test", tmp_path / "ms"))


def test_plan_covers_every_python_configuration(tmp_path, toy):
    case = _case()  # 7series.TOYFF.L1.capture: init0, init1
    assert PythonRunner().run(case, _ctx(tmp_path)).status == "pass"
    plan = plan_case(case, _ctx(tmp_path))
    assert sorted(it.cfg for it in plan.items) == ["init0", "init1"] and plan.settled == {}
    assert plan.groups == [[0, 1]] or plan.groups == [[1, 0]]
    assert plan.slots(0)[:2] == SELFTEST_SLOTS and set(plan.programs(0)) == {0, 1, 2, 3}


def test_exclusions_are_settled_skips(tmp_path, toy):
    case = dataclasses.replace(_case(), config_exclusions={"hw": {"init1": "why not"}})
    PythonRunner().run(case, _ctx(tmp_path))
    plan = plan_case(case, _ctx(tmp_path))
    assert plan.settled == {"init1": ("skip", "excluded: why not")}


def test_no_python_run_raises(tmp_path, toy):
    with pytest.raises(NoPythonRun):
        plan_case(_case(), _ctx(tmp_path))


def _emulated_simulate(slots, steps, sim, workdir, **kw):
    """`simulate` without a simulator: the reference emulator answers the session."""
    workdir.mkdir(parents=True, exist_ok=True)

    def sim_for(s):
        if s.kind == "passthrough":
            return PassthroughSim()
        if s.kind == "counter":
            return CounterSim()
        m = DutMap.from_json(s.map_json)
        return ModelDut(ToyDff, m.attrs, m, two_state=True)

    emu = Harness(SIM_BUILD_ID, [EmuSlot(s.nin, s.nout, s.nclk, s.t0, sim_for(s)) for s in slots])
    tx = b"".join(emu.feed(st.send) for st in steps)
    return SimResult(tx, split_replies(tx, steps), workdir / "run.log", [])


def test_sim_case_judges_through_judge_trace_with_the_s15_guard(tmp_path, toy, monkeypatch):
    """An expected trace without samples is an error, never a pass (ruling S15), on the
    `xut hw sim` path too; the other configuration still passes."""
    case, ctx = _case(), _ctx(tmp_path)
    assert PythonRunner().run(case, ctx).status == "pass"
    exp = python_dir(ctx, case) / "cfg-init0" / "expected.xtr"
    xtr.dump(xtr.Trace(xtr.load(exp).header), exp)
    monkeypatch.setattr(hwsim, "simulate", _emulated_simulate)
    out = {r.cfg: r for r in hwsim.sim_case(case, ctx, "iverilog")}
    assert out["init0"].status == "error" and out["init0"].reason == S15_REASON
    assert out["init1"].status == "pass"
```

- [ ] **Step 2: Implement `tools/xut/hw/plan.py`** (as follows), then `sim_case`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What the hardware harness runs for one vector test: every configuration the python run
generated, compiled for the harness or settled without it (a skip or an error, with the
reason), and packed into bitstreams (``xut.hw.slots.pack``)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from xut.formats import xtr, xvec
from xut.hw.compile import HwUnrenderable, compile_program
from xut.hw.image import HwProgram
from xut.hw.selftest import selftest_programs
from xut.hw.slots import SELFTEST_SLOTS, SlotBuild, dut_slot, pack
from xut.runners.base import RunContext, error_reason, expected_trace, load_generated, sha256_file
from xut.testspec import TestCase, exclusions_for
from xut.wrap import DutMap


@dataclass
class CfgPlan:
    cfg: str
    m: DutMap
    prog: HwProgram
    slot: SlotBuild
    expected: xtr.Trace
    seed: int
    stim_sha256: str


@dataclass
class TestPlan:
    __test__ = False  # not a pytest class

    case: TestCase
    items: list[CfgPlan]
    settled: dict[str, tuple[str, str]]  # cfg -> (skip | error, reason): never on hardware
    groups: list[list[int]]  # indices into items, one list per bitstream

    def members(self, g: int) -> list[CfgPlan]:
        return [self.items[i] for i in self.groups[g]]

    def slots(self, g: int) -> tuple[SlotBuild, ...]:
        return (*SELFTEST_SLOTS, *(it.slot for it in self.members(g)))

    @staticmethod
    def dut_slot(j: int) -> int:
        """The harness slot of a group's ``j``-th member: after the self-test slots."""
        return len(SELFTEST_SLOTS) + j

    def programs(self, g: int) -> dict[int, HwProgram]:
        progs = selftest_programs()
        for j, it in enumerate(self.members(g)):
            progs[self.dut_slot(j)] = it.prog
        return progs


def plan_case(case: TestCase, ctx: RunContext) -> TestPlan:
    """Every configuration of the python run (``configs.json``, errored ones included):
    ``config_exclusions`` for ``hw`` -> skip; not hardware-renderable -> skip with the
    validator's reasons; no expected trace or any other failure -> error; the rest are
    compiled and packed."""
    excluded = exclusions_for(case, "hw")
    settled: dict[str, tuple[str, str]] = {}
    items: list[CfgPlan] = []
    for cfg, src, _ in load_generated(ctx, case):
        pat = next((g for g in excluded if fnmatch.fnmatchcase(cfg, g)), None)
        if pat is not None:
            settled[cfg] = ("skip", f"excluded: {excluded[pat]}")
            continue
        try:
            exp = xtr.load(expected_trace(ctx, case, cfg))
            vec = xvec.load(src / "stim.xvec")
            m = DutMap.load(src / "dut" / "xut_dut.map.json")
            prog = compile_program(vec, m)
            slot = dut_slot(m, (src / "dut" / "xut_dut.v").read_text(), prog.t0)
        except HwUnrenderable as e:
            settled[cfg] = ("skip", f"not hardware-renderable: {e}")
            continue
        except Exception as e:  # recorded, never dropped (spec §14)
            settled[cfg] = ("error", error_reason(e))
            continue
        items.append(CfgPlan(cfg, m, prog, slot, exp, vec.seed, sha256_file(src / "stim.xvec")))
    return TestPlan(case, items, settled, pack([it.slot for it in items]))
```

Then add the **one shared judging step** to `tools/xut/runners/sim.py` (must-fix: the samples → trace → compare path exists once). `judge_trace` is `vector_check`'s body after the trace exists: the ruling-S15 guard (an expected trace without samples is an `error`: zero evidence is never a pass), `trace.xtr`, `compare`, `mismatches.txt`, and the reason from any extra problems plus the first three mismatches. `vector_check` keeps parsing `raw.txt` and calls it; `sim_case` (here) and the hw runner (Task 10) call it with a trace built from harness samples:

```python
#: Ruling S15: an expected trace without samples is never a pass.
S15_REASON = "expected trace has no samples (ruling S15)"


def judge_trace(
    cd: Path,
    actual: xtr.Trace,
    expected: xtr.Trace,
    *,
    x_observable: bool,
    stim_sha256: str | None,
    problems: Sequence[str] = (),
) -> ConfigResult:
    """Judge one configuration's actual trace: write ``trace.xtr`` and ``mismatches.txt``
    in ``cd`` and return pass or fail. ``problems`` are already-worded reasons that fail the
    configuration whatever the comparison says (model error lines, nondeterminism)."""
    cfg = cfg_of(actual.header)
    if not expected.samples:
        return ConfigResult(cfg, "error", S15_REASON)
    xtr.dump(actual, cd / "trace.xtr")
    mm = xtr.compare(expected, actual, x_observable=x_observable)
    (cd / "mismatches.txt").write_text("".join(f"{x}\n" for x in mm))
    reasons = [*problems, *(str(x) for x in mm[:3])]
    return ConfigResult(
        cfg,
        "fail" if mm or problems else "pass",
        "; ".join(reasons) or None,
        stim_sha256,
        sha256_file(cd / "trace.xtr"),
        len(mm),
    )
```

and `vector_check`'s tail becomes:

```python
    cfg = cfg_of(header)
    if not expected.samples:  # validate refuses such a stimulus; never pass on nothing
        return ConfigResult(cfg, "error", S15_REASON)
    raw = cd / "raw.txt"
    if not raw.is_file():
        return ConfigResult(cfg, "error", "no raw.txt (simulation did not start)")
    actual = raw_to_trace(raw.read_text(), labels, m, header)
    errors = model_errors(run_text)
    return judge_trace(
        cd,
        actual,
        expected,
        x_observable=x_observable,
        stim_sha256=sha256_file(cd / "stim.xvec"),
        problems=[_errors_reason(errors)] if errors else [],
    )
```

(Add `from collections.abc import Sequence` to `runners/sim.py`. The step-2 tests of `vector_check` must pass unchanged: same reasons, same files.)

Then add ``sim_case`` to `tools/xut/hw/hwsim.py`, with these imports added to its block:

```python
import json
from dataclasses import asdict

from xut.hw import proto
from xut.hw.plan import plan_case
from xut.hw.replay import samples_to_trace
from xut.hw.selftest import COUNT_SLOT, PASS_SLOT
from xut.hw.selftest import check as selftest_check
from xut.hw.steps import run_replies, session_steps
from xut.runners.base import ConfigResult, RunContext, error_reason, trace_header
from xut.runners.sim import judge_trace
from xut.testspec import TestCase
```

```python
def sim_case(case: TestCase, ctx: RunContext, sim: str) -> list[ConfigResult]:
    """Every configuration of vector test ``case`` through the simulated harness, judged by
    ``judge_trace`` against the golden expected trace (2-state, as silicon would be)."""
    out_dir = ctx.root / "build" / "hwsim-runs" / sim / ctx.model_source.name / case.id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    plan = plan_case(case, ctx)
    outcomes = {c: ConfigResult(c, st, why) for c, (st, why) in plan.settled.items()}
    runner = f"hwsim-{sim}"
    for g in range(len(plan.groups)):
        members = plan.members(g)
        programs = plan.programs(g)
        steps = session_steps(programs)
        try:
            r = simulate(
                plan.slots(g),
                steps,
                sim,
                out_dir / f"g{g}",
                model_source=ctx.model_source,
                work_root=ctx.root,
            )
            runs = run_replies(r.replies, programs)
            bad = [selftest_check(s, runs[s]) for s in (PASS_SLOT, COUNT_SLOT)]
            problems = [b for b in bad if b] + r.margin_violations
            if problems:
                raise HwSimError("; ".join(problems))
        except Exception as e:
            for it in members:
                outcomes[it.cfg] = ConfigResult(it.cfg, "error", error_reason(e), it.stim_sha256)
            continue
        for j, it in enumerate(members):
            run = runs[plan.dut_slot(j)]
            cd = out_dir / f"cfg-{it.cfg}"
            cd.mkdir()
            if run.status != proto.STATUS_CODE["ok"]:
                why = f"harness status {proto.STATUS.get(run.status, run.status)}"
                outcomes[it.cfg] = ConfigResult(it.cfg, "error", why, it.stim_sha256)
                continue
            header = trace_header(runner, case, it.cfg, ctx) | {"seed": str(it.seed)}
            actual = samples_to_trace(run.samples, it.prog.labels, it.m, header)
            outcomes[it.cfg] = judge_trace(
                cd, actual, it.expected, x_observable=False, stim_sha256=it.stim_sha256
            )
    result = [outcomes[c] for c in sorted(outcomes)]
    (out_dir / "report.json").write_text(json.dumps([asdict(o) for o in result], indent=1) + "\n")
    return result
```

(`trace_header` names flow `ctx.flow`, which is `rtl` here: `xut hw sim` runs with an `rtl` context.)

- [ ] **Step 3: Add the golden-reproduction test** to `tools/tests/test_hw_rtl.py`. Add these imports to the file's import block:

```python
from xut import crosscheck
from xut.hw.hwsim import sim_case
from xut.paths import repo_root
from xut.runners.base import RunContext
from xut.runners.python import PythonRunner
from xut.testspec import discover, select
```

and append:

```python
def _flops_case(test_id: str):
    return select(discover(repo_root()), [test_id])[0]


@pytest.mark.slow
@pytest.mark.parametrize("sim", SIMS)
@pytest.mark.parametrize("test_id", ["7series.FDRE.L2.exhaustive", "7series.FDCE.L1.clear_over_ce"])
def test_simulated_harness_reproduces_the_golden_trace(sim, test_id, tmp_path):
    case = _flops_case(test_id)
    ctx = RunContext(tmp_path, "rtl", resolve("auto"))
    assert PythonRunner().run(case, ctx).status == "pass"
    outcomes = sim_case(case, ctx, sim)
    bad = [o for o in outcomes if o.status not in ("pass", "skip")]
    assert not bad, bad
    assert any(o.status == "pass" for o in outcomes)
    # build/hwsim-runs/ is not a runner directory: crosscheck never sees it
    views = crosscheck.gather(tmp_path, case.id)
    assert all(not r.startswith("hwsim") for vs in views.values() for (_, r) in vs)
```

- [ ] **Step 4: Add `xut hw sim`** to `tools/xut/cli.py`:

```python
@hw_grp.command("sim")
@click.argument("selectors", nargs=-1)
@click.option(
    "--sim", type=click.Choice(["iverilog", "xsim"]), default="iverilog", show_default=True
)
@click.option("--model-source", default="auto", show_default=True)
@click.option("--jobs", type=click.IntRange(min=1, max=24), default=1, show_default=True)
def hw_sim_cmd(selectors: tuple[str, ...], sim: str, model_source: str, jobs: int) -> None:
    """Run vector tests' configurations through the simulated harness (spec §7.1) and
    compare with the golden traces. Exit 0: all pass or skip; 3: any mismatch (it wins,
    as in xut crosscheck); 4: otherwise any error."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    from xut.hw.hwsim import sim_case
    from xut.modelsrc import resolve
    from xut.run import run_tests
    from xut.runners.base import RunContext
    from xut.testspec import discover

    root = repo_root()
    cases = [c for c in _select_cases(root, discover(root), selectors) if c.style == "vector"]
    ctx = RunContext(root, "rtl", resolve(model_source), jobs=jobs)
    run_tests(cases, ["python"], ctx)
    t0 = time.monotonic()
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = pool.map(lambda c: sim_case(c, ctx, sim), cases)
        for done, (case, outcomes) in enumerate(zip(cases, results, strict=True), start=1):
            counts = {
                s: sum(o.status == s for o in outcomes) for s in ("pass", "fail", "error", "skip")
            }
            click.echo(
                f"progress: done={done} total={len(cases)} elapsed_s={time.monotonic() - t0:.1f}"
                f"  {case.id} {counts}"
            )
            for o in outcomes:
                seen.add(o.status)
                if o.status in ("fail", "error"):
                    click.echo(f"  {o.cfg}: {o.status}: {o.reason}")
    raise SystemExit(3 if "fail" in seen else 4 if "error" in seen else 0)
```

- [ ] **Step 5: Prove the golden reproduction for FDRE (and FDCE's async clear).** First the two pinned tests, then the whole flops unit on both simulators:

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwrtl-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run pytest tools/tests/test_hw_rtl.py -k golden -v > .cache/pytest-hwgolden.log 2>&1; cat .cache/pytest-hwgolden.log
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsim-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run xut hw sim 'unit:flops' --sim iverilog --jobs 8 > .cache/hwsim-flops-iverilog.log 2>&1; echo "exit=$?"
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsim-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run xut hw sim 'unit:flops' --sim xsim --jobs 2 > .cache/hwsim-flops-xsim.log 2>&1; echo "exit=$?"
```

- **Estimate:** about 32 hardware-declared flops vector tests, each one or two harness simulations of about 10–60 s. On Icarus with 8 jobs that is about 3–6 minutes (report every 60 s). xsim elaborates slower: about 32 × 1–2 min ÷ 2 ≈ 15–30 minutes (report every 5 minutes). Anchor the ETA on the `progress:` lines.
- **Expected:** `exit=0` for both runs. Every configuration is `pass` or `skip`. Each skip reason is either the test's `config_exclusions` (IS_D_INVERTED) or the validator's `hw_reasons`.
- A `fail` here is a harness or compiler bug (the golden model and the UNISIM simulators already agree on these tests, from step 2). Debug it with `build/hwsim-runs/<sim>/unisim-2025.2/<test>/g<g>/run.log` and the `mismatches.txt`, fix it, and re-run. Never relax the comparison.

- [ ] **Step 6: Lint, log, commit, push and open PR A**

```bash
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
systemd-run --user --scope --slice=vivado.slice --unit=xut-pytest-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run pytest -n 4 --dist loadfile -m "not slow" > .cache/pytest-all.log 2>&1; tail -n 5 .cache/pytest-all.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
git add tools/xut/hw/plan.py tools/xut/hw/hwsim.py tools/xut/cli.py tools/tests/test_hw_plan.py tools/tests/test_hw_rtl.py
git commit -m "hw: the shared planner, sim_case and xut hw sim; FDRE's golden trace reproduced in simulation" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(`tail` reads the log file, not a pipe.) Write `log/<ts>-infra-hw-harness-harness.md`: the byte-exact results per simulator, the `xut hw sim 'unit:flops'` summary for both simulators (pass/skip counts, durations) and the next steps. Commit it, push, and open PR A:

```bash
git add log/<ts>-infra-hw-harness-harness.md
git commit -m "infra: log the hw harness session" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


```bash
git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/mithro/xilinx-unittests.git infra/hw-harness
gh pr create --base main --title "infra: hw harness — program compiler, reference interpreter, harness RTL and simulation" --body-file .cache/pr-a.md
```

The PR body lists Tasks 1–5b, the per-task review outcomes and Review Focus items 2, 3 and 5, and ends with the Claude Code line. Run the §13.4 review gate with sequential reviewers.

---

---

## PR B: the Vivado flow (branch `infra/hw-vivado`)

### Task 6: The Vivado batch build (constraints, post-flow DUT check, build IDs, bitstream cache)

**Files:**
- Create: `tools/xut/hw/vivado.py`, `hw/boards/arty_a7_35t/board.xdc`, `tools/tests/test_hw_vivado.py`
- Modify: `tools/xut/cli.py` (`xut hw build`)

**Interfaces:**
- Consumes: `xut.scope` (Task 5a): `scoped_run`, `VIVADO_MEMORY_MAX`, `OOM_RCS`; `xut.slots.vivado_slot()` (PR #10).
- Produces (`xut.hw.vivado`):
  - `PART = "xc7a35ticsg324-1L"`, `BOARD = "arty_a7_35t"`, `board_xdc() -> Path`, `BUILD_TIMEOUT_S = 3600`, `ALLOWED_CRITICAL: tuple[str, ...] = ()`
  - `build_tcl() -> str`, `build_script() -> str`, `post_route_tcl(slots) -> str`
  - `check_dut_cells(text, slots) -> list[str]` (spec §6's post-flow DUT check), `check_latency(text) -> tuple[dict[str, float], list[str]]`, `LATENCY_BUDGET_NS = 20.0`
  - `FlowMismatch(BuildError)`: the post-flow DUT check failed (spec §8 `flow-mismatch`)
  - `build_inputs(slots, *, maxwords, margin, build_id) -> dict[str, str]`
  - `build_key(slots, vivado, *, maxwords, margin) -> str`, `build_id_of(key) -> int`
  - `Bitstream(path, key, build_id, sha256, manifest)`, `BuildError`
  - `vivado_version(scratch) -> str`
  - `ensure_bitstream(slots, *, cache_root, vivado, maxwords=MAXWORDS, margin=MARGIN, timeout_s=BUILD_TIMEOUT_S) -> Bitstream`
  - `VivadoBuilder(root, cache_root=None)` with `version() -> str` and `ensure(slots) -> Bitstream`, plus the `Builder` Protocol (the same two methods), which Task 9a's `FakeBuilder` also implements
- CLI: `xut hw build SELECTORS... [--jobs N<=4]` builds (or finds in the cache) every bitstream the selected vector tests need, printing `progress:` lines.

Rules:

- **Deterministic build IDs.** `build_key` is the sha256 of the part, the Vivado version line and every build input (harness RTL, generated slots, cfg, constraints, board XDC, build script), computed with the build ID set to 0. The build ID is the key's first 32 bits. The same slots on the same Vivado always get the same key, the same ID and the same cache entry. Vivado's `.bit` header carries a date, so bitstream *bytes* are not reproducible; the manifest records their sha256 per build.
- **The ID is visible on the board.** It is compiled into the harness (the `I` reply's `build=`), and it is also the bitstream's `BITSTREAM.CONFIG.USERID`.
- **Scoped, bounded, strict.** Vivado runs only through `scoped_run` (16G) inside `vivado_slot()` (PR #10's host-wide slots, 4 by default). It is sourced in a subshell, never with `XIL_TIMING`. The build is an error when:
  - a constraint matched nothing (`XUT_CONSTRAINT_EMPTY`, exit 4);
  - timing did not close (`XUT_TIMING_FAILED`, exit 3);
  - there is any `CRITICAL WARNING` not listed in `ALLOWED_CRITICAL` (each entry needs a comment justifying it);
  - Vivado was OOM-killed (retryable: lower the parallelism, never raise the cap);
  - Vivado exited non-zero or wrote no bitstream;
  - the **post-flow DUT check** (spec §6, ruling S49 I3) fails: after `route_design`, `post_route.tcl` writes `dut_cells.txt` with every DUT instance's `REF_NAME` and the value of every attribute its configuration sets. `check_dut_cells` compares them with the slot's map; any difference (a retargeted cell, an absorbed inversion, a changed INIT, a missing cell) raises `FlowMismatch`, which the hw runner reports as a `flow-mismatch` (never a DUT result);
  - the **DUT clock latency** is over budget: `post_route.tcl` also measures, per DUT clock, the routed delay from its flip-flop to the BUFG plus the BUFG's global net (`XUT_LATENCY <clock> <ns>`). `(MARGIN − 2)` periods cover the datapath (`set_max_delay -datapath_only`), and the remaining 2 periods (20 ns) must cover clock-to-Q, the BUFG and that latency: `check_latency` fails the build when latency + 2 ns exceeds `LATENCY_BUDGET_NS`, or when a latency could not be measured (never a pass by default).
- **Smaller bitstreams.** `BITSTREAM.GENERAL.COMPRESS TRUE` (less to `scp` through the jump host and to shift over JTAG).
- **Cache.** `.cache/hw/bit/<key>/`. A post-flow DUT check failure is cached too (`flow_mismatch.json`, no bitstream) and re-raised from the cache: the same slots on the same Vivado fail the same way, so nothing is rebuilt. A build writes to `<key>.tmp-<pid>-<rand>/` under a per-key `flock` and renames it into place when it is complete, so a concurrent or interrupted build never leaves a half-written entry. A failed build's temporary directory is kept for diagnosis and never used.

- [ ] **Step 1: Create the stacked worktree**

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git fetch origin && git worktree add ../xilinx-unittests-worktrees/infra-hw-vivado -b infra/hw-vivado infra/hw-harness
cd ../xilinx-unittests-worktrees/infra-hw-vivado
mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
git config core.hooksPath tools/hooks
```

- [ ] **Step 2: Write the board constraints** — `hw/boards/arty_a7_35t/board.xdc`. First confirm every pin against Digilent's master XDC (`Arty-A7-35-Master.xdc` in github.com/Digilent/digilent-xdc). Record the file's commit in the log entry; do not copy its text.

```tcl
# SPDX-License-Identifier: Apache-2.0
# Digilent Arty A7-35T (xc7a35ticsg324-1L): the pins the stepped harness uses.
# Pins checked against Digilent's Arty-A7-35-Master.xdc (see the step-3 log entry).
set_property -dict { PACKAGE_PIN E3  IOSTANDARD LVCMOS33 } [get_ports { CLK100MHZ }]
create_clock -name sysclk -period 10.000 -waveform {0.000 5.000} [get_ports { CLK100MHZ }]
set_property -dict { PACKAGE_PIN D10 IOSTANDARD LVCMOS33 } [get_ports { uart_rxd_out }]
set_property -dict { PACKAGE_PIN A9  IOSTANDARD LVCMOS33 } [get_ports { uart_txd_in }]
set_property -dict { PACKAGE_PIN H5  IOSTANDARD LVCMOS33 } [get_ports { led[0] }]
set_property -dict { PACKAGE_PIN J5  IOSTANDARD LVCMOS33 } [get_ports { led[1] }]
set_property -dict { PACKAGE_PIN T9  IOSTANDARD LVCMOS33 } [get_ports { led[2] }]
set_property -dict { PACKAGE_PIN T10 IOSTANDARD LVCMOS33 } [get_ports { led[3] }]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property CFGBVS VCCO [current_design]
# The UART and the LEDs are asynchronous to everything (timing is out of scope, spec §2).
set_false_path -from [get_ports { uart_txd_in }]
set_false_path -to [get_ports { uart_rxd_out led[*] }]
```

- [ ] **Step 3: Write the failing tests.** `tools/tests/test_hw_vivado.py` (pure-Python parts, plus one `vivado`-marked build in Task 7):

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest
from hw_toy import toy_map, toy_spec

from xut.hw import vivado
from xut.hw.slots import SELFTEST_SLOTS, dut_slot
from xut.wrap import render_wrapper


def _slots(init=0):
    m = toy_map("c", init)
    return (*SELFTEST_SLOTS, dut_slot(m, render_wrapper(toy_spec("c", init), m), "0"))


def test_key_is_deterministic_and_input_sensitive():
    k1 = vivado.build_key(_slots(), "vivado v2025.2 (64-bit)", maxwords=8192, margin=16)
    assert k1 == vivado.build_key(_slots(), "vivado v2025.2 (64-bit)", maxwords=8192, margin=16)
    assert k1 != vivado.build_key(_slots(1), "vivado v2025.2 (64-bit)", maxwords=8192, margin=16)
    assert k1 != vivado.build_key(_slots(), "vivado v2025.1 (64-bit)", maxwords=8192, margin=16)
    assert k1 != vivado.build_key(_slots(), "vivado v2025.2 (64-bit)", maxwords=8192, margin=12)
    assert vivado.build_id_of(k1) == int(k1[:8], 16)


def test_build_inputs_carry_the_id_and_everything_the_key_hashes():
    ins = vivado.build_inputs(_slots(), maxwords=8192, margin=16, build_id=0xCAFEF00D)
    assert "`define XUT_HW_BUILD_ID 32'hcafef00d" in ins["xut_hw_cfg.vh"]
    assert set(ins) >= {
        "xut_hw_top.sv",
        "xut_hw_msgs.vh",
        "xut_hw_slots.v",
        "timing.tcl",
        "post_route.tcl",
        "board.xdc",
        "build.tcl",
    }


def test_build_script_sources_vivado_only_in_a_subshell_and_never_xil_timing():
    text = vivado.build_script()
    head = text.split("bash -c", 1)[0]
    assert "settings64" not in head and "XIL_TIMING" not in text
    assert "vivado -mode batch" in text


def test_build_tcl_fails_on_timing_and_sets_userid():
    tcl = vivado.build_tcl()
    assert "XUT_TIMING_FAILED" in tcl and "exit 3" in tcl
    assert "BITSTREAM.CONFIG.USERID" in tcl and "source timing.tcl" in tcl
    assert tcl.index("synth_design") < tcl.index("source timing.tcl") < tcl.index("place_design")
    assert (
        tcl.index("route_design")
        < tcl.index("source post_route.tcl")
        < tcl.index("write_bitstream")
    )
    assert "BITSTREAM.GENERAL.COMPRESS TRUE" in tcl


def test_every_vivado_run_takes_a_host_wide_slot(tmp_path, monkeypatch):
    """`vivado -version` and builds run only inside PR #10's `vivado_slot()`."""
    from contextlib import contextmanager

    held = []

    @contextmanager
    def slot():
        held.append(True)
        yield
        held.pop()

    def fake_run(argv, *, what, memory_max, cwd, log, timeout_s):
        assert held, f"{what} ran outside a vivado_slot()"
        Path(log).write_text("vivado v2025.2 (64-bit)\n")
        return 0

    monkeypatch.setattr(vivado, "vivado_slot", slot)
    monkeypatch.setattr(vivado, "scoped_run", fake_run)
    monkeypatch.setattr(vivado, "_VERSION", {})
    assert vivado.VivadoBuilder(tmp_path).version() == "vivado v2025.2 (64-bit)"
    with pytest.raises(vivado.BuildError):  # the fake "build" writes no bitstream
        vivado.VivadoBuilder(tmp_path).ensure(_slots())


def test_a_cached_dut_check_failure_is_raised_without_a_rebuild(tmp_path, monkeypatch):
    def no_vivado(*a, **k):
        raise AssertionError("Vivado must not run for a cached failure")

    monkeypatch.setattr(vivado, "scoped_run", no_vivado)
    key = vivado.build_key(_slots(), "v", maxwords=8192, margin=16)
    d = tmp_path / "bit" / key
    d.mkdir(parents=True)
    (d / "flow_mismatch.json").write_text(
        '{"key": "k", "dut_check": "fail", "detail": "slot 2: X"}'
    )
    with pytest.raises(vivado.FlowMismatch, match="slot 2: X .cached"):
        vivado.ensure_bitstream(_slots(), cache_root=tmp_path, vivado="v")


def test_post_route_tcl_queries_every_dut_and_clock():
    tcl = vivado.post_route_tcl(_slots())
    assert "get_cells -quiet u_slots/u_dut_s2/dut" in tcl and "foreach a {INIT}" in tcl
    assert "xut_latency dclk_s1_0 " in tcl and "xut_latency dclk_s2_0 " in tcl


def _cells(**over):
    row = {"ref": "TOYFF", "INIT": "1'b0"} | over
    return f"2\t{row['ref']}\tINIT={row['INIT']}\n"


def test_dut_check_passes_a_faithful_implementation():
    assert vivado.check_dut_cells(_cells(), _slots()) == []
    assert vivado.check_dut_cells(_cells(INIT="1'h0"), _slots()) == []  # same value, other radix
    assert vivado._same("10.000", "10.0") and vivado._same('"TRUE"', "true")
    assert not vivado._same("10.5", "10.0")


@pytest.mark.parametrize(
    "text,match",
    [
        (_cells(ref="LUT1"), "REF_NAME LUT1"),
        (_cells(INIT="1'b1"), "INIT"),
        ("2\tMISSING\n", "no DUT cell"),
        ("", "no DUT cell"),
    ],
)
def test_dut_check_flags_a_retargeted_or_missing_cell(text, match):
    problems = vivado.check_dut_cells(text, _slots())
    assert problems and match in problems[0]


def test_latency_budget():
    lat, bad = vivado.check_latency("XUT_LATENCY dclk_s1_0 3.25\nXUT_LATENCY dclk_s2_0 17.5\n")
    assert lat == {"dclk_s1_0": 3.25, "dclk_s2_0": 17.5} and bad == [
        "dclk_s2_0: 17.500 ns + 2.0 ns > 20.0 ns"
    ]
    assert vivado.check_latency("XUT_LATENCY dclk_s1_0 unknown\n")[1] == [
        "dclk_s1_0: latency could not be measured"
    ]


def test_log_classification():
    ok = "XUT_TIMING wns=1.2 whs=0.05\nXUT_BUILD_OK\n"
    assert vivado.classify_log(ok, 0) is None
    assert "constraint" in vivado.classify_log("XUT_CONSTRAINT_EMPTY in_s\n", 4)
    assert "timing" in vivado.classify_log("XUT_TIMING_FAILED wns=-0.3 whs=0.1\n", 3)
    assert "CRITICAL" in vivado.classify_log(ok + "CRITICAL WARNING: [Foo 1-2] bar\n", 0)
    assert "OOM" in vivado.classify_log("", 137)
    assert "rc 1" in vivado.classify_log("ERROR: x\n", 1)
```

Run it; expected: `No module named 'xut.hw.vivado'`.

- [ ] **Step 4: Implement `tools/xut/hw/vivado.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The Vivado batch build of a harness bitstream (spec §7.1; flow ``vivado``, spec §6).

The build key is the sha256 of the part, the Vivado version and every build input with
the build ID set to 0; the build ID is the key's first 32 bits. So the same slots on the
same Vivado always get the same ID and the same cache entry, and the ID (compiled into
the harness and set as the bitstream's USERID) tells the host which bitstream a board
runs. Vivado runs only in a subshell that sources settings64.sh (never XIL_TIMING),
inside ``scoped_run`` (16G) and a host-wide ``vivado_slot()`` (PR #10).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import threading
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from xut.errors import XutError
from xut.hw.image import MARGIN, MAXWORDS
from xut.hw.slots import (
    HW_HDL,
    HW_INCLUDES,
    HW_SOURCES,
    SlotBuild,
    render_cfg_vh,
    render_slots,
    timing_tcl,
)
from xut.paths import VIVADO_SETTINGS, repo_root
from xut.scope import OOM_RCS, VIVADO_MEMORY_MAX, scoped_run
from xut.slots import vivado_slot
from xut.wrap import WrapError, literal_value

PART = "xc7a35ticsg324-1L"
BOARD = "arty_a7_35t"
BUILD_TIMEOUT_S = 3600
BUILD_OK = "XUT_BUILD_OK"
#: CRITICAL WARNING ids a build may show. Empty: every one is a build error until a
#: reviewed entry (with a comment saying why it is benign) is added here.
ALLOWED_CRITICAL: tuple[str, ...] = ()
_CRITICAL = re.compile(r"^CRITICAL WARNING: \[([^\]]+)\]", re.MULTILINE)
_TIMING = re.compile(r"^XUT_TIMING wns=(\S+) whs=(\S+)$", re.MULTILINE)


class BuildError(XutError, RuntimeError):
    """A bitstream build failed; the message says why and where the log is."""


class FlowMismatch(BuildError):
    """The post-flow DUT check (spec §6) failed: the implemented DUT cell or one of its
    attributes differs from the configuration. Spec §8 ``flow-mismatch``."""


#: The 2 system periods (MARGIN - 2 cover the datapath) left for clock-to-Q, the BUFG and
#: the DUT clock's routed latency (spec §7.1).
LATENCY_BUDGET_NS = 20.0
#: Added to the measured net delays: flip-flop clock-to-Q plus the BUFG cell.
CLK_TO_Q_AND_BUFG_NS = 2.0
_LATENCY = re.compile(r"^XUT_LATENCY (\S+) (\S+)$", re.MULTILINE)


def post_route_tcl(slots: Sequence[SlotBuild]) -> str:
    """Sourced after route_design: writes ``../dut_cells.txt`` (one line per DUT slot:
    ``<k> TAB <REF_NAME> TAB <ATTR>=<value> ...``, or ``<k> TAB MISSING``) and prints one
    ``XUT_LATENCY <clock> <ns|unknown>`` line per DUT clock. ``get_net_delays`` reports
    ``SLOW_MAX`` in ps (Task 7 checks the unit against ``report_timing`` on one path)."""
    out = [
        "# SPDX-License-Identifier: Apache-2.0",
        "# GENERATED by xut.hw.vivado: sourced after route_design by build.tcl. Do not edit.",
        "proc xut_net_max {net} {",
        "  set n [get_nets -quiet $net]",
        "  if {[llength $n] != 1} { return -1 }",
        "  set d [get_net_delays -quiet -of_objects $n]",
        "  if {[llength $d] == 0} { return -1 }",
        "  return [lindex [lsort -real [get_property SLOW_MAX $d]] end]",
        "}",
        "proc xut_latency {name q g} {",
        "  set a [xut_net_max $q]",
        "  set b [xut_net_max $g]",
        '  if {$a < 0 || $b < 0} { puts "XUT_LATENCY $name unknown"; return }',
        '  puts "XUT_LATENCY $name [expr {($a + $b) / 1000.0}]"',
        "}",
        "set fh [open ../dut_cells.txt w]",
    ]
    for k, s in enumerate(slots):
        if s.kind != "dut":
            continue
        attrs = " ".join(sorted(json.loads(s.map_json)["attrs"]))
        out += [
            f"set c [get_cells -quiet u_slots/u_dut_s{k}/dut]",
            "if {[llength $c] != 1} {",
            f'  puts $fh "{k}\tMISSING"',
            "} else {",
            f'  set line "{k}\t[get_property REF_NAME $c]"',
            f'  foreach a {{{attrs}}} {{ append line "\t$a=[get_property $a $c]" }}',
            "  puts $fh $line",
            "}",
        ]
    out.append("close $fh")
    for k, s in enumerate(slots):
        for i in range(s.nclk):
            out.append(f"xut_latency dclk_s{k}_{i} u_slots/dclk_s{k}_{i} u_slots/gclk_s{k}_{i}")
    return "\n".join(out) + "\n"


def _same(got: str | None, want: str) -> bool:
    """One attribute value as configured and as Vivado reports it: equal Verilog literals
    (any radix), equal reals (``10.0`` against ``10.000``), or equal strings ignoring
    quotes and case."""

    def norm(x: str) -> object:
        x = str(x).strip().strip('"')
        try:
            return literal_value(x)
        except (ValueError, WrapError):
            pass
        try:
            return float(x)
        except ValueError:
            return x.upper()

    return got is not None and norm(got) == norm(want)


def check_dut_cells(text: str, slots: Sequence[SlotBuild]) -> list[str]:
    """The post-flow DUT check: every DUT slot's cell is its primitive and every attribute
    its configuration sets reads back with that value. The problems, or []."""
    rows = {}
    for ln in text.splitlines():
        if ln.strip():
            k, *rest = ln.split("\t")
            rows[int(k)] = rest
    problems = []
    for k, s in enumerate(slots):
        if s.kind != "dut":
            continue
        m = json.loads(s.map_json)
        row = rows.get(k)
        if not row or row == ["MISSING"]:
            problems.append(f"slot {k}: no DUT cell u_slots/u_dut_s{k}/dut after implementation")
            continue
        ref, props = row[0], dict(p.split("=", 1) for p in row[1:])
        if ref != m["prim"]:
            problems.append(f"slot {k}: REF_NAME {ref}, configured {m['prim']} (retargeted)")
        for a, v in sorted(m["attrs"].items()):
            if not _same(props.get(a), v):
                problems.append(
                    f"slot {k}: {a} = {props.get(a)!r} after implementation, configured {v}"
                )
    return problems


def check_latency(text: str) -> tuple[dict[str, float], list[str]]:
    """Per DUT clock, the measured latency in ns; and the clocks over budget or unmeasured."""
    lat, problems = {}, []
    for name, value in _LATENCY.findall(text):
        if value == "unknown":
            problems.append(f"{name}: latency could not be measured")
            continue
        lat[name] = float(value)
        if lat[name] + CLK_TO_Q_AND_BUFG_NS > LATENCY_BUDGET_NS:
            problems.append(
                f"{name}: {lat[name]:.3f} ns + {CLK_TO_Q_AND_BUFG_NS} ns > {LATENCY_BUDGET_NS} ns"
            )
    return lat, problems


def board_xdc() -> Path:
    return repo_root() / "hw" / "boards" / BOARD / "board.xdc"


def build_tcl() -> str:
    top = " ".join(HW_SOURCES)
    return f"""# SPDX-License-Identifier: Apache-2.0
# GENERATED by xut.hw.vivado: batch build of one harness bitstream. Do not edit.
# usage: vivado -mode batch -source build.tcl -tclargs <part> <build-id-hex>
set part [lindex $argv 0]
set build_id [lindex $argv 1]
set_param general.maxThreads 2
read_verilog -sv [list {top}]
read_verilog xut_hw_slots.v
read_xdc board.xdc
synth_design -top xut_hw_top -part $part -include_dirs [list [pwd]]
source timing.tcl
opt_design
place_design
route_design
report_timing_summary -file ../timing.rpt
report_utilization -file ../utilization.rpt
report_drc -file ../drc.rpt
proc xut_slack {{kind}} {{
  set p [get_timing_paths -max_paths 1 -nworst 1 -$kind]
  if {{[llength $p] == 0}} {{ return 0.0 }}
  return [get_property SLACK $p]
}}
set wns [xut_slack setup]
set whs [xut_slack hold]
puts "XUT_TIMING wns=$wns whs=$whs"
if {{$wns < 0 || $whs < 0}} {{ puts "XUT_TIMING_FAILED wns=$wns whs=$whs"; exit 3 }}
set_property BITSTREAM.CONFIG.USERID "0x$build_id" [current_design]
source post_route.tcl
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
write_bitstream -force ../top.bit
puts {BUILD_OK}
exit 0
"""


def build_script() -> str:
    """``build.sh``: Vivado sourced only inside ``bash -c``; run inside ``sources/``."""
    inner = (
        f"source {shlex.quote(str(VIVADO_SETTINGS))} && "
        'vivado -mode batch -nojournal -nolog -notrace -source build.tcl -tclargs "$0" "$1"'
    )
    return (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# GENERATED by xut.hw.vivado. Vivado is sourced only in this subshell.\n"
        "set -e\n"
        'cd "$(dirname "$0")/sources"\n'
        f'bash -c {shlex.quote(inner)} "$1" "$2"\n'
    )


def build_inputs(
    slots: Sequence[SlotBuild], *, maxwords: int, margin: int, build_id: int
) -> dict[str, str]:
    files = {f: (HW_HDL / f).read_text() for f in (*HW_SOURCES, *HW_INCLUDES)}
    files["xut_hw_slots.v"] = render_slots(slots)
    files["xut_hw_cfg.vh"] = render_cfg_vh(slots, build_id, maxwords, margin)
    files["timing.tcl"] = timing_tcl(slots, margin)
    files["post_route.tcl"] = post_route_tcl(slots)
    files["board.xdc"] = board_xdc().read_text()
    files["build.tcl"] = build_tcl()
    files["build.sh"] = build_script()
    return files


def build_key(slots: Sequence[SlotBuild], vivado: str, *, maxwords: int, margin: int) -> str:
    h = hashlib.sha256(f"part={PART}\nvivado={vivado}\n".encode())
    for name, text in sorted(
        build_inputs(slots, maxwords=maxwords, margin=margin, build_id=0).items()
    ):
        h.update(name.encode() + b"\0" + text.encode() + b"\0")
    return h.hexdigest()


def build_id_of(key: str) -> int:
    return int(key[:8], 16)


def classify_log(text: str, rc: int) -> str | None:
    """None for a good build; otherwise why it failed."""
    if rc in OOM_RCS:
        return (
            f"Vivado was OOM-killed at the {VIVADO_MEMORY_MAX} cap (retryable: lower the "
            "parallelism, never raise the cap)"
        )
    for line in text.splitlines():
        if line.startswith("XUT_CONSTRAINT_EMPTY"):
            return f"a timing constraint matched no object ({line}): nothing may go unconstrained"
        if line.startswith("XUT_TIMING_FAILED"):
            return f"timing did not close ({line})"
    bad = [c for c in _CRITICAL.findall(text) if c not in ALLOWED_CRITICAL]
    if bad:
        return f"CRITICAL WARNING(s) {sorted(set(bad))} (not in ALLOWED_CRITICAL)"
    if rc != 0 or BUILD_OK not in text:
        return f"Vivado failed (rc {rc})"
    return None


@dataclass(frozen=True)
class Bitstream:
    path: Path
    key: str
    build_id: int
    sha256: str
    manifest: dict


@contextmanager
def _flock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _load(d: Path) -> Bitstream:
    man = json.loads((d / "manifest.json").read_text())
    return Bitstream(
        d / "top.bit", man["key"], int(man["build_id"], 16), man["bitstream_sha256"], man
    )


def ensure_bitstream(
    slots: Sequence[SlotBuild],
    *,
    cache_root: Path,
    vivado: str,
    maxwords: int = MAXWORDS,
    margin: int = MARGIN,
    timeout_s: int = BUILD_TIMEOUT_S,
) -> Bitstream:
    """The cached bitstream for ``slots``, building it first if needed."""
    key = build_key(slots, vivado, maxwords=maxwords, margin=margin)
    bid = build_id_of(key)
    final = cache_root / "bit" / key
    with _flock(cache_root / "locks" / f"build-{key[:16]}.lock"):
        if (final / "manifest.json").is_file():
            return _load(final)
        if (final / "flow_mismatch.json").is_file():  # a cached failure: never rebuilt
            failed = json.loads((final / "flow_mismatch.json").read_text())
            raise FlowMismatch(f"{failed['detail']} (cached; see {final})")
        tmp = cache_root / "bit" / f"{key}.tmp-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        src = tmp / "sources"
        src.mkdir(parents=True)
        for name, text in build_inputs(
            slots, maxwords=maxwords, margin=margin, build_id=bid
        ).items():
            (tmp if name == "build.sh" else src).joinpath(name).write_text(text)
        log = tmp / "build.log"
        with vivado_slot():
            rc = scoped_run(
                ["bash", str(tmp / "build.sh"), PART, f"{bid:08x}"],
                what=f"vivado-{key[:12]}",
                memory_max=VIVADO_MEMORY_MAX,
                cwd=tmp,
                log=log,
                timeout_s=timeout_s,
            )
        text = log.read_text(errors="replace")
        why = classify_log(text, rc)
        if why is None and not (tmp / "top.bit").is_file():
            why = "Vivado reported success but wrote no top.bit"
        if why is not None:
            raise BuildError(f"{why}; see {log}")
        cells = (tmp / "dut_cells.txt").read_text() if (tmp / "dut_cells.txt").is_file() else ""
        dut_problems = check_dut_cells(cells, slots)
        if dut_problems:
            # The same slots on the same Vivado fail the same way: cache the failure, so
            # every test with this slot set reports it without a 5-15 minute rebuild.
            detail = f"post-flow DUT check: {'; '.join(dut_problems)}"
            record = {"key": key, "dut_check": "fail", "detail": detail}
            (tmp / "flow_mismatch.json").write_text(json.dumps(record, indent=1) + "\n")
            os.rename(tmp, final)
            raise FlowMismatch(f"{detail}; see {final}")
        latency, lat_problems = check_latency(text)
        n_clocks = sum(s.nclk for s in slots)
        if lat_problems or len(latency) != n_clocks:
            raise BuildError(
                "DUT clock latency: "
                + ("; ".join(lat_problems) or f"{len(latency)} of {n_clocks} measured")
                + f"; see {log}"
            )
        wns, whs = _TIMING.findall(text)[-1]
        sha = hashlib.sha256((tmp / "top.bit").read_bytes()).hexdigest()
        manifest = {
            "format": "xut-hw-bitstream 1",
            "key": key,
            "build_id": f"{bid:08x}",
            "part": PART,
            "board": BOARD,
            "vivado": vivado,
            "maxwords": maxwords,
            "margin": margin,
            "wns_ns": float(wns),
            "whs_ns": float(whs),
            "dut_check": "pass",
            "dclk_latency_ns": latency,
            "bitstream_sha256": sha,
            "built": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "slots": [
                {
                    "index": k,
                    "kind": s.kind,
                    "label": s.label,
                    "nin": s.nin,
                    "nout": s.nout,
                    "nclk": s.nclk,
                    "t0": s.t0,
                    "digest": s.digest(),
                    "map": json.loads(s.map_json) if s.map_json else None,
                }
                for k, s in enumerate(slots)
            ],
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        os.rename(tmp, final)
        return _load(final)


def vivado_version(scratch: Path) -> str:
    """The first line of ``vivado -version`` (e.g. ``vivado v2025.2 (64-bit)``). The caller
    holds a ``vivado_slot()``: it is a Vivado process like any other."""
    scratch.mkdir(parents=True, exist_ok=True)
    log = scratch / f"vivado-version-{uuid.uuid4().hex[:6]}.log"
    inner = f"source {shlex.quote(str(VIVADO_SETTINGS))} && vivado -version"
    rc = scoped_run(
        ["bash", "-c", inner],
        what="vivado-version",
        memory_max=VIVADO_MEMORY_MAX,
        cwd=scratch,
        log=log,
        timeout_s=300,
    )
    text = log.read_text(errors="replace")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith("vivado v")), "")
    if rc != 0 or not first:
        raise BuildError(f"vivado -version failed (rc {rc}); see {log}")
    log.unlink()
    return first


class Builder(Protocol):
    def version(self) -> str: ...

    def ensure(self, slots: Sequence[SlotBuild]) -> Bitstream: ...


_VERSION: dict[str, str] = {}
_VERSION_LOCK = threading.Lock()


class VivadoBuilder:
    """Builds in this worktree's cache (``.cache/hw``), bounded by the host-wide slots."""

    def __init__(self, root: Path, cache_root: Path | None = None) -> None:
        self.cache_root = cache_root or Path(root) / ".cache" / "hw"

    def version(self) -> str:
        """``vivado -version``, run once per process, under a slot."""
        with _VERSION_LOCK:
            if "vivado" not in _VERSION:
                with vivado_slot():
                    _VERSION["vivado"] = vivado_version(self.cache_root / "scratch")
            return _VERSION["vivado"]

    def ensure(self, slots: Sequence[SlotBuild]) -> Bitstream:
        return ensure_bitstream(slots, cache_root=self.cache_root, vivado=self.version())
```

- [ ] **Step 5: Add `xut hw build`** to `tools/xut/cli.py`:

```python
@hw_grp.command("build")
@click.argument("selectors", nargs=-1)
@click.option("--model-source", default="auto", show_default=True)
@click.option("--jobs", type=click.IntRange(min=1, max=4), default=4, show_default=True)
def hw_build_cmd(selectors: tuple[str, ...], model_source: str, jobs: int) -> None:
    """Build (or find in .cache/hw/bit) every bitstream the selected vector tests need.
    Each Vivado run is capped at 16G in its own scope, at most 4 at a time."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from xut.hw.plan import plan_case
    from xut.hw.vivado import VivadoBuilder
    from xut.modelsrc import resolve
    from xut.run import run_tests
    from xut.runners.base import RunContext
    from xut.testspec import discover

    root = repo_root()
    cases = [c for c in _select_cases(root, discover(root), selectors) if c.style == "vector"]
    ctx = RunContext(root, "rtl", resolve(model_source), jobs=jobs)
    run_tests(cases, ["python"], ctx)
    builder = VivadoBuilder(root)
    wanted = {}
    for case in cases:
        plan = plan_case(case, ctx)
        for g in range(len(plan.groups)):
            slots = plan.slots(g)
            wanted[tuple(s.digest() for s in slots)] = slots
    t0, done, failed = time.monotonic(), 0, 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(builder.ensure, s): s for s in wanted.values()}
        for f in as_completed(futures):
            done += 1
            try:
                bit = f.result()
                what = f"build {bit.build_id:08x} {bit.path}"
            except Exception as e:  # reported, never swallowed
                failed += 1
                what = f"FAILED: {e}"
            click.echo(
                f"progress: done={done} total={len(wanted)} "
                f"elapsed_s={time.monotonic() - t0:.1f}  {what}"
            )
    raise SystemExit(4 if failed else 0)
```

- [ ] **Step 6: Run the unit tests, lint and commit**

```bash
uv run pytest tools/tests/test_hw_vivado.py -v -m "not vivado" > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/hw/vivado.py tools/xut/cli.py hw/boards tools/tests/test_hw_vivado.py
git commit -m "hw: Vivado batch build with generated constraints, post-flow DUT check, build IDs and a bitstream cache" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The first real builds — self-test, the 28-clock limit, FDRE and the cache

**Files:**
- Modify: `tools/tests/test_hw_vivado.py` (the `vivado`-marked build tests), `tools/xut/hw/vivado.py` (only if a build shows a justified `ALLOWED_CRITICAL` entry, or a constraint/Tcl fix), `tools/xut/hw/slots.py` (only if `DUT_BUFG_BUDGET` must be lowered)

- [ ] **Step 1: Add the build test** to `tools/tests/test_hw_vivado.py`:

```python
@pytest.mark.vivado
def test_build_selftest_and_toy_then_hit_the_cache(tmp_path):
    """A real build: timing closes, the constraints matched their objects, the manifest
    records the ID, and a second ensure() is a cache hit (no second Vivado run). Only the
    self-test slots: TOYFF is not a Vivado cell, so a toy slot would be synthesised as
    plain logic, which is not what a DUT slot claims to hold."""
    b = vivado.VivadoBuilder(tmp_path, cache_root=tmp_path / "hw")
    slots = SELFTEST_SLOTS
    bit = b.ensure(slots)
    assert bit.path.is_file() and bit.manifest["build_id"] == f"{bit.build_id:08x}"
    assert bit.manifest["wns_ns"] >= 0 and bit.manifest["whs_ns"] >= 0
    again = b.ensure(slots)
    assert again.path == bit.path and again.sha256 == bit.sha256
    assert list((tmp_path / "hw" / "bit").glob("*.tmp-*")) == []
    assert bit.manifest["dut_check"] == "pass" and set(bit.manifest["dclk_latency_ns"]) == {
        "dclk_s1_0"
    }


@pytest.mark.vivado
def test_build_at_the_clock_budget(tmp_path):
    """DUT_BUFG_BUDGET real FDRE slots (one clock each) plus the self-test: the most global
    clocks a bitstream may use. 7-series clock regions take at most 12 global clocks each,
    so placement must spread the slots; this build proves that it does, that timing closes,
    that every DUT passes the post-flow DUT check, and that every DUT clock's latency is
    within budget (spec §7.1)."""
    from xut.catalog.model import load_entry
    from xut.hw.slots import DUT_BUFG_BUDGET
    from xut.paths import repo_root
    from xut.wrap import build_map, spec_from_catalog

    entry = load_entry("7series", "FDRE", repo_root())
    duts = []
    for k in range(DUT_BUFG_BUDGET):
        spec = spec_from_catalog(entry, f"c{k}", {"INIT": f"1'b{k % 2}"})
        m = build_map(spec)
        duts.append(dut_slot(m, render_wrapper(spec, m), format(k % 8, "03b")))
    b = vivado.VivadoBuilder(tmp_path, cache_root=tmp_path / "hw")
    bit = b.ensure((*SELFTEST_SLOTS, *duts))
    assert bit.manifest["dut_check"] == "pass"
    assert len(bit.manifest["dclk_latency_ns"]) == DUT_BUFG_BUDGET + 1
    assert bit.manifest["wns_ns"] >= 0 and bit.manifest["whs_ns"] >= 0
```

(FDRE's wrapper has 3 in_vec bits: D, CE, R in catalog order, so `t0` is 3 bits.)

- [ ] **Step 2: Run it** (Vivado, one build of about 3–6 minutes; report every 60 s from `.cache/pytest-vivado.log`, which pytest writes as it goes):

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-pytest-vivado-$(date +%s) -p MemoryMax=8G -p MemorySwapMax=0 -- \
  uv run pytest tools/tests/test_hw_vivado.py -m vivado -n 2 -v > .cache/pytest-vivado.log 2>&1; cat .cache/pytest-vivado.log
```

- **Estimate:** two builds, about 3–6 minutes and 8–15 minutes; report every 60 s, then every 5 minutes.
- **Expected:** both pass. The Vivado runs are scopes of their own (16G each).
- **The latency unit.** In the 28-clock build's `timing.rpt`, find one `dclk_s<k>_0` → DUT path and compare its clock-path delay with the `XUT_LATENCY dclk_s<k>_0` line in `build.log`. If they differ by a factor of 1000, `get_net_delays`' `SLOW_MAX` is in ns, not ps: fix the `/ 1000.0` in `post_route_tcl` and re-run.
- **The clock budget.** If the 28-clock build cannot place (a clock-region or BUFG error), lower `DUT_BUFG_BUDGET` to the largest value that builds (try 24, then 20), update the test and Decision 10, and record why in the log.
- Record both builds' utilization (slice LUTs/FFs, BUFGCTRL used out of 32, RAMB36 used) and the largest measured latency.

 For each `CRITICAL WARNING` that fails the build: read it in `<cache>/bit/<key>.tmp-*/build.log`. Fix the cause if it is ours (a constraint, a pin, a missing include). Only if it is inherent and harmless, add its id to `ALLOWED_CRITICAL` with a one-line comment saying why, as a separate commit (`hw: allow CRITICAL WARNING [<id>] (<why>)`). Reviewers must check every such entry.

- [ ] **Step 3: Build the flops unit's bitstreams** (this also measures build time for the Task 12 estimate):

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwbuild-$(date +%s) -p MemoryMax=8G -p MemorySwapMax=0 -- \
  uv run xut hw build 'unit:flops' --jobs 4 > .cache/hwbuild-flops.log 2>&1; echo "exit=$?"
```

- **Estimate:** the flops unit's hardware-declared tests need about 15–25 distinct bitstreams: identical DUT sets are shared, for example L1 `capture`, `ce_hold` and `reset_over_ce` all use `{INIT=0, INIT=1}` with an all-zero `t0`. At about 4–6 minutes each and 4 at a time, that is about 20–40 minutes, so report every 5 minutes from the `progress:` lines.
- **Expected:** `exit=0`, and every line is `build <id> <path>`. For each build, record the WNS/WHS from its manifest and the utilization (`utilization.rpt`: slice LUTs/FFs, BUFGCTRL used out of 32, RAMB36 used) in the log entry.
- Re-running the command must finish in seconds with the same IDs (all cache hits). Run it once more to show that.

- [ ] **Step 4: Log, commit, push and open PR B**

Commit the build tests (and any fix this task made to the flow), then write `log/<ts>-infra-hw-vivado-builds.md`: build count, durations, IDs, WNS/WHS, utilization, the largest DUT clock latency, the cache re-run, and any `ALLOWED_CRITICAL` entries with their justification. If Task 7 lowered `DUT_BUFG_BUDGET`, the log says so and a docs PR amends spec §7.1's "28 DUT clocks" to match.

```bash
git add tools/tests/test_hw_vivado.py tools/xut/hw/vivado.py tools/xut/hw/slots.py
git commit -m "hw: real builds — self-test, the 28-clock budget, latency and DUT checks" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add log/<ts>-infra-hw-vivado-builds.md
git commit -m "infra: log the hw Vivado build session" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Push and open PR B:

```bash
git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/mithro/xilinx-unittests.git infra/hw-vivado
gh pr create --base infra/hw-harness --title "infra: hw Vivado flow — scoped builds, constraints, build IDs, bitstream cache" --body-file .cache/pr-b.md
```

The body covers Tasks 6–7 and Review Focus items 2 and 6, and ends with the Claude Code line.

---

## PR C: board access and the `hw` runner (branch `infra/hw-runner`)

### Task 8: The rigs config, SSH config and the Pi-side scripts (lock, program, UART)

**Files:**
- Create: `hw/rigs.yaml`, `tools/xut/schemas/rigs.schema.json`, `tools/xut/hw/rigs.py`, `hw/pi/xut_lock.sh`, `hw/pi/xut_work.sh`, `hw/pi/xut_uart.py`, `hw/README.md`, `tools/tests/test_hw_rigs.py`, `tools/tests/test_hw_pi.py`
- Modify: `AGENTS.md` (a "Hardware" section), `pyproject.toml` (the `hw` pytest marker), `tools/tests/conftest.py` (skip `hw` tests without boards)

**Interfaces:**
- Produces (`xut.hw.rigs`):
  - `Jump(name, host, user=None, port=22, identity_file)`
  - `Rig(name, host, jump, board, uart, baud, lock, lock_ttl_s, lock_wait_s, site, identity_file, user=None, port=22, enabled=True, reason="", reboot_command=None)` with the property `alias` (`"xut-rig-<name>"`)
  - `RigsConfig(path, rigs, jumps)` with `enabled() -> list[Rig]` and `get(name) -> Rig`
  - `config_path(root) -> Path` (`$XUT_HW_CONFIG`, else `hw/rigs.yaml`), `load_rigs(path) -> RigsConfig`
  - `render_ssh_config(cfg, known_hosts) -> str`, `write_ssh_config(cfg, root) -> Path`
  - `RigsError(ConfigError)`
- Produces (Pi side, run in a job directory on the rig):
  - `xut_lock.sh LOCK TTL_S WAIT_S OWNER -- CMD...`, exiting with CMD's code, 75 when the lock could not be taken, or 124 when CMD outlived its TTL;
  - `xut_work.sh UART BAUD`, exiting 0 (ok), 90 (programming failed), 91 (UART session failed) or 92 (no UART device);
  - `xut_uart.py --dev D --baud B --session session.json --out resp.json`, exiting 0 or 3 (a step timed out).
- pytest marker `hw`: "needs a reachable fpgas.online board". Tests with it skip unless `XUT_HW=1` is set **and** the rigs config loads. CI never sets `XUT_HW`, so CI skips them.

- [ ] **Step 1: Create the stacked worktree**

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git fetch origin && git worktree add ../xilinx-unittests-worktrees/infra-hw-runner -b infra/hw-runner infra/hw-vivado
cd ../xilinx-unittests-worktrees/infra-hw-runner
mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
git config core.hooksPath tools/hooks
```

- [ ] **Step 2: Write `hw/rigs.yaml`** — the known facts, no secrets. Board access is pending (fpgas-online/fpgas.online-infra#124). The addresses of p10, p12 and p15 follow p9's pattern; confirm them when access is granted (Task 12, Step 2), and fix this file on an infra branch if they differ.

```yaml
# SPDX-License-Identifier: Apache-2.0
# fpgas.online rigs this suite may use (spec §7.5). No secrets here: the key is a PATH.
# Override the whole file with XUT_HW_CONFIG=<path>. Access: fpgas-online/fpgas.online-infra#124.
# Each rig is one Raspberry Pi with one Digilent Arty A7-35T on USB (JTAG + UART).
format: xut-rigs 1
defaults:
  identity_file: ~/.ssh/keys/xilinx-unittests_ed25519
  jump: tweed
  board: arty_a7_35t
  uart: /dev/ttyUSB1          # the Arty's FT2232 channel B (spec §7.5)
  baud: 115200
  lock: /run/lock/fpga.lock   # per rig (one board per Pi); confirm the shared name with fpgas.online
  lock_ttl_s: 900
  lock_wait_s: 600
  site: welland
jumps:
  tweed:
    host: 10.99.21.2
rigs:
  - name: pi-sw2-p9
    host: 10.21.2.9
  - name: pi-sw2-p10
    host: 10.21.2.10    # inferred from p9's pattern; unconfirmed until fpgas.online-infra#124
  - name: pi-sw2-p12
    host: 10.21.2.12    # inferred from p9's pattern; unconfirmed until fpgas.online-infra#124
    enabled: false
    reason: UART output is garbled on this rig; do not use
  - name: pi-sw2-p15
    host: 10.21.2.15    # inferred from p9's pattern; unconfirmed until fpgas.online-infra#124
```

`user` (in `defaults`, a jump or a rig), `port`, `uart`, `baud`, `lock*` and `reboot_command` may be set per rig. When `user` is absent, ssh's default applies. The account comes from #124: add `user:` here once it is known.

- [ ] **Step 3: Write `tools/xut/schemas/rigs.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "xut rigs config: the fpgas.online rigs a run may program (spec §7.5)",
  "$comment": "hw/rigs.yaml, or the file XUT_HW_CONFIG names (xut.hw.rigs). Key paths only, never key material.",
  "type": "object",
  "additionalProperties": false,
  "required": ["format", "defaults", "jumps", "rigs"],
  "$defs": {
    "common": {
      "type": "object",
      "properties": {
        "identity_file": {"type": "string", "minLength": 1},
        "jump": {"type": "string", "minLength": 1},
        "board": {"enum": ["arty_a7_35t"]},
        "uart": {"type": "string", "pattern": "^/dev/[A-Za-z0-9_/.-]+$"},
        "baud": {"enum": [115200]},
        "lock": {"type": "string", "pattern": "^/run/[A-Za-z0-9_/.-]+$"},
        "lock_ttl_s": {"type": "integer", "minimum": 60, "maximum": 7200},
        "lock_wait_s": {"type": "integer", "minimum": 0, "maximum": 7200},
        "site": {"type": "string", "minLength": 1},
        "user": {"type": "string", "pattern": "^[a-z_][a-z0-9_-]*$"},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
        "reboot_command": {"type": "string", "minLength": 1}
      }
    }
  },
  "properties": {
    "format": {"const": "xut-rigs 1"},
    "defaults": {"$ref": "#/$defs/common", "unevaluatedProperties": false},
    "jumps": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "required": ["host"],
        "properties": {
          "host": {"type": "string", "minLength": 1},
          "user": {"type": "string", "pattern": "^[a-z_][a-z0-9_-]*$"},
          "port": {"type": "integer", "minimum": 1, "maximum": 65535},
          "identity_file": {"type": "string", "minLength": 1}
        }
      }
    },
    "rigs": {
      "type": "array",
      "minItems": 1,
      "items": {
        "allOf": [{"$ref": "#/$defs/common"}],
        "type": "object",
        "required": ["name", "host"],
        "properties": {
          "name": {"type": "string", "pattern": "^[A-Za-z0-9_.-]+$"},
          "host": {"type": "string", "minLength": 1},
          "enabled": {"type": "boolean"},
          "reason": {"type": "string"}
        },
        "unevaluatedProperties": false
      }
    }
  }
}
```

`baud` and `board` are single-valued enums on purpose: the harness is built for 115200 baud on the Arty. Widen them only when a harness variant exists.

- [ ] **Step 4: Write the Pi-side scripts.** `hw/pi/xut_lock.sh`:

```sh
#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# xut_lock.sh LOCK TTL_S WAIT_S OWNER -- CMD [ARG...]
# The rig lock (spec §7.5, ruling S49): runs CMD while holding flock(LOCK).
# - The lock file is never deleted, re-created or unlinked, by this script or anyone.
# - While held, LOCK.owner holds one line:
#     xut-lock label=xut.session owner=OWNER host=H boot=B pid=P pgid=G cpgid=C since=S ttl=T
#   (P and G: this script and its process group; C: timeout's process group, which runs
#   CMD). OWNER is "<user>@<client-host>:<pid>" and contains no spaces.
# - CMD runs under `timeout -k 10 TTL_S`, so a holder of ours never outlives its TTL.
#   CMD inherits the lock descriptor: the lock stays held while any part of the job lives.
# - A held lock is waited for, up to WAIT_S seconds. Then:
#   - if LOCK.owner shows OUR OWN stale holder, both of its process groups are killed
#     (TERM, then KILL) and the lock is waited for once more, for at most 30 s. "Our own"
#     means all of: label xut.session; the same client "<user>@<client-host>" as OWNER
#     (the pid part differs); this host and boot id; past since + ttl + XUT_LOCK_GRACE_S;
#     the recorded pid alive, in the recorded process group, running `xut_lock.sh` for
#     this LOCK (its /proc cmdline), and started no later than the record's `since` (its
#     /proc stat start time). A reused pid fails the last two checks and is never killed;
#   - otherwise exit 75 (busy); a record past its TTL adds "(stale)" to the message.
#   The kill path is nearly unreachable: `timeout -k 10` already kills our holder by
#   TTL + 10 s. A live holder past TTL + 60 s means `timeout` itself died or the job is in
#   uninterruptible sleep (a stuck USB call), where SIGKILL may not help either. It is a
#   last resort, not a mechanism to rely on.
# Programming the FPGA and any reboot of the rig happen only under this lock.
# Exit: CMD's status; 75 busy (only); 93 the lock file cannot be created or opened (a rig
# fault, not busy); 124 if timeout(1) stopped CMD at its TTL, or 137 if it had to SIGKILL
# it (-k 10). The session treats 124 and 137 alike (a transport error).
set -u
LOCK=$1
TTL=$2
WAIT=$3
OWNER=$4
shift 4
[ "${1:-}" = "--" ] && shift
GRACE=${XUT_LOCK_GRACE_S:-60}
HOST=$(hostname)
BOOT=$(cat /proc/sys/kernel/random/boot_id)

field() {  # field NAME RECORD
  printf '%s\n' "$2" | sed -n "s/.* $1=\([^ ]*\).*/\1/p"
}
client() {  # "<user>@<client-host>:<pid>" -> "<user>@<client-host>"
  printf '%s\n' "$1" | sed 's/:[^:]*$//'
}
pgid_of() {
  ps -o pgid= -p "$1" | tr -d ' '
}
is_our_lock_script() {  # PID: is it an xut_lock.sh for this LOCK?
  cmd=$(tr '\000' ' ' < "/proc/$1/cmdline")
  case "$cmd" in
    *xut_lock.sh*" $LOCK "*) return 0 ;;
    *) return 1 ;;
  esac
}
started_by() {  # PID EPOCH: did PID start at or before EPOCH?
  # /proc/PID/stat field 22 is the start time in clock ticks after boot; the fields are
  # counted after the ")" that ends field 2 (the command name may hold spaces).
  ticks=$(sed 's/.*) //' "/proc/$1/stat" | awk '{print $20}')
  btime=$(awk '/^btime /{print $2}' /proc/stat)
  hz=$(getconf CLK_TCK)
  [ -n "$ticks" ] && [ $((btime + ticks / hz)) -le "$2" ]
}

if [ ! -e "$LOCK" ]; then
  (umask 0; : >> "$LOCK") || { echo "xut_lock: lock fault: cannot create $LOCK" >&2; exit 93; }
fi
exec 9<"$LOCK" || { echo "xut_lock: lock fault: cannot open $LOCK" >&2; exit 93; }

if ! flock -w "$WAIT" 9; then
  rec=""
  if [ -f "$LOCK.owner" ]; then
    rec=$(cat "$LOCK.owner")
  fi
  since=$(field since "$rec")
  ttl=$(field ttl "$rec")
  pid=$(field pid "$rec")
  pgid=$(field pgid "$rec")
  cpgid=$(field cpgid "$rec")
  stale=""
  if [ -n "$since" ] && [ -n "$ttl" ] && [ "$(date +%s)" -gt $((since + ttl + GRACE)) ]; then
    stale=" (stale)"
  fi
  mine=no
  if [ -n "$stale" ] && [ "$(field label "$rec")" = xut.session ] \
    && [ "$(client "$(field owner "$rec")")" = "$(client "$OWNER")" ] \
    && [ "$(field host "$rec")" = "$HOST" ] && [ "$(field boot "$rec")" = "$BOOT" ] \
    && [ -n "$pid" ] && [ -n "$pgid" ] && [ -n "$cpgid" ] && kill -0 "$pid" \
    && [ "$(pgid_of "$pid")" = "$pgid" ] && [ "$pgid" != "$(pgid_of $$)" ] \
    && is_our_lock_script "$pid" && started_by "$pid" "$since"; then
    mine=yes
  fi
  if [ "$mine" != yes ]; then
    echo "xut_lock: busy$stale: ${rec:-no owner record}" >&2
    exit 75
  fi
  echo "xut_lock: killing our own stale holder (process groups $pgid, $cpgid): $rec" >&2
  kill -TERM -- "-$cpgid" "-$pgid"
  sleep 2
  kill -KILL -- "-$cpgid" "-$pgid"
  if ! flock -w 30 9; then
    echo "xut_lock: busy after killing our own stale holder: $rec" >&2
    exit 75
  fi
fi

timeout -k 10 "$TTL" "$@" &
child=$!
rec="xut-lock label=xut.session owner=$OWNER host=$HOST boot=$BOOT pid=$$"
rec="$rec pgid=$(pgid_of $$) cpgid=$child since=$(date +%s) ttl=$TTL"
if ! (umask 0; printf '%s\n' "$rec" > "$LOCK.owner.$$" && mv -f "$LOCK.owner.$$" "$LOCK.owner"); then
  echo "xut_lock: warning: cannot write $LOCK.owner (the lock is held regardless)" >&2
fi
wait "$child"
rc=$?
rm -f "$LOCK.owner"
exit $rc
```

Notes for the implementer:
- `timeout` (GNU coreutils) makes itself a process-group leader, so its pid is the process group that runs CMD (`cpgid`); the script's own group is `pgid`. Recovery kills both.
- Only the owner record is ever removed (by its own holder). `kill -0` and `kill` print an error for a process that is already gone; that goes to the job's log, which is where it belongs.
- The cmdline check needs the lock path followed by a space: the script's argv is `sh ./xut_lock.sh LOCK TTL WAIT OWNER -- ...`, and `/proc/PID/cmdline` separates arguments with NUL, which `tr` turns into spaces.
- The waits are bounded: at most `WAIT_S` + 2 s + 30 s before the TTL starts, so the host's SSH timeout for a job is `lock_wait_s + lock_ttl_s + 180` (Task 9a).

`hw/pi/xut_work.sh`:

```sh
#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# xut_work.sh UART BAUD — runs on a rig's Raspberry Pi, in the job directory, INSIDE the
# rig lock (xut_lock.sh): program the FPGA's SRAM with ./top.bit, then run the UART
# session (./session.json -> ./resp.json).
# SRAM ONLY: the single programming line below never takes a flash option (-f,
# --write-flash, ...); tools/tests/test_hw_pi.py pins that.
# Exit: 0 ok; 90 programming failed; 91 the UART session failed; 92 no UART device.
set -u
UART=$1
BAUD=$2
[ -c "$UART" ] || { echo "xut_work: no UART device $UART" >&2; exit 92; }
dev=$(readlink -f "/sys/class/tty/$(basename "$UART")/device")
if [ -r "$dev/../../serial" ]; then
  cat "$dev/../../serial" > serial.txt
else
  echo "unknown (no USB serial for $UART)" > serial.txt
fi
openFPGALoader --Version > ofl-version.txt 2>&1
echo "rc=$?" >> ofl-version.txt
openFPGALoader -b arty top.bit > program.log 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "xut_work: openFPGALoader failed rc=$rc (see program.log)" >&2
  exit 90
fi
python3 ./xut_uart.py --dev "$UART" --baud "$BAUD" --session session.json --out resp.json > uart.log 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "xut_work: the UART session failed rc=$rc (see uart.log)" >&2
  exit 91
fi
exit 0
```

`hw/pi/xut_uart.py`:

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""UART session with the stepped harness. Runs on a rig's Raspberry Pi, standard library
only (also tested on the host against a pty and the reference emulator).

session.json: {"steps": [{"send": "<hex>", "until": "line" | "end", "timeout_s": N}]}.
The tty is opened raw at --baud, 8N1, no flow control. Bytes already buffered are
discarded (counted). Then for each step: write its bytes and read until the reply is
complete: "line" = one newline; "end" = a complete "# xut-hw 1 end ..." or
"# xut-hw 1 err ..." line. Writes {"steps": [{"rx": "<hex>"}], "discarded": N} to --out
even when a step times out (the host logs what arrived). Exit 0; 3 on a step timeout.
"""

import argparse
import contextlib
import json
import os
import select
import sys
import termios
import time
import tty

BAUDS = {115200: termios.B115200}
END_MARKERS = (b"# xut-hw 1 end ", b"# xut-hw 1 err ")
DRAIN_S = 0.2


def open_tty(dev: str, baud: int) -> int:
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    a = termios.tcgetattr(fd)
    a[2] &= ~(termios.CSTOPB | termios.PARENB | termios.CRTSCTS | termios.CSIZE)
    a[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
    a[4] = a[5] = BAUDS[baud]
    termios.tcsetattr(fd, termios.TCSANOW, a)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def complete(buf: bytes, until: str) -> bool:
    if until == "line":
        return b"\n" in buf
    return any(ln.startswith(END_MARKERS) for ln in buf.split(b"\n")[:-1])


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            n = os.write(fd, view)
        except BlockingIOError:
            select.select([], [fd], [], 1.0)
            continue
        view = view[n:]
    termios.tcdrain(fd)


def read_until(fd: int, until: str, timeout_s: float) -> tuple[bytes, bool]:
    buf = bytearray()
    deadline = time.monotonic() + timeout_s
    while not complete(bytes(buf), until):
        left = deadline - time.monotonic()
        if left <= 0:
            return bytes(buf), False
        ready, _, _ = select.select([fd], [], [], min(left, 0.5))
        if ready:
            try:
                buf += os.read(fd, 4096)
            except BlockingIOError:
                continue
    return bytes(buf), True


def drain(fd: int) -> int:
    n, deadline = 0, time.monotonic() + DRAIN_S
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            with contextlib.suppress(BlockingIOError):
                n += len(os.read(fd, 4096))
    return n


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", required=True)
    ap.add_argument("--baud", type=int, required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.session) as f:
        steps = json.load(f)["steps"]
    fd = open_tty(args.dev, args.baud)
    out = {"steps": [], "discarded": drain(fd)}
    rc = 0
    try:
        for i, s in enumerate(steps):
            write_all(fd, bytes.fromhex(s["send"]))
            rx, ok = read_until(fd, s["until"], float(s["timeout_s"]))
            out["steps"].append({"rx": rx.hex()})
            if not ok:
                print(
                    f"xut_uart: step {i} ({s['until']}) timed out after {s['timeout_s']}s "
                    f"with {len(rx)} byte(s)",
                    file=sys.stderr,
                )
                rc = 3
                break
    finally:
        os.close(fd)
        with open(args.out, "w") as f:
            json.dump(out, f)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Write the failing tests.** `tools/tests/test_hw_pi.py` (the scripts run on the host: `flock` and `timeout` come from util-linux and coreutils; the UART is a pty served by the reference emulator):

```python
# SPDX-License-Identifier: Apache-2.0
import json
import os
import re
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from xut.hw import proto
from xut.hw.steps import session_steps
from xut.hw.interp import EmuSlot, Harness
from xut.hw.selftest import CounterSim, PassthroughSim, selftest_programs
from xut.paths import repo_root

PI = repo_root() / "hw" / "pi"
FLASH = re.compile(
    r"(\s-f\b|--write-flash|--external-flash|--bulk-erase|--flash-sector|\s-o\b|--offset)"
)


#: Prose and this test itself name the forbidden options on purpose.
SRAM_SCAN_SKIP = {"AGENTS.md", "hw/README.md", "tools/tests/test_hw_pi.py"}


def test_the_only_programming_line_is_sram():
    lines = [
        ln for ln in (PI / "xut_work.sh").read_text().splitlines() if "openFPGALoader -b" in ln
    ]
    assert lines == ["openFPGALoader -b arty top.bit > program.log 2>&1"]
    root = repo_root()
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for name in tracked:
        if name in SRAM_SCAN_SKIP or name.startswith("docs/") or name.startswith("log/"):
            continue
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue  # binary
        for ln in text.splitlines():
            if "openFPGALoader" in ln or "openocd" in ln:
                assert not FLASH.search(ln), f"{name}: {ln}"
                assert " program " not in ln, f"{name}: {ln} (openocd program is forbidden)"


def _lock(tmp_path, *cmd, ttl="30", wait="1", owner="me@test"):
    return subprocess.run(
        ["sh", str(PI / "xut_lock.sh"), str(tmp_path / "fpga.lock"), ttl, wait, owner, "--", *cmd],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_lock_runs_the_command_with_an_owner_record(tmp_path):
    r = _lock(tmp_path, "sh", "-c", f"cat {tmp_path}/fpga.lock.owner; exit 7")
    assert r.returncode == 7 and r.stdout.startswith("xut-lock label=xut.session owner=me@test ")
    assert " ttl=30" in r.stdout and " boot=" in r.stdout and " cpgid=" in r.stdout
    assert not (tmp_path / "fpga.lock.owner").exists()
    assert (tmp_path / "fpga.lock").exists()  # never deleted


def _foreign_holder(tmp_path):
    lock = tmp_path / "fpga.lock"
    lock.touch()
    holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
    threading.Event().wait(0.3)
    return lock, holder


@pytest.mark.parametrize("since", ["now", "1"])
def test_a_held_lock_is_busy_and_never_broken(tmp_path, since):
    """A live foreign holder, with a fresh or a long-expired owner record: 75, the holder
    keeps the lock, and the lock file is the same inode (ruling S49)."""
    lock, holder = _foreign_holder(tmp_path)
    try:
        t0 = int(time.time()) if since == "now" else 1
        (tmp_path / "fpga.lock.owner").write_text(
            f"xut-lock label=xut.session owner=other@elsewhere:1 host=x boot=y pid=1 pgid=1 "
            f"cpgid=1 since={t0} ttl=60\n"
        )
        inode = lock.stat().st_ino
        r = _lock(tmp_path, "true")
        assert r.returncode == 75 and "busy" in r.stderr
        assert ("(stale)" in r.stderr) == (since == "1")
        assert lock.stat().st_ino == inode and holder.poll() is None
    finally:
        holder.kill()
        holder.wait()


def test_busy_without_an_owner_record(tmp_path):
    lock, holder = _foreign_holder(tmp_path)
    try:
        r = _lock(tmp_path, "true")
        assert r.returncode == 75 and "no owner record" in r.stderr
    finally:
        holder.kill()
        holder.wait()


def _stale_own_record(tmp_path, pid, since=1):
    """An owner record of OUR client, past its TTL, naming ``pid`` and its group."""
    host = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    (tmp_path / "fpga.lock.owner").write_text(
        f"xut-lock label=xut.session owner=me@client:1 host={host} boot={boot} pid={pid} "
        f"pgid={pid} cpgid={pid} since={since} ttl=60\n"
    )


def test_a_reused_pid_that_is_not_a_lock_script_survives(tmp_path):
    """The recorded pid now belongs to an unrelated process of ours (a reused pid): it
    fails the cmdline check, is never killed, and the rig is busy."""
    env = {**os.environ, "XUT_LOCK_GRACE_S": "0"}
    lock, holder = _foreign_holder(tmp_path)
    victim = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        _stale_own_record(tmp_path, victim.pid)
        r = subprocess.run(
            ["sh", str(PI / "xut_lock.sh"), str(lock), "30", "1", "me@client:9", "--", "true"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 75 and "(stale)" in r.stderr
        assert victim.poll() is None and holder.poll() is None
    finally:
        for p in (victim, holder):
            p.kill()
            p.wait()


def test_a_lock_script_that_started_after_the_record_survives(tmp_path):
    """The recorded pid is an xut_lock.sh for this lock, but it started after the record's
    `since` (it is merely waiting, not the holder the record describes): never killed."""
    env = {**os.environ, "XUT_LOCK_GRACE_S": "0"}
    lock, holder = _foreign_holder(tmp_path)
    waiter = subprocess.Popen(
        ["sh", str(PI / "xut_lock.sh"), str(lock), "30", "25", "other@elsewhere:2", "--", "true"],
        start_new_session=True,
    )
    try:
        threading.Event().wait(0.5)
        _stale_own_record(tmp_path, waiter.pid, since=1)
        r = subprocess.run(
            ["sh", str(PI / "xut_lock.sh"), str(lock), "30", "1", "me@client:9", "--", "true"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 75 and waiter.poll() is None
    finally:
        for p in (waiter, holder):
            p.kill()
            p.wait()


def test_a_lock_file_fault_is_93_not_busy(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        r = subprocess.run(
            [
                "sh",
                str(PI / "xut_lock.sh"),
                str(ro / "fpga.lock"),
                "30",
                "1",
                "me@t:1",
                "--",
                "true",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 93 and "lock fault" in r.stderr
    finally:
        ro.chmod(0o700)


def test_only_our_own_stale_holder_is_killed(tmp_path):
    """Our own holder, alive past its TTL (it ignores SIGTERM until timeout's -k KILL):
    the same client owner recovers it by killing its process groups, never by touching
    the lock file."""
    env = {**os.environ, "XUT_LOCK_GRACE_S": "0"}
    lock = tmp_path / "fpga.lock"
    holder = subprocess.Popen(
        [
            "sh",
            str(PI / "xut_lock.sh"),
            str(lock),
            "1",
            "1",
            "me@client:111",
            "--",
            "sh",
            "-c",
            'trap "" TERM; while :; do sleep 1; done',
        ],
        env=env,
        start_new_session=True,
    )
    try:
        threading.Event().wait(2.5)  # past since + ttl, before timeout's KILL at ttl + 10
        inode = lock.stat().st_ino
        other = subprocess.run(
            ["sh", str(PI / "xut_lock.sh"), str(lock), "30", "1", "you@client:222", "--", "true"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert other.returncode == 75 and "(stale)" in other.stderr  # not ours: never killed
        r = subprocess.run(
            ["sh", str(PI / "xut_lock.sh"), str(lock), "30", "1", "me@client:333", "--", "true"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 0 and "killing our own stale holder" in r.stderr
        assert lock.stat().st_ino == inode
        holder.wait(timeout=10)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()


def test_ttl_is_enforced(tmp_path):
    r = _lock(tmp_path, "sleep", "10", ttl="1")
    assert r.returncode == 124


def _serve(master: int, h: Harness, stop: threading.Event) -> None:
    while not stop.is_set():
        ready, _, _ = select.select([master], [], [], 0.05)
        if ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                return
            reply = h.feed(data)
            if reply:
                os.write(master, reply)


def _session(tmp_path) -> tuple[Path, list]:
    progs = selftest_programs()
    steps = session_steps(progs)
    sess = {
        "steps": [
            {
                "send": s.send.hex(),
                "until": "end" if s.send == proto.CMD_RUN else "line",
                "timeout_s": 10,
            }
            for s in steps
        ]
    }
    p = tmp_path / "session.json"
    p.write_text(json.dumps(sess))
    return p, steps


def _emulated_tty(build=0x1234):
    master, slave = os.openpty()
    h = Harness(
        build,
        [EmuSlot(16, 16, 0, "0" * 16, PassthroughSim()), EmuSlot(2, 8, 1, "00", CounterSim())],
    )
    stop = threading.Event()
    t = threading.Thread(target=_serve, args=(master, h, stop), daemon=True)
    t.start()
    return master, slave, stop, t


def test_uart_session_against_the_emulator(tmp_path):
    sess, steps = _session(tmp_path)
    master, slave, stop, t = _emulated_tty()
    try:
        r = subprocess.run(
            [
                sys.executable,
                str(PI / "xut_uart.py"),
                "--dev",
                os.ttyname(slave),
                "--baud",
                "115200",
                "--session",
                str(sess),
                "--out",
                str(tmp_path / "resp.json"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        stop.set()
        t.join()
        os.close(master)
        os.close(slave)
    assert r.returncode == 0, r.stderr
    rx = [bytes.fromhex(s["rx"]) for s in json.loads((tmp_path / "resp.json").read_text())["steps"]]
    assert proto.parse_id(rx[0]).build == 0x1234
    assert proto.parse_run(rx[2]).status == 0 and proto.parse_run(rx[4]).status == 0


def test_work_sh_programs_sram_then_runs_the_session(tmp_path):
    """xut_lock.sh + xut_work.sh end to end with a shim openFPGALoader (records its argv)
    and a pty UART served by the emulator."""
    job = tmp_path / "job"
    job.mkdir()
    for f in ("xut_lock.sh", "xut_work.sh", "xut_uart.py"):
        (job / f).write_text((PI / f).read_text())
    (job / "top.bit").write_bytes(b"not a real bitstream")
    _session(job)
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "openFPGALoader").write_text(f'#!/bin/sh\necho "$@" >> {job}/ofl-argv.txt\n')
    (shim / "openFPGALoader").chmod(0o755)
    master, slave, stop, t = _emulated_tty()
    try:
        env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}"}
        r = subprocess.run(
            [
                "sh",
                "./xut_lock.sh",
                str(tmp_path / "fpga.lock"),
                "60",
                "1",
                "me",
                "--",
                "sh",
                "./xut_work.sh",
                os.ttyname(slave),
                "115200",
            ],
            cwd=job,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        stop.set()
        t.join()
        os.close(master)
        os.close(slave)
    assert r.returncode == 0, r.stderr
    assert (job / "ofl-argv.txt").read_text().splitlines() == ["--Version", "-b arty top.bit"]
    assert (job / "resp.json").is_file() and (job / "serial.txt").read_text().startswith("unknown")
```

(`xut_work.sh` checks `[ -c "$UART" ]`; a pty slave is a character device, so the test exercises the real path.)

`tools/tests/test_hw_rigs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from xut.hw.rigs import RigsError, config_path, load_rigs, render_ssh_config
from xut.paths import repo_root


def test_committed_rigs_file_loads():
    cfg = load_rigs(repo_root() / "hw" / "rigs.yaml")
    names = [r.name for r in cfg.enabled()]
    assert names == ["pi-sw2-p9", "pi-sw2-p10", "pi-sw2-p15"]
    p9 = cfg.get("pi-sw2-p9")
    assert p9.host == "10.21.2.9" and p9.jump == "tweed" and p9.uart == "/dev/ttyUSB1"
    assert p9.identity_file == Path("~/.ssh/keys/xilinx-unittests_ed25519").expanduser()
    assert cfg.get("pi-sw2-p12").reason.startswith("UART output is garbled")


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("XUT_HW_CONFIG", str(tmp_path / "r.yaml"))
    assert config_path(repo_root()) == tmp_path / "r.yaml"


def test_ssh_config(tmp_path):
    cfg = load_rigs(repo_root() / "hw" / "rigs.yaml")
    text = render_ssh_config(cfg, tmp_path / "known_hosts")
    assert "Host xut-jump-tweed\n  HostName 10.99.21.2\n" in text
    block = text.split("Host xut-rig-pi-sw2-p9\n", 1)[1].split("\nHost ", 1)[0]
    for opt in (
        "HostName 10.21.2.9",
        "ProxyJump xut-jump-tweed",
        "IdentitiesOnly yes",
        "BatchMode yes",
        f"UserKnownHostsFile {tmp_path / 'known_hosts'}",
    ):
        assert f"  {opt}\n" in block + "\n"
    assert "pi-sw2-p12" not in text  # disabled rigs get no host entry


@pytest.mark.parametrize(
    "bad,match",
    [
        ("rigs: [{name: a, host: h, jump: nowhere}]", "jump"),
        ("rigs: [{name: a, host: h, lock: /tmp/x}]", "lock"),
        ("rigs: [{name: a, host: h}, {name: a, host: h2}]", "twice"),
    ],
)
def test_invalid_configs(tmp_path, bad, match):
    base = (
        "format: xut-rigs 1\n"
        "defaults: {jump: tweed, uart: /dev/ttyUSB1, baud: 115200, lock: /run/lock/fpga.lock,\n"
        "           lock_ttl_s: 900, lock_wait_s: 600, site: s, board: arty_a7_35t}\n"
        "jumps: {tweed: {host: j}}\n"
    )
    (tmp_path / "r.yaml").write_text(base + bad + "\n")
    with pytest.raises(RigsError, match=match):
        load_rigs(tmp_path / "r.yaml")
```

- [ ] **Step 6: Implement `tools/xut/hw/rigs.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The rigs this suite may program (spec §7.5): hw/rigs.yaml, or $XUT_HW_CONFIG.

No secret is ever stored: the file names the SSH key's path. SSH runs with a generated
``.cache/hw/ssh_config`` (IdentitiesOnly, BatchMode, a private known_hosts), so neither
the user's ssh config nor an agent's other keys take part.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml

from xut.errors import ConfigError
from xut.schemas import validate as validate_schema

_SSH_OPTS = (
    "IdentitiesOnly yes",
    "BatchMode yes",
    "ConnectTimeout 10",
    "ServerAliveInterval 15",
    "ServerAliveCountMax 4",
    "StrictHostKeyChecking accept-new",
)


class RigsError(ConfigError):
    """An invalid rigs config."""


@dataclass(frozen=True)
class Jump:
    name: str
    host: str
    identity_file: Path
    user: str | None = None
    port: int = 22


@dataclass(frozen=True)
class Rig:
    name: str
    host: str
    jump: str
    board: str
    uart: str
    baud: int
    lock: str
    lock_ttl_s: int
    lock_wait_s: int
    site: str
    identity_file: Path
    user: str | None = None
    port: int = 22
    enabled: bool = True
    reason: str = ""
    reboot_command: str | None = None

    @property
    def alias(self) -> str:
        return f"xut-rig-{self.name}"


@dataclass(frozen=True)
class RigsConfig:
    path: Path
    rigs: tuple[Rig, ...]
    jumps: dict[str, Jump]

    def enabled(self) -> list[Rig]:
        return [r for r in self.rigs if r.enabled]

    def get(self, name: str) -> Rig:
        for r in self.rigs:
            if r.name == name:
                return r
        raise RigsError(f"{self.path}: no rig {name!r} (have {[r.name for r in self.rigs]})")


def config_path(root: Path) -> Path:
    env = os.environ.get("XUT_HW_CONFIG")
    return Path(env) if env else Path(root) / "hw" / "rigs.yaml"


def load_rigs(path: Path) -> RigsConfig:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
        validate_schema(data, "rigs")
    except FileNotFoundError as e:
        raise RigsError(f"no rigs config at {path} (set XUT_HW_CONFIG)") from e
    except yaml.YAMLError as e:
        raise RigsError(f"{path}: invalid YAML: {e}") from e
    except jsonschema.ValidationError as e:
        raise RigsError(f"{path}: {e.json_path}: {e.message}") from e
    d = data["defaults"]
    key = Path(d.get("identity_file", "~/.ssh/id_ed25519")).expanduser()
    jumps = {
        n: Jump(
            n,
            j["host"],
            Path(j.get("identity_file", key)).expanduser(),
            j.get("user"),
            j.get("port", 22),
        )
        for n, j in data["jumps"].items()
    }
    rigs, seen = [], set()
    for raw in data["rigs"]:
        r = {**d, **raw}
        if r["name"] in seen:
            raise RigsError(f"{path}: rig {r['name']} is listed twice")
        seen.add(r["name"])
        if r.get("jump") not in jumps:
            raise RigsError(f"{path}: rig {r['name']}: jump {r.get('jump')!r} is not under jumps")
        missing = [
            k
            for k in ("uart", "baud", "lock", "lock_ttl_s", "lock_wait_s", "site", "board")
            if k not in r
        ]
        if missing:
            raise RigsError(f"{path}: rig {r['name']} lacks {missing} (set them in defaults)")
        rigs.append(
            Rig(
                r["name"],
                r["host"],
                r["jump"],
                r["board"],
                r["uart"],
                r["baud"],
                r["lock"],
                r["lock_ttl_s"],
                r["lock_wait_s"],
                r["site"],
                Path(r.get("identity_file", key)).expanduser(),
                r.get("user"),
                r.get("port", 22),
                r.get("enabled", True),
                r.get("reason", ""),
                r.get("reboot_command"),
            )
        )
    return RigsConfig(path, tuple(rigs), jumps)


def _host(
    alias: str, host: str, port: int, user: str | None, key: Path, known: Path, jump: str | None
) -> list[str]:
    out = [f"Host {alias}", f"  HostName {host}", f"  Port {port}"]
    if user:
        out.append(f"  User {user}")
    if jump:
        out.append(f"  ProxyJump {jump}")
    out.append(f"  IdentityFile {key}")
    out += [f"  {o}" for o in _SSH_OPTS]
    out.append(f"  UserKnownHostsFile {known}")
    return out


def render_ssh_config(cfg: RigsConfig, known_hosts: Path) -> str:
    out = ["# GENERATED by xut.hw.rigs from " + str(cfg.path) + ". Do not edit."]
    for j in cfg.jumps.values():
        out += _host(
            f"xut-jump-{j.name}", j.host, j.port, j.user, j.identity_file, known_hosts, None
        )
    for r in cfg.enabled():
        out += _host(
            r.alias, r.host, r.port, r.user, r.identity_file, known_hosts, f"xut-jump-{r.jump}"
        )
    return "\n".join(out) + "\n"


def write_ssh_config(cfg: RigsConfig, root: Path) -> Path:
    d = Path(root) / ".cache" / "hw"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "ssh_config"
    p.write_text(render_ssh_config(cfg, d / "known_hosts"))
    p.chmod(0o600)
    return p
```

(The schema's `lock` pattern already refuses `/tmp/x`. The test's `match="lock"` holds because the schema error's `json_path` names `lock`. The schema uses draft 2020-12's `unevaluatedProperties`, so that `defaults` and the rig entries share `$defs/common`; `xut.schemas.validate` honours the `$schema` draft, as for the existing schemas.)

- [ ] **Step 7: Add the marker and the skip.** In `pyproject.toml` `markers`, add:

```toml
  "hw: needs a reachable fpgas.online board (set XUT_HW=1; CI never does)",
```

In `tools/tests/conftest.py`'s `pytest_collection_modifyitems`, add:

```python
    from xut.hw.rigs import RigsError, config_path, load_rigs
    from xut.paths import repo_root

    have_hw = os.environ.get("XUT_HW") == "1"
    if have_hw:
        try:
            load_rigs(config_path(repo_root()))
        except RigsError:
            have_hw = False
    no_hw = pytest.mark.skip(reason="no board access (set XUT_HW=1 with a valid rigs config)")
    for item in items:
        if item.get_closest_marker("hw"):
            item.add_marker(pytest.mark.slow)
            if not have_hw:
                item.add_marker(no_hw)
```

- [ ] **Step 8: Document it.** Add to `AGENTS.md`, after §10.1:

```markdown
### 10.2 Hardware (fpgas.online)

- **SRAM only.** Program a board only with `openFPGALoader -b arty <bitstream>`
  (`xut.hw.session.PROGRAM_ARGV`, run by `hw/pi/xut_work.sh`). Never pass a flash
  option (`-f`, `--write-flash`, `--external-flash`, `--bulk-erase`), and never use
  openocd's `program`.
- **The rig lock** (spec §7.5, ruling S49). Programming and any reboot of a rig happen
  only inside `hw/pi/xut_lock.sh` (flock on the rig's `lock`, an owner record, the TTL
  enforced by `timeout` on our own holder). Never delete, re-create or unlink a lock
  file, and never break a lock. A held lock is waited for, then the rig is `busy` and
  the job moves on; the only recovery is killing a holder verified as our own. xut never
  reboots a Pi unless the rig names a `reboot_command`.
- **Access** comes from `hw/rigs.yaml` (or `XUT_HW_CONFIG`) and the key
  `~/.ssh/keys/xilinx-unittests_ed25519`. Never commit key material. Coordinate board
  use with the fpgas.online sessions first.
- Tests that need a board carry the `hw` pytest marker and run only with `XUT_HW=1`.
```

`hw/README.md` gives operators the same rules, plus: how to run a command under the rig lock by hand (`sh xut_lock.sh /run/lock/fpga.lock 600 600 "$USER@$(hostname):$$" -- <cmd>`); how to reboot a rig safely (the same wrapper around the reboot command); that a rig reported `busy` is cleared by whoever holds it, never by deleting the lock file; and where results come back (`build/vivado/hw/...`).

- [ ] **Step 9: Run the tests, lint and commit**

```bash
uv run pytest tools/tests/test_hw_pi.py tools/tests/test_hw_rigs.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools hw > .cache/ruff.log 2>&1; uv run ruff check tools hw >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add hw tools/xut/hw/rigs.py tools/xut/schemas/rigs.schema.json tools/tests/test_hw_pi.py tools/tests/test_hw_rigs.py tools/tests/conftest.py pyproject.toml AGENTS.md
git commit -m "hw: rigs config, generated ssh config, and the Pi-side lock, SRAM programming and UART scripts" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: all pass (the lock tests need `flock` and `timeout`, which are on this host).

---

### Task 9a: `BoardSession` and the fake transport

**Files:**
- Create: `tools/xut/hw/session.py`, `tools/xut/hw/fake.py`, `tools/tests/test_hw_session.py`

**Interfaces:**
- Produces (`xut.hw.session`):
  - `PROGRAM_ARGV = ("openFPGALoader", "-b", "arty")`, `pi_dir()`, `PI_FILES`, `FETCH`
  - errors: `TransportError` (retried once), `BoardBusy` (the lock stayed held: the job moves to the next rig; ruling S49), `BoardError` (the board is marked bad), `HarnessError`
  - `Transport` (Protocol): `run(alias, command, log, timeout_s) -> int`, `capture(alias, command, out, log, timeout_s) -> int` (stdout to `out` alone; the log gets the command line and stderr), `put(alias, files, remote_dir, log, timeout_s) -> int`, `get(alias, remote_files, local_dir, log, timeout_s) -> int`
  - `SshTransport(ssh_config)`
  - `SlotRun(slot, program)`, `HwJob(job_id, bitstream, build_id, runs)`
  - `JobResult(rig, site, board, serial, ofl_version, ident, loads, runs, duration_s, workdir)`
  - `Preflight(ok, detail, ofl_version)`; `PI_TOOLS`, `PREFLIGHT_OK`, `preflight_command(rig) -> str` (shared with `xut doctor`)
  - `BoardSession` (Protocol): `rig`, `preflight(log) -> Preflight`, `run_job(job, workdir) -> JobResult`, `reboot(log) -> None`
  - `SshBoardSession(rig, transport, owner=None)`
  - `session_json(job, baud) -> dict`, `parse_session(job, resp) -> tuple[IdReply, dict[int, LoadReply], dict[int, RunReply]]`
- Produces (`xut.hw.fake`): `FakeRig`, `FakeTransport(rigs, sim_factory=default_sim_factory)` (with `calls`, `programmings`), `FakeBuilder(cache_root)`, `default_sim_factory(slot: dict) -> DutSim`, `FlipSim`

The adapter boundary (spec §7.5): everything above `BoardSession` (pool, runner) speaks jobs; everything below it is SSH, `scp` and the three Pi scripts. A later fpgas.online lease API replaces `SshBoardSession` without touching the runner.

One job, from the session's point of view:

1. `mkdir -p xut-hw/<job-id>` on the rig;
2. `scp` into it `top.bit`, `session.json` and the three scripts from `hw/pi/`;
3. `cd xut-hw/<job-id> && sh ./xut_lock.sh <lock> <ttl> <wait> <owner> -- sh ./xut_work.sh <uart> <baud>`, with an SSH timeout of `lock_wait_s + lock_ttl_s + 180`: exit 0, or 75 (busy, and only busy: `BoardBusy`), 93 (a rig lock fault: `BoardError` naming the lock), 90/92 (board), or 91, 124/137 (the TTL: `timeout` stopped or killed the job), 255 or anything else (transport);
4. `scp` back `resp.json`, `program.log`, `uart.log`, `serial.txt` and `ofl-version.txt` (whatever exists, also on failure: they are the evidence);
5. `rm -rf xut-hw/<job-id>` (always; a failure here is logged, not raised);
6. `parse_session`: the `I` reply must name the job's build ID, or it is a `TransportError` (programming did not take). A load `badcrc` or a malformed or CRC-failing run reply is a `TransportError`. Other load statuses are a `HarnessError`. Run statuses are returned for the pool and the runner to judge.

- [ ] **Step 1: Write the failing tests.** `tools/tests/test_hw_session.py` drives `SshBoardSession` through `FakeTransport`:

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from xut.hw import proto
from xut.hw.fake import FakeBuilder, FakeRig, FakeTransport
from xut.hw.rigs import Rig
from xut.hw.selftest import selftest_programs
from xut.hw.session import (
    PI_TOOLS,
    PROGRAM_ARGV,
    BoardBusy,
    BoardError,
    HwJob,
    SlotRun,
    SshBoardSession,
    TransportError,
    preflight_command,
    session_json,
)
from xut.hw.slots import SELFTEST_SLOTS


def rig(name="r1", **kw) -> Rig:
    base = dict(
        name=name,
        host="10.0.0.1",
        jump="j",
        board="arty_a7_35t",
        uart="/dev/ttyUSB1",
        baud=115200,
        lock="/run/lock/fpga.lock",
        lock_ttl_s=900,
        lock_wait_s=600,
        site="test",
        identity_file=Path("/nonexistent/key"),
    )
    return Rig(**{**base, **kw})


def selftest_job(tmp_path) -> HwJob:
    bit = FakeBuilder(tmp_path / "cache").ensure(SELFTEST_SLOTS)
    runs = tuple(SlotRun(s, p) for s, p in selftest_programs().items())
    return HwJob("t-job", bit.path, bit.build_id, runs)


def test_program_argv_is_sram_only():
    assert PROGRAM_ARGV == ("openFPGALoader", "-b", "arty")


def test_run_job_ok_and_cleans_up(tmp_path):
    t = FakeTransport({"r1": FakeRig(serial="SN123")})
    res = SshBoardSession(rig(), t).run_job(selftest_job(tmp_path), tmp_path / "w")
    assert res.serial == "SN123" and res.ident.build == selftest_job(tmp_path).build_id
    assert res.runs[0].status == 0 and res.runs[1].status == 0
    cmds = [c for _, c in t.calls]
    job_cmds = [c for c in cmds if "xut_work.sh" in c]
    assert len(job_cmds) == 1 and "sh ./xut_lock.sh /run/lock/fpga.lock 900 600 " in job_cmds[0]
    assert cmds[-1].startswith("rm -rf xut-hw/")
    assert t.remote["xut-rig-r1"] == {}  # nothing left behind


@pytest.mark.parametrize(
    "fault,exc",
    [
        (dict(fail_transport=1), TransportError),
        (dict(busy=1), BoardBusy),
        (dict(program_fails=True), BoardError),
        (dict(no_uart=True), BoardError),
        (dict(lock_fault=True), BoardError),
        (dict(corrupt=1), TransportError),
        (dict(wrong_build=True), TransportError),
    ],
)
def test_faults_map_to_their_error_classes(tmp_path, fault, exc):
    t = FakeTransport({"r1": FakeRig(**fault)})
    with pytest.raises(exc):
        SshBoardSession(rig(), t).run_job(selftest_job(tmp_path), tmp_path / "w")
    assert t.remote["xut-rig-r1"] == {}  # cleaned up on failure too


def test_session_json_steps_and_timeouts(tmp_path):
    s = session_json(selftest_job(tmp_path), 115200)["steps"]
    assert [x["until"] for x in s] == ["line", "line", "end", "line", "end"]
    assert bytes.fromhex(s[0]["send"]) == proto.CMD_ID
    assert all(x["timeout_s"] >= 5 for x in s)


def test_preflight_reports_the_tools_version_not_the_command_line(tmp_path):
    """The real transport logs `$ ssh ... 'openFPGALoader --Version && echo XUT_PREFLIGHT_OK'`
    before the output; the fake does the same, so parsing the log would be caught here."""
    t = FakeTransport({"r1": FakeRig(ofl_version="openFPGALoader v0.13.1")})
    log = tmp_path / "pf.log"
    pf = SshBoardSession(rig(), t).preflight(log)
    assert pf.ok and pf.ofl_version == "openFPGALoader v0.13.1"
    assert log.read_text().startswith("$ ssh ")


def test_preflight_fails_when_openfpgaloader_fails(tmp_path):
    t = FakeTransport({"r1": FakeRig(ofl_version_fails=True)})
    pf = SshBoardSession(rig(), t).preflight(tmp_path / "pf.log")
    assert not pf.ok and "cannot open libftdi" in pf.detail and pf.ofl_version == ""


def test_preflight_command_masks_nothing():
    cmd = preflight_command(rig(uart="/dev/tty USB1"))
    assert "openFPGALoader --Version && echo XUT_PREFLIGHT_OK" in cmd
    assert "'/dev/tty USB1'" in cmd  # quoted
    for tool in PI_TOOLS:
        assert tool in cmd


def test_reboot_needs_a_configured_command_and_takes_the_lock(tmp_path):
    t = FakeTransport({"r1": FakeRig()})
    with pytest.raises(BoardError, match="reboot_command"):
        SshBoardSession(rig(), t).reboot(tmp_path / "l.log")
    SshBoardSession(rig(reboot_command="sudo -n /sbin/reboot"), t).reboot(tmp_path / "l.log")
    cmd = [c for _, c in t.calls if "reboot" in c][-1]
    assert "xut_lock.sh /run/lock/fpga.lock" in cmd and cmd.endswith(
        "-- sh -c 'sudo -n /sbin/reboot'"
    )
```

Run it; expected: `No module named 'xut.hw.session'`.

- [ ] **Step 2: Implement `tools/xut/hw/session.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Board access (spec §7.5): the ``BoardSession`` adapter and its SSH implementation.

A session runs whole *jobs*: program one bitstream (SRAM only) and exchange one UART
session, under the rig lock, in a single SSH command (see ``SshBoardSession.run_job``).
The ``Transport`` protocol separates this logic from ssh/scp, so ``xut.hw.fake``
tests every path without hardware. A later fpgas.online lease API replaces
``SshBoardSession`` without changing its callers.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from xut.errors import XutError
from xut.hw import proto
from xut.hw.image import HwProgram
from xut.hw.rigs import Rig
from xut.hw.steps import session_steps, slot_replies
from xut.paths import repo_root

#: The one programming command: SRAM only (never a flash option; AGENTS.md §10.2).
PROGRAM_ARGV = ("openFPGALoader", "-b", "arty")
PI_FILES = ("xut_lock.sh", "xut_work.sh", "xut_uart.py")
FETCH = ("resp.json", "program.log", "uart.log", "serial.txt", "ofl-version.txt")
RC_BUSY, RC_PROGRAM, RC_UART, RC_NO_UART, RC_LOCK_FAULT, RC_SSH = 75, 90, 91, 92, 93, 255
#: timeout(1) stopped the job at its TTL (124), or had to SIGKILL it (137): transport errors.
RC_TTL = (124, 137)


class TransportError(XutError, RuntimeError):
    """SSH/scp failed, the UART session timed out, a reply was corrupt, or the board runs
    another build: retried once (spec §7.5); a second one is an error."""


class BoardBusy(XutError, RuntimeError):
    """The rig lock stayed held for lock_wait_s (spec §7.5, ruling S49): a retryable
    ``error``, not a result and not the ``harness-error`` class. The job moves to the next
    rig; it does not use the transport retry, and the rig is not marked bad."""


class BoardError(XutError, RuntimeError):
    """The board cannot be used (programming failed, no UART): marked bad for the session."""


class HarnessError(XutError, RuntimeError):
    """The harness answered, but not as the protocol requires: a harness bug."""


class Transport(Protocol):
    def run(self, alias: str, command: str, log: Path, timeout_s: int) -> int: ...

    def capture(self, alias: str, command: str, out: Path, log: Path, timeout_s: int) -> int:
        """Run ``command``; its stdout goes to ``out`` alone, and ``log`` gets the command
        line and stderr. Callers parse ``out``, never ``log`` (it holds the command text)."""
        ...

    def put(
        self, alias: str, files: Sequence[Path], remote_dir: str, log: Path, timeout_s: int
    ) -> int: ...

    def get(
        self, alias: str, remote_files: Sequence[str], local_dir: Path, log: Path, timeout_s: int
    ) -> int: ...


class SshTransport:
    def __init__(self, ssh_config: Path) -> None:
        self.cfg = str(ssh_config)

    def _call(self, argv: list[str], log: Path, timeout_s: int, out: Path | None = None) -> int:
        """``argv`` with its command line and stderr in ``log``; stdout in ``out`` when
        given, else in ``log`` too."""
        with Path(log).open("a") as f:
            f.write(f"$ {shlex.join(argv)}\n")
            f.flush()
            try:
                if out is None:
                    return subprocess.run(
                        argv, stdout=f, stderr=subprocess.STDOUT, timeout=timeout_s
                    ).returncode
                with Path(out).open("w") as o:
                    return subprocess.run(argv, stdout=o, stderr=f, timeout=timeout_s).returncode
            except subprocess.TimeoutExpired:
                f.write(f"timeout after {timeout_s}s\n")
                return RC_SSH

    def run(self, alias: str, command: str, log: Path, timeout_s: int) -> int:
        return self._call(["ssh", "-F", self.cfg, alias, command], log, timeout_s)

    def capture(self, alias: str, command: str, out: Path, log: Path, timeout_s: int) -> int:
        return self._call(["ssh", "-F", self.cfg, alias, command], log, timeout_s, out)

    def put(
        self, alias: str, files: Sequence[Path], remote_dir: str, log: Path, timeout_s: int
    ) -> int:
        return self._call(
            ["scp", "-F", self.cfg, "-q", *map(str, files), f"{alias}:{remote_dir}/"],
            log,
            timeout_s,
        )

    def get(
        self, alias: str, remote_files: Sequence[str], local_dir: Path, log: Path, timeout_s: int
    ) -> int:
        srcs = [f"{alias}:{f}" for f in remote_files]
        return self._call(["scp", "-F", self.cfg, "-q", *srcs, str(local_dir)], log, timeout_s)


@dataclass(frozen=True)
class SlotRun:
    slot: int
    program: HwProgram


@dataclass(frozen=True)
class HwJob:
    job_id: str  # [A-Za-z0-9_.-]+: a directory name on the rig
    bitstream: Path
    build_id: int
    runs: tuple[SlotRun, ...]  # the self-test slots first


@dataclass
class JobResult:
    rig: str
    site: str
    board: str
    serial: str
    ofl_version: str
    ident: proto.IdReply
    loads: dict[int, proto.LoadReply]
    runs: dict[int, proto.RunReply]
    duration_s: float
    workdir: Path


@dataclass(frozen=True)
class Preflight:
    ok: bool
    detail: str
    ofl_version: str = ""


class BoardSession(Protocol):
    rig: Rig

    def preflight(self, log: Path) -> Preflight: ...

    def run_job(self, job: HwJob, workdir: Path) -> JobResult: ...

    def reboot(self, log: Path) -> None: ...


#: The Pi-side tools a rig needs (xut_lock.sh uses ps; xut_work.sh openFPGALoader and
#: python3), checked by the preflight and by ``xut doctor``.
PI_TOOLS = ("openFPGALoader", "flock", "timeout", "python3", "ps")
PREFLIGHT_OK = "XUT_PREFLIGHT_OK"
_OFL_VERSION = re.compile(r"^openFPGALoader v\S+")


def preflight_command(rig: Rig) -> str:
    """The rig preflight: every tool present, the UART a character device, and
    ``openFPGALoader --Version`` succeeding; ``PREFLIGHT_OK`` is printed only if all do
    (the ``&&`` keeps a failing ``--Version`` from being masked)."""
    q = shlex.quote
    uart = q(rig.uart)
    return (
        f"for t in {' '.join(PI_TOOLS)}; do command -v \"$t\" || "
        '{ echo "missing $t"; exit 3; }; done; '
        f'test -c {uart} || {{ echo "no UART device {rig.uart}"; exit 4; }}; '
        f"openFPGALoader --Version && echo {PREFLIGHT_OK}"
    )


def pi_dir() -> Path:
    """The Pi-side scripts (``hw/pi``), resolved when used, not at import."""
    return repo_root() / "hw" / "pi"


def _timeout_s(nbytes: int, baud: int) -> int:
    return int(5 + 3 * nbytes * 10 / baud)


def session_json(job: HwJob, baud: int) -> dict:
    """The UART steps (``session_steps`` order: I, then L and R per slot) with timeouts
    from the bytes each direction carries (3x the line time, plus 5 s)."""
    progs = {r.slot: r.program for r in job.runs}
    steps = []
    for s in session_steps(progs):
        if s.send == proto.CMD_RUN:
            width = max(p.noutw for p in progs.values())
            steps.append(
                {
                    "send": s.send.hex(),
                    "until": "end",
                    "timeout_s": _timeout_s(s.lines * (12 + width) + 128, baud),
                }
            )
        else:
            steps.append(
                {
                    "send": s.send.hex(),
                    "until": "line",
                    "timeout_s": _timeout_s(len(s.send) + 96, baud),
                }
            )
    return {"steps": steps}


def parse_session(
    job: HwJob, resp: dict
) -> tuple[proto.IdReply, dict[int, proto.LoadReply], dict[int, proto.RunReply]]:
    rx = [bytes.fromhex(s["rx"]) for s in resp["steps"]]
    slots = sorted(r.slot for r in job.runs)
    if len(rx) != 1 + 2 * len(slots):
        raise TransportError(f"UART session incomplete: {len(rx)} of {1 + 2 * len(slots)} replies")
    try:
        ident = proto.parse_id(rx[0])
        if ident.build != job.build_id:
            raise TransportError(
                f"the board runs build {ident.build:08x}, not {job.build_id:08x} "
                "(programming did not take?)"
            )
        loads, runs = {}, {}
        for slot, (load_rx, run_rx) in slot_replies(rx, slots).items():
            load = proto.parse_load(load_rx)
            if load.status == proto.STATUS_CODE["badcrc"]:
                raise TransportError(
                    f"slot {slot}: the harness received a corrupt program (badcrc)"
                )
            if load.status != proto.STATUS_CODE["ok"]:
                raise HarnessError(
                    f"slot {slot}: load status {proto.STATUS.get(load.status, load.status)}"
                )
            loads[slot], runs[slot] = load, proto.parse_run(run_rx)
    except proto.ProtoError as e:
        raise TransportError(f"corrupt UART reply: {e}") from e
    return ident, loads, runs


class SshBoardSession:
    def __init__(self, rig: Rig, transport: Transport, owner: str | None = None) -> None:
        self.rig, self.t = rig, transport
        self.owner = owner or f"{getpass.getuser()}@{socket.gethostname()}:{os.getpid()}"

    def preflight(self, log: Path) -> Preflight:
        """The rig's tools, UART device and ``openFPGALoader --Version``, judged from the
        command's stdout alone (``Transport.capture``), never from the log."""
        out = Path(log).with_suffix(".out")
        rc = self.t.capture(self.rig.alias, preflight_command(self.rig), out, log, 60)
        lines = out.read_text(errors="replace").splitlines() if out.is_file() else []
        ok = rc == 0 and PREFLIGHT_OK in lines
        ver = next((ln for ln in lines if _OFL_VERSION.match(ln)), "")
        if not ok:
            last = lines[-1] if lines else "no output"
            return Preflight(False, f"rc {rc}: {last} (see {log})", ver)
        return Preflight(True, "ok", ver)

    def _ok(self, rc: int, what: str) -> None:
        if rc != 0:
            raise TransportError(f"{self.rig.name}: {what} failed (rc {rc})")

    def run_job(self, job: HwJob, workdir: Path) -> JobResult:
        q, rig = shlex.quote, self.rig
        stage, got = workdir / "stage", workdir / "fetched"
        stage.mkdir(parents=True)
        got.mkdir()
        shutil.copy(job.bitstream, stage / "top.bit")
        for f in PI_FILES:
            shutil.copy(pi_dir() / f, stage / f)
        (stage / "session.json").write_text(json.dumps(session_json(job, rig.baud)))
        rdir, log, t0 = f"xut-hw/{job.job_id}", workdir / "transport.log", time.monotonic()
        try:
            self._ok(self.t.run(rig.alias, f"mkdir -p {q(rdir)}", log, 60), "mkdir")
            self._ok(
                self.t.put(rig.alias, sorted(stage.iterdir()), rdir, log, 600), "scp to the rig"
            )
            (stage / "top.bit").unlink()  # 2 MB per attempt adds up; the manifest has its sha256
            cmd = (
                f"cd {q(rdir)} && sh ./xut_lock.sh {q(rig.lock)} "
                f"{rig.lock_ttl_s} {rig.lock_wait_s} "
                f"{q(self.owner)} -- sh ./xut_work.sh {q(rig.uart)} {rig.baud}"
            )
            rc = self.t.run(rig.alias, cmd, log, rig.lock_wait_s + rig.lock_ttl_s + 180)
            got_rc = self.t.get(rig.alias, [f"{rdir}/{n}" for n in FETCH], got, log, 300)
        finally:
            self.t.run(rig.alias, f"rm -rf {q(rdir)}", log, 60)
        if rc == RC_BUSY:
            raise BoardBusy(f"{rig.name}: the rig lock {rig.lock} is busy (see {log})")
        if rc == RC_LOCK_FAULT:
            raise BoardError(
                f"{rig.name}: rig lock fault: {rig.lock} cannot be created or opened "
                f"(rc {rc}; a permissions or configuration problem, not busy; see {log})"
            )
        if rc in (RC_PROGRAM, RC_NO_UART):
            raise BoardError(
                f"{rig.name}: "
                + ("programming failed" if rc == RC_PROGRAM else "no UART device")
                + f" (rc {rc}; see {got})"
            )
        if rc != 0:
            raise TransportError(f"{rig.name}: the job failed (rc {rc}; see {log} and {got})")
        if got_rc != 0 or not (got / "resp.json").is_file():
            raise TransportError(f"{rig.name}: fetching the results failed (rc {got_rc})")
        ident, loads, runs = parse_session(job, json.loads((got / "resp.json").read_text()))

        def read(name: str) -> str:
            p = got / name
            return p.read_text(errors="replace").strip() if p.is_file() else ""

        ofl = read("ofl-version.txt").splitlines()
        return JobResult(
            rig.name,
            rig.site,
            rig.board,
            read("serial.txt"),
            ofl[0] if ofl else "",
            ident,
            loads,
            runs,
            round(time.monotonic() - t0, 3),
            workdir,
        )

    def reboot(self, log: Path) -> None:
        """Reboot the rig under its lock, when (and only when) the rig names a
        ``reboot_command``. The connection dropping (rc 255) is the expected outcome."""
        rig, q = self.rig, shlex.quote
        if not rig.reboot_command:
            raise BoardError(
                f"{rig.name}: no reboot_command configured; xut never reboots a rig by default"
            )
        rdir = f"xut-hw/reboot-{int(time.time())}"
        stage = Path(log).parent / "reboot-stage"
        stage.mkdir(parents=True, exist_ok=True)
        shutil.copy(pi_dir() / "xut_lock.sh", stage / "xut_lock.sh")
        self._ok(self.t.run(rig.alias, f"mkdir -p {q(rdir)}", log, 60), "mkdir")
        self._ok(self.t.put(rig.alias, [stage / "xut_lock.sh"], rdir, log, 60), "scp to the rig")
        cmd = (
            f"sh {q(rdir)}/xut_lock.sh {q(rig.lock)} 300 {rig.lock_wait_s} {q(self.owner)} "
            f"-- sh -c {q(rig.reboot_command)}"
        )
        rc = self.t.run(rig.alias, cmd, log, rig.lock_wait_s + 360)
        if rc not in (0, RC_SSH):
            raise BoardError(f"{rig.name}: reboot failed (rc {rc}; see {log})")
```

- [ ] **Step 3: Implement `tools/xut/hw/fake.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""A fake transport and builder for testing board access without hardware.

``FakeTransport`` plays the Pis: ``put``/``get`` use an in-memory file store per rig,
and the job command (which must run ``xut_work.sh`` under ``xut_lock.sh``) programs a
reference ``Harness`` from the fake bitstream and answers the session with it. Faults
are injected per rig: transport failures, a busy lock, failed programming, no UART,
a corrupt reply, a wrong build, a broken self-test, a flipped or flaky DUT output bit.
``FakeBuilder`` writes a JSON "bitstream" (the slots) instead of running Vivado.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from xut.hw.interp import DutSim, EmuSlot, Harness
from xut.hw.replay import ModelDut
from xut.hw.selftest import CounterSim, PassthroughSim
from xut.hw.session import PREFLIGHT_OK, RC_BUSY, RC_LOCK_FAULT, RC_NO_UART, RC_PROGRAM, RC_SSH
from xut.hw.slots import SlotBuild
from xut.hw.vivado import Bitstream, FlowMismatch
from xut.wrap import DutMap
from xut_models import registry


class FakeTransportError(AssertionError):
    """The code under test sent the fake something a real rig must never see."""


class FlipSim:
    """Inverts out_vec bit ``bit`` of ``inner`` (always, or on every other programming)."""

    def __init__(self, inner: DutSim, bit: int, active: bool = True) -> None:
        self.inner, self.bit, self.active = inner, bit, active

    def reset(self, t0: str) -> None:
        self.inner.reset(t0)

    def drive(self, in_bits: str, clk_bits: str) -> None:
        self.inner.drive(in_bits, clk_bits)

    def out_bits(self) -> str:
        b = list(self.inner.out_bits())
        if self.active:
            i = len(b) - 1 - self.bit
            b[i] = "1" if b[i] == "0" else "0"
        return "".join(b)


def default_sim_factory(slot: dict) -> DutSim:
    if slot["kind"] == "passthrough":
        return PassthroughSim()
    if slot["kind"] == "counter":
        return CounterSim()
    m = DutMap.from_json(slot["map_json"])
    model = registry.get(m.family, m.prim)  # looked up per call: tests monkeypatch it
    return ModelDut(model, m.attrs, m, two_state=True)


@dataclass
class FakeRig:
    serial: str = "FAKE0001"
    ofl_version: str = "openFPGALoader v0.13.1"
    ofl_version_fails: bool = False  # `openFPGALoader --Version` exits 1 in the preflight
    fail_transport: int = 0  # the next N job commands exit 255
    busy: int = 0  # the next N job commands find the lock busy (75)
    program_fails: bool = False  # 90
    no_uart: bool = False  # 92
    lock_fault: bool = False  # 93
    corrupt: int = 0  # the next N sessions get one byte of the last reply flipped
    wrong_build: bool = False  # the harness answers with another build ID
    broken_selftest: bool = False  # the passthrough slot inverts its bit 0
    flip_dut: dict[int, int] = field(default_factory=dict)  # slot -> out bit, always
    flaky_dut: dict[int, int] = field(default_factory=dict)  # slot -> out bit, odd programmings


class FakeTransport:
    def __init__(
        self, rigs: dict[str, FakeRig], sim_factory: Callable[[dict], DutSim] = default_sim_factory
    ) -> None:
        self.rigs, self.sim_factory = rigs, sim_factory
        self.remote: dict[str, dict[str, bytes]] = {f"xut-rig-{n}": {} for n in rigs}
        self.calls: list[tuple[str, str]] = []
        self.programmings: dict[str, int] = {n: 0 for n in rigs}

    def put(
        self, alias: str, files: Sequence[Path], remote_dir: str, log: Path, timeout_s: int
    ) -> int:
        for f in files:
            self.remote[alias][f"{remote_dir}/{Path(f).name}"] = Path(f).read_bytes()
        return 0

    def get(
        self, alias: str, remote_files: Sequence[str], local_dir: Path, log: Path, timeout_s: int
    ) -> int:
        rc = 0
        for f in remote_files:
            if f in self.remote[alias]:
                (Path(local_dir) / Path(f).name).write_bytes(self.remote[alias][f])
            else:
                rc = 1  # scp reports a missing source and carries on
        return rc

    def _log_command(self, alias: str, command: str, log: Path) -> None:
        """What ``SshTransport._call`` writes first: the full command line."""
        with Path(log).open("a") as f:
            f.write(f"$ {shlex.join(['ssh', '-F', 'ssh_config', alias, command])}\n")

    def capture(self, alias: str, command: str, out: Path, log: Path, timeout_s: int) -> int:
        self.calls.append((alias, command))
        self._log_command(alias, command, log)
        rig = self.rigs[alias.removeprefix("xut-rig-")]
        if PREFLIGHT_OK not in command:
            raise FakeTransportError(f"unexpected captured command {command!r}")
        if rig.ofl_version_fails:
            Path(out).write_text("/usr/bin/openFPGALoader\nerror: cannot open libftdi\n")
            return 1
        Path(out).write_text(f"/usr/bin/openFPGALoader\n{rig.ofl_version}\n{PREFLIGHT_OK}\n")
        return 0

    def run(self, alias: str, command: str, log: Path, timeout_s: int) -> int:
        self.calls.append((alias, command))
        self._log_command(alias, command, log)
        store = self.remote[alias]
        if command.startswith("mkdir -p "):
            return 0
        if command.startswith("rm -rf "):
            prefix = shlex.split(command)[2] + "/"
            for k in [k for k in store if k.startswith(prefix)]:
                del store[k]
            return 0
        if "xut_work.sh" in command:
            return self._job(alias, command)
        if "xut_lock.sh" in command:  # a reboot under the lock
            return RC_SSH
        return 127

    def _job(self, alias: str, command: str) -> int:
        # The fake is the oracle of the SRAM-under-lock rule: refuse any other job shape
        # (a raise, not an assert, so it holds under python -O too).
        if "sh ./xut_lock.sh " not in command or " -- sh ./xut_work.sh " not in command:
            raise FakeTransportError(f"a job must run xut_work.sh under xut_lock.sh: {command!r}")
        name = alias.removeprefix("xut-rig-")
        rig, store = self.rigs[name], self.remote[alias]
        rdir = shlex.split(command)[1]
        if rig.fail_transport:
            rig.fail_transport -= 1
            return RC_SSH
        if rig.busy:
            rig.busy -= 1
            return RC_BUSY
        if rig.program_fails:
            return RC_PROGRAM
        if rig.no_uart:
            return RC_NO_UART
        if rig.lock_fault:
            return RC_LOCK_FAULT
        bit = json.loads(store[f"{rdir}/top.bit"])
        session = json.loads(store[f"{rdir}/session.json"])
        self.programmings[name] += 1
        odd = self.programmings[name] % 2 == 1
        slots = []
        for k, s in enumerate(bit["slots"]):
            sim = self.sim_factory(s)
            if k == 0 and rig.broken_selftest:
                sim = FlipSim(sim, 0)
            if k in rig.flip_dut:
                sim = FlipSim(sim, rig.flip_dut[k])
            if k in rig.flaky_dut:
                sim = FlipSim(sim, rig.flaky_dut[k], active=odd)
            slots.append(EmuSlot(s["nin"], s["nout"], s["nclk"], s["t0"], sim))
        build = bit["build_id"] ^ (1 if rig.wrong_build else 0)
        h = Harness(build, slots)
        rx = [bytearray(h.feed(bytes.fromhex(st["send"]))) for st in session["steps"]]
        if rig.corrupt:
            rig.corrupt -= 1
            rx[-1][len(rx[-1]) // 2] ^= 0x01
        store[f"{rdir}/resp.json"] = json.dumps(
            {"steps": [{"rx": r.hex()} for r in rx], "discarded": 0}
        ).encode()
        store[f"{rdir}/serial.txt"] = f"{rig.serial}\n".encode()
        store[f"{rdir}/ofl-version.txt"] = b"openFPGALoader v0.13.1 (fake)\nrc=0\n"
        store[f"{rdir}/program.log"] = b"fake: programmed SRAM\n"
        store[f"{rdir}/uart.log"] = b""
        return 0


class FakeBuilder:
    """``flow_mismatch``: raise the post-flow DUT check's ``FlowMismatch`` instead, for
    every build (``True``) or for the slot sets a predicate picks."""

    def __init__(
        self,
        cache_root: Path,
        flow_mismatch: bool | Callable[[Sequence[SlotBuild]], bool] = False,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.flow_mismatch = flow_mismatch

    def version(self) -> str:
        return "fake-vivado"

    def ensure(self, slots: Sequence[SlotBuild]) -> Bitstream:
        fm = self.flow_mismatch
        if fm(slots) if callable(fm) else fm:
            raise FlowMismatch(
                "post-flow DUT check: slot 2: REF_NAME LUT1, configured TOYFF (retargeted)"
            )
        key = hashlib.sha256("".join(s.digest() for s in slots).encode()).hexdigest()
        bid = int(key[:8], 16)
        d = self.cache_root / "bit" / key
        d.mkdir(parents=True, exist_ok=True)
        body = {
            "fake": True,
            "build_id": bid,
            "slots": [
                {
                    "kind": s.kind,
                    "nin": s.nin,
                    "nout": s.nout,
                    "nclk": s.nclk,
                    "t0": s.t0,
                    "map_json": s.map_json,
                }
                for s in slots
            ],
        }
        (d / "top.bit").write_text(json.dumps(body))
        sha = hashlib.sha256((d / "top.bit").read_bytes()).hexdigest()
        man = {"key": key, "build_id": f"{bid:08x}", "bitstream_sha256": sha, "fake": True}
        return Bitstream(d / "top.bit", key, bid, sha, man)
```

The "corrupt" fault flips a byte in the middle of the last run reply. That breaks the reply's CRC, or its line syntax, and either way `parse_session` must turn it into a `TransportError`. Pin this with the parametrised test.

- [ ] **Step 4: Run the tests, lint and commit**

```bash
uv run pytest tools/tests/test_hw_session.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/hw/session.py tools/xut/hw/fake.py tools/tests/test_hw_session.py
git commit -m "hw: BoardSession over SSH (SRAM programming under the rig lock) and the fake transport" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9b: The board pool, `xut doctor` and `xut hw rigs`

**Files:**
- Create: `tools/xut/hw/pool.py`, `tools/tests/test_hw_pool.py`
- Modify: `tools/xut/doctor.py`, `tools/tests/test_doctor.py`, `tools/xut/cli.py` (`xut hw rigs`)

**Interfaces:**
- Consumes: `xut.hw.session`, `xut.hw.fake` (Task 9a), `xut.hw.selftest.check` (Task 3).
- Produces (`xut.hw.pool`): `BoardPool(sessions, lease_timeout_s=3600)` with `lease(avoid=())`, `mark_bad(name, why)`, `usable()` and `bad`; `NoBoard`; `JobOutcome(result, selftest, selftest_detail, attempts)`; `run_job(pool, job, workdir) -> JobOutcome`
- CLI: `xut hw rigs` runs the preflight of every enabled rig and prints `ok`/`FAIL` with the details (`openFPGALoader` version, the UART device), plus each disabled rig with its reason.

- [ ] **Step 1: Write the failing tests.** `tools/tests/test_hw_pool.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest
from test_hw_session import rig, selftest_job

from xut.hw.fake import FakeRig, FakeTransport
from xut.hw.pool import BoardPool, NoBoard, run_job
from xut.hw.session import BoardBusy, SshBoardSession, TransportError


def pool(rigs: dict[str, FakeRig]):
    t = FakeTransport(rigs)
    return BoardPool([SshBoardSession(rig(n), t) for n in rigs]), t


def test_ok(tmp_path):
    p, t = pool({"a": FakeRig()})
    out = run_job(p, selftest_job(tmp_path), tmp_path / "w")
    assert out.selftest == "pass" and out.attempts == ["attempt 1 on a: ok"]


def test_one_transport_retry_then_pass(tmp_path):
    p, _ = pool({"a": FakeRig(fail_transport=1)})
    out = run_job(p, selftest_job(tmp_path), tmp_path / "w")
    assert out.selftest == "pass" and len(out.attempts) == 2


def test_two_transport_errors_raise(tmp_path):
    p, _ = pool({"a": FakeRig(fail_transport=2)})
    with pytest.raises(TransportError):
        run_job(p, selftest_job(tmp_path), tmp_path / "w")


def test_selftest_failure_moves_to_another_board_once(tmp_path):
    p, _ = pool({"a": FakeRig(broken_selftest=True), "b": FakeRig()})
    out = run_job(p, selftest_job(tmp_path), tmp_path / "w")
    assert out.selftest == "pass" and "a" in p.bad and out.result.rig == "b"


def test_selftest_failing_everywhere_is_reported_not_raised(tmp_path):
    p, _ = pool({"a": FakeRig(broken_selftest=True), "b": FakeRig(broken_selftest=True)})
    out = run_job(p, selftest_job(tmp_path), tmp_path / "w")
    assert out.selftest == "fail" and "slot 0" in out.selftest_detail and set(p.bad) == {"a", "b"}


def test_single_board_selftest_failure_is_reported(tmp_path):
    p, _ = pool({"a": FakeRig(broken_selftest=True)})
    out = run_job(p, selftest_job(tmp_path), tmp_path / "w")
    assert out.selftest == "fail" and "no other board" in out.selftest_detail


def test_board_error_marks_bad_and_moves(tmp_path):
    p, _ = pool({"a": FakeRig(program_fails=True), "b": FakeRig()})
    out = run_job(p, selftest_job(tmp_path), tmp_path / "w")
    assert out.result.rig == "b" and "a" in p.bad


def test_a_busy_rig_moves_the_job_without_using_the_retry(tmp_path):
    p, _ = pool({"a": FakeRig(busy=1), "b": FakeRig(fail_transport=1)})
    out = run_job(p, selftest_job(tmp_path), tmp_path / "w")
    assert out.selftest == "pass" and out.result.rig == "b" and "a" not in p.bad
    assert [a.split(":")[1].strip() for a in out.attempts][:2] == ["busy", "transport error"]


def test_every_rig_busy_is_a_busy_error(tmp_path):
    p, _ = pool({"a": FakeRig(busy=1)})
    with pytest.raises(BoardBusy, match="every usable rig is busy"):
        run_job(p, selftest_job(tmp_path), tmp_path / "w")


def test_no_usable_board(tmp_path):
    p, _ = pool({"a": FakeRig()})
    p.mark_bad("a", "test")
    with pytest.raises(NoBoard):
        run_job(p, selftest_job(tmp_path), tmp_path / "w")
```

Run it; expected: `No module named 'xut.hw.pool'`.

- [ ] **Step 2: Implement `tools/xut/hw/pool.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Boards for a run (spec §7.5): lease, retry once, self-test first, mark bad.

``BoardPool`` gives each job one rig at a time (the threads of one ``xut run`` share
it); the rig's own flock (``xut_lock.sh``) protects it from every other user.
``run_job``:

- a ``BoardBusy`` (the rig lock stayed held) moves the job to the next rig without using
  the transport retry; when every usable rig was busy, ``BoardBusy`` is raised (a
  retryable `error`, never a result and not a `harness-error`; ruling S49);
- a ``TransportError`` is retried once (spec §7.5, §14); a second one is raised;
- a ``BoardError`` marks the board bad for the session and moves the job to another
  board, once;
- after every exchange the self-test slots are checked first. A failure marks the board
  bad and moves the job once; a second failure (or no other board) is returned with
  ``selftest="fail"`` (crosscheck: harness-error), never as a DUT result.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from xut.errors import XutError
from xut.hw import selftest
from xut.hw.session import BoardBusy, BoardError, BoardSession, HwJob, JobResult, TransportError


class NoBoard(XutError, RuntimeError):
    """No usable board is left for this job."""


class BoardPool:
    def __init__(self, sessions: Sequence[BoardSession], lease_timeout_s: float = 3600) -> None:
        self._sessions = {s.rig.name: s for s in sessions}
        self._free = list(self._sessions)
        self.bad: dict[str, str] = {}
        self.lease_timeout_s = lease_timeout_s
        self._cv = threading.Condition()

    def usable(self) -> list[str]:
        return [n for n in self._sessions if n not in self.bad]

    def mark_bad(self, name: str, why: str) -> None:
        with self._cv:
            self.bad[name] = why
            self._cv.notify_all()

    @contextmanager
    def lease(self, avoid: Collection[str] = ()) -> Iterator[BoardSession]:
        deadline = time.monotonic() + self.lease_timeout_s
        with self._cv:
            while True:
                ok = [n for n in self._sessions if n not in self.bad and n not in avoid]
                if not ok:
                    raise NoBoard(f"no usable board (bad: {self.bad}; avoided: {sorted(avoid)})")
                free = [n for n in self._free if n in ok]
                if free:
                    name = free[0]
                    self._free.remove(name)
                    break
                left = deadline - time.monotonic()
                if left <= 0:
                    raise NoBoard(f"no board became free within {self.lease_timeout_s}s")
                self._cv.wait(timeout=min(left, 5.0))
        try:
            yield self._sessions[name]
        finally:
            with self._cv:
                self._free.append(name)
                self._cv.notify_all()


@dataclass
class JobOutcome:
    result: JobResult
    selftest: str  # pass | fail
    selftest_detail: str | None
    attempts: list[str] = field(default_factory=list)


def run_job(pool: BoardPool, job: HwJob, workdir: Path) -> JobOutcome:
    attempts: list[str] = []
    avoid: set[str] = set()
    busy: list[str] = []
    retried = moved = False
    failed: tuple[JobResult, str] | None = None
    n = 0
    while True:
        n += 1
        try:
            lease = pool.lease(avoid)
            s = lease.__enter__()
        except NoBoard:
            if failed is not None:
                return JobOutcome(
                    failed[0], "fail", f"{failed[1]} (no other board to retry on)", attempts
                )
            if busy:
                raise BoardBusy(
                    f"every usable rig is busy (a retryable error, not a result): {'; '.join(busy)}"
                ) from None
            raise
        try:
            rig = s.rig.name
            try:
                res = s.run_job(job, workdir / f"attempt-{n}")
            except BoardBusy as e:  # ruling S49: move to the next rig; not a transport retry
                attempts.append(f"attempt {n} on {rig}: busy: {e}")
                busy.append(str(e))
                avoid.add(rig)
                continue
            except TransportError as e:
                attempts.append(f"attempt {n} on {rig}: transport error: {e}")
                if retried:
                    raise
                retried = True
                continue
            except BoardError as e:
                attempts.append(f"attempt {n} on {rig}: board error: {e}")
                pool.mark_bad(rig, str(e))
                if moved:
                    raise
                moved = True
                avoid.add(rig)
                continue
        finally:
            lease.__exit__(None, None, None)
        bad = [
            selftest.check(slot, res.runs[slot])
            for slot in (selftest.PASS_SLOT, selftest.COUNT_SLOT)
        ]
        detail = "; ".join(b for b in bad if b) or None
        if detail is None:
            attempts.append(f"attempt {n} on {rig}: ok")
            return JobOutcome(res, "pass", None, attempts)
        attempts.append(f"attempt {n} on {rig}: self-test failed: {detail}")
        pool.mark_bad(rig, f"self-test failed: {detail}")
        if moved:
            return JobOutcome(res, "fail", detail, attempts)
        moved, failed = True, (res, detail)
        avoid.add(rig)
```

(Write the lease handling with a `with` block and a small inner function if that reads better; the rules are the docstring's.)

- [ ] **Step 3: Doctor.** In `tools/xut/doctor.py`, replace the hard-coded `FPGAS_ONLINE_*` constants and `_check_fpgas_online` (the step-1 TODO: "read these from hw/boards/…") with checks driven by the rigs config. Nothing here may raise out of `run_checks` (a file write included), and a passing rig enables `hw` only when the key check passed and Vivado is installed:

```python
def _hw_checks(p: Probe) -> list[Check]:
    """hw-rigs (the config loads), hw-key (each key exists, mode 0600 or stricter),
    hw-ssh-config (the generated ssh config was written) and one hw:<rig> check per
    enabled rig (ssh through the jump host, the Pi's tools, the UART device). A passing
    hw:<rig> enables the hw runner only when every hw-key check passed and Vivado is
    installed (no bitstream can be built without it)."""
    from xut.hw.rigs import config_path, load_rigs, write_ssh_config
    from xut.hw.session import preflight_command
    from xut.paths import VIVADO_SETTINGS, repo_root

    try:
        root = repo_root()
        cfg = load_rigs(config_path(root))
    except Exception as e:  # noqa: BLE001 - doctor reports, never raises
        return [Check("hw-rigs", False, f"{type(e).__name__}: {e}")]
    out = [Check("hw-rigs", True, f"{cfg.path}: {len(cfg.enabled())} enabled rig(s)")]
    keys = [
        _safe("hw-key", (), lambda k=k: _check_key(p, k))
        for k in sorted({r.identity_file for r in cfg.enabled()})
    ]
    out += keys
    written: list[Path] = []

    def write() -> tuple[bool, str]:
        written.append(write_ssh_config(cfg, root))
        return True, str(written[0])

    out.append(_safe("hw-ssh-config", (), write))
    if not written:
        return out
    vivado = p.exists(VIVADO_SETTINGS)
    enables = ("hw",) if vivado and all(k.ok for k in keys) else ()
    why = (
        "" if enables else f" (hw unavailable: {'no Vivado' if not vivado else 'key check failed'})"
    )
    for r in cfg.enabled():
        cmd = [
            "ssh",
            "-F",
            str(written[0]),
            r.alias,
            preflight_command(r),
        ]
        c = _safe(f"hw:{r.name}", enables, lambda cmd=cmd: p.command_ok(cmd, timeout=30))
        out.append(Check(c.name, c.ok, c.detail + why, c.enables))
    for r in cfg.rigs:
        if not r.enabled:
            out.append(Check(f"hw:{r.name}", False, f"disabled: {r.reason}"))
    return out


def _check_key(p: Probe, key: Path) -> tuple[bool, str]:
    if not p.exists(key):
        return False, f"{key} not found (the project key; see fpgas-online/fpgas.online-infra#124)"
    mode = p.mode(key)
    if mode & 0o077:
        return False, f"{key} is group/world accessible ({oct(mode)})"
    return True, f"{key} ok"
```

Add `Probe.mode(path) -> int` (`Path(path).stat().st_mode & 0o777`). In `run_checks`, replace the `fpgas.online` entry with `*_hw_checks(p)`. Update `tools/tests/test_doctor.py`:
- a fake probe with a missing key gives `hw-key` false and no `hw` in `available_runners`, even with a passing rig;
- a missing Vivado likewise leaves `hw` out, with "no Vivado" in the rig's detail;
- a failing ssh command gives `hw:<rig>` false;
- one passing rig, with the key and Vivado present, enables `hw`;
- a broken `XUT_HW_CONFIG` file gives one failing `hw-rigs` check, an unwritable `.cache` gives a failing `hw-ssh-config` check, and doctor still does not raise.

(The command is `xut.hw.session.preflight_command`, the same one `xut hw rigs` runs: one tool list, `PI_TOOLS`, with `ps` for `xut_lock.sh`'s process groups, and the UART path quoted.)

- [ ] **Step 4: Add `xut hw rigs`** to `tools/xut/cli.py`:

```python
@hw_grp.command("rigs")
def hw_rigs_cmd() -> None:
    """Preflight every enabled rig (ssh via the jump host, the Pi's tools, the UART)."""
    from xut.hw.rigs import config_path, load_rigs, write_ssh_config
    from xut.hw.session import SshBoardSession, SshTransport

    root = repo_root()
    cfg = load_rigs(config_path(root))
    t = SshTransport(write_ssh_config(cfg, root))
    logs = root / ".cache" / "hw" / "rigs"
    logs.mkdir(parents=True, exist_ok=True)
    bad = 0
    for r in cfg.rigs:
        if not r.enabled:
            click.echo(f"{r.name:<14} disabled: {r.reason}")
            continue
        log = logs / f"{r.name}.log"
        log.write_text("")
        pf = SshBoardSession(r, t).preflight(log)
        bad += not pf.ok
        click.echo(
            f"{r.name:<14} {'ok  ' if pf.ok else 'FAIL'} {r.host} via {r.jump}  "
            f"{pf.ofl_version or pf.detail}  (log: {log})"
        )
    raise SystemExit(1 if bad else 0)
```

- [ ] **Step 5: Run the tests, lint and commit**

```bash
uv run pytest tools/tests/test_hw_pool.py tools/tests/test_doctor.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/hw/pool.py tools/xut/doctor.py tools/xut/cli.py tools/tests/test_hw_pool.py tools/tests/test_doctor.py
git commit -m "hw: board pool (busy rigs, one transport retry, self-test first), doctor rig checks and xut hw rigs" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: The `hw` runner

**Files:**
- Create: `tools/xut/runners/hw.py`, `tools/tests/test_runner_hw.py`
- Modify: `tools/xut/runners/__init__.py` (register `hw`), `tools/xut/runners/base.py` (`Runner.flows`, `RunContext.hw_repeats`/`hw_rigs`, `python_dir` always at flow `rtl`), `tools/xut/run.py` (python runs at `rtl`; a runner must run the selected flow), `tools/xut/cli.py` (`xut run --flow vivado --hw-repeats N --hw-rig NAME`), `tools/xut/schemas/result.schema.json` (the `hw` object), `tools/xut/crosscheck.py` (`dut_check` → `flow-mismatch`), `tools/tests/test_run.py`, `tools/tests/test_crosscheck.py`

**Interfaces:**
- Consumes: `plan_case` (Task 5b), `Builder`/`VivadoBuilder` (Task 6), `BoardPool`/`run_job` (Task 9b), `samples_to_trace` (Task 3), and the step-2 `Runner` template.
- Produces:
  - `xut.runners.hw.HwRunner` (`name = "hw"`, `x_observable = False`, `styles = {"vector"}`, `flows = {"vivado"}`)
  - `HwBackend(builder, pool, preflight)`, `backend(root, rigs=()) -> HwBackend` (process-wide, one per rig selection; tests replace it)
  - `REFERENCE = "unisim-2025.2"`
  - `Runner.flows: ClassVar[frozenset[str]] = frozenset({"rtl"})` on the base
  - `RunContext.hw_repeats: int = 3`, `RunContext.hw_rigs: tuple[str, ...] = ()`
  - `result.json` `hw`: `{rig, rigs, site, serial, board, part, repeats, repeats_differ, selftest, dut_check, dut_check_detail, build_ids, bitstream_sha256}` (`dna` stays optional; see "Spec ambiguities" 6)
  - `xut.crosscheck.classify`: a `hw` result with `dut_check = "fail"` is a `flow-mismatch` finding (spec rev 3.6 §8), with the check's detail as its point

How the runner plugs in (it is the xsim runner's shape; `Runner.run` does the rest):

- `available`: flow `vivado` (the base's new flow check), model source `unisim-2025.2`, Vivado installed, the rigs config loads, and at least one rig passed its preflight. Otherwise the result is a `skip` whose reason is the first failed condition, with every rig's preflight outcome.
- `configs`: the base's (the python run's `configs.json`). `config_exclusions.hw` are skipped by the base with their reason.
- `run_config`: the first call runs `_batch` for the whole test; each call then writes its configuration's `trace.xtr` (repeat 1), `trace-r<k>.xtr`, `mismatches.txt` and `run.log`, and returns its `ConfigResult`.
- `finish`: sets `res.hw` and adds the `openFPGALoader` version to `res.tools`.
- `tools` and `available` both call `backend()`; it is built (and the rigs preflighted) once per process and rig selection, then cached.

- [ ] **Step 1: Write the failing tests** — `tools/tests/test_runner_hw.py`. They use the step-2 TOYFF fixture test (`toy` fixture: `ToyDff` is its golden model) with `hw` declared, and the fakes from Task 9a:

```python
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import json
import subprocess
import sys

import pytest
from test_hw_session import rig
from test_runner_base import _case

from xut import crosscheck, schemas
from xut.errors import XutError
from xut.hw.fake import FakeBuilder, FakeRig, FakeTransport
from xut.hw.pool import BoardPool
from xut.hw.session import SshBoardSession
from xut.modelsrc import ModelSource
from xut.run import run_tests
from xut.runners import hw as hw_runner
from xut.formats import xtr
from xut.runners.base import RunContext, python_dir
from xut.runners.hw import HwBackend, HwRunner
from xut.runners.python import PythonRunner
from xut.runners.sim import S15_REASON

MS = "unisim-2025.2"


@pytest.fixture
def fake_hw(tmp_path, monkeypatch, toy):
    def make(rigs: dict[str, FakeRig], flow_mismatch=False):
        t = FakeTransport(rigs)
        pool = BoardPool([SshBoardSession(rig(n), t) for n in rigs])
        builder = FakeBuilder(tmp_path / "cache", flow_mismatch=flow_mismatch)
        be = HwBackend(builder, pool, {n: "ok" for n in rigs})
        monkeypatch.setattr(hw_runner, "backend", lambda root, rigs=(): be)
        monkeypatch.setattr(hw_runner, "settings_available", lambda: True)
        return be, t

    return make


def _case_hw():
    c = _case()  # 7series.TOYFF.L1.capture: configs init0, init1
    return dataclasses.replace(c, runners={**c.runners, "hw": "yes"}, flows=["rtl", "vivado"])


def _ctx(tmp_path, flow, **kw):
    return RunContext(tmp_path, flow, ModelSource(MS, tmp_path / "ms"), **kw)


def _run(tmp_path, repeats=3):
    case = _case_hw()
    assert PythonRunner().run(case, _ctx(tmp_path, "rtl")).status == "pass"
    return case, HwRunner().run(case, _ctx(tmp_path, "vivado", hw_repeats=repeats))


def _classes(tmp_path, case):
    views = crosscheck.gather(tmp_path, case.id)[MS]
    return sorted(f.cls for f in crosscheck.classify(case.id, views))


def test_pass(tmp_path, fake_hw):
    _, t = fake_hw({"a": FakeRig(serial="SN1")})
    case, res = _run(tmp_path)
    assert res.status == "pass", res.reason
    assert res.hw["selftest"] == "pass" and res.hw["repeats"] == 3 and not res.hw["repeats_differ"]
    assert res.hw["serial"] == "SN1" and res.hw["rig"] == "a" and len(res.hw["build_ids"]) == 1
    assert t.programmings["a"] == 3  # every repeat reprograms: slots run from power-on
    d = tmp_path / "build" / "vivado" / "hw" / MS / case.id
    schemas.validate(json.loads((d / "result.json").read_text()), "result")
    assert (d / "cfg-init0" / "trace-r3.xtr").is_file()
    assert _classes(tmp_path, case) == []
    jobs = [c for _, c in t.calls if "xut_work.sh" in c]
    assert len(jobs) == 3 and all(" sh ./xut_lock.sh " in f" {c}" for c in jobs)


def test_silicon_mismatch(tmp_path, fake_hw):
    fake_hw({"a": FakeRig(flip_dut={2: 0})})
    case, res = _run(tmp_path)
    assert res.status == "fail"
    assert _classes(tmp_path, case) == ["silicon-mismatch"]


def test_repeats_that_differ_are_nondeterminism(tmp_path, fake_hw):
    fake_hw({"a": FakeRig(flaky_dut={2: 0})})
    case, res = _run(tmp_path)
    assert res.status == "fail" and res.hw["repeats_differ"] is True
    assert "nondeterminism" in _classes(tmp_path, case)


def test_selftest_failing_everywhere_is_a_harness_error(tmp_path, fake_hw):
    fake_hw({"a": FakeRig(broken_selftest=True), "b": FakeRig(broken_selftest=True)})
    case, res = _run(tmp_path)
    assert res.status == "error" and res.hw["selftest"] == "fail"
    assert "self-test" in res.reason
    assert _classes(tmp_path, case) == ["harness-error"]


def test_a_failed_post_flow_dut_check_is_a_flow_mismatch(tmp_path, fake_hw):
    _, t = fake_hw({"a": FakeRig()}, flow_mismatch=True)
    case, res = _run(tmp_path)
    assert res.status == "error" and "flow-mismatch" in res.reason
    assert res.hw["dut_check"] == "fail" and t.programmings["a"] == 0  # nothing ran
    assert _classes(tmp_path, case) == ["flow-mismatch"]


def test_an_empty_expected_trace_is_an_error_on_hardware_too(tmp_path, fake_hw):
    """Ruling S15 on the hw path: no expected samples is never a pass."""
    fake_hw({"a": FakeRig()})
    case = _case_hw()
    assert PythonRunner().run(case, _ctx(tmp_path, "rtl")).status == "pass"
    exp = python_dir(_ctx(tmp_path, "rtl"), case) / "cfg-init0" / "expected.xtr"
    xtr.dump(xtr.Trace(xtr.load(exp).header), exp)
    res = HwRunner().run(case, _ctx(tmp_path, "vivado"))
    by_cfg = {c.cfg: c for c in res.configs}
    assert by_cfg["init0"].status == "error" and by_cfg["init0"].reason == S15_REASON
    assert by_cfg["init1"].status == "pass"


def test_a_dut_check_failure_does_not_hide_a_silicon_mismatch(tmp_path, fake_hw, monkeypatch):
    """Two bitstream groups (one configuration each): group A fails its post-flow DUT
    check, group B runs and its DUT output differs on silicon. Both findings are reported:
    neither class masks the other (spec §8)."""
    monkeypatch.setattr("xut.hw.slots.DUT_BUFG_BUDGET", 1)  # one DUT per bitstream
    failing: list[str] = []

    def fails_first_group(slots):
        if not failing:
            failing.append(slots[2].digest())
        return slots[2].digest() == failing[0]

    fake_hw({"a": FakeRig(flip_dut={2: 0})}, flow_mismatch=fails_first_group)
    case, res = _run(tmp_path)
    assert res.hw["dut_check"] == "fail"
    assert [c.status for c in res.configs].count("error") == 1
    assert [c.status for c in res.configs].count("fail") == 1
    assert _classes(tmp_path, case) == ["flow-mismatch", "silicon-mismatch"]


def test_a_golden_dont_care_bit_reaches_the_fake_board_as_0(monkeypatch):
    """A '-' output (a documented don't-care) must not break the fake board's protocol."""
    from xut.hw.fake import default_sim_factory
    from xut.wrap import Bit, DutMap
    from xut_models.base import Model, Out

    class DontCare(Model):
        PRIM, CLOCKS, OUTPUTS = "DC", (), {"O": 1}

        @classmethod
        def inputs(cls):
            return {"I": 1}

        def power_on(self):
            pass

        def set_input(self, port, value):
            pass

        def clock_edge(self, port, rising):
            pass

        def glbl(self, signal, value):
            pass

        def outputs(self):
            return {"O": Out("-", "doc:1")}

    bits = [Bit("in", 0, "I", 0, "data"), Bit("out", 0, "O", 0, "data")]
    m = DutMap("DC", "7series", "c", {}, 0, 1, 1, bits)
    monkeypatch.setattr("xut_models.registry.get", lambda family, prim: DontCare)
    sim = default_sim_factory({"kind": "dut", "map_json": m.to_json()})
    sim.reset("0")
    assert sim.out_bits() == "0"


def test_a_bad_board_is_replaced(tmp_path, fake_hw):
    be, _ = fake_hw({"a": FakeRig(broken_selftest=True), "b": FakeRig()})
    _, res = _run(tmp_path, repeats=2)
    assert res.status == "pass" and "a" in be.pool.bad and res.hw["rigs"] == ["b"]


def test_transport_error_retried_once_never_into_a_pass(tmp_path, fake_hw):
    fake_hw({"a": FakeRig(fail_transport=1)})
    assert _run(tmp_path, repeats=1)[1].status == "pass"


def test_transport_twice_is_an_error(tmp_path, fake_hw):
    fake_hw({"a": FakeRig(fail_transport=2)})
    _, res = _run(tmp_path, repeats=1)
    assert res.status == "error" and "rc 255" in res.reason


def test_flow_rtl_is_a_skip(tmp_path, fake_hw):
    fake_hw({"a": FakeRig()})
    res = HwRunner().run(_case_hw(), _ctx(tmp_path, "rtl"))
    assert res.status == "skip" and "does not run flow rtl" in res.reason


@pytest.mark.parametrize(
    "mod", ["xut.hw.plan", "xut.hw.hwsim", "xut.hw.session", "xut.hw.fake", "xut.runners"]
)
def test_each_module_imports_first(mod):
    """xut.hw.plan and xut.hw.hwsim import xut.runners, whose registry imports the hw
    runner: each module must import cleanly as the first one in a fresh interpreter."""
    r = subprocess.run([sys.executable, "-c", f"import {mod}"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_run_tests_python_at_rtl_hw_at_vivado(tmp_path, fake_hw):
    fake_hw({"a": FakeRig()})
    case = _case_hw()
    results = run_tests([case], ["hw"], _ctx(tmp_path, "vivado"))
    assert {(r.runner, r.flow) for r in results} == {("python", "rtl"), ("hw", "vivado")}
    assert (tmp_path / "build" / "rtl" / "python" / MS / case.id / "result.json").is_file()
    with pytest.raises(XutError, match=r"runner\(s\) \['xsim'\] do not run flow vivado"):
        run_tests([case], ["xsim"], _ctx(tmp_path, "vivado"))
```

Run `uv run pytest tools/tests/test_runner_hw.py > .cache/pytest.log 2>&1; cat .cache/pytest.log`. Expected: `No module named 'xut.runners.hw'`.

- [ ] **Step 2: Extend the base, `run.py` and the schema.**

In `tools/xut/runners/base.py`:
- add `from typing import ClassVar` (already imported) and on `Runner`: `flows: ClassVar[frozenset[str]] = frozenset({"rtl"})`;
- in `Runner._run`, after the style check: `if ctx.flow not in self.flows: return self._skip(case, ctx, d, f"runner {self.name} does not run flow {ctx.flow}")`;
- on `RunContext`, after `provenance`: `hw_repeats: int = 3` and `hw_rigs: tuple[str, ...] = ()`;
- `python_dir` becomes `return ctx.root / "build" / "rtl" / "python" / ctx.model_source.name / case.id` (the golden model only ever runs the `rtl` flow: `xut.testspec.runner_flows`). Its docstring says so.

In `tools/xut/run.py` `run_tests`:

```python
    known = runner_registry.RUNNERS
    names = with_companions(runner_names)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise XutError(f"unknown runner(s) {unknown} (known: {sorted(known)})")
    wrong = [n for n in names if n != "python" and ctx.flow not in known[n].flows]
    if wrong:
        runs = sorted(n for n, r in known.items() if ctx.flow in r.flows)
        raise XutError(f"runner(s) {wrong} do not run flow {ctx.flow} (flow {ctx.flow}: {runs})")
    rtl = dataclasses.replace(ctx, flow="rtl")  # the golden model runs flow rtl only
```

and run every python pair with `rtl` (`_one(c, n, rtl if n == "python" else ctx)` in `job`). Add `import dataclasses`. Extend `tools/tests/test_run.py` with the error case and a check that an `rtl` run is unchanged.

In `tools/xut/cli.py` `run_cmd`: `--flow` becomes `click.Choice(["rtl", "vivado"])`. The default runner list becomes `[r for r in RUNNERS if r != "iverilog-vz" and flow in RUNNERS[r].flows]` (flow `vivado`: `["hw"]`; python runs first regardless). Add

```python
@click.option(
    "--hw-repeats",
    type=click.IntRange(min=1, max=20),
    default=3,
    show_default=True,
    help="hw: programmings per bitstream; repeats that differ are nondeterminism (spec §5.6)",
)
@click.option(
    "--hw-rig", "hw_rigs", multiple=True, help="hw: only these rigs (default: every enabled rig)"
)
```

and pass them into the `RunContext` (`hw_repeats=hw_repeats, hw_rigs=tuple(hw_rigs)`).

In `tools/xut/crosscheck.py` `classify`, in the `runner == "hw"` branch, add the `flow-mismatch` finding and **delete the existing `continue` after the `harness-error` finding**. Neither class may mask another (spec §8, AGENTS.md §9): one hw result spans several bitstream groups, and a group whose DUT check or self-test failed has only `error` configurations, which `View.ran` already leaves out of every comparison, so the other groups' `nondeterminism` and `silicon-mismatch` findings still follow. The branch becomes:

```python
        if runner == "hw":
            hw = v.result.get("hw") or {}
            if hw.get("dut_check") == "fail":
                detail = hw.get("dut_check_detail") or "post-flow DUT check failed"
                out.append(_f("flow-mismatch", test_id, flow, None, ["hw"], [detail]))
            if hw.get("selftest") == "fail":
                out.append(_f("harness-error", test_id, flow, None, ["hw"], ["self-test failed"]))
            if hw.get("repeats_differ"):
                ...  # unchanged: the nondeterminism finding
            if exp is not None and _has_trace(exp) and _has_trace(v):
                ...  # unchanged: the silicon-mismatch comparison over the configurations that ran
```

Pin it in `tools/tests/test_crosscheck.py` with synthetic views, as the existing `harness-error` test does: a hw view with `dut_check = "fail"` **and** one configuration that ran with a mismatching trace gives both `flow-mismatch` and `silicon-mismatch`; the same with `selftest = "fail"` gives both `harness-error` and `silicon-mismatch`.

In `tools/xut/schemas/result.schema.json`, replace the `hw` property:

```json
    "hw": {
      "type": ["object", "null"],
      "$comment": "hw runner only (spec §6, §7.5); crosscheck reads selftest (harness-error), repeats and repeats_differ (nondeterminism), dut_check (flow-mismatch).",
      "additionalProperties": false,
      "properties": {
        "dna": {"type": "string"},
        "serial": {"type": "string"},
        "site": {"type": "string"},
        "rig": {"type": "string"},
        "rigs": {"type": "array", "items": {"type": "string"}},
        "board": {"type": "string"},
        "part": {"type": "string"},
        "repeats": {"type": "integer", "minimum": 1},
        "repeats_differ": {"type": "boolean"},
        "selftest": {"enum": ["pass", "fail", "not-run"]},
        "dut_check": {"enum": ["pass", "fail", "not-run"]},
        "dut_check_detail": {"type": "string"},
        "build_ids": {"type": "array", "items": {"type": "string", "pattern": "^[0-9a-f]{8}$"}},
        "bitstream_sha256": {"type": "array", "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}
      }
    }
```

- [ ] **Step 3: Implement `tools/xut/runners/hw.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The hardware runner (spec §6 ``hw``, §7): vector tests on fpgas.online boards.

Flow ``vivado`` only for now (step 4 adds the open flows' bitstreams). Results go to
``build/vivado/hw/<model-source>/<test-id>/``, beside the golden model's
``build/rtl/python/<model-source>/<test-id>/``, so crosscheck pairs them (spec §8
``silicon-mismatch``). Only the reference model source records hw results.

On the first ``run_config`` of a test, ``_batch`` does the whole test:

1. ``plan_case``: every python configuration compiled for the harness, or settled
   (``config_exclusions`` or not hardware-renderable: skip with the reason; anything
   else: error);
2. one bitstream per packed group (``Builder.ensure``, cached);
3. ``ctx.hw_repeats`` programmings per bitstream (``pool.run_job``: self-test first,
   one transport retry, a bad board replaced once). Every repeat reprograms: a slot runs
   once per configuration of the FPGA, so every DUT starts from its power-on state;
4. per configuration: the samples of every repeat as traces. Repeats that differ fail
   (nondeterminism, spec §5.6); otherwise repeat 1 is compared with the golden trace
   (2-state: x/z expectations are not observable).

A self-test failure makes every configuration of that bitstream an ``error`` and sets
``hw.selftest = "fail"`` (crosscheck: harness-error), never a DUT ``fail``. A build
failure, a second transport error or a harness status other than ``ok`` is an ``error``
with the reason, never retried into a pass (spec §14).
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from xut.errors import XutError
from xut.formats import xtr
from xut.hw import proto
from xut.hw.pool import BoardPool, run_job
from xut.hw.replay import samples_to_trace
from xut.hw.rigs import config_path, load_rigs, write_ssh_config
from xut.hw.session import HwJob, SlotRun, SshBoardSession, SshTransport
from xut.hw.vivado import PART, Builder, FlowMismatch, VivadoBuilder
from xut.runners.base import (
    ConfigResult,
    RunContext,
    Runner,
    RunResult,
    error_reason,
    trace_header,
    workdir,
)
from xut.runners.sim import judge_trace
from xut.runners.xsim import settings_available
from xut.testspec import TestCase

if TYPE_CHECKING:
    from xut.hw.plan import CfgPlan, TestPlan

REFERENCE = "unisim-2025.2"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass
class HwBackend:
    builder: Builder
    pool: BoardPool
    preflight: dict[str, str] = field(default_factory=dict)  # rig -> "ok" or why not


_BACKENDS: dict[tuple[Path, tuple[str, ...]], HwBackend] = {}
_LOCK = threading.Lock()


def backend(root: Path, rigs: tuple[str, ...] = ()) -> HwBackend:
    """The process-wide backend for ``root`` and ``rigs`` (every enabled rig when empty): the
    Vivado builder and a pool of the rigs that passed their preflight."""
    key = (Path(root).resolve(), rigs)
    with _LOCK:
        if key not in _BACKENDS:
            cfg = load_rigs(config_path(root))
            chosen = [cfg.get(n) for n in rigs] if rigs else cfg.enabled()
            t = SshTransport(write_ssh_config(cfg, root))
            logs = Path(root) / ".cache" / "hw" / "preflight"
            logs.mkdir(parents=True, exist_ok=True)
            sessions, pre = [], {}
            for r in chosen:
                if not r.enabled:
                    pre[r.name] = f"disabled: {r.reason}"
                    continue
                s = SshBoardSession(r, t)
                log = logs / f"{r.name}.log"
                log.write_text("")
                pf = s.preflight(log)
                pre[r.name] = "ok" if pf.ok else f"preflight failed ({pf.detail}; see {log})"
                if pf.ok:
                    sessions.append(s)
            _BACKENDS[key] = HwBackend(VivadoBuilder(root), BoardPool(sessions), pre)
        return _BACKENDS[key]


@dataclass
class _Done:
    """One configuration's outcome from ``_batch``: either settled (``result``: a skip or
    an error) or its plan item with the traces of every repeat, judged in ``run_config``."""

    result: ConfigResult | None = None
    item: CfgPlan | None = None
    traces: list[xtr.Trace] = field(default_factory=list)
    differ: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


class HwRunner(Runner):
    name = "hw"
    x_observable = False
    styles = frozenset({"vector"})
    flows: ClassVar[frozenset[str]] = frozenset({"vivado"})

    def __init__(self) -> None:
        self._done: dict[str, _Done] | None = None
        self._hw: dict = {}
        self._ofl = ""

    def available(self, ctx: RunContext) -> tuple[bool, str]:
        if ctx.model_source.name != REFERENCE:
            return (
                False,
                f"hw results are recorded against the reference model source {REFERENCE} only",
            )
        if not settings_available():
            return False, "Vivado 2025.2 not installed (bitstreams cannot be built)"
        try:
            be = backend(ctx.root, ctx.hw_rigs)
        except XutError as e:
            return False, f"no board access: {e}"
        if not be.pool.usable():
            detail = "; ".join(f"{k}: {v}" for k, v in be.preflight.items()) or "no enabled rig"
            return False, f"no rig passed its preflight: {detail}"
        return True, ""

    def tools(self, ctx: RunContext) -> dict:
        return {
            "vivado": backend(ctx.root, ctx.hw_rigs).builder.version(),
            "harness": f"xut-hw {proto.PROTO}",
        }

    def run_config(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext) -> ConfigResult:
        if self._done is None:
            self._done = self._batch(case, ctx, workdir(ctx, self.name, case.id))
        done = self._done.get(cfg)
        if done is None:
            return ConfigResult(
                cfg, "error", "the python run lists this configuration but the hw plan does not"
            )
        (cd / "run.log").write_text("".join(f"{ln}\n" for ln in done.log))
        if done.result is not None:
            return done.result
        if done.item is None or not done.traces:  # _batch sets both together
            return ConfigResult(cfg, "error", "hw batch left this configuration without traces")
        for k, t in enumerate(done.traces, start=1):
            xtr.dump(t, cd / f"trace-r{k}.xtr")
        problems = []
        if done.differ:
            shown = "; ".join(done.differ[:3])
            problems.append(f"nondeterminism ({len(done.differ)} difference(s)): {shown}")
        r = judge_trace(
            cd,
            done.traces[0],
            done.item.expected,
            x_observable=self.x_observable,
            stim_sha256=done.item.stim_sha256,
            problems=problems,
        )
        if done.differ:
            with (cd / "mismatches.txt").open("a") as f:
                f.writelines(f"{m}\n" for m in done.differ)
        return r

    def finish(self, case: TestCase, ctx: RunContext, d: Path, res: RunResult) -> None:
        res.hw = self._hw or None
        if self._ofl:
            res.tools = {**res.tools, "openFPGALoader": self._ofl}

    def _batch(self, case: TestCase, ctx: RunContext, d: Path) -> dict[str, _Done]:
        # Imported here: xut.hw.plan imports xut.runners.base, and importing that package
        # imports this module (the RUNNERS registry), so a module-level import is circular.
        from xut.hw.plan import plan_case

        plan = plan_case(case, ctx)
        done = {c: _Done(ConfigResult(c, st, why)) for c, (st, why) in plan.settled.items()}
        self._hw = {
            "part": PART,
            "repeats": ctx.hw_repeats,
            "repeats_differ": False,
            "selftest": "not-run",
            "dut_check": "not-run",
            "build_ids": [],
            "bitstream_sha256": [],
            "rigs": [],
        }
        for g in range(len(plan.groups)):
            done.update(self._group(case, ctx, d, plan, g))
        return done

    def _group(self, case: TestCase, ctx: RunContext, d: Path, plan: TestPlan, g: int) -> dict:
        """One bitstream group: build it, run it ``hw_repeats`` times, and return each
        member configuration's ``_Done``."""
        hw, be = self._hw, backend(ctx.root, ctx.hw_rigs)
        members = plan.members(g)
        log = [f"group {g}: configurations {', '.join(it.cfg for it in members)}"]

        def settle(why: str) -> dict:
            return {
                it.cfg: _Done(ConfigResult(it.cfg, "error", why, it.stim_sha256), log=[*log, why])
                for it in members
            }

        try:
            bit = be.builder.ensure(plan.slots(g))
        except FlowMismatch as e:  # spec §6 post-flow DUT check: a toolchain bug, no DUT result
            hw["dut_check"] = "fail"
            hw["dut_check_detail"] = str(e)
            return settle(f"flow-mismatch: {e}")
        except Exception as e:
            return settle(f"bitstream build failed: {error_reason(e)}")
        if hw["dut_check"] == "not-run":
            hw["dut_check"] = "pass"
        hw["build_ids"].append(f"{bit.build_id:08x}")
        hw["bitstream_sha256"].append(bit.sha256)
        log.append(f"bitstream {bit.build_id:08x}: {bit.path}")
        runs = tuple(SlotRun(s, p) for s, p in plan.programs(g).items())
        dut_slots = [plan.dut_slot(j) for j in range(len(members))]
        reps: dict[int, list[tuple[str, ...]]] = {s: [] for s in dut_slots}
        for r in range(1, ctx.hw_repeats + 1):
            job_id = f"{_SAFE.sub('_', case.id)}-g{g}-r{r}-{uuid.uuid4().hex[:8]}"
            try:
                out = run_job(be.pool, HwJob(job_id, bit.path, bit.build_id, runs), d / "jobs" / job_id)
            except Exception as e:  # a second transport error, no free rig, a harness bug
                return settle(f"repeat {r}: {error_reason(e)}")
            log += out.attempts
            res = out.result
            hw.update(rig=res.rig, site=res.site, serial=res.serial, board=res.board)
            if res.rig not in hw["rigs"]:
                hw["rigs"].append(res.rig)
            self._ofl = res.ofl_version or self._ofl
            if out.selftest == "fail":
                hw["selftest"] = "fail"
                return settle(
                    f"harness self-test failed on {res.rig} (a harness error, "
                    f"not a DUT result): {out.selftest_detail}"
                )
            if hw["selftest"] == "not-run":
                hw["selftest"] = "pass"
            bad = [s for s in dut_slots if res.runs[s].status != proto.STATUS_CODE["ok"]]
            if bad:
                st = proto.STATUS.get(res.runs[bad[0]].status, res.runs[bad[0]].status)
                return settle(f"repeat {r}: the harness ended slot {bad[0]} with status {st}")
            for s in dut_slots:
                reps[s].append(res.runs[s].samples)
        out_done = {}
        for j, it in enumerate(members):
            header = trace_header(self.name, case, it.cfg, ctx) | {
                "seed": str(it.seed),
                "rig": hw["rig"],
            }
            traces = [samples_to_trace(s, it.prog.labels, it.m, header) for s in reps[dut_slots[j]]]
            differ = [
                f"repeat {k + 1} vs repeat 1: {m}"
                for k in range(1, len(traces))
                for m in xtr.diff(traces[0], traces[k], a_x=False, b_x=False)
            ]
            hw["repeats_differ"] = hw["repeats_differ"] or bool(differ)
            out_done[it.cfg] = _Done(item=it, traces=traces, differ=differ, log=list(log))
        return out_done
```

Register it in `tools/xut/runners/__init__.py`: `from xut.runners.hw import HwRunner` and `"hw": HwRunner` in `RUNNERS`.

- [ ] **Step 4: Run the tests, the whole fast suite, lint and commit**

```bash
uv run pytest tools/tests/test_runner_hw.py tools/tests/test_run.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
systemd-run --user --scope --slice=vivado.slice --unit=xut-pytest-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run pytest -n 4 --dist loadfile -m "not slow" > .cache/pytest-all.log 2>&1; tail -n 5 .cache/pytest-all.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/runners tools/xut/run.py tools/xut/cli.py tools/xut/crosscheck.py tools/xut/schemas/result.schema.json tools/tests/test_runner_hw.py tools/tests/test_run.py tools/tests/test_crosscheck.py
git commit -m "runners: add the hw runner (flow vivado; self-test, repeats, silicon cross-check) and xut run --flow vivado" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: all pass, including every step-2 test (the `python_dir` change is a no-op for `rtl` runs).

CI needs no change. The `hw` tests skip without `XUT_HW=1` (Task 8). The `container`-marked harness tests (Tasks 4, 5 and 11) run in the existing container job, against the submodule's models. CI never selects `--flow vivado`.

---

### Task 11: The LUT6 smoke design and `xut hw smoke` (board bring-up)

**Files:**
- Create: `tools/xut/hw/smoke.py`, `tools/tests/test_hw_smoke.py`
- Modify: `tools/xut/cli.py` (`xut hw smoke`)

**Interfaces:**
- Produces (`xut.hw.smoke`):
  - `LUT6_INITS`, `Lut6Sim(init, m)`, `SmokeSlot(m, prog, slot, init)`
  - `smoke_slots(root) -> list[SmokeSlot]`, `smoke_layout(root) -> tuple[slots, programs, expected]`
  - `check_replies(runs, expected) -> list[str]`
  - `smoke_sim(root, sim, workdir, model_source) -> list[str]`, `smoke_board(root, session, builder, workdir) -> list[str]`
- CLI: `xut hw smoke [--sim iverilog|xsim] [--rig NAME]...`. With `--sim`, it runs the smoke bitstream's design in simulation. Otherwise it builds the bitstream and runs it on each named (default: every enabled) rig, one after the other, printing `PASS`/`FAIL` per rig with the first problems. It exits 1 on any failure.

The smoke design needs no work unit: four LUT6 slots (INIT all 0, all 1, alternating and one fixed pattern), each driven through all 64 addresses with a sample after each, plus the self-test channels. Its expectation is LUT6's documented function, O = INIT[{I5,I4,I3,I2,I1,I0}] (UG953, LUT6), computed by `Lut6Sim`; the luts unit's golden model is not involved. It is the stand-in for the luts pilot when that unit has not merged (Task 13).

- [ ] **Step 1: Write the failing tests** — `tools/tests/test_hw_smoke.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest
from test_hw_session import rig

from xut.hw.fake import FakeBuilder, FakeRig, FakeTransport, default_sim_factory
from xut.hw.session import SshBoardSession
from xut.hw.smoke import LUT6_INITS, Lut6Sim, smoke_board, smoke_layout, smoke_sim
from xut.modelsrc import resolve
from xut.paths import repo_root
from xut.wrap import DutMap, literal_value


def test_expected_is_the_truth_table():
    _, progs, exp = smoke_layout(repo_root())
    assert exp[2] == ["0"] * 64 and exp[3] == ["1"] * 64
    assert exp[4] == ["0", "1"] * 32  # 0xAAAA...: O = address bit 0
    fixed = LUT6_INITS[3]
    assert exp[5] == [str((fixed >> a) & 1) for a in range(64)]


def _lut_factory(slot: dict):
    if slot["kind"] != "dut":
        return default_sim_factory(slot)
    m = DutMap.from_json(slot["map_json"])
    return Lut6Sim(literal_value(m.attrs["INIT"]), m)


def test_smoke_on_a_fake_board(tmp_path):
    t = FakeTransport({"a": FakeRig()}, sim_factory=_lut_factory)
    problems = smoke_board(
        repo_root(), SshBoardSession(rig("a"), t), FakeBuilder(tmp_path / "c"), tmp_path / "w"
    )
    assert problems == []


def test_smoke_detects_a_wrong_lut(tmp_path):
    t = FakeTransport({"a": FakeRig(flip_dut={4: 0})}, sim_factory=_lut_factory)
    problems = smoke_board(
        repo_root(), SshBoardSession(rig("a"), t), FakeBuilder(tmp_path / "c"), tmp_path / "w"
    )
    assert problems and "slot 4" in problems[0]


@pytest.mark.container
def test_smoke_in_icarus(tmp_path):
    assert (
        smoke_sim(repo_root(), "iverilog", tmp_path / "sim", resolve("auto"), work_root=tmp_path)
        == []
    )


@pytest.mark.hw
@pytest.mark.vivado
def test_smoke_on_every_enabled_rig(tmp_path):
    """Real boards (XUT_HW=1 only; CI never runs it)."""
    from xut.hw.rigs import config_path, load_rigs, write_ssh_config
    from xut.hw.session import SshTransport
    from xut.hw.vivado import VivadoBuilder

    root = repo_root()
    cfg = load_rigs(config_path(root))
    t = SshTransport(write_ssh_config(cfg, root))
    builder = VivadoBuilder(root)
    for r in cfg.enabled():
        assert smoke_board(root, SshBoardSession(r, t), builder, tmp_path / r.name) == [], r.name
```

(`literal_value` is `xut.wrap`'s parser of a Verilog literal such as `64'haaaa...`. If the merged name differs, use the merged one.)

- [ ] **Step 2: Implement `tools/xut/hw/smoke.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The LUT6 smoke design (``xut hw smoke``): board bring-up that needs no work unit.

Four LUT6 slots (INIT all 0, all 1, alternating, one fixed pattern), each driven through
all 64 addresses with a sample after each, plus the self-test channels, in one
bitstream. The expectation is LUT6's documented function, O = INIT[{I5..I0}] (UG953,
LUT6), computed by ``Lut6Sim``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from xut.catalog.model import load_entry
from xut.hw import proto
from xut.hw.compile import compile_program
from xut.hw.hwsim import simulate
from xut.hw.steps import run_replies, session_steps
from xut.hw.image import HwProgram, width
from xut.hw.interp import run_program
from xut.hw.selftest import expected_samples, selftest_programs
from xut.hw.session import BoardSession, HwJob, SlotRun
from xut.hw.slots import SELFTEST_SLOTS, SlotBuild, dut_slot
from xut.hw.vivado import Builder
from xut.modelsrc import ModelSource
from xut.stimgen import VecBuilder
from xut.wrap import DutMap, build_map, render_wrapper, spec_from_catalog

LUT6_INITS = (0x0000000000000000, 0xFFFFFFFFFFFFFFFF, 0xAAAAAAAAAAAAAAAA, 0x9C3B61E405FD27A8)


class Lut6Sim:
    def __init__(self, init: int, m: DutMap) -> None:
        self.init, self.m = init, m

    def reset(self, t0: str) -> None:
        self._in = t0

    def drive(self, in_bits: str, clk_bits: str) -> None:
        self._in = in_bits

    def out_bits(self) -> str:
        bits = self._in[::-1]
        addr = sum(int(bits[self.m.port_bits("in", f"I{i}")[0].bit]) << i for i in range(6))
        out = ["0"] * width(self.m.nout)
        out[self.m.port_bits("out", "O")[0].bit] = str((self.init >> addr) & 1)
        return "".join(reversed(out))


@dataclass
class SmokeSlot:
    m: DutMap
    prog: HwProgram
    slot: SlotBuild
    init: int


def smoke_slots(root: Path) -> list[SmokeSlot]:
    entry = load_entry("7series", "LUT6", root)
    out = []
    for k, init in enumerate(LUT6_INITS):
        spec = spec_from_catalog(entry, f"smoke{k}", {"INIT": f"64'h{init:016x}"})
        m = build_map(spec)
        b = VecBuilder(m, seed=k)
        for a in range(64):
            b.set(**{f"I{i}": (a >> i) & 1 for i in range(6)})
            b.sample(f"a{a:02d}")
        prog = compile_program(b.build(), m)
        out.append(SmokeSlot(m, prog, dut_slot(m, render_wrapper(spec, m), prog.t0), init))
    return out


def _expected(s: SmokeSlot) -> list[str]:
    sim = Lut6Sim(s.init, s.m)
    sim.reset(s.prog.t0)
    return run_program(s.prog.words, s.prog.nin, s.prog.nclk, sim, s.prog.t0).samples


def smoke_layout(
    root: Path,
) -> tuple[tuple[SlotBuild, ...], dict[int, HwProgram], dict[int, list[str]]]:
    ss = smoke_slots(root)
    slots = (*SELFTEST_SLOTS, *(s.slot for s in ss))
    progs = selftest_programs()
    exp = {s: expected_samples(s) for s in progs}
    for k, s in enumerate(ss):
        progs[2 + k] = s.prog
        exp[2 + k] = _expected(s)
    return slots, progs, exp


def check_replies(runs: dict[int, proto.RunReply], expected: dict[int, list[str]]) -> list[str]:
    problems = []
    for slot, exp in sorted(expected.items()):
        r = runs[slot]
        if r.status != proto.STATUS_CODE["ok"]:
            problems.append(f"slot {slot}: status {proto.STATUS.get(r.status, r.status)}")
            continue
        wrong = [i for i, (g, e) in enumerate(zip(r.samples, exp, strict=False)) if g != e]
        if len(r.samples) != len(exp) or wrong:
            problems.append(
                f"slot {slot}: {len(wrong)} wrong sample(s) (first: {wrong[:3]}), "
                f"{len(r.samples)}/{len(exp)} received"
            )
    return problems


def smoke_sim(
    root: Path, sim: str, workdir: Path, model_source: ModelSource, *, work_root: Path | None = None
) -> list[str]:
    slots, progs, exp = smoke_layout(root)
    r = simulate(
        slots,
        session_steps(progs),
        sim,
        workdir,
        model_source=model_source,
        work_root=work_root or root,
    )
    return check_replies(run_replies(r.replies, progs), exp) + r.margin_violations


def smoke_board(root: Path, session: BoardSession, builder: Builder, workdir: Path) -> list[str]:
    slots, progs, exp = smoke_layout(root)
    bit = builder.ensure(slots)
    job = HwJob(
        f"smoke-{uuid.uuid4().hex[:8]}",
        bit.path,
        bit.build_id,
        tuple(SlotRun(s, p) for s, p in progs.items()),
    )
    res = session.run_job(job, workdir)
    return check_replies(res.runs, exp)
```

- [ ] **Step 3: Add `xut hw smoke`** to `tools/xut/cli.py`:

```python
@hw_grp.command("smoke")
@click.option(
    "--sim", type=click.Choice(["iverilog", "xsim"]), help="simulate instead of using boards"
)
@click.option("--rig", "rigs", multiple=True, help="only these rigs (default: every enabled rig)")
@click.option("--model-source", default="auto", show_default=True)
def hw_smoke_cmd(sim: str | None, rigs: tuple[str, ...], model_source: str) -> None:
    """The LUT6 smoke design: self-test + 4 LUT6 truth tables, on boards or in simulation."""
    import time

    from xut.hw.rigs import config_path, load_rigs, write_ssh_config
    from xut.hw.session import SshBoardSession, SshTransport
    from xut.hw.smoke import smoke_board, smoke_sim
    from xut.hw.vivado import VivadoBuilder
    from xut.modelsrc import resolve

    root = repo_root()
    stamp = time.strftime("%Y%m%dT%H%M%S")
    if sim:
        problems = smoke_sim(
            root, sim, root / "build" / "hwsmoke" / f"{sim}-{stamp}", resolve(model_source)
        )
        click.echo(f"smoke ({sim}): {'PASS' if not problems else 'FAIL'}")
        for p in problems:
            click.echo(f"  {p}")
        raise SystemExit(1 if problems else 0)
    cfg = load_rigs(config_path(root))
    t = SshTransport(write_ssh_config(cfg, root))
    builder, failed = VivadoBuilder(root), 0
    for r in [cfg.get(n) for n in rigs] if rigs else cfg.enabled():
        try:
            problems = smoke_board(
                root,
                SshBoardSession(r, t),
                builder,
                root / "build" / "hwsmoke" / f"{r.name}-{stamp}",
            )
        except Exception as e:  # reported per rig, never swallowed
            problems = [f"{type(e).__name__}: {e}"]
        failed += bool(problems)
        click.echo(f"{r.name:<14} {'PASS' if not problems else 'FAIL'}")
        for p in problems[:5]:
            click.echo(f"  {p}")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 4: Run the tests, the smoke in both simulators, lint and commit**

```bash
uv run pytest tools/tests/test_hw_smoke.py -v > .cache/pytest.log 2>&1; cat .cache/pytest.log
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsmoke-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run xut hw smoke --sim iverilog > .cache/hwsmoke-iverilog.log 2>&1; echo "exit=$?"; cat .cache/hwsmoke-iverilog.log
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsmoke-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run xut hw smoke --sim xsim > .cache/hwsmoke-xsim.log 2>&1; echo "exit=$?"; cat .cache/hwsmoke-xsim.log
uv run ruff format tools > .cache/ruff.log 2>&1; uv run ruff check tools >> .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools/xut/hw/smoke.py tools/xut/cli.py tools/tests/test_hw_smoke.py
git commit -m "hw: LUT6 smoke design and xut hw smoke (board bring-up, also in simulation)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: `exit=0` and `smoke (iverilog): PASS`, `smoke (xsim): PASS`. Each simulation takes about 1–3 minutes (report every 60 s).

Also build the smoke bitstream now, so bring-up (Task 12) does not wait on Vivado. `xut hw smoke` builds it on first use; the pytest-level build proves it closes timing:

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsmokebuild-$(date +%s) -p MemoryMax=8G -p MemorySwapMax=0 -- \
  uv run python -c "from xut.hw.smoke import smoke_layout; from xut.hw.vivado import VivadoBuilder; from xut.paths import repo_root; r=repo_root(); b=VivadoBuilder(r).ensure(smoke_layout(r)[0]); print(b.build_id, b.path, b.manifest['wns_ns'], b.manifest['whs_ns'])" > .cache/hwsmoke-build.log 2>&1; cat .cache/hwsmoke-build.log
```

- [ ] **Step 5: Whole-branch verification, log, push and PR C**

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-pytest-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run pytest -n 4 --dist loadfile > .cache/pytest-all.log 2>&1; tail -n 8 .cache/pytest-all.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
uv run xut doctor > .cache/doctor.log 2>&1; cat .cache/doctor.log
```

- **Expected:** the full suite passes, with `vivado` and `container` tests included (they need Vivado and the image, both on this host). The `hw` tests skip with "no board access". Lint is clean.
- `xut doctor` shows `hw-rigs` ok and, until #124 is done, a failing `hw:<rig>` per rig, with the ssh error as the detail. Record that output in the log: it is the honest state of board access.

Write `log/<ts>-infra-hw-runner-runner.md` (what changed, the test results, the doctor output, the smoke build's ID and timing, next steps: Task 12 once #124 grants access). Commit it (`git add log/<ts>-infra-hw-runner-runner.md && git commit -m "infra: log the hw runner session" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`), push and open PR C with `--base infra/hw-vivado`. The body covers Tasks 8–11 and Review Focus items 1, 4 and 5, and ends with the Claude Code line.

---

## Pilot: `flops` (and `luts`) on silicon

### Task 12: The flops pilot on a real board — run, cross-check, record (branch `unit/7series/flops`)

**Files:**
- Modify (only if the evidence requires it): `tests/7series/register/_shared/flops/flop_tests.py` and the regenerated `tests/7series/register/FD*/test.yaml`/`README.md`, `findings/FD*-*.md`, the flops golden models (a model bug found against UG953, with a test)
- Modify: `status/7series/FD{R,S,C,P}E.yaml` (via `xut status record` only)
- Create: `log/<ts>-unit-7series-flops-hw-pilot.md`

**How GSR/INIT tests are declared** (spec §7.2: until the GSR-immune harness exists, they are `hw: unsupported`):

- A test whose purpose is a GSR pulse (for example `L1.gsr_init`, `L1.sv_gsr_midsim`) declares `hw: "unsupported"` with `unsupported_reasons.hw: "GSR pulses need the GSR-immune harness state of spec §7.2"`. The flops unit already does this in `flop_tests.py`, and every later unit copies the pattern. The hw runner then writes a `skip` with that reason.
- A test declared `hw: "yes"` whose *individual* configuration pulses GSR, drives x/z, or is otherwise not renderable is not hidden: `plan_case` records that configuration as a `skip` with the validator's reason, and the result's reason lists it (`N config(s) skipped: ...`).
- The power-on INIT value itself **is** tested on hardware. The configuration start-up applies INIT, and every slot runs from power-on (the `t0` design). Only *re-applying* INIT through a GSR pulse needs §7.2.
- `IS_D_INVERTED=1` stays excluded on `hw` through `config_exclusions` (UG953 p376: only legal on I/O registers; the fabric harness uses SLICE flops).

- [ ] **Step 0: The gate.** All of these must hold before any other step. Otherwise stop, write the log entry saying which gate failed, commit and push it, and report "blocked" to the orchestrator.
  - PRs A, B and C are merged into `main`.
  - Board access exists (fpgas-online/fpgas.online-infra#124 is done): `uv run xut doctor > .cache/doctor.log 2>&1; cat .cache/doctor.log` shows `hw` among the available runners.
  - The fpgas.online sessions (ten64.welland.mithis.com, desktop.buddy.mithis.com) have confirmed that the Welland Artys are free for this run, and that the lock name in `hw/rigs.yaml` (`/run/lock/fpga.lock`) is the one they use. If their name differs, do not start: the rigs file must change first, on an infra branch.
  - PR E (step 2's flops unit) is merged, and the orchestrator has deleted the old remote `unit/7series/flops` branch (`gh pr view <E> --json state,headRefName`; `git ls-remote origin unit/7series/flops` prints nothing).

- [ ] **Step 1: A fresh unit worktree**

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git fetch origin && git worktree add ../xilinx-unittests-worktrees/unit-7series-flops -b unit/7series/flops origin/main
cd ../xilinx-unittests-worktrees/unit-7series-flops
mkdir -p .cache/hw && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
git config core.hooksPath tools/hooks
```

If a worktree that ran Task 7 or Task 11 still exists (`../infra-hw-vivado`, `../infra-hw-runner`), copy its bitstream cache first: `cp -a ../infra-hw-runner/.cache/hw/bit .cache/hw/`. This is only an optimisation. Entries are keyed by their full inputs, so a stale one is never used; it is simply not hit. (If `../xilinx-unittests-worktrees/unit-7series-flops` still exists from step 2, the orchestrator removes it first with `git worktree remove`, after confirming it holds no unpushed work.)

- [ ] **Step 2: Bring-up — rigs**

```bash
uv run xut hw rigs > .cache/hw-rigs.log 2>&1; echo "exit=$?"; cat .cache/hw-rigs.log
```

- **Expected:** `exit=0`; `ok` for pi-sw2-p9, p10 and p15, with each one's `openFPGALoader` version; p12 `disabled: UART output is garbled ...`.
- If an address or account differs from `hw/rigs.yaml`, do **not** edit it here: it is an infra path. Copy it to `.cache/hw/rigs.local.yaml`, correct the copy, `export XUT_HW_CONFIG=$PWD/.cache/hw/rigs.local.yaml` for this session, and record a TODO in the log entry for an infra PR that fixes `hw/rigs.yaml`.
- Record each rig's USB serial and openFPGALoader version in the log.
- Check whether the rigs' openFPGALoader can read the Xilinx DNA without programming: `ssh -F .cache/hw/ssh_config xut-rig-pi-sw2-p9 'openFPGALoader --help' > .cache/ofl-help.log 2>&1`, then look for a DNA option in the log file. Record the answer (Decision 6); if it can, file the infra follow-up there.

- [ ] **Step 3: Bring-up — self-test and the LUT6 smoke on every rig**

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsmoke-$(date +%s) -p MemoryMax=8G -p MemorySwapMax=0 -- \
  uv run xut hw smoke > .cache/hw-smoke.log 2>&1; echo "exit=$?"; cat .cache/hw-smoke.log
```

- **Estimate:** one build (a cache hit if Task 11's build was copied), then about 30 s per rig. Under 10 minutes: report every 60 s.
- **Expected:** `exit=0` and `PASS` for every enabled rig. This is the first silicon evidence that the harness, the protocol, SRAM programming and the rig lock all work.
- On a `FAIL`:
  - A self-test failure on one rig only: that rig is suspect. Report it to the fpgas.online sessions, disable it in the local rigs copy, and log it.
  - A failure on every rig: this is an infra bug (harness, constraints or protocol). Stop, and report it to the orchestrator for an infra fix branch. Never continue past a failing self-test.

- [ ] **Step 4: The simulation baseline in this worktree** (crosscheck and status need every runner's results at one tree hash):

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-run-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:flops' --jobs 16 > .cache/run-flops-rtl.log 2>&1; echo "exit=$?"
```

- **Estimate:** as in step 2's Task 27, about 5–8 minutes, so report every 60 s from the `progress:` lines.
- **Expected:** `exit=0`, with the same matrix as the merged step-2 status.

- [ ] **Step 5: The bitstreams**

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwbuild-$(date +%s) -p MemoryMax=8G -p MemorySwapMax=0 -- \
  uv run xut hw build 'unit:flops' --jobs 4 > .cache/hwbuild-flops.log 2>&1; echo "exit=$?"
```

- **Estimate:** seconds if the copied cache hits; otherwise use the Task 7 measurement (about 20–40 minutes, report every 5 minutes).
- **Expected:** `exit=0`.

- [ ] **Step 6: The hardware run**

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-run-hw-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:flops' --flow vivado --runner hw --jobs 3 > .cache/run-flops-hw.log 2>&1; echo "exit=$?"
```

- **Estimate:** about 32 hardware-declared flops tests. Each needs 1–2 bitstreams × 3 repeats × about 20–40 s per job (scp of about 2 MB through the jump host, SRAM programming, the UART session). With 3 rigs in parallel that is about 15–40 minutes, so report every 5 minutes from the `progress:` lines. If the first ETA exceeds 4 hours, switch to a 15-minute cadence.
- This command also re-runs the golden model at flow `rtl` (python always runs first for vector tests), replacing Step 4's python results with identical ones at the same tree hash. That is expected, not a problem.
- **Expected:** every `hw` cell is `pass`, or `skip` with a reason (declared unsupported, or the `IS_D_INVERTED` exclusion). `build/vivado/hw/unisim-2025.2/7series.FD*/result.json` exist, each with `hw.selftest = "pass"`, `hw.repeats = 3` and the rig, site and serial.

- [ ] **Step 7: Cross-check and classify**

```bash
uv run xut crosscheck 'unit:flops' --write-findings > .cache/xc-flops.log 2>&1; echo "exit=$?"; cat .cache/xc-flops.log
```

Expected in the best case: `exit=0`, with every test's matrix showing `hw` agreeing with the golden model. For each finding (never weaken a test; AGENTS.md §9):

- **`silicon-mismatch`** (hardware ≠ the golden trace):
  1. Re-run just that test on another rig: `--hw-rig <other>` with `--hw-repeats 5`. If the other rig agrees with the golden model, the first board is suspect: report it and keep the finding open with both results.
  2. Read the evidence against UG953 (pages 374–376 and the FD\*E pages), clean-room: never open UNISIM for the model.
  3. If the golden model contradicts UG953, it is a model bug. Fix it in the unit's model with a test, re-run, and do not file a finding.
  4. Otherwise, complete the finding's **Analysis** section and keep it open. Add `{finding: findings/<id>.md, cls: silicon-mismatch, runners: [hw], flows: [vivado]}` to the test's `expected_divergence` in `flop_tests.py`, regenerate, and re-run crosscheck: it now reports `known-divergence`.
  5. Tell the orchestrator: a silicon mismatch that survives two boards is a headline result of step 3.
- **`nondeterminism`** (repeats disagree): re-run the test with `--hw-repeats 10` and record how often each value occurs. A harness margin problem is the first suspect. Report it to the orchestrator as a possible infra bug before filing it against the primitive.
- **`harness-error`** (a self-test failed): an infra bug. Stop, and do not record status. Report it for an infra fix branch.

- [ ] **Step 8: Commit, then record status**

```bash
git add tests/7series/register findings models catalog/7series/FD*.overrides.yaml && git commit -m "flops: hardware pilot findings and expected divergences" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(Skip this commit if Step 7 changed nothing. If it changed any tree-hashed input, go back to Step 4 so every result carries the new tree hash.)

```bash
uv run xut status record --unit flops > .cache/status-flops.log 2>&1; cat .cache/status-flops.log
git diff --stat status/7series > .cache/status-diff.log 2>&1; cat .cache/status-diff.log
git add status/7series && git commit -m "flops: record the hardware results (flow vivado)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected in each `status/7series/FD*.yaml`:
- `results` gains `L0/hw/vivado`, `L1/hw/vivado` and `L2/hw/vivado` (`pass` where the tests passed on silicon);
- `L*/hw/yosys`, `L*/hw/openxc7` and `L*/hw/vpr` stay `not-run` (step 4);
- the GSR tests' `hw` cells are `unsupported`;
- `measured.tree_hash` is unchanged from the step-2 recording unless Step 7 changed an input.

- [ ] **Step 9: Verify, log and open PR D**

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-pytest-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run pytest -n 4 --dist loadfile -m "not slow" > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
git status --porcelain > .cache/git-status.log 2>&1; cat .cache/git-status.log
```

Expected: tests pass, lint is clean, and only committed changes remain; `status/PROGRESS.md` is **not** modified.

Write `log/<ts>-unit-7series-flops-hw-pilot.md`:
- the rigs used, with serials and openFPGALoader versions;
- the smoke results;
- the build IDs with WNS/WHS;
- the crosscheck matrix (pasted from the log);
- the findings;
- the durations: builds, per job, whole run;
- any rigs-file TODO for infra;
- the luts decision (Task 13 or its TODO).

Commit it, push, and open PR D:

```bash
git add log/<ts>-unit-7series-flops-hw-pilot.md
git commit -m "flops: log the hardware pilot" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/mithro/xilinx-unittests.git unit/7series/flops
gh pr create --base main --title "flops: hardware pilot" --body-file .cache/pr-d.md
```

The body summarises the silicon results and findings, and ends with the Claude Code line. Run the review gate. After the merge, the orchestrator regenerates status on `main` (`status: regenerate`).

---

### Task 13 (conditional): The luts pilot on hardware (branch `unit/7series/luts`)

**Condition.** Run this task only if the `luts` work unit has merged into `main`: `tests/7series/clb/LUT6/test.yaml` exists on `origin/main`, and the unit's PR is merged. Otherwise:
- skip this task;
- Task 11's LUT6 smoke design (run on every rig in Task 12, Step 3) is step 3's LUT evidence;
- Task 12's log entry records the TODO: "luts: declare `hw: \"yes\"` with flow `vivado` for the renderable vector tests, and run Task 13 of the step-3 plan once the unit merges".

**Files:** the luts unit's paths only: `tests/7series/clb/_shared/luts/**`, `tests/7series/clb/LUT*/`, `tests/7series/clb/CFGLUT5/`, `findings/LUT*-*.md`, `findings/CFGLUT5-*.md`, `status/7series/{LUT1..LUT6,LUT6_2,CFGLUT5}.yaml`, and its log entry.

- [ ] **Step 1: A fresh worktree, then check the declarations.** Create `unit/7series/luts` from `origin/main`, as in Task 12, Step 1. Then, in the unit's test metadata generator (not in the generated `test.yaml`):
  - every vector test declares `hw: "yes"` and lists `vivado` in `flows`;
  - any test built on a GSR pulse declares `hw: "unsupported"` with the §7.2 reason;
  - `CFGLUT5`'s `CLK` is a stepped clock like a flop's, so its shift tests are renderable.

  Commit any change: `git add tests/7series/clb && git commit -m "luts: declare the hw runner for the vector tests" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`.
- [ ] **Step 2: Prove it in simulation first**

```bash
systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsim-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run xut hw sim 'unit:luts' --sim iverilog --jobs 8 > .cache/hwsim-luts.log 2>&1; echo "exit=$?"
```

Expected: `exit=0`. A failure here is an infra bug: report it and stop.

- [ ] **Step 3: Baseline, build, run, cross-check and record** — exactly Task 12, Steps 4–9, with `unit:luts`, `luts:` commit prefixes and PR E ("luts: hardware pilot"). The gate of Task 12, Step 0 applies unchanged.

---

## Self-review against the spec (performed while writing this plan)

- **§7.1 stepped fabric harness.**
  - *Stimulus compiled into a BRAM image of harness operations:* Task 2 (`compile_program`: SET/COMMIT/EDGE/SAMPLE/END), loaded into the harness's BRAM (Task 4 `mem`), with a reference interpreter (Task 3) that makes it testable without hardware.
  - *Sequencer on a conservative system clock:* Task 4, 100 MHz with shallow logic; timing must close (Task 6).
  - *DUT clock = a harness flip-flop through a BUFG:* `dclk_s<k>_<i>` → `BUFG` per DUT clock (Task 4).
  - *At least N system cycles between an in_vec change, the next DUT edge and the next capture:* enforced in RTL (`S_WAITM`, `MARGIN = 16`), checked by the RTL testbench monitor and by `margin_violations` (Tasks 3–5).
  - *Generated-clock and max-delay constraints for Vivado:* `timing_tcl` (Task 4), applied after synthesis, guarded by `xut_must` (Task 6).
  - *Async events separated from edges:* they are separate COMMITs by construction (the validator makes async changes lonely), and each is followed by the margin.
  - *Multi-DUT packing, selected by a harness register:* `sel`, slots, `pack` with the BUFG budget (Task 4).
  - *Self-test passthrough and counter channel, run first:* slots 0 and 1, run first in every job; a failure is `harness-error` (Tasks 3, 9, 10).
  - *UART dumper with build ID, configuration and CRC:* the `run`/`end` lines carry `build`, `slot` and `crc` (Task 1), and the host maps slot → configuration through the build manifest. See ambiguity 2 for why the harness streams raw samples.
- **§7.2 GSR-immune harness:** deliberately not built. GSR tests stay `hw: unsupported` with the §7.2 reason, and GSR-pulsing configurations of hw-declared tests are visible skips (Task 12).
- **§7.3 pad harness, §7.4 configuration primitives:** out of step 3 (spec §16: step 5, io and configuration groups). The harness uses no pad-class DUT, and `validate` makes any pad or inout wrapper `hw_renderable: no`.
- **§7.5 board access.**
  - *SSH to the Pi, scp, `openFPGALoader -b arty`, UART `/dev/ttyUSB1` at 115200:* Tasks 8–9. The UART device is set per rig, with that default.
  - *Lock file with owner, time and TTL:* `xut_lock.sh` (Task 8), taken around programming and any reboot. Per ruling S49 (spec rev 3.6) the lock file is never deleted and a lock never broken: a held lock is waited for, then the rig is `busy` and the job moves on (`BoardBusy`, Task 9a); only a verified own holder may be killed.
  - *Transport errors retried once; a self-test failure marks the board bad:* `run_job` (Task 9b).
  - *`BoardSession` adapter:* Task 9a (Protocol + SSH implementation + fake).
  - *Preflight:* `xut doctor` hw checks and `xut hw rigs` (Task 9b).
- **§5.6 hw runner capabilities:** `x_observable = False` (2-state; x/z expectations are skipped in the comparison). The run repeats N = 3 times; any difference is `nondeterminism` (Task 10).
- **§6 flows and runners:** the post-flow DUT check (cell type and attributes after implementation) is Task 6's `check_dut_cells`, reported as `flow-mismatch` (Task 10). `hw` runs flow `vivado` ("bitstream on hw"). `runner_flows` already maps `hw` to non-`rtl` flows. `result.json` records the bitstream hashes, build IDs, serial, site and rig (DNA: ambiguity 6).
- **§8 crosscheck:** `silicon-mismatch`, `nondeterminism` and `harness-error` come from the existing classifier, fed by the `hw` object. Task 10's tests pin all three with the fake board. `expected_divergence` never masks (Task 12).
- **§11 status:** `xut status record` records `L*/hw/vivado` from `build/vivado/hw/unisim-2025.2/`, with the tree hash from `xut run` (Task 12).
- **§13 process:** three stacked infra PRs, then unit PRs; owned paths only; small commits; the review gate; the two-agent limit; orchestrator-only rebases.
- **§14 no silent skips; errors distinct from failures:** every configuration ends `pass`/`fail`/`error`/`skip`, with a reason for every non-pass (Tasks 5, 10).
- **§15 preflight:** `xut doctor` gains the rigs, key and per-rig SSH/tool/UART checks (Task 9b).
- **§16 step 3:** the stepped harness on the Arty A7-35T, the Vivado flow and the `hw` runner, piloted on flops, with luts conditional (Task 13) or the LUT6 smoke design (Task 11).
- **Placeholder scan.** No step says "TBD" or "similar to". Every code block is complete for its module. `<ts>` in log file names is the AGENTS.md pattern. The rigs' `user` is intentionally absent (it comes from #124), and the plan says how and where it is added. The p10/p12/p15 addresses are marked as inferred and are confirmed in Task 12, Step 2.
- **Type consistency.** These names are used identically across tasks: `HwProgram(nin, nclk, noutw, t0, words, labels)`, `SlotBuild`, `TestPlan.members/slots/programs`, `session_steps`/`run_replies`, `HwJob(job_id, bitstream, build_id, runs)`, `SlotRun(slot, program)`, `JobResult.runs: dict[int, RunReply]`, `JobOutcome(result, selftest, selftest_detail, attempts)`, `Bitstream(path, key, build_id, sha256, manifest)`, `Builder.ensure/version`, `RunContext.hw_repeats/hw_rigs`, `proto.STATUS_CODE`.

**Spec ambiguities resolved in this plan** (recorded in spec rev 3.6, below):

1. **Stimulus over the UART, not in the bitstream.** Spec §7.1 says timed events are compiled into "a BRAM image". They still are, but the image is loaded into the harness's BRAM over the UART at run time (`L`), not baked into the bitstream's BRAM INIT. A bitstream then depends only on its DUT slots, so tests with the same slot set share one cached bitstream, and changing a stimulus never costs a Vivado run.
2. **The harness streams raw samples; the host writes the `.xtr`.** Spec §7.1: "streams `.xtr` with a header carrying the build ID, the configuration and a CRC". The fabric has no port names (they live in the wrapper's map), so the harness streams `S <n> <out_vec bits>` lines framed by a `run` line (build ID, slot) and an `end` line (sample count, status, CRC-32). The host checks the CRC and renders the `.xtr` with the map (`samples_to_trace`). The slot is the configuration, via the build manifest.
3. **Power-on state.** The spec does not say how a stepped harness reproduces simulation's time-0 state. Here, each slot's input register powers up as the stimulus's `t=0` vector (flip-flop INIT in the bitstream), so the DUT sees those values through the configuration's GSR, as in simulation. A slot runs once per programming (the harness refuses a second run, status `used`), and every repeat reprograms. A different `t0` is a different slot, and part of the bitstream key.
4. **Host-driven protocol.** The harness waits for commands (`I`, `L`, `R`) instead of dumping once after configuration, so the host can never miss the start of a dump, and one programming can run many slots in turn. A lost host byte leaves the loader waiting for data that never comes; the session times out, and the retry reprograms the FPGA (there is deliberately no inter-byte timeout in the RTL, which the emulator would have to mirror).
5. **The hw runner's flow and model source.** `hw` runs flow `vivado` (spec §6 lists "bitstream on hw" under the Vivado flow). Its results are recorded only against the reference model source `unisim-2025.2`, so crosscheck groups them with the golden model's; any other source is a skip with the reason.
6. **Board DNA.** Spec rev 3.4 §6 wanted "board DNA, serial number and site" in `result.json`. Two separate facts: the *harness* must not use the device's single DNA_PORT site, which is a primitive under test (§7.4); and reading the DNA over *JTAG* needs no DNA_PORT at all, only a JTAG tool that can do it without programming. Whether the rigs' `openFPGALoader` can (for example a `--read-dna` option) is unverified, because no board is reachable yet. Task 12, Step 2 checks `openFPGALoader --help` on a rig: if it offers a DNA read, a follow-up infra change adds it to `xut_work.sh` as a separate, non-programming invocation under the lock, extends the SRAM test's allow-list for exactly that line, and records `hw.dna`. Until then step 3 records the Arty's USB serial (FT2232), the rig and the site; `hw.dna` stays optional (spec rev 3.6 §6, §7.5).
7. **The lock's mechanics** (ruling S49; spec rev 3.6 §7.5). `flock` on the rig's `lock` path under `/run/lock`, an owner record beside it (label, owner, host, boot id, pid, process groups, since, TTL), and our holder run under `timeout -k 10 <ttl>`, so it cannot outlive its TTL. flock is released by the kernel when its holder dies, so a lock that cannot be taken has a *live* holder: deleting or re-creating the file would put two holders on one board. So the lock file is never touched. A held lock is waited for up to `lock_wait_s`; then the rig is `busy` (a retryable `error`, not a result and not a `harness-error`) and the job moves to the next rig. The only recovery is killing a holder verified as our own: the same client (`user@host`; the pid differs) and label, the same host and boot id, past its TTL, and a live recorded pid that is in the recorded process group, runs `xut_lock.sh` for this lock, and started no later than the record's `since` (so a reused pid is never killed). That path is a last resort and nearly unreachable (`timeout -k 10` kills our holder by TTL + 10 s). Exit 75 means busy and nothing else; a lock file that cannot be created or opened exits 93, a rig fault (`BoardError`). The same wrapper guards any reboot. xut reboots a rig only through a configured `reboot_command`, and never by default. The lock path must match whatever the other fpgas.online users take; Task 12 checks this before any programming.
8. **N and the system clock.** `MARGIN = 16` cycles at 100 MHz (160 ns, far above BUFG insertion and SLICE clock-to-out skews), with `set_max_delay -datapath_only` of (MARGIN − 2) periods. The system clock is the board oscillator through one BUFG, with no MMCM: the harness should not depend on a clock-management primitive, since those are primitives under test themselves.
9. **What "run N times" means.** N = 3 programmings per bitstream (`--hw-repeats`). Any difference is `nondeterminism`, and the configuration fails.
10. **Packing scope.** Configurations are packed per test, in content order, into bitstreams of at most 28 DUT clocks (32 BUFGCTRL, minus the harness's 2, minus 2 spare) and 64 slots. The content-addressed cache shares identical sets across tests. Packing across tests is left for later, if build time demands it.
11. **The harness relies on BUFG and block RAM.** Both are primitives. A toolchain that breaks them fails the self-test (passthrough through the BRAM-held program, counter through a BUFG) before any DUT result, which spec §7.1's self-test rule turns into `harness-error`.
12. **`xut hw sim` is not a runner.** Simulating the harness is evidence about the harness, not about the primitive, so it writes no `result.json` or status. It gates every hardware run, in Tasks 5, 11 and 13.
13. **The rigs file.** p9's address comes from the task brief. The p10, p12 and p15 addresses are inferred from its pattern, and the account from fpgas-online/fpgas.online-infra#124 (pending). Both are confirmed at bring-up (Task 12, Step 2), and corrected through an infra PR.

**Spec rev 3.6** (committed in this plan's docs PR, before the plan; it follows PR C's rev 3.5, which amends only §6.2, so the orchestrator merges the two status lines when rebasing):
- §7.1: ambiguities 1–4, 8, 10 and 11 as rules, including the checked clock-latency budget;
- §7.5: ambiguity 7 as ruling S49 (the lock is never deleted or broken; busy rigs move the job; only a verified own holder may be killed), "SRAM only", and ambiguity 6;
- §6: the post-flow DUT check for the `vivado` flow, and the `hw` fields of `result.json`;
- §8: a failed post-flow DUT check is a `flow-mismatch`;
- §5.6: N = 3 by default.
