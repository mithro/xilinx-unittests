# Unit Fan-out Playbook (luts first) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One reusable procedure that takes any remaining work unit of `docs/work-units.yaml` from nothing to a merged unit PR, at the standard the `flops` pilot set in step 2, so that the fan-out of spec §16 step 5 does not need a new plan per unit. The plan has three parts:

- **Part 0** — the infra prerequisites every later unit needs (Task P1, one infra PR): the coverage-bin fix, `xut.unitkit` (the shared metadata helpers and guard set, ruling S53), the ANN exemption, and the AGENTS.md §7 (own-stub refresh) and §10.1 (heavy-command lock) rules.
- **Part A** — the generic unit procedure, Tasks A1–A8, parameterised by `<unit>`, `<group>` and `<PRIMS>`: overrides and claims, clean-room golden models, vector recipes and the metadata generator with its reach guard, sv tests, a cocotb session, the full run with crosscheck, findings and status, the unit PR, and the hardware follow-up once the step-3 `hw` runner exists.
- **Part B** — the `luts` unit (LUT1–LUT6, LUT6_2, CFGLUT5) as the first concrete instance, Tasks B1–B8, with complete code for everything load-bearing: the golden models, the recipes (exhaustive truth tables, spec §4.2 INIT sampling, CFGLUT5 reconfiguration sequences), the test.yaml/README generator and its guards, the sv testbenches and the cocotb session.

Appendix W is the fan-out worksheet: the order of the remaining 26 units after luts and, per unit, what its intake already knows (portability rows, hardware class, infra blockers).

**How to use it.**

- For **luts**, run Part 0 (if P1 is not merged yet), then Part B. Every Part B task names the Part A task whose rules it follows; read that task first.
- For **any later unit**, the orchestrator gives the implementer a brief naming `<unit>` and pointing at its Appendix W row; the implementer follows Part A, using Part B as the worked example and `xut.unitkit` for everything generic. A unit never copies the flops unit's code (ruling S53): flops predates the kit and migrates to it in its own later PR.
- Placeholders: `<unit>` is the work-unit name (`luts`), `<group>` its lower-case PRIMITIVE_GROUP directory (`clb`), `<PRIMS>` its primitives (`LUT1 ... CFGLUT5`), `<PRIM>` one of them and `<prim>` its lower-case form. `<U>` is the worktree `../xilinx-unittests-worktrees/unit-7series-<unit>`. `<ts>` in a log file name is the AGENTS.md `YYYY-MM-DDTHHMM` pattern.

**Architecture** (step 2's, plus `xut.unitkit`):

- A unit owns `catalog/7series/<PRIM>.overrides.yaml`, `models/xut_models/7series/_common/<unit>.py` and `<prim>.py`, `tests/7series/<group>/<PRIM>/**`, `tests/7series/<group>/_shared/<unit>/**`, `status/7series/<PRIM>.yaml`, `findings/<PRIM>-*.md` and its own log entries (`xut.workunits.owned_paths`).
- The shared directory holds the unit's single sources, every file named with the stem `<unit>` (unique across units: pytest's flat namespace): `<unit>_recipes.py` (stimulus), `<unit>_tests.py` (renders every generated file of every primitive: `test.yaml`, `README.md`, `vectors/gen.py`, the cocotb module and the sv wrappers), `<unit>_cocotb.py` (the cocotb session), the sv bodies (`<unit>_*_tb.svh`) and the unit's pytest files.
- `xut.unitkit` (Task P1) supplies what is not unit-specific: the standard reasons, test entries, bin names, the YAML dumper, the README skeleton, the reach replay and the guard set `UnitGuards`. A unit imports it and never copies it.
- Expected values come only from the clean-room golden model (python runner). Recipes never compute them. sv tests check only documented behaviour and record the rest as checkpoints; cocotb compares against the same model step by step.

**Tech stack:** as step 2: Python ≥ 3.12, uv, pytest, ruff, the `xut-sim:1` container (Icarus 12, Verilator 5.048, cocotb 2.0.1), Vivado 2025.2 xsim; for Task A8 the step-3 `hw` runner.

**Spec:** `docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md`, the revision on `main` (3.4 when this plan was written; 3.5 arrives with PR #10 and 3.6 with PR #11). Read §§3, 4, 5.1, 5.3, 6.2, 7, 8, 9, 11, 12, 13 and 16 step 5. AGENTS.md §1: where this plan and the spec on `main` disagree, the spec wins; say so in the log entry.

**Prerequisites and Step 0.** Before any unit starts:

- PR #10 (`infra/verilatorize`, step-2 PR C) is merged, and the orchestrator has regenerated `status/PORTABILITY.md` on `main` (it carries ruling S51's `config` category and the memory-capped smoke run).
- The flops unit (step-2 PR E) is merged: it is the worked example, and it carries the rulings the fan-out inherits (S30, S32, S33, S36, S37, S44). Nothing in a later unit imports flops code, so if the orchestrator starts a unit first, the implementer reads the worked example on the `unit/7series/flops` branch instead and drops the flops path from Step 0's `ls`.
- Task P1 is merged, or the unit branch is stacked on `infra/unit-prereqs` (AGENTS.md §13).

- [ ] **Step 0: verify the prerequisites on `main`**

```bash
cd /home/tim/github/f4pga/xilinx-unittests && git fetch origin && git checkout main && git pull --ff-only
mkdir -p .cache
uv run python -c "from xut.runners.verilator import VerilatorRunner; from xut.golden import coverage_reach, attr_bins; from xut_models.registry import get; print('prereqs OK', get('7series', 'FDRE').PRIM)" > .cache/playbook-step0.log 2>&1
ls status/PORTABILITY.md tests/7series/register/_shared/flops/flop_tests.py >> .cache/playbook-step0.log 2>&1
cat .cache/playbook-step0.log
```

Expected: `prereqs OK FDRE` and both paths listed. `ImportError: cannot import name 'coverage_reach'` means P1 has not merged: stack the unit on `infra/unit-prereqs` (Task A1, Step 1 shows how). A missing `status/PORTABILITY.md` or `VerilatorRunner` means PR #10 has not merged: stop and report to the orchestrator.

## Global Constraints

- **SPDX.** Every source file (`.py .v .sv .svh .vh .yaml .sh .tcl .toml`) starts with an `SPDX-License-Identifier: Apache-2.0` comment line. Generated `test.yaml` files carry it too (the generators write it). Markdown is exempt.
- **Nothing AMD is committed.** No UG953 PDF or text, no AMD prose (claims are paraphrases of at most 200 characters with a page number), no UNISIM source.
- **Generated status files** `status/PROGRESS.md`, `TODO.md`, `LOG.md` and `PORTABILITY.md` are never committed on a unit branch. Only the orchestrator regenerates them on `main` (`status: regenerate`).
- **Commits** are small, one meaningful change each, subject prefixed `<unit>: ` (the commit-msg hook enforces it), each ending with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`, passed as a second `-m` as every commit command below does.
- **Shell.** Never redirect to `/dev/null` in any form. Never pipe a command into `grep`, `tail` or `head`: write the whole output to a log file under `.cache/` (`cmd > .cache/x.log 2>&1`) and then read or search the log file. Vivado is only ever sourced in a subshell: `bash -c 'source /opt/xilinx/Vivado/2025.2/settings64.sh && ...'` (the xsim runner does this itself).
- **MEMORY SAFETY (AGENTS.md §10.1, mandatory).** Every heavy command (`xut run`, `xut portability`, `xut verilatorize --check`, `xut hw sim`, `xut hw build`, and `pytest` with `-n` above 1) takes the **one host-wide lock** and then runs in its own capped scope, never in the agent's own cgroup (ruling S53):

  ```bash
  flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice \
    --unit=xut-<what>-$(date +%s) -p MemoryMax=<cap> -p MemorySwapMax=0 -- <command> > .cache/<log> 2>&1
  ```

  The lock has one holder at a time, host-wide, so two agents (two units in parallel, say) never run heavy jobs at once, and each command's own budget below (at most 96G) is the whole project's use. `flock` waits for a holder; nothing ever deletes the lock file. Task P1 writes the rule into AGENTS.md §10.1. The caps keep each command inside the project's 100G share of `vivado.slice`. Containers run outside the scope, capped at 4G each by xut (PR #10), and Vivado/xsim runs take one of the 4 host-wide slots (`XUT_VIVADO_SLOTS`), so both count:

  | Command | Scope cap | Parallelism | Worst case |
  |---|---|---|---|
  | `xut run` (python, xsim, iverilog, verilator) | 32G | `--jobs 16` (AGENTS.md allows ≤ 24; 16 keeps 32G + 16 × 4G = 96G) | 96G |
  | `pytest` over the unit's own tests, one process | unscoped: light (as `ruff`) | none | about 1G |
  | `pytest` over the whole repository (container tests included) | 32G | `-n 4 --dist loadfile` (never `-n auto`) | 32G + 4 × 4G; after step 3, 32G + 4 × 16G (a worker may start a Vivado child) = 96G |
  | `xut hw sim` (Task A8) | 16G | `--jobs 8` (Icarus) | 48G |
  | `xut hw build` / `xut run --flow vivado --runner hw` (Task A8) | 8G / 32G | Vivado 4 × 16G | 72G / 96G |

  An OOM kill (`oom-kill` in the scope result, or docker `OOMKilled=true`) is a retryable failure: lower the parallelism and re-run; never raise a cap. A model OOM-killed on its own is a portability result to report, not a reason to raise the cap. `ruff`, `xut lint`, `xut crosscheck`, `xut status record`, `git`, the metadata generators and single-process `pytest` over the unit's own tests are light and run unscoped, without the lock.
- **Clean room (AGENTS.md §8).** Golden models are written from UG953 alone: `uv run xut fetch-docs`, then read `.cache/docs/ug953-2026.1.txt`. Nobody working on `models/xut_models/7series/**` opens a UNISIM `.v` file of either model source, for writing a model or for analysing a finding. A model is committed before any simulator runs its tests, and it is never changed to follow a simulator: only a contradiction with UG953 (a model bug, fixed with a test) changes it.
- **What runs in the container.** `models/xut_models/**`, `<unit>_recipes.py` and `<unit>_cocotb.py` are imported by cocotb inside the simulator container, where only the standard library, `xut_models`, `xut.formats` and `xut.cocotb_dut` exist. So: models import only the standard library and `xut_models`; the recipes import `xut` only for type checking; the session imports `xut.cocotb_dut` (it must, to drive the DUT) and nothing else from `xut`. `<unit>_tests.py` and the guards run on the host and use `xut.unitkit` freely.
- **Never weaken a test to hide a divergence** (AGENTS.md §9, spec §8). A disagreement is classified and recorded as a finding; an `expected_divergence` never masks it (it is reported as `known-divergence`); an expected bit is never turned into `-`; a check is never deleted.
- **Long runs** follow the global progress rule: run in the background with the log in `.cache/`, watch it with a Monitor that reads the latest `progress: done=N total=M elapsed_s=E` line, compute the rate as N ÷ E and the remaining time as (M − N) ÷ rate, and report the remaining time and the finish clock-time at the cadence the estimate gives (under 10 minutes: every 60 s; under 4 hours: every 5 minutes; longer: every 15 minutes). Tighten the cadence if a later estimate drops below a threshold.
- **Code in this plan is `ruff format`-clean at line length 100** and passes `ruff check` with the repository's rules once Task P1's `tests/**/test_*.py` ANN exemption is in. Every Part B module was extracted and run while the plan was written: the models, the recipes and the metadata generator against the step-2 infra (plus P1), the unit's pytest files (167 tests passing, through `xut.unitkit`'s guards, the failing-mutant guard included), P1's own tests and the non-container suite on a copy of `main` (1699 passed with P1 alone; 1866 with P1 and the luts unit), the cocotb session against a stand-in `XutDut`, and the sv testbenches on Icarus against UNISIM 2025.2 in a 1G-capped container (every documented check passing; only pass/fail was read, never an undocumented checkpoint's value, per the clean-room rule). The formatter wins if a later ruff version disagrees.
- **Worktrees** live under `../xilinx-unittests-worktrees/<branch-with-dashes>`. **One PR per branch, always.**

### Branches and PRs

| Branch | Branched from | Worktree | Tasks | PR (base) |
|---|---|---|---|---|
| `infra/unit-prereqs` | `origin/main` after PR #10 | `infra-unit-prereqs` | P1 | "infra: unit prerequisites — coverage bins, xut.unitkit, AGENTS.md stub and heavy-lock rules" (base `main`) |
| `unit/7series/luts` | `origin/main` once P1 has merged, else `origin/infra/unit-prereqs` | `unit-7series-luts` | B1–B7 | "luts: LUT1-LUT6, LUT6_2 and CFGLUT5" (base `main`, or `infra/unit-prereqs` while P1 is open) |
| `unit/7series/<unit>` | `origin/main` | `unit-7series-<unit>` | A1–A7 | "`<unit>`: `<PRIMS>`" (base `main`) |
| `unit/7series/<unit>` (fresh, after the unit's first PR merged) | `origin/main` after step-3 PRs A–C | `unit-7series-<unit>` | A8 (luts: B8) | "`<unit>`: hardware results" (base `main`) |

- **One unit, one PR.** Each task is still reviewed on local commits before the next starts (the step-2 per-task review: a reviewer writes a report file; must-fix items are fixed in new commits). The spec §13.4 gate (two fresh reviewers with the `docs/review/` prompts, posting `gh pr review`) runs once, on the unit PR (Task A7).
- **Stacking.** A unit branch stacked on an open infra branch has that branch as its PR base. After the infra PR merges, only the orchestrator rebases the unit onto `main`, re-runs its tests, pushes with `git push --force-with-lease` and retargets the PR (`gh pr edit <N> --base main`).
- **Push after every task**, as a remote backup: `git push -u origin unit/7series/<unit>` (origin is HTTPS; if it asks for credentials, `git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/mithro/xilinx-unittests.git unit/7series/<unit>`).
- **Two-agent limit** (spec §13.5): at most two sub-agents at once, reviewers included; reviewers (a) and (b) run one after the other. Two units may proceed in parallel only as one implementer each with no reviewer running, and their heavy commands still take turns through the host-wide lock.
- **Ownership.** A unit branch touches only its unit's owned paths plus its own `log/<ts>-unit-7series-<unit>-<slug>.md` entries. `uv run xut lint --branch` enforces it before every push. An infra need is a TODO in the log entry or a stacked infra branch (AGENTS.md §13), never an edit under `tools/`.

## Review Focus

1. **Clean room and provenance.** Every modelled behaviour carries `doc:<page>` for a page that says it, or `inferred:<reason>` with a real reason. `-` appears only where UG953 declares a value undefined (ruling S30). A claim is hit only where a documented rule decides the output at that event (S32), never by an inferred rule alone (S44), and never by an output whose value depends on an inferred detail, even under a documented rule (S52). Knowledge that does not depend on an inference is tracked explicitly, never read off inferred state (S53: CFGLUT5's known-uniform contents). A claim credits only on an event whose documented outcome depends on its rule, one a model breaking the rule would get wrong (S55). No UNISIM internal names or quirks leak into a model.
2. **Reach, not declaration.** Every vector test's `exercises` is a subset of what its own generator reaches through the golden model, checked by `xut.unitkit.UnitGuards` through `vector_reach` (the python runner's own generation and `replay_config`). Every catalog bin is in some test's `exercises` or opens a `gaps` entry (`xut.lint.gap_bin`). Every exercised bin has at least one **pure** configuration, all of whose samples are documented, so it is credited whatever an inferred detail turns out to be (S52, S53). Every exercised claim has a named mutant in the unit's `mutants(prim)` table that fails a documented bit in a configuration crediting it, and in every such configuration for an event claim (S55, S55a, `UnitGuards`).
3. **No weakened test, no masked finding.** Findings are handled by class (Task A6). A model changes only for a UG953 contradiction. `expected_divergence` entries name open findings and never turn a bit into `-`.
4. **Portability declarations match the table.** A `no` row is declared `unsupported` with the table's reason; a `no: config:` row keeps `"yes"` (a lint warning until the smoke configuration is legal); a verilatorize refusal, `blocked`, or an equivalence `fail`/`error` makes `verilator` unsupported (and `iverilog-vz` with it).
5. **Hardware honesty.** A vector test declares `hw: "yes"` only if its configurations are order-renderable (spec §5.1 S8′); GSR pulses, reject tests, sv and cocotb tests, free-running clocks and pad-class ports are `hw: "unsupported"` with their reason.
6. **Memory safety.** Every heavy command in the plan and in the unit's README takes the host-wide lock and runs in a capped scope at the parallelism of the budget table.
7. **No copied infra.** Generic metadata, rendering and guard code comes from `xut.unitkit`; a unit neither copies it nor copies the flops unit.

---

## File Structure

Generic (Part A), per unit. The file stem is the unit's name, `<unit>`, everywhere (ruling S53): pytest's default import mode puts every `_shared/<unit>` directory's modules into one flat namespace, so the stem must be unique across units, and the unit name is.

```
catalog/7series/<PRIM>.overrides.yaml                 claims, active levels, allowed-value fixes, crosses
models/xut_models/7series/_common/<unit>.py           the shared clean-room model
models/xut_models/7series/<prim>.py                   one per primitive: constants + MODEL
tests/7series/<group>/_shared/<unit>/<unit>_recipes.py   stimulus recipes, generators(prim)
tests/7series/<group>/_shared/<unit>/<unit>_tests.py     tests_for, render(prim), UNIT (xut.unitkit)
tests/7series/<group>/_shared/<unit>/<unit>_cocotb.py    the cocotb random session
tests/7series/<group>/_shared/<unit>/<unit>_*_tb.svh     shared sv testbench bodies
tests/7series/<group>/_shared/<unit>/test_<unit>_models.py   claim-by-claim model tests
tests/7series/<group>/_shared/<unit>/test_<unit>_tests.py    class TestUnit(UnitGuards) + unit invariants
tests/7series/<group>/<PRIM>/test.yaml, README.md     GENERATED by <unit>_tests.py, committed
tests/7series/<group>/<PRIM>/vectors/gen.py           GENERATED: globals().update(<unit>_recipes.generators(...))
tests/7series/<group>/<PRIM>/sv/tb_<prim>_*.sv        GENERATED wrappers (defines + `include), or hand-written
tests/7series/<group>/<PRIM>/cocotb/cocotb_<prim>_*.py   GENERATED: one @cocotb.test calling the session
status/7series/<PRIM>.yaml                            via xut status record only (and the stub refresh)
findings/<PRIM>-<cls>-<level>-<name>.md               stubs from xut crosscheck --write-findings, or by hand (S52)
log/<ts>-unit-7series-<unit>-<slug>.md                one per session
```

luts (Part B):

```
catalog/7series/{LUT1..LUT6,LUT6_2,CFGLUT5}.overrides.yaml
models/xut_models/7series/_common/luts.py             Lut (LUT1-LUT6), DualLut (LUT6_2), CfgLut5
models/xut_models/7series/{lut1..lut6,lut6_2,cfglut5}.py
tests/7series/clb/_shared/luts/luts_recipes.py        KINDS, INIT sampling, drivers, 18 recipes
tests/7series/clb/_shared/luts/luts_tests.py          88 tests over 8 primitives, and every generated file
tests/7series/clb/_shared/luts/luts_cocotb.py
tests/7series/clb/_shared/luts/luts_x_tb.svh, luts_gsr_tb.svh
tests/7series/clb/_shared/luts/test_luts_models.py, test_luts_tests.py
tests/7series/clb/CFGLUT5/sv/tb_cfglut5_{x,gsr}.sv    hand-written (CFGLUT5 has its own ports)
tests/7series/clb/<PRIM>/...                          generated: test.yaml, README.md, vectors/gen.py,
                                                      cocotb/cocotb_<prim>_random.py, sv/tb_<prim>_{x,gsr}.sv (LUTs)
status/7series/{LUT1..LUT6,LUT6_2,CFGLUT5}.yaml
findings/CFGLUT5-doc-gap-L1-{projections,partial_shift}.md   the missing O5/O6 tables and shift direction (S52)
```

Part 0 (infra):

```
tools/xut/golden.py              attr_bins, coverage_reach
tools/xut/runners/python.py      replay_config (the runner's replay, shared with unitkit)
tools/xut/unitkit.py             reasons, runners, entry, class_bins, dump_test_yaml, render_readme,
                                 vector_reach, mutant_fails, Unit, UnitGuards (rulings S53, S55)
tools/tests/test_golden_reach.py, tools/tests/test_unitkit.py, tools/tests/test_runner_base.py
tools/tests/test_status_schema.py   the TEMPORARY pre_s19 / REGENERATED_ON_BRANCH allowances dropped
pyproject.toml                   "tests/**/test_*.py" = ["ANN"]
AGENTS.md                        §7: a unit refreshes its own stubs (D16); §10.1: the heavy-command lock (S53)
```

---

## Part 0: infra prerequisites (branch `infra/unit-prereqs`)

### Task P1: coverage bins, `xut.unitkit`, and the AGENTS.md rules every unit needs

Everything here affects every unit after flops, so it lands once, before the fan-out.

1. **`attr:<A>` is never reached.** Spec §9 and `xut.status.coverage_bins` give an attribute whose catalog `allowed` list is not enumerated (a range such as `2'h0 to 2'h3`, prose such as `Any 64-bit HEX value`, or nothing) the single bin `attr:<A>`. The golden replay's `Reach.bins()` names every explicitly-set attribute `attr:<A>=<value>`, so a vector test's `attr:<A>` can never be credited. Every LUT INIT, BRAM `INIT_xx` and DSP/MMCM integer attribute hits this. Fix: `xut.golden.coverage_reach` names the bins exactly as `coverage_bins` does, and the python runner records them through one function, `replay_config`.
2. **`xut.unitkit`** (ruling S53, code-quality review M1). Without it every unit re-implements about 350 lines of generic metadata and guard code, and a fix to any of it becomes 27 edits. The kit holds the standard runner reasons, `runners`/`claims`/`class_bins`/`entry`/`cell`, the no-alias YAML dumper, the README skeleton (every template section, with the "How to run" block under the heavy lock), `vector_reach` (the python runner's own `generate` and `replay_config`, never a copy), and the parametrised guard set `UnitGuards`: drift of every rendered file, schema and reasons, generators, reach, bins accounted (through `xut.lint.gap_bin`), pure crediting and, ruling S55, the **mutant guard**: every claim a vector test exercises has a named mutant model (`Unit.mutants(prim)`, `{claim: Mutant(factory, event=...)}`), and `mutant_fails` shows the mutant failing a documented bit in at least one configuration that credits a read claim, and in **every** configuration that credits an event claim (`event=True`: a clock edge, a shift, a hold; ruling S55a). A claim no wrong model can be caught on is not tested, however often it is credited. Units import it; **no unit copies it or the flops unit's code** (Part A).
3. **Unit test files fail `ruff check`**: extend the `ANN` exemption to `tests/**/test_*.py` (the flops unit's open TODO).
4. **AGENTS.md §7** (decision D16, confirmed on PR #12): a unit branch may refresh its own never-recorded stubs.
5. **AGENTS.md §10.1** (ruling S53, correctness review M4): one host-wide lock, `$XDG_RUNTIME_DIR/xut-heavy.lock`, around every heavy command, so two agents never run heavy jobs at once and each command's own budget (at most 96G) holds.
6. **`tools/tests/test_status_schema.py`**: drop the TEMPORARY `pre_s19` and `REGENERATED_ON_BRANCH` allowances. The orchestrator ran the S19 `--refresh-bins` on `main` (a11e51e), so every never-recorded stub now has exactly its current bins.

**Follow-up (not in this PR):** the flops unit migrates to `xut.unitkit` in its own later PR (its `flop_tests.py` helpers, the reach guard's private `_polarity_context` import), and then `_polarity_context` is deleted. Record it as a TODO in P1's log entry.

**Files:**
- Modify: `tools/xut/golden.py`, `tools/xut/runners/python.py`, `tools/tests/test_runner_base.py`, `tools/tests/test_status_schema.py`, `pyproject.toml`, `AGENTS.md` (§7, §10.1)
- Create: `tools/xut/unitkit.py`, `tools/tests/test_golden_reach.py`, `tools/tests/test_unitkit.py`

**Interfaces:**
- Produces:
  - `xut.golden.attr_bins(attributes, attrs) -> set[str]`, `xut.golden.coverage_reach(entry, vec, reach) -> set[str]`
  - `xut.runners.python.replay_config(entry, model_cls, vec, m) -> tuple[Trace, set[str]]`
  - `xut.unitkit`: `Reason`, `Declared`, `ALL_FLOWS`, `SV_PY`, `SV_HW`, `X_VL`, `CO_PY`, `CO_XS`, `CO_HW`, `VL_REJ`, `HW_REJ`, `HW_GSR`, `HW_PAD`; `runners(**over)`, `claims(prim, *ns)`, `class_bins(entry, port, *events)`, `entry(family, prim, level, name, style, source, exercises, *, gaps, sampling, declared, flows, configs, related)`, `dump_test_yaml(doc, generator)`, `cell`, `run_block(prim)`, `render_readme(...)`; `ConfigReach(cfg, bins, pure)`, `vector_reach(case, root)`, `mutant_fails(case, root, claim, mutant, *, every=False) -> bool | None`, `Mutant(factory, event=False)`; `Unit(name, family, root, group_dir, prims, render, generators, mutants=lambda prim: {}, pure=True)`, `UnitGuards`

- [ ] **Step 1: Worktree**

```bash
cd /home/tim/github/f4pga/xilinx-unittests && git fetch origin
git worktree add ../xilinx-unittests-worktrees/infra-unit-prereqs -b infra/unit-prereqs origin/main
cd ../xilinx-unittests-worktrees/infra-unit-prereqs && mkdir -p .cache
uv venv > .cache/uv-venv.log 2>&1 && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
git config core.hooksPath tools/hooks
```

- [ ] **Step 2: Write the failing tests.** `tools/tests/test_golden_reach.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""xut.golden.attr_bins / coverage_reach: bins_reached is named like coverage_bins (spec §9)."""

from xut.catalog.model import load_entry
from xut.formats.xvec import loads
from xut.golden import Reach, attr_bins, coverage_reach
from xut.paths import repo_root
from xut.status import coverage_bins

ATTRS = [
    {"name": "INIT", "allowed": ["Any 64-bit HEX value"]},
    {"name": "IS_C_INVERTED", "allowed": ["1'b0", "1'b1"]},
    {"name": "WIDTH", "allowed": []},
]


def test_attr_bins_name_only_set_non_enumerated_attributes():
    assert attr_bins(ATTRS, {"INIT": "64'h1", "IS_C_INVERTED": "1'b1"}) == {"attr:INIT"}
    assert attr_bins(ATTRS, {"WIDTH": 4}) == {"attr:WIDTH"}
    assert attr_bins(ATTRS, {}) == set()  # a default reaches no attribute bin


def test_coverage_reach_names_lut6_bins_as_coverage_bins_does():
    lit = "64'h8000000000000001"
    vec = loads(
        "# xut-vec 2  prim=LUT6 cfg=c nin=6 nout=1 nclk=0 settle_ps=120000 seed=0 "
        f"attr.INIT={lit}\nt=121000 set in[0]=1\nt=122000 sample S0\n"
    )
    reach = Reach(ports={"O", "I0"}, attrs=dict(vec.attrs), events={"I0:1"})
    got = coverage_reach(load_entry("7series", "LUT6", repo_root()), vec, reach)
    assert {"attr:INIT", "port:O", "port:I0", "port:I0:1"} <= got
    assert got - set(coverage_bins(load_entry("7series", "LUT6", repo_root()))) == {
        f"attr:INIT={lit}"
    }


def test_coverage_reach_keeps_polarity_renaming():
    vec = loads(
        "# xut-vec 2  prim=FDCE cfg=c nin=4 nout=1 nclk=1 settle_ps=120000 seed=0 "
        "attr.IS_CLR_INVERTED=1'b1\nclock  clk0  period=10000 phase=0 duty=50 mode=stepped\n"
        "t=121000 sample S0\n"
    )
    entry = load_entry("7series", "FDCE", repo_root())
    entry.ports = [dict(p, active="high") if p["name"] == "CLR" else p for p in entry.ports]
    reach = Reach(events={"CLR:fall"})  # the pin falls: an active-Low CLR asserts
    assert "port:CLR:assert" in coverage_reach(entry, vec, reach)
```

`tools/tests/test_unitkit.py` (the TOYFF fixture and its `toy` monkeypatch, as the runner tests use them):

```python
# SPDX-License-Identifier: Apache-2.0
"""xut.unitkit: the shared pieces of a work unit's metadata and guards (ruling S53)."""

import pytest
import yaml
from test_runner_base import FIX, TOY_ENTRY

from xut import unitkit
from xut.testspec import DECLARED_RUNNERS, discover


def test_runners_default_yes_and_reasons_for_the_rest():
    runs, reasons = unitkit.runners(hw=unitkit.HW_GSR, python=unitkit.SV_PY)
    assert list(runs) == list(DECLARED_RUNNERS)
    assert runs["hw"] == "unsupported" and runs["python"] == "no" and runs["xsim"] == "yes"
    assert reasons == {"hw": unitkit.HW_GSR[1], "python": unitkit.SV_PY[1]}


def test_class_bins_come_from_the_catalog():
    assert unitkit.class_bins(TOY_ENTRY, "D") == ["port:D", "port:D:0", "port:D:1"]
    assert unitkit.class_bins(TOY_ENTRY, "D", "1") == ["port:D", "port:D:1"]
    assert unitkit.class_bins(TOY_ENTRY, "C") == ["port:C", "port:C:edge"]


def test_entry_requires_gaps_and_dedupes_exercises():
    with pytest.raises(ValueError, match="misses"):
        unitkit.entry("7series", "TOYFF", "L1", "x", "vector", "vectors/gen.py:x", [], gaps=[])
    e = unitkit.entry(
        "7series",
        "TOYFF",
        "L1",
        "x",
        "vector",
        "vectors/gen.py:x",
        ["port:D"] * 2,
        gaps=["g"],
        declared=unitkit.runners(hw=unitkit.HW_REJ),
    )
    assert e["id"] == "7series.TOYFF.L1.x" and e["exercises"] == ["port:D"]
    assert e["unsupported_reasons"] == {"hw": unitkit.HW_REJ[1]}


def test_dump_test_yaml_writes_no_aliases_and_quoted_yes():
    shared = ["rtl"]
    text = unitkit.dump_test_yaml({"a": shared, "b": shared, "c": "yes"}, "x/y.py")
    assert text.startswith("# SPDX-License-Identifier: Apache-2.0\n# GENERATED by x/y.py")
    assert "&id" not in text and "*id" not in text
    assert yaml.safe_load(text)["c"] == "yes"


def test_render_readme_has_every_template_section(tmp_path):
    e = unitkit.entry("7series", "TOYFF", "L1", "x", "vector", "vectors/gen.py:x", [], gaps=["g"])
    text = unitkit.render_readme(
        prim="TOYFF",
        title="toy",
        reference="ref",
        overview="ov",
        tests=[(e, "why")],
        oracle=["model"],
        known_gaps=["timing"],
        root=tmp_path,
    )
    for section in (
        "## Overview",
        "## Tests",
        "## Why each test",
        "## Oracle",
        "## Known gaps",
        "## Runner support",
        "## Related tests",
        "## How to run",
    ):
        assert section in text
    assert 'flock "$XDG_RUNTIME_DIR/xut-heavy.lock"' in text


def test_vector_reach_replays_like_the_python_runner(toy):
    case = next(c for c in discover(FIX) if c.id == "7series.TOYFF.L1.capture")
    reach = unitkit.vector_reach(case, FIX)
    assert [c.cfg for c in reach] == ["init0", "init1"]
    assert all(c.pure for c in reach)  # ToyDff tags every bit doc:1
    assert "claim:TOYFF.C1" in set().union(*(c.bins for c in reach))
    reject = next(c for c in discover(FIX) if c.id == "7series.TOYFF.L0.reject")
    assert unitkit.vector_reach(reject, FIX) == []  # reject configurations are not replayed


def test_documented_is_false_for_any_inferred_bit():
    assert unitkit._documented({"S0": {"Q": "doc:1"}})
    assert not unitkit._documented({"S0": {"Q": "doc:1,inferred:x"}})


def test_unit_guards_parametrizes_over_the_units_primitives():
    unit = unitkit.Unit(
        "toy", "7series", FIX, FIX / "tests/7series/register", ("TOYFF",), dict, dict
    )
    guards = type("TestToy", (unitkit.UnitGuards,), {"unit": unit})()
    seen = []

    class Meta:
        fixturenames = ("prim",)

        def parametrize(self, name, values):
            seen.append((name, tuple(values)))

    guards.pytest_generate_tests(Meta())
    assert seen == [("prim", ("TOYFF",))]
    assert not unitkit.UnitGuards.__name__.startswith("Test")


def test_mutant_fails_on_a_crediting_configuration(toy):
    from test_golden import ToyDff

    class NoCapture(ToyDff):  # breaks TOYFF.C1: never captures D
        def clock_edge(self, port, rising):
            pass

    case = next(c for c in discover(FIX) if c.id == "7series.TOYFF.L1.capture")
    assert unitkit.mutant_fails(case, FIX, "TOYFF.C1", NoCapture) is True
    assert unitkit.mutant_fails(case, FIX, "TOYFF.C1", ToyDff) is False  # golden: no mismatch
    assert unitkit.mutant_fails(case, FIX, "TOYFF.C9", NoCapture) is None  # nothing credits it


def test_an_event_mutant_must_fail_every_crediting_configuration(toy):
    """Ruling S55a: ``every=True`` (an event claim) needs the mutant caught in each
    configuration that credits the claim; one catching configuration is not enough."""
    from test_golden import ToyDff

    from xut_models.base import bit_attr

    class CapturesOnlyFromInit1(ToyDff):  # breaks C1 in init0 only
        def clock_edge(self, port, rising):
            if bit_attr(self.attrs.get("INIT", 0)) == 1:
                super().clock_edge(port, rising)

    case = next(c for c in discover(FIX) if c.id == "7series.TOYFF.L1.capture")
    assert unitkit.mutant_fails(case, FIX, "TOYFF.C1", CapturesOnlyFromInit1) is True
    assert unitkit.mutant_fails(case, FIX, "TOYFF.C1", CapturesOnlyFromInit1, every=True) is False
    assert unitkit.Mutant(ToyDff).event is False  # a read claim unless marked


def test_doc_mismatch_ignores_inferred_bits():
    from xut.formats.xtr import Trace

    want, got = Trace({"runner": "python"}), Trace({"runner": "x"})
    want.add("S0", {"Q": "10"}, {"Q": "inferred:x,doc:1"})  # per-bit tags, LSB first
    got.add("S0", {"Q": "11"})
    assert not unitkit._doc_mismatch(want, got)
    got2 = Trace({"runner": "x"})
    got2.add("S0", {"Q": "00"})
    assert unitkit._doc_mismatch(want, got2)
```

Append to `tools/tests/test_runner_base.py` (the runner-level check: `bins_reached` gains `attr:INIT`):

```diff
diff --git a/tools/tests/test_runner_base.py b/tools/tests/test_runner_base.py
index cadc1f5..47ca337 100644
--- a/tools/tests/test_runner_base.py
+++ b/tools/tests/test_runner_base.py
@@ -751,3 +751,16 @@ def test_missing_python_run_is_a_named_xut_error(ctx):
     (d / "configs.json").write_text('{"not": "a list"}')
     with pytest.raises(NoPythonRun, match="not a list of configuration names"):
         load_generated(ctx, _case())
+
+
+def test_python_runner_records_a_non_enumerated_attribute_bin(ctx, toy, monkeypatch):
+    """bins_reached names attr:<A> for an explicitly set non-enumerated attribute, as
+    coverage_bins does (unit playbook Task P1)."""
+    open_init = {**TOY_ENTRY.attributes[0], "allowed": []}  # INIT: not enumerated
+    entry = dataclasses.replace(TOY_ENTRY, attributes=[open_init])
+    monkeypatch.setattr("xut.catalog.model.load_entry", lambda family, name, root: entry)
+    res = PythonRunner().run(_case(), ctx)
+    assert res.status == "pass", res.reason
+    data = _result(workdir(ctx, "python", _case().id))
+    assert "attr:INIT" in data["bins_reached"]
+    assert all("attr:INIT" in c["bins_reached"] for c in data["configs"])
```

```bash
uv run pytest tools/tests/test_golden_reach.py tools/tests/test_unitkit.py -q > .cache/p1-red.log 2>&1; cat .cache/p1-red.log
```

Expected: collection fails with `ImportError: cannot import name 'attr_bins' from 'xut.golden'` (and `xut.unitkit` missing).

- [ ] **Step 3: Implement.** In `tools/xut/golden.py`, add `from collections.abc import Mapping` and `from xut.catalog.model import CatalogEntry, is_enumerated` to the imports (`xut.wrap` already imports `xut.catalog.model`, so there is no new cycle), and add after `polarity_bins`:

```python
def attr_bins(attributes: list[dict], attrs: Mapping[str, object]) -> set[str]:
    """``attr:<A>`` for every explicitly-set attribute whose catalog ``allowed`` list is
    not enumerated (a range, prose, or nothing): spec §9 gives such an attribute the one
    bin ``attr:<A>``, which ``Reach.bins()``'s ``attr:<A>=<v>`` never names."""
    return {
        f"attr:{a['name']}"
        for a in attributes
        if a["name"] in attrs and not is_enumerated(a.get("allowed") or [])
    }


def coverage_reach(entry: CatalogEntry, vec: Vec, reach: Reach) -> set[str]:
    """The coverage bins one replayed configuration reached, named exactly as
    ``xut.status.coverage_bins`` names them: ``Reach.bins()``, the async/gate bins
    renamed by the catalog's declared ``active`` levels (``polarity_bins``), and the
    non-enumerated attribute bins (``attr_bins``)."""
    active = {p["name"]: p["active"] for p in entry.ports if p.get("active")}
    bins = reach.bins()
    if active:
        defaults = {a["name"]: a["default"] for a in entry.attributes}
        bins = polarity_bins(bins, active, {**defaults, **vec.attrs})
    return bins | attr_bins(entry.attributes, vec.attrs)
```

`tools/xut/runners/python.py` (the whole diff against `main`). `load_entry` is reached through the module (`catalog_model.load_entry`), so the `toy` fixture's monkeypatch still applies:

```diff
diff --git a/tools/xut/runners/python.py b/tools/xut/runners/python.py
index ec2dab1..c4fb788 100644
--- a/tools/xut/runners/python.py
+++ b/tools/xut/runners/python.py
@@ -28,11 +28,13 @@ from contextlib import contextmanager
 from pathlib import Path
 from typing import ClassVar
 
+from xut.catalog import model as catalog_model
+from xut.catalog.model import CatalogEntry
 from xut.errors import XutError
 from xut.formats import xtr, xvec
 from xut.formats.common import is_cfg
 from xut.formats.xvec import Vec
-from xut.golden import InvalidStimulus, polarity_bins, replay
+from xut.golden import InvalidStimulus, coverage_reach, replay
 from xut.runners.base import (
     ConfigResult,
     RunContext,
@@ -46,9 +48,9 @@ from xut.runners.base import (
 from xut.stimgen import GenContext
 from xut.testspec import TestCase
 from xut.validate import mark, validate
-from xut.wrap import DutSpec, spec_from_catalog, write_dut
+from xut.wrap import DutMap, DutSpec, spec_from_catalog, write_dut
 from xut_models import registry
-from xut_models.base import ModelContractError, ModelUnsupported
+from xut_models.base import Model, ModelContractError, ModelUnsupported
 
 
 class SourceError(XutError, ValueError):
@@ -147,12 +149,22 @@ def generate(case: TestCase, ctx: RunContext) -> list[tuple[Vec, DutSpec]]:
     return out
 
 
+def replay_config(
+    entry: CatalogEntry, model_cls: type[Model], vec: Vec, m: DutMap
+) -> tuple[xtr.Trace, set[str]]:
+    """The golden replay of one configuration and the coverage bins it reached, named as
+    ``xut.status.coverage_bins`` names them (``xut.golden.coverage_reach``). The one path
+    the python runner and ``xut.unitkit.vector_reach`` share."""
+    trace, reach = replay(model_cls, vec, m)
+    return trace, coverage_reach(entry, vec, reach)
+
+
 def _polarity_context(case: TestCase, ctx: RunContext) -> tuple[dict[str, str], dict]:
-    """The catalog's declared port ``active`` levels and attribute defaults, for naming
-    async/gate bins ``assert``/``release`` (``xut.golden.polarity_bins``). Without a
-    declared level the bins stay ``rise``/``fall``."""
-    from xut.catalog import model as catalog_model
+    """The catalog's declared port ``active`` levels and attribute defaults.
 
+    Unused here since ``replay_config``: kept only because the flops unit's reach guard
+    imports it; the flops migration to ``xut.unitkit`` (a follow-up of the unit playbook,
+    Task P1) removes that import, and then this function."""
     entry = catalog_model.load_entry(case.family, case.prim, ctx.root)
     active = {p["name"]: p["active"] for p in entry.ports if p.get("active")}
     return active, {a["name"]: a["default"] for a in entry.attributes}
@@ -166,9 +178,8 @@ class PythonRunner(Runner):
     def __init__(self) -> None:
         self._gen: dict[str, tuple[Vec, DutSpec]] = {}
         self._bins: set[str] = set()
-        #: port -> declared active level, and attribute defaults (catalog; polarity_bins)
-        self._active: dict[str, str] = {}
-        self._defaults: dict[str, object] = {}
+        #: the catalog entry (overrides applied) that names the bins (replay_config)
+        self._entry: CatalogEntry | None = None
         self._seed: int | None = None
         self._deadline = float("inf")
         self._limit_s = 0
@@ -193,7 +204,7 @@ class PythonRunner(Runner):
             raise SourceError(f"{case.id}: bad configuration names {bad} / duplicates {dups}")
         self._gen = {v.cfg: (v, s) for v, s in gen}
         self._bins = set()
-        self._active, self._defaults = _polarity_context(case, ctx)
+        self._entry = catalog_model.load_entry(case.family, case.prim, ctx.root)
         d = workdir(ctx, self.name, case.id)
         (d / "configs.json").write_text(json.dumps(names, indent=1) + "\n")
         return names
@@ -236,9 +247,12 @@ class PythonRunner(Runner):
                     model_cls = registry.get(case.family, case.prim)
                 except LookupError as e:
                     return ConfigResult(cfg, "skip", f"no golden model: {e}", stim_sha)
+                entry = self._entry
+                if entry is None:
+                    raise XutError(f"{case.id}: run_config before configs")
                 try:
-                    trace, reach = _watchdog(
-                        lambda: replay(model_cls, vec, m),
+                    trace, bins = _watchdog(
+                        lambda: replay_config(entry, model_cls, vec, m),
                         self._deadline,
                         f"golden model ({cfg})",
                         self._limit_s,
@@ -252,9 +266,6 @@ class PythonRunner(Runner):
                 if not trace.samples:  # validate refuses this; zero evidence never passes
                     return ConfigResult(cfg, "error", "golden replay has no samples", stim_sha)
                 trace.header["flow"] = ctx.flow
-                bins = reach.bins()
-                if self._active:
-                    bins = polarity_bins(bins, self._active, {**self._defaults, **vec.attrs})
                 self._bins |= bins
             xtr.dump(trace, cfgdir / "expected.xtr")
             shutil.copyfile(cfgdir / "expected.xtr", cfgdir / "trace.xtr")
```

`tools/xut/unitkit.py`:

````python
# SPDX-License-Identifier: Apache-2.0
"""What every work unit's metadata generator and guard tests share (ruling S53).

A unit's ``<stem>_tests.py`` builds its test entries with ``entry``, renders its files
with ``dump_test_yaml``/``render_readme``, and describes itself as a ``Unit``; its
``test_<stem>_tests.py`` is one line, ``class TestUnit(UnitGuards): unit = UNIT``. A unit
never copies this code, or the flops unit's.

- The standard ``unsupported_reasons`` (``SV_PY`` ... ``HW_GSR``) and ``runners``.
- Bin names from the catalog (``class_bins``), never hand-rolled.
- ``vector_reach``: what each configuration of a vector test reaches, through the python
  runner's own generation (``generate``, the ``xut run`` seed) and replay
  (``replay_config``), and whether every sampled bit is documented (``pure``).
- ``mutant_fails``: whether a model variant that breaks one claimed rule fails a
  documented bit in some configuration that credits that claim (ruling S55).
- ``UnitGuards``: drift of every rendered file, presence, schema and reasons, generators,
  reach, bins accounted (``xut.lint.gap_bin``), pure crediting (rulings S44, S52) and one
  failing mutant per credited claim (ruling S55).
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import yaml

from xut.catalog import model as catalog_model
from xut.catalog.model import CatalogEntry
from xut.testspec import DECLARED_RUNNERS, TestCase, discover

if TYPE_CHECKING:
    import pytest

    from xut.formats.xtr import Trace
    from xut.formats.xvec import Vec
    from xut.wrap import DutMap
    from xut_models.base import Model

#: ``(value, reason)``: a runner declaration other than ``"yes"``.
Reason = tuple[str, str]
#: ``(runners, unsupported_reasons)`` of one test.
Declared = tuple[dict[str, str], dict[str, str]]

ALL_FLOWS = ("rtl", "vivado", "yosys", "openxc7", "vpr")
SV_PY: Reason = ("no", "self-checking sv testbench; there is no golden-model replay")
SV_HW: Reason = ("unsupported", "sv testbenches are simulation-only (spec §4.3)")
X_VL: Reason = (
    "unsupported",
    "2-state simulator: x stimulus is randomised per X seed (spec §5.6), so the "
    "undocumented x checkpoints cannot be compared",
)
CO_PY: Reason = ("no", "the cocotb test compares against the golden model itself")
CO_XS: Reason = ("unsupported", "cocotb has no xsim backend (spec §4.3)")
CO_HW: Reason = (
    "unsupported",
    "cocotb runs in simulation; failing seeds are frozen into vector tests",
)
VL_REJ: Reason = ("unsupported", "a 2-state simulator cannot represent an x attribute value")
HW_REJ: Reason = ("unsupported", "rejection of an illegal attribute is a simulation-model check")
HW_GSR: Reason = ("unsupported", "GSR pulses need the GSR-immune harness state of spec §7.2")
HW_PAD: Reason = (
    "unsupported",
    "the primitive sits on IOB/ILOGIC/OLOGIC/IDELAY/BUFIO/BUFR sites: it needs the pad "
    "harness of spec §7.3",
)


def runners(**over: Reason) -> Declared:
    """Every declared runner ``"yes"`` except those in ``over``, with their reasons."""
    declared = {r: over[r][0] if r in over else "yes" for r in DECLARED_RUNNERS}
    return declared, {r: reason for r, (_, reason) in over.items()}


def claims(prim: str, *ns: int) -> list[str]:
    return [f"claim:{prim}.C{n}" for n in ns]


def class_bins(entry: CatalogEntry, port: str, *events: str) -> list[str]:
    """``port:<P>`` and the named class bins of one port (all of them when none is
    named), from ``xut.status.port_class_bins``."""
    from xut.status import port_class_bins

    p = next(p for p in entry.ports if p["name"] == port)
    by_event = {b.rsplit(":", 1)[1]: b for b in port_class_bins(p)}
    return [f"port:{port}", *(by_event[e] for e in events or by_event)]


def entry(
    family: str,
    prim: str,
    level: str,
    name: str,
    style: str,
    source: str,
    exercises: Sequence[str],
    *,
    gaps: Sequence[str],
    sampling: Mapping[str, list] | None = None,
    declared: Declared | None = None,
    flows: Sequence[str] = ALL_FLOWS,
    configs: Sequence[dict] = (),
    related: Sequence[str] = (),
) -> dict[str, Any]:
    """One ``test.yaml`` test, in the schema's key order. Every test says what it
    misses (lint rule gaps-present); every non-``"yes"`` runner has its reason."""
    if not gaps:
        raise ValueError(f"{prim}.{level}.{name}: every test must say what it misses")
    runs, reasons = declared or runners()
    e: dict[str, Any] = {
        "id": f"{family}.{prim}.{level}.{name}",
        "level": level,
        "style": style,
        "source": source,
        "exercises": list(dict.fromkeys(exercises)),
        "attr_sampling": dict(sampling or {}),
        "runners": runs,
        "flows": list(flows),
        "related": list(related),
        "gaps": list(gaps),
    }
    if reasons:
        e["unsupported_reasons"] = reasons
    if configs:
        e["configs"] = list(configs)
    return e


class _NoAliasDumper(yaml.SafeDumper):
    """Every test written out in full: no YAML anchors or aliases (flops review M4)."""

    def ignore_aliases(self, data: object) -> bool:
        return True


def dump_test_yaml(doc: dict, generator: str) -> str:
    """``doc`` as a committed ``test.yaml``: the SPDX line, a GENERATED line naming
    ``generator`` (a repository path), and the strings "yes"/"no" quoted."""
    header = f"# SPDX-License-Identifier: Apache-2.0\n# GENERATED by {generator}; edit that file.\n"
    return header + yaml.dump(
        doc, Dumper=_NoAliasDumper, sort_keys=False, width=100, allow_unicode=True
    )


def cell(test: dict, runner: str) -> str:
    """A runner-support table cell: ``yes``, or the value and its reason."""
    v = test["runners"][runner]
    return v if v == "yes" else f"{v}: {test['unsupported_reasons'][runner]}"


def run_block(prim: str) -> list[str]:
    """The README's "How to run": the heavy command under the host-wide lock and a
    capped scope (AGENTS.md §10.1), then crosscheck and record."""
    p = prim.lower()
    return [
        "```bash",
        'flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope \\',
        "  --slice=vivado.slice --unit=xut-run-$(date +%s) \\",
        "  -p MemoryMax=32G -p MemorySwapMax=0 -- \\",
        f"  uv run xut run {prim} --jobs 16 > .cache/run-{p}.log 2>&1",
        f"uv run xut crosscheck {prim} > .cache/xc-{p}.log 2>&1",
        f"uv run xut status record {prim} > .cache/status-{p}.log 2>&1",
        "```",
    ]


def render_readme(
    *,
    prim: str,
    title: str,
    reference: str,
    overview: str,
    tests: Sequence[tuple[dict, str]],
    oracle: Sequence[str],
    known_gaps: Sequence[str],
    root: Path,
) -> str:
    """A primitive's README with every section of docs/templates/primitive-README.md.
    ``tests`` pairs each test.yaml entry with why it is useful; findings are the open
    and closed ``findings/<PRIM>-*.md`` files, linked."""
    findings = sorted((root / "findings").glob(f"{prim}-*.md"))
    lines = [f"# {prim} — {title}", "", reference, "", "## Overview", "", overview, ""]
    lines += ["## Tests", "", "| ID | Level | Style | Exercises |", "|---|---|---|---|"]
    lines += [
        f"| `{e['id']}` | {e['level']} | {e['style']} | {', '.join(e['exercises'])} |"
        for e, _ in tests
    ]
    lines += ["", "## Why each test is useful, and what it misses", ""]
    for e, why in tests:
        lines.append(f"- `{e['id']}`: {why}")
        lines += [f"  - Misses: {g}" for g in e["gaps"]]
    lines += ["", "## Oracle", "", *(f"- {o}" for o in oracle), ""]
    lines += ["## Known gaps (all tests)", "", *(f"- {g}" for g in known_gaps)]
    lines += [f"- {g}" for g in dict.fromkeys(g for e, _ in tests for g in e["gaps"])]
    lines += ["", "## Runner support and expected divergences", ""]
    lines += ["| Test | " + " | ".join(DECLARED_RUNNERS) + " |"]
    lines += ["|---|" + "---|" * len(DECLARED_RUNNERS)]
    lines += [
        f"| `{e['id']}` | " + " | ".join(cell(e, r) for r in DECLARED_RUNNERS) + " |"
        for e, _ in tests
    ]
    lines += ["", "Findings:" if findings else "Findings: none recorded.", ""]
    lines += [f"- [{f.stem}](../../../../findings/{f.name})" for f in findings]
    lines += ["", "## Related tests", ""]
    lines += [
        f"- `{e['id']}`: " + (", ".join(f"`{r}`" for r in e["related"]) or "none") for e, _ in tests
    ]
    lines += ["", "## How to run", "", *run_block(prim), ""]
    return "\n".join(lines)


# --- reach -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigReach:
    """One configuration of a vector test, replayed through the golden model."""

    cfg: str
    bins: frozenset[str]
    #: every sampled bit's provenance is ``doc:`` (none ``inferred:``): the configuration
    #: can credit claims whatever the inferred details turn out to be (ruling S52)
    pure: bool


@dataclass(frozen=True)
class _Replayed:
    reach: ConfigReach
    vec: Vec
    m: DutMap
    trace: Trace


def _documented(prov: Mapping[str, Mapping[str, str]]) -> bool:
    return all(
        tag.startswith("doc:")
        for ports in prov.values()
        for token in ports.values()
        for tag in token.split(",")
    )


def _replay_all(case: TestCase, root: Path) -> list[_Replayed]:
    from xut.modelsrc import ModelSource
    from xut.runners.base import RunContext
    from xut.runners.python import generate, replay_config
    from xut.wrap import build_map
    from xut_models import registry

    ctx = RunContext(root, "rtl", ModelSource("golden", root))
    ent = catalog_model.load_entry(case.family, case.prim, root)
    model_cls = registry.get(case.family, case.prim)
    out = []
    for vec, spec in generate(case, ctx):
        if vec.expect == "reject":
            continue
        m = build_map(spec)
        trace, bins = replay_config(ent, model_cls, vec, m)
        out.append(
            _Replayed(ConfigReach(vec.cfg, frozenset(bins), _documented(trace.prov)), vec, m, trace)
        )
    return out


def vector_reach(case: TestCase, root: Path) -> list[ConfigReach]:
    """Every non-reject configuration of vector test ``case``, generated and replayed
    exactly as ``xut run --runner python`` does (``generate`` with the default seed,
    ``replay_config``)."""
    return [r.reach for r in _replay_all(case, root)]


def _doc_mismatch(want: Trace, got: Trace) -> bool:
    """``got`` differs from ``want`` on a bit ``want`` documents (``doc:``)."""
    for label, ports in want.samples.items():
        for port, bits in ports.items():
            tags = want.prov[label][port].split(",")
            for i, (w, g) in enumerate(
                zip(reversed(bits), reversed(got.samples[label][port]), strict=True)
            ):
                tag = tags[i] if len(tags) > 1 else tags[0]
                if tag.startswith("doc:") and w != g:
                    return True
    return False


def mutant_fails(
    case: TestCase, root: Path, claim: str, mutant: type[Model], *, every: bool = False
) -> bool | None:
    """Whether ``mutant`` (a model that breaks the rule of ``claim``) fails a documented
    bit in some configuration of vector test ``case`` that credits ``claim`` (with
    ``every``: in each one); ``None`` when no configuration of ``case`` credits it
    (rulings S55, S55a)."""
    from xut.golden import replay

    crediting = [r for r in _replayed(root, case) if f"claim:{claim}" in r.reach.bins]
    if not crediting:
        return None
    caught = (_doc_mismatch(r.trace, replay(mutant, r.vec, r.m)[0]) for r in crediting)
    return all(caught) if every else any(caught)


@dataclass(frozen=True)
class Mutant:
    """A unit's mutant for one claim: ``factory`` turns the golden model class into a
    model breaking exactly that claim's rule. ``event`` marks an event claim (a clock
    edge, a shift, a hold), whose every crediting configuration must catch the mutant;
    a read claim's (a stuck-at output agrees on reads of its own value) needs only one
    (ruling S55a)."""

    factory: Callable[[type[Model]], type[Model]]
    event: bool = False


# --- the guard set ---------------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    """A work unit as its guards see it."""

    name: str
    family: str
    root: Path
    group_dir: Path  # tests/<family>/<group>
    prims: tuple[str, ...]
    #: prim -> {path relative to the primitive's directory: rendered text}; test.yaml,
    #: README.md and every wrapper file the generator writes
    render: Callable[[str], dict[str, str]]
    #: prim -> test.yaml function name -> generator
    generators: Callable[[str], Mapping[str, Callable]]
    #: prim -> {claim id: its Mutant} (rulings S55, S55a)
    mutants: Callable[[str], Mapping[str, Mutant]] = lambda prim: {}
    #: every exercised vector bin has a configuration whose samples are all doc:
    pure: bool = True


class UnitGuards:
    """The guards every unit runs. Subclass as ``class TestUnit(UnitGuards): unit = U``;
    each guard is parametrized over the unit's primitives."""

    unit: ClassVar[Unit]  # not named Test*: pytest collects only the unit's subclass

    def pytest_generate_tests(self, metafunc: pytest.Metafunc) -> None:
        if "prim" in metafunc.fixturenames:
            metafunc.parametrize("prim", self.unit.prims)

    # helpers ------------------------------------------------------------------------
    def _doc(self, prim: str) -> dict:
        return yaml.safe_load((self.unit.group_dir / prim / "test.yaml").read_text())

    def _cases(self, prim: str) -> list[TestCase]:
        return [c for c in _discovered(self.unit.root) if c.prim == prim]

    # guards -------------------------------------------------------------------------
    def test_committed_files_are_current(self, prim: str) -> None:
        """Every file the generator renders exists and is current (flops review M5: a
        missing file fails; wrappers are rendered too, so none is hand-edited)."""
        d = self.unit.group_dir / prim
        for rel, text in self.unit.render(prim).items():
            path = d / rel
            assert path.is_file(), f"{path} missing: run the unit's generator"
            assert path.read_text() == text, f"{path} is stale: run the unit's generator"

    def test_validates_against_the_schema(self, prim: str) -> None:
        import jsonschema

        schema = json.loads((self.unit.root / "tools/xut/schemas/test.schema.json").read_text())
        doc = self._doc(prim)
        jsonschema.validate(doc, schema)
        assert doc["work_unit"] == self.unit.name
        for t in doc["tests"]:
            assert t["gaps"], t["id"]
            need = {r for r, v in t["runners"].items() if v != "yes"}
            assert need == set(t.get("unsupported_reasons", {})), t["id"]

    def test_every_generator_exists(self, prim: str) -> None:
        names = self.unit.generators(prim)
        for t in self._doc(prim)["tests"]:
            if t["style"] == "vector" and ":" in t["source"]:  # not a frozen .xvec
                assert t["source"].split(":", 1)[1] in names, t["id"]

    def test_exercises_are_reached(self, prim: str) -> None:
        """A vector test's exercises are reached by its own configurations (S23, S33)."""
        for case in self._cases(prim):
            if case.style != "vector":
                continue
            reached = set().union(*(r.reach.bins for r in _replayed(self.unit.root, case)))
            missing = set(case.exercises) - reached
            assert not missing, f"{case.id}: declared but never reached: {sorted(missing)}"

    def test_every_bin_is_exercised_or_a_gap(self, prim: str) -> None:
        from xut.lint import gap_bin
        from xut.status import coverage_bins

        cases = self._cases(prim)
        named = {b for c in cases for b in c.exercises}
        gaps = {gap_bin(g) for c in cases for g in c.gaps}
        ent = catalog_model.load_entry(self.unit.family, prim, self.unit.root)
        missing = [b for b in coverage_bins(ent) if b not in named | gaps]
        assert not missing, missing

    def test_every_exercised_bin_has_a_pure_configuration(self, prim: str) -> None:
        """Every bin a vector test exercises is reached by at least one configuration
        whose samples are all documented, so it is credited whatever an inferred detail
        turns out to be (rulings S44, S52; a failing configuration credits nothing)."""
        if not self.unit.pure:
            return
        vector = [c for c in self._cases(prim) if c.style == "vector"]
        pure = set().union(
            *(r.reach.bins for v in vector for r in _replayed(self.unit.root, v) if r.reach.pure)
        )
        missing = {b for v in vector for b in v.exercises} - pure
        assert not missing, f"only order- or inference-dependent configurations reach {missing}"

    def test_every_credited_claim_has_a_failing_mutant(self, prim: str) -> None:
        """Ruling S55: a claim credits only where its rule decides a documented bit. Each
        claim a vector test exercises has a named mutant that breaks exactly that rule,
        and the mutant fails a documented bit in some configuration crediting the claim;
        for an event claim, in every one (S55a)."""
        from xut_models import registry

        vector = [c for c in self._cases(prim) if c.style == "vector"]
        claimed = sorted(
            {b.split(":", 1)[1] for v in vector for b in v.exercises if b.startswith("claim:")}
        )
        mutants = self.unit.mutants(prim)
        assert not set(claimed) - set(mutants), (
            f"no mutant for {sorted(set(claimed) - set(mutants))}"
        )
        golden = registry.get(self.unit.family, prim)
        for claim in claimed:
            spec = mutants[claim]
            mutant = spec.factory(golden)
            verdicts = [
                mutant_fails(v, self.unit.root, claim, mutant, every=spec.event) for v in vector
            ]
            crediting = [
                (v.id, ok) for v, ok in zip(vector, verdicts, strict=True) if ok is not None
            ]
            assert crediting, f"{claim}: no configuration credits it"
            if spec.event:
                missed = [i for i, ok in crediting if not ok]
                assert not missed, (
                    f"{claim} (event): the mutant passes a crediting configuration of {missed}"
                )
            else:
                assert any(ok for _, ok in crediting), (
                    f"{claim}: the mutant passes every crediting configuration"
                )


@functools.cache
def _discovered(root: Path) -> tuple[TestCase, ...]:
    return tuple(discover(root))


@functools.cache
def _replayed_cached(root: Path, case_id: str) -> tuple[_Replayed, ...]:
    case = next(c for c in _discovered(root) if c.id == case_id)
    return tuple(_replay_all(case, root))


def _replayed(root: Path, case: TestCase) -> tuple[_Replayed, ...]:
    return _replayed_cached(root, case.id)
````

`tools/tests/test_status_schema.py` (drop the allowances):

```diff
diff --git a/tools/tests/test_status_schema.py b/tools/tests/test_status_schema.py
index a5c4d98..1e41e95 100644
--- a/tools/tests/test_status_schema.py
+++ b/tools/tests/test_status_schema.py
@@ -143,11 +143,6 @@ def test_unquoted_yaml_boolean_runner_value_fails_validation():
         jsonschema.validate(data, TEST_SCHEMA)
 
 
-#: TEMPORARY: primitive -> the attribute whose catalog values were regenerated on this
-#: branch; drop with ``pre_s19`` after the orchestrator's `status init --refresh-bins`.
-REGENERATED_ON_BRANCH = {"ICAPE2": "DEVICE_ID"}
-
-
 def test_every_status_stub_matches_its_catalog_entry_and_work_unit():
     """Repo invariant (reads the live checkout on purpose): every committed status stub
     matches its catalog entry's coverage bins and its docs/work-units.yaml unit."""
@@ -166,30 +161,11 @@ def test_every_status_stub_matches_its_catalog_entry_and_work_unit():
             continue  # recorded: its coverage is `xut status record`'s
         assert data["coverage"]["covered"] == []
         # `entry` is `load_entry`'s merge of the generated catalog with that primitive's
-        # overrides (crosses, claims, port/attribute corrections): a work unit owns its
-        # own stub and is expected to refresh it (`xut status init --refresh-bins`) when
-        # its overrides add claims or otherwise change `coverage_bins`, so a refreshed
-        # stub's `uncovered` is exactly `new` below.
-        new = coverage_bins(entry)
-        # TEMPORARY (ruling S20): the committed stubs predate ruling S19's port-class
-        # and cross bins, and an infra branch may not modify a status file. Once the
-        # orchestrator runs `xut status init --refresh-bins` on main, drop `pre_s19`:
-        # every never-recorded stub then has exactly `new`. `claim:` bins are excluded
-        # too: a work unit's overrides may add claims (or a cross) before that unit gets
-        # around to refreshing its own stub, and an unrefreshed stub never has those.
-        pre_s19 = [b for b in new if not b.startswith(("cross:", "claim:")) and b.count(":") == 1]
-        got = data["coverage"]["uncovered"]
-        # TEMPORARY (PR D fix wave): the catalog of a primitive in REGENERATED_ON_BRANCH
-        # was regenerated on this infra branch (ICAPE2: DEVICE_ID had been truncated);
-        # its stub is refreshed on main with the same --refresh-bins run. Until then the
-        # regenerated attribute's bins are left out of the comparison.
-        attr = REGENERATED_ON_BRANCH.get(entry.name)
-        if attr is not None:
-            got, new, pre_s19 = (
-                [b for b in bins if not b.startswith(f"attr:{attr}=")]
-                for bins in (got, new, pre_s19)
-            )
-        assert got in (new, pre_s19), entry.name
+        # overrides: a work unit refreshes its own stub (`xut status init
+        # --refresh-bins`, AGENTS.md §7) whenever its overrides change `coverage_bins`,
+        # and the orchestrator refreshed every stub on main (a11e51e), so a never-recorded
+        # stub's `uncovered` is exactly its current bins.
+        assert data["coverage"]["uncovered"] == coverage_bins(entry), entry.name
 
 
 def test_every_fresh_stub_has_exactly_the_current_bins():
```

`pyproject.toml`:

```diff
diff --git a/pyproject.toml b/pyproject.toml
index 83fb91e..ab49d05 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -48,6 +48,7 @@ select = ["E", "F", "W", "I", "B", "UP", "SIM", "ANN"]
 [tool.ruff.lint.per-file-ignores]
 # Type hints are enforced for the tool (tools/xut), not for pytest test functions.
 "tools/tests/**" = ["ANN"]
+"tests/**/test_*.py" = ["ANN"]
 
 [tool.ruff.lint.isort]
 known-first-party = ["xut", "xut_models"]
```

`AGENTS.md` (§7 and §10.1):

````diff
diff --git a/AGENTS.md b/AGENTS.md
index def4d92..375ae13 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -159,7 +159,12 @@ there is no override. Each model source keeps its own tree hash, tools and
 results (`results_by_model_source`).
 
 `xut status init --refresh-bins` updates the bins of never-recorded stubs to
-the current catalog. The orchestrator runs it on `main` only.
+the current catalog. The orchestrator runs it on `main`. A unit branch may
+also run it after its overrides change its own primitives' bins (new claims,
+`active` levels, crosses), but commits only its own never-recorded
+`status/<family>/<PRIM>.yaml` stubs: any other file it changes is restored
+with `git checkout -- <path>` and reported to the orchestrator (ruling on
+PR #12, D16).
 
 ## 8. Clean-room golden models
 
@@ -261,6 +266,20 @@ smoke simulation whose memory grows without bound. Its container peaked at
   value in a plan or task brief is capped by this section. For example, the
   step-2 plan's `--jobs 80` and `--jobs 40` predate this section. Use 8
   until PR C is merged, and 24 after.
+- **One heavy command at a time, host-wide** (ruling S53). Every heavy command
+  (`xut run`, `xut portability`, `xut verilatorize --check`, `xut hw sim`,
+  `xut hw build`, and `pytest` with `-n` above 1) takes the one host-wide lock
+  before its scope, so two agents never run heavy jobs at once and each
+  command's own budget (at most 96G) holds:
+
+  ```bash
+  flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope \
+    --slice=vivado.slice --unit=xut-<what>-$(date +%s) \
+    -p MemoryMax=<cap> -p MemorySwapMax=0 -- <command> > <log> 2>&1
+  ```
+
+  `flock` waits while another agent holds the lock; nothing ever deletes the
+  lock file.
 - **No `ulimit -v`.** It breaks Vivado. Use cgroup caps.
 - **An OOM kill is a normal result.** A scope result of `oom-kill`, or docker
   `OOMKilled=true`, is a retryable failure: lower the parallelism and re-run.
````

- [ ] **Step 4: Test and lint.** The whole suite is a heavy command: it takes the host-wide lock.

```bash
uv run pytest tools/tests/test_golden_reach.py tools/tests/test_unitkit.py tools/tests/test_runner_base.py -q > .cache/p1-green.log 2>&1; cat .cache/p1-green.log
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-pytest-p1-$(date +%s) \
  -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run pytest -n 4 --dist loadfile -m "not slow" > .cache/p1-pytest.log 2>&1; echo "exit=$?" >> .cache/p1-pytest.log
uv run ruff format --check tools > .cache/p1-ruff.log 2>&1; uv run ruff check tools >> .cache/p1-ruff.log 2>&1; cat .cache/p1-ruff.log
uv run xut lint --branch > .cache/p1-lint.log 2>&1; cat .cache/p1-lint.log
```

Expected: the focused tests pass; the suite passes (the summary line at the end of `.cache/p1-pytest.log`); ruff clean; lint 0 errors. (Checked while writing this plan on a copy of `main`: the non-container suite gives `1699 passed, 5 skipped`, including `test_family_literal_lives_only_in_work_units_yaml`, which is why `unitkit` takes the family as a parameter and never spells it.)

- [ ] **Step 5: Commit, log, PR**

```bash
git add tools/xut/golden.py tools/xut/runners/python.py tools/tests/test_golden_reach.py tools/tests/test_runner_base.py && git commit -m "infra: bins_reached names a non-enumerated attribute's attr:<A> bin (coverage_reach, replay_config)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tools/xut/unitkit.py tools/tests/test_unitkit.py && git commit -m "infra: add xut.unitkit, the shared metadata helpers and guard set of every work unit (S53)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tools/tests/test_status_schema.py && git commit -m "infra: stub invariant compares exact bins; drop the TEMPORARY pre_s19 and REGENERATED_ON_BRANCH allowances" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add pyproject.toml && git commit -m "infra: exempt unit test files (tests/**/test_*.py) from ruff ANN, as tools/tests" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add AGENTS.md && git commit -m "infra: AGENTS.md: a unit refreshes its own stubs (§7, D16); one host-wide lock for heavy commands (§10.1, S53)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Write `log/<ts>-infra-unit-prereqs-unitkit.md` (what changed, test results, the flops-migration TODO, next step: the luts unit), commit it with `infra: log the unit-prereqs session`, push (`git push -u origin infra/unit-prereqs`) and open the PR with `gh pr create -R mithro/xilinx-unittests --base main --head infra/unit-prereqs --title "infra: unit prerequisites — coverage bins, xut.unitkit, AGENTS.md stub and heavy-lock rules"`, whose body ends with the Claude Code line. It gets the §13.4 two-reviewer gate like every PR.

---

## Part A: the generic unit procedure

Every step below is written for `<unit>`/`<group>`/`<PRIMS>`. Run all commands from the unit worktree `<U>` unless a step says otherwise. Part B shows each task filled in for luts.

### Task A1: Worktree, intake, overrides and claims

**Files:**
- Create: `catalog/7series/<PRIM>.overrides.yaml` for each `<PRIM>`
- Modify: `status/7series/<PRIM>.yaml` (the stub bin refresh only)
- Create: `log/<ts>-unit-7series-<unit>-claims.md`

**Interfaces:**
- Consumes: `xut.catalog.model.load_entry`, `xut.status.coverage_bins`, `status/PORTABILITY.md`, `catalog/EXTRACTION_REPORT.md`
- Produces: claim ids `<PRIM>.C<n>` (a unit's primitives share numbering where the claims mean the same thing, as FD*.C1–C8 do), `active` levels for async/gate ports, corrected `allowed` lists, declared crosses, `min_event_gap_ps` when needed

- [ ] **Step 1: Create the worktree**

```bash
cd /home/tim/github/f4pga/xilinx-unittests && git fetch origin
git worktree add ../xilinx-unittests-worktrees/unit-7series-<unit> -b unit/7series/<unit> origin/main
cd ../xilinx-unittests-worktrees/unit-7series-<unit> && mkdir -p .cache
uv venv > .cache/uv-venv.log 2>&1 && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
git config core.hooksPath tools/hooks
uv run xut fetch-docs > .cache/fetch.log 2>&1; cat .cache/fetch.log
```

If Step 0 showed P1 unmerged, branch from `origin/infra/unit-prereqs` instead of `origin/main`, and open the unit PR with `--base infra/unit-prereqs` (Task A7).

- [ ] **Step 2: Intake.** Collect every fact the later tasks depend on into `.cache/intake-<unit>.md` (never committed), and summarise it in the log entry. Start from the unit's Appendix W row, then check each item on `main`, because the table and the catalog move.

  1. **UG953 pages.** For each `<PRIM>`, find its section in `.cache/docs/ug953-2026.1.txt` (a line holding only the primitive name, followed by `Primitive: ...`). A page's number is on the `UG953 v2026.1 ... <n>` footer line that *ends* it: text above the footer `<n>` is on page `<n>`. Note the Introduction, Logic Table, Port Descriptions and Available Attributes pages.
  2. **Catalog facts** (ports, classes, widths, attributes, kinds, allowed, defaults) and the current bins:

     ```bash
     uv run python -c "
     from xut.catalog.model import load_entry
     from xut.status import coverage_bins
     from xut.paths import repo_root
     for p in '<PRIMS>'.split():
         e = load_entry('7series', p, repo_root())
         print(p, [(q['name'], q['direction'], q['width'], q['cls']) for q in e.ports])
         print('   ', [(a['name'], a['kind'], a.get('width'), a['default'], a.get('allowed')) for a in e.attributes])
         print('   ', len(coverage_bins(e)), 'bins')
     " > .cache/intake-catalog.log 2>&1; cat .cache/intake-catalog.log
     ```

     Also read the `<PRIM>` entries of `catalog/EXTRACTION_REPORT.md` (names or values the extractor could not resolve).
  3. **Portability rows.** Read the rows for `<PRIMS>` in both sections of `status/PORTABILITY.md` (`unisim-2025.2` and `unisim-gh-2020.1`). For each simulator cell, record which case applies; Task A3 turns it into a declaration:

     | Cell | Meaning | Declaration (Task A3) |
     |---|---|---|
     | `yes` | the model compiled and ran its smoke configurations | `"yes"` |
     | `no` + a category (`udp`, `tri0-tri1`, `real`, `secureip`, `strength`, `timeout`, `other`) | the simulator cannot run the model | `"unsupported"`, reason quoting the table |
     | `no: config: <why> [<key>]` | the model's own attribute check refused the smoke configuration (ruling S51); says nothing about the simulator | `"yes"`; the unit's own L0 smoke, with legal configurations (Task A3), proves elaboration; the lint warning is noted in the log |
     | `no: verilatorize: ...`, verilatorize `unsupported`, `blocked by refused dependency`, or equiv `fail`/`error` | no trustworthy Verilator result | `verilator: "unsupported"`, reason quoting the table and the ruling; `iverilog-vz` follows automatically |
     | `oom` | the smoke run grew past its container cap | `"unsupported"` with the table's reason, and a note to the orchestrator (AGENTS.md §10.1: a model that is OOM-killed on its own is a result to report) |
     | `infra-error` | the smoke run itself failed | nothing yet: ask the orchestrator to regenerate the table |

  4. **Hardware class** (spec §5.1 ruling S8′, §7): which ports are `pad`/`inout` (pad harness, §7.3, not built in step 3), which claims need a GSR pulse (§7.2), whether any test needs a `mode=free` clock, `clock_out` ports (clock observers, §5.4, not built yet: the wrapper refuses them), `drp` ports (§5.5 transactions, not built yet), and attribute values illegal on fabric sites (like FDRE's `IS_D_INVERTED=1`). Model-internal delays above 1 ns need `min_event_gap_ps` in the overrides.
  5. **Legality.** Every attribute rule UG953 states ("X must be 0 when Y is 0", width pairs, ranges): each becomes a rule of the generator's legality model (Task A3), with its page.
  6. **Configuration count estimate.** Sum, over the planned tests, the configurations each generates. Every configuration is one simulator build on every runner, so the count sets the run time (Task A6, Step 2).

- [ ] **Step 3: Write `catalog/7series/<PRIM>.overrides.yaml` for each primitive.** Rules:
  - The header comment names the UG953 pages every fact below comes from (clean room), and records doc notes (typos, a template that contradicts the table) as comments.
  - `claims:` one entry per documented behavioural statement: `{id: <PRIM>.C<n>, page: <page>, provenance: "doc:<page>", text: "<paraphrase, at most 200 characters>"}`. The page is the one the statement is on. Never quote more than a phrase: the text is a paraphrase (no AMD prose).
  - Do not add a claim for inferred behaviour. A claim is a documented statement; rulings S44 and S52 let only outputs decided by documented rules credit claims, so an inferred claim could never be covered.
  - A documented rule that no simulation can reach (a placement or usage rule of one instance's configuration, like FDRE.C8) is still a claim. The test that would cover it lists it in `gaps` as `claim:<id> — <why>`.
  - Statements about how Vivado may **pack several primitives** together (LUT1–LUT5's "can be grouped with … into a single LUT6", p488 etc.) are not claims: they describe the tool's placement of many instances, not a behaviour or a configuration rule of one. Record them as a comment in the overrides, as luts does.
  - `ports:` `{<P>: {active: high|low}}` for every async/gate port whose active level UG953 states (spec §9: gives `assert`/`release` bins); a corrected `doc_function` (a paraphrase of at most 120 characters) where the extractor cut it.
  - `attributes:` correct an `allowed` list only where UG953 differs from the generated one, with the page in a comment. The generated lists are advisory (AGENTS.md, catalog notes).
  - `crosses:` only for attribute pairs whose interaction UG953 documents, over enumerated attributes only (lint rule `crosses-enumerated`). A cross value pair UG953 forbids is a bin no legal configuration can reach: it goes in a `gaps` entry citing the rule's page.
  - `min_event_gap_ps:` when a model-internal delay exceeds 1 ns (spec §5.1).
  - Do not add `smoke_attrs` yet: the key does not exist until infra ruling S51.5 is implemented (Appendix W lists the units that need it).

- [ ] **Step 4: Validate**

```bash
uv run python -c "
from xut.catalog.model import load_entry
from xut.status import coverage_bins
from xut.paths import repo_root
for p in '<PRIMS>'.split():
    e = load_entry('7series', p, repo_root())
    print(p, len(e.claims), 'claims', len(coverage_bins(e)), 'bins')
" > .cache/overrides.log 2>&1; cat .cache/overrides.log
```

Expected: every primitive loads (an `OverrideError` names a bad key or an unknown port/attribute), with the claim and bin counts the intake predicted.

- [ ] **Step 5: Refresh the unit's own status stubs.** Adding claims or `active` levels changes the primitive's bins, and the infra invariant test `test_every_status_stub_matches_its_catalog_entry_and_work_unit` compares every never-recorded stub with its catalog. Confirmed on PR #12 (decision D16): a unit branch may refresh its **own** never-recorded stubs; Task P1 amends AGENTS.md §7 to say so, and the flops unit's 115f0cc is covered retroactively.

```bash
uv run xut status init --refresh-bins > .cache/refresh-bins.log 2>&1; cat .cache/refresh-bins.log
git status --porcelain > .cache/git-status.log 2>&1; cat .cache/git-status.log
```

Expected: only `status/7series/<PRIM>.yaml` of this unit's primitives are modified. If any other file changed, restore it with `git checkout -- <path>`, and tell the orchestrator (another stub was stale on `main`).

- [ ] **Step 6: Commit**

```bash
git add catalog/7series status/7series && git commit -m "<unit>: add catalog overrides with behavioural claims for <PRIMS>" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Write `log/<ts>-unit-7series-<unit>-claims.md`: the intake summary (pages, portability cases, hardware class, legality rules, configuration estimate), the claims table, any doc notes, next step. Commit it with `<unit>: log the intake and claims`.

---

### Task A2: Clean-room golden models

**Files:**
- Create: `models/xut_models/7series/_common/<unit>.py`, `models/xut_models/7series/<prim>.py` per primitive
- Create: `tests/7series/<group>/_shared/<unit>/test_<unit>_models.py`

**Interfaces:**
- Consumes: `xut_models.base` (`Model`, `Out`, `ModelUnsupported`, `ModelContractError`, `bit_attr`); `xut_models.registry.get`
- Produces: `xut_models.7series.<prim>.MODEL` for every `<PRIM>`

The model contract (step 2, Task 6, and the flops reviews):

- `PRIM`, `CLOCKS`, `OUTPUTS` (name → width) and `inputs()` (clock ports included) match the catalog ports exactly; `replay` refuses a mismatch.
- `power_on()` is the time-0 state with glbl GSR asserted. `glbl("GSR", v)` must be accepted, because replay releases GSR at ROC_WIDTH; any other glbl signal raises `ModelUnsupported`.
- `set_input`, `clock_edge`, `glbl` and `outputs` raise `ModelContractError` before `power_on()`, for a port that is not an input (or not a clock), and for a value other than 0 or 1.
- `outputs()` returns exactly `OUTPUTS`, each an `Out(bits, prov)`; a multi-bit output whose bits have different provenance uses a per-bit tuple (LSB first).
- Attribute defaults come from UG953's attribute tables; the model receives only the explicitly-set attributes, so the model default and the UNISIM default are cross-checked by any configuration that sets nothing.

Provenance and claim rules:

- `doc:<page>` where UG953 states the behaviour on that page; the page is the rule's own (an inversion attribute's page for an output an inversion shaped: ruling S32's `ATTR_PAGE`).
- `inferred:<reason>` where UG953 is silent. The reason is one token: no whitespace, `#`, `|`, `=` or `,` (use `_`, `;`, `/`, `(`, `)`, `{`, `}`); it must be checkable ("UG953_names_no_GSR_effect_on_a_LUT"), not a placeholder.
- `-` only where UG953 **declares** a value undefined, with `doc:` provenance (ruling S30: where UG953 is silent, give a definite inferred value, so a disagreement becomes a `doc-gap` finding, never a mask). `Out` refuses `-` with an `inferred:` tag.
- A claim is hit only where its documented rule decides the output at that event (S32): not from a probe, not redundantly from an earlier decision, not for an edge that decides nothing. An output decided by an inferred rule alone credits no claim (S44). Ruling S52: nor does an output whose **value depends on an inferred detail**, even when the rule it follows is documented (CFGLUT5's reconfiguration is documented, its bit order is not). Such an output is exercised, tagged `inferred:`, and credits nothing. Credit the claim only from outputs you can prove independent of the inferred detail. Ruling S53: track that knowledge **explicitly** in the model, never by testing state computed under the inference (CFGLUT5's contents look uniform after 31 ones shifted into INIT=1 only under the inferred direction; the model instead tracks "known-uniform": uniform at power-on with only equal bits shifted in since, or 32 equal shifts in a row). Every credited claim also needs at least one **pure configuration**, one whose every sample is order-independent, because status credits per configuration, and a configuration with one mismatching inferred bit fails and credits nothing (spec §9, S21/S23); `xut.unitkit.UnitGuards` checks this. If no pure configuration can decide a claim, the claim goes to `gaps` and the plan says so. Ruling S55: a claim is credited only on an event whose **observable outcome depends on the claimed rule**, one where a model breaking that rule would show a different documented bit (CFGLUT5: a shift credits C3 only when it sets `known` to a new value, since shifting the value the contents already hold changes nothing; a CE-Low edge credits C4 only when CDI differs from `known`; CDO credits C5 only after a 32-shift run that flipped `known`). An event that merely obeys the rule decides nothing. "New" is measured against the last value a rule-breaking model could still show, not against the momentary state: CFGLUT5 keeps `_last_known` across a loss, so all ones lost part-way and re-established as all ones credits nothing (correctness re-review M7). **Every credited claim needs a named mutant**: a model that breaks exactly that rule (never shifts, ignores CE, a stuck CDO, INIT read in the wrong bit order, …), listed in the unit's `mutants(prim)` table, which `UnitGuards` shows failing a documented bit in some configuration that credits the claim. Mark **event claims** (a claim credited on an edge, a shift, a hold or a cascade) `event=True`: their mutant must fail in **every** configuration that credits them (ruling S55a), because one catching configuration lets any other credit the claim on a non-deciding event. Read claims keep `any`: a stuck-at output legitimately agrees on reads of its own value. Write a `doc-gap` finding stub by hand for the missing documentation (Task B1 shows the form), so crosscheck later records what UNISIM does.
- The model is written before, and committed without, any simulator run of the unit's tests. Once tests run, it changes only for a contradiction with UG953, with a test that shows it.

- [ ] **Step 1: Write the failing model tests** in `test_<unit>_models.py`. For every claim: a test that drives the documented situation, asserts the output bits, asserts the exact provenance against a **literal** page table in the test (never read from the model), and asserts the claim is hit; and a negative test that the claim is **not** hit where its rule does not decide the output. Also: the defaults (no attribute set), every inferred path (tagged `inferred:`, credits nothing), the contract guards, and GTS raising `ModelUnsupported`. Parametrize exactly (`[(p, j) for p ... for j in range(...)]`) rather than skipping inapplicable combinations.

```bash
uv run pytest tests/7series/<group>/_shared/<unit>/test_<unit>_models.py -q > .cache/models-red.log 2>&1; cat .cache/models-red.log
```

Expected: every test fails with `LookupError: no golden model for 7series/<PRIM>`.

- [ ] **Step 2: Implement the shared model and the per-primitive files.** The shared class carries the behaviour; each `<prim>.py` sets `PRIM`, the pages and the primitive's constants, and exports `MODEL`. The module docstring lists the pages, the claim numbering and every inference with its reason.

- [ ] **Step 3: Run the model tests**

```bash
uv run pytest tests/7series/<group>/_shared/<unit>/test_<unit>_models.py -q > .cache/models-green.log 2>&1; cat .cache/models-green.log
uv run ruff format models tests/7series/<group>/_shared/<unit> > .cache/ruff.log 2>&1; uv run ruff check models tests/7series/<group>/_shared/<unit> >> .cache/ruff.log 2>&1; cat .cache/ruff.log
```

Expected: all pass, no skips; ruff clean. Optional but recommended (the step-2 reviewers did it): revert one rule at a time in a scratch copy of the model (a wrong page, a claim hit on a probe, a missing guard) and confirm some test fails for each.

- [ ] **Step 4: Commit** the model before any test file that a simulator will run. Stage every file the model tests import (Part B's model tests import the top part of `<unit>_recipes.py`), so the commit's own tests pass:

```bash
git add models/xut_models/7series tests/7series/<group>/_shared/<unit>/test_<unit>_models.py tests/7series/<group>/_shared/<unit>/<unit>_recipes.py && git commit -m "<unit>: add clean-room golden models for <PRIMS> (UG953 pp. <pages>)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task A3: Recipes, the metadata generator and the guards

**Files:**
- Create: `tests/7series/<group>/_shared/<unit>/<unit>_recipes.py` (complete it), `<unit>_tests.py`, `test_<unit>_tests.py`
- Create (generated by `<unit>_tests.py`, committed): per primitive `test.yaml`, `README.md`, `vectors/gen.py`, and (Tasks A4, A5) the cocotb module and the sv wrappers

**Interfaces:**
- Consumes: `GenContext`, `VecBuilder` (`init`, `set`, `async_`, `edge`, `cycle`, `glbl`, `sample`, `simultaneous`, `build`); `xut.unitkit` (Task P1)
- Produces: `generators(prim)`; `tests_for(kind) -> list[tuple[dict, str]]`; `render(prim) -> dict[str, str]` (every generated file by its path under the primitive's directory); `UNIT = unitkit.Unit(...)`; `main(prims)`

Recipe rules:

- A recipe drives inputs and places samples; it never computes an expected value. `VecBuilder` makes every file satisfy the spec §5.1 class rules; a builder error is a recipe bug.
- **Legality model.** Where UG953 forbids attribute values or combinations, the recipes enumerate configurations through one `legal(attrs) -> str | None` function (the reason with its page, or `None`), so no L0–L2 configuration is illegal. Each documented illegal case gets a reject configuration: `ctx.dut(cfg, allow_illegal=True, expect="reject", illegal=[<names>], **attrs)` with one `sample()`.
- **Sampling (spec §4.2).** Every value of an enumerated attribute; a bit-vector or integer attribute by its boundaries, walking ones and walking zeros, and seeded random values from `ctx.rng` (the test's seed); declared crosses pairwise, over legal pairs only. Record the plan in each test's `attr_sampling`. Name every tuning constant (random step counts and probabilities) and derive widths from the kind, never a literal.
- **Class bins are reached only by real events** (rulings S19, S33): `VecBuilder.set` of an unchanged value emits nothing; `init` always emits; the power-on 0 of an input is not a `set`; a configuration that sets no attribute reaches no `attr:` bin. Prime a value before the transition you need (flops review N2), end a sweep by driving inputs back to 0, and set attributes explicitly in the configurations meant to reach them.
- **Observe power-on first** (flops review M6): sample once before the first change, so INIT/default values are compared.
- **Pure configurations** (S52, S53): where a model tags outputs `inferred:` under documented rules, give every claim and bin a configuration whose samples are all documented (read only where the order-free state is known).
- **Deciding events** (S55): every credited claim needs a configuration in which a model that breaks it fails a documented bit, so drive the stimulus that tells the rule apart from its mutant (for CFGLUT5's C4: a CDI opposite to the contents while CE is Low; for C3/C5: a flip of the uniform value).
- **Hardware.** Keep GSR pulses out of tests meant for hardware (spec §7.2); put them in their own test declared `hw: "unsupported"`. A configuration illegal on fabric is excluded per runner with `config_exclusions.hw` and its reason.

Metadata generator rules (`<unit>_tests.py`, the single source of every generated file):

- **Use `xut.unitkit`; copy nothing** (ruling S53): `unitkit.entry` builds each test (schema key order, non-empty `gaps`, a reason for every non-`"yes"` runner), `unitkit.runners` and the standard reasons (`SV_PY`, `SV_HW`, `X_VL`, `CO_XS`, `CO_HW`, `CO_PY`, `VL_REJ`, `HW_REJ`, `HW_GSR`, `HW_PAD`) declare runners, `unitkit.class_bins` names bins from the catalog, `unitkit.dump_test_yaml` writes the YAML, `unitkit.render_readme` writes a README with every template section and a "How to run" block under the heavy lock. The unit supplies only what is its own: the tests, their "why", overview and oracle text, and the wrapper files.
- `render(prim)` returns **every** generated file of the primitive (`test.yaml`, `README.md`, `vectors/gen.py`, the cocotb module, sv wrappers), so the drift guard covers wrappers too and none is hand-edited.
- A test's `exercises` names only bins its own recipe reaches. Portability declarations follow the intake table (Task A1, Step 2.3). `related` ids exist (lint warns otherwise).
- The generated `vectors/gen.py` is, for each primitive:

```python
# SPDX-License-Identifier: Apache-2.0
"""<PRIM> vector generators (test.yaml: source: vectors/gen.py:<name>).

The recipes live in tests/7series/<group>/_shared/<unit>/<unit>_recipes.py.
"""

import <unit>_recipes

globals().update(<unit>_recipes.generators("<PRIM>"))
```

Guards (`test_<unit>_tests.py`): one class, `class TestUnit(UnitGuards): unit = UNIT`, gives every primitive `unitkit`'s guards: every rendered file current; the schema, reasons and gaps; every vector source a generator; **reach** (each vector test's exercises reached by its configurations, through `vector_reach`: the python runner's own generation and `replay_config`); **bins accounted** (`xut.lint.gap_bin`, as the lint rule); **pure crediting** (every exercised vector bin reached by a configuration whose samples are all `doc:`); **a failing mutant per claim** (ruling S55: the unit's `mutants(prim)` returns `{claim: unitkit.Mutant(factory, event=...)}`, each factory taking the golden model class and returning a subclass that breaks that one rule; for every claim a vector test exercises, `unitkit.mutant_fails` replays the crediting configurations under the mutant and must find a documented bit that differs, in one of them for a read claim and in each of them for an event claim, S55a). Write the mutants in `<unit>_tests.py` and pass them as `Unit(..., mutants=mutants)`. Add only the unit's own invariants beside it (for luts: CFGLUT5 never declares Verilator; the edge mutants fail documented bits).

- [ ] **Step 1: Complete the recipes; write `<unit>_tests.py` and `test_<unit>_tests.py`.**

- [ ] **Step 2: Generate the files and run the guards**

```bash
uv run python tests/7series/<group>/_shared/<unit>/<unit>_tests.py > .cache/meta.log 2>&1; cat .cache/meta.log
uv run pytest tests/7series/<group>/_shared/<unit> -q > .cache/unit-pytest.log 2>&1; echo "exit=$?" >> .cache/unit-pytest.log; cat .cache/unit-pytest.log
uv run xut lint > .cache/lint.log 2>&1; cat .cache/lint.log
```

Expected: one `wrote ...` line per primitive; every guard passes; lint has no errors. Its warnings are only: `related` ids of primitives not yet generated (none once all are), `portability-agreement` warnings for tests that declare a runner unsupported for a property of the test rather than the model (an x stimulus, an x attribute; the lint message itself says an x stimulus is a valid reason; decision D12), and `no: config:` rows (Task A1, Step 2.3). List every warning in the log entry.

- [ ] **Step 3: The python runner: stimuli validate and the golden model replays them**

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-run-<unit>-py-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:<unit>' --runner python --jobs 16 > .cache/run-<unit>-python.log 2>&1; echo "exit=$?"
```

Expected: `exit=0`; every vector test `pass` (reject tests included: they are prepared, not replayed); every sv and cocotb test `skip` with its declared reason. Spot-check one `build/rtl/python/unisim-2025.2/<test-id>/cfg-<cfg>/stim.xvec`: `hw_renderable yes` for a hardware test, `no` with the §7.2 reason for a GSR test. `xut vec check <stim.xvec> --map <dut>/xut_dut.map.json` reports no `error:` lines.

- [ ] **Step 4: Commit** in two pieces:

```bash
git add tests/7series/<group>/_shared/<unit> && git commit -m "<unit>: add shared stimulus recipes, the file generator and its guards" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tests/7series/<group> && git commit -m "<unit>: add the generated <PRIMS> test files" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task A4: sv tests (GSR mid-simulation, X inputs, unit-specific behaviour)

**Files:**
- Create: `tests/7series/<group>/_shared/<unit>/<unit>_<what>_tb.svh` (shared bodies); the wrappers `tests/7series/<group>/<PRIM>/sv/tb_<prim>_<what>.sv` are rendered by `<unit>_tests.py` (`render(prim)`), or hand-written for a primitive whose ports no shared body fits

**Interfaces:**
- Consumes: `tools/xut/hdl/xut_trace.svh` (`XUT_CHECK`, `XUT_CHECKN`, `XUT_POINT1`, `XUT_POINT2`, `xut_open`, `xut_fd`, `xut_finish`); glbl's `GSR_int`
- Produces: one sv test per documented-but-not-vectorisable behaviour; every unit has at least a GSR mid-simulation test and an X-input test

Rules:

- The common subset of xsim, Icarus `-g2012` and Verilator `--timing` (spec §4.3). Declare any departure in the test's `sv_deviations`.
- The top module is the file stem; configurations (`configs` in test.yaml) set **module parameters** of that top (`-G`/`-P`), so a body is written with its attributes as parameters.
- **Checks only for documented behaviour** (`XUT_CHECK`/`XUT_CHECKN`, which count toward `XUT_CHECKS`); everything UG953 does not define (x propagation, GSR interactions it does not describe) is a **checkpoint** only (`$fdisplay(xut_fd, "<label>  <port>=%b ...")` after `xut_open`, or `XUT_POINT1/2`). A pass needs at least one check and one checkpoint (ruling S15). Checkpoint labels are deterministic and match `[A-Za-z0-9_./-]+`.
- A macro under an `if` is wrapped in `begin ... end` (ruling S36).
- **Time-0 inputs** (decision D7): give the testbench's input regs no declaration initialiser; drive their first values with a non-blocking assignment at time 0 (`I <= 0;` as the first statement of the `initial` block), as the vector testbench's time-0 barrier does. On Icarus a combinational UNISIM model (LUT6) left its output x for a declaration initialiser that raised no event; the FD* flops happened not to care.
- Wait past glbl's power-on GSR (ROC_WIDTH, 100 ns: `#120000` at `timescale 1ps/1ps`) before the first check.
- GSR mid-simulation: `glbl.GSR_int = 1'b1;` ... `glbl.GSR_int = 1'b0;` (the runner makes `glbl` reachable on every simulator).
- Runner declarations: `python: "no"` (`SV_PY`), `hw: "unsupported"` (`SV_HW`); an x-stimulus test is `verilator: "unsupported"` (`X_VL`); every portability `no` applies as for vectors. Flows are `["rtl"]`.
- Unit-specific sv tests are those spec §4.3 lists: clock management, runtime attribute rejection that needs more than a vector reject configuration, DRP transactions (§5.5, when infra adds them), GTS/GRESTORE (sim-only).

- [ ] **Step 1: Write the bodies; add the wrappers to `render(prim)` and regenerate** (`uv run python tests/7series/<group>/_shared/<unit>/<unit>_tests.py > .cache/meta.log 2>&1; cat .cache/meta.log`).
- [ ] **Step 2: Run them on every simulator**

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-run-<unit>-sv-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:<unit>' --style sv --runner iverilog --runner xsim --runner verilator --jobs 16 > .cache/run-<unit>-sv.log 2>&1; echo "exit=$?"
```

Expected: `pass` wherever declared `"yes"` (Verilator's `iverilog-vz` companion runs with it); `skip` with the declared reason elsewhere. The checkpoint traces of iverilog and xsim may differ only where a simulator really behaves differently: `xut crosscheck` classifies that in Task A6.

A `fail` means one of two things:
- a **documented** check fails on UNISIM: keep the test unchanged; it becomes a finding in Task A6;
- a **testbench** bug (a race, a wrong label, a wrong expected value for the documented rule): fix the testbench, never by deleting or loosening a check.

- [ ] **Step 3: Commit** with `<unit>: add shared GSR and X-input sv testbenches and the <PRIMS> instances`.

---

### Task A5: cocotb constrained-random session

**Files:**
- Create: `tests/7series/<group>/_shared/<unit>/<unit>_cocotb.py`, `tests/7series/<group>/<PRIM>/cocotb/cocotb_<prim>_random.py`

**Interfaces:**
- Consumes: `xut.cocotb_dut.XutDut` (`set`, `edge`, `settle`, `get`, `value`, `sample`, `close`, `attrs`); `xut_models.registry.get`; the unit's `KINDS`
- Produces: `random_session(dut, prim, steps)`

Rules (rulings S37, the flops Task 23 review, PR #10 must-fix 6):

- Drive every input explicitly (`await x.set(...)`) before telling the model about it; never seed the model from a port the session never drove.
- `model.power_on()`, drive the idle inputs, `await x.settle()` (120 ns), `model.glbl("GSR", 0)`, then **compare once before the first random step** (the power-on value).
- After every event (an input change, each clock edge), compare every output and write a sample with the model's provenance. Skip the comparison only for a model `-` bit (spec §5.3).
- Never drive z: `XutDut` refuses it (ruling S38).
- cocotb runs on Icarus and Verilator, never xsim (`CO_XS`); `python: "no"` (`CO_PY`), `hw: "unsupported"` (`CO_HW`). A primitive whose Verilator row is `no` declares that too, so its session runs on Icarus only.
- A failing seed is never fixed by changing the session. Classify it (Task A6), then freeze it: copy the session's events into `tests/7series/<group>/<PRIM>/vectors/frozen/<seed>.xvec` and add a vector test with `source: vectors/frozen/<seed>.xvec`, so it also runs on xsim and hardware (`xut freeze-seed` is deferred; spec §4.3).

- [ ] **Step 1: Write the session; add the per-primitive modules to `render(prim)` and regenerate.** A generated module is exactly:

```python
# SPDX-License-Identifier: Apache-2.0
"""7series.<PRIM>.L2.cocotb_random: random <PRIM> session vs the golden model."""

import cocotb
from <unit>_cocotb import random_session


@cocotb.test()
async def <prim>_random(dut: object) -> None:
    await random_session(dut, "<PRIM>", steps=2000)
```

- [ ] **Step 2: Run**

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-run-<unit>-cocotb-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:<unit>' --style cocotb --runner iverilog --runner verilator --runner xsim --jobs 16 > .cache/run-<unit>-cocotb.log 2>&1; echo "exit=$?"
```

Expected: `pass` on iverilog (and verilator plus its `iverilog-vz` companion where declared), every configuration with `steps + 1` samples at least (one per step, plus the power-on comparison; a clocked step samples after each edge); `skip` on xsim with `CO_XS`.

- [ ] **Step 3: Commit** with `<unit>: add the shared cocotb random session and the <PRIMS> cocotb tests`.

---

### Task A6: Full run, crosscheck, findings and status

**Files:**
- Modify (only when the evidence requires it): `<unit>_tests.py` (an `expected_divergence`, a gap), the regenerated `test.yaml`/`README.md`, a golden model (a UG953 contradiction, with a test)
- Create: `findings/<PRIM>-<cls>-<level>-<name>.md` (stubs from crosscheck, analysed by hand)
- Modify: `status/7series/<PRIM>.yaml` (via `xut status record` only)
- Create: `log/<ts>-unit-7series-<unit>-results.md`

- [ ] **Step 1: Commit every input first.** `xut run` stamps each `result.json` with the primitive's tree hash (its test directory, `_shared/<unit>`, its model files and its overrides), and `xut status record` refuses results from another tree hash or a dirty tree (spec §11, AGENTS.md §7). `git status --porcelain > .cache/git-status.log 2>&1; cat .cache/git-status.log` must show nothing under the unit's paths.

- [ ] **Step 2: Estimate, then run the whole unit on the reference model source**

- **Estimate.** Every configuration is one build per runner. With C vector configurations, S sv and K cocotb configurations: python is seconds; iverilog is about 2 s per configuration over 16 jobs; Verilator about 30–40 s per build over 16 jobs (twice run, once built); xsim about 10–15 s per configuration over the 4 host-wide slots, which usually dominates: about (C + S) × 15 s ÷ 4. Write the estimate and the cadence it implies into the log before starting.
- **Run it in the background** and watch it with a Monitor on the log's `progress:` lines, at the cadence of the estimate:

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-run-<unit>-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:<unit>' --jobs 16 > .cache/run-<unit>.log 2>&1; echo "exit=$?" >> .cache/run-<unit>.log
```

Expected: every declared runner `pass` for every test; every undeclared cell `skip` with a reason; `build/rtl/{python,xsim,iverilog,iverilog-vz,verilator}/unisim-2025.2/<test-id>/result.json` exist. A `fail` is evidence for Step 4, not a reason to stop.

- [ ] **Step 3: The open-source model source** (spec §6.2 "Model identity"; CI runs it too):

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-run-<unit>-gh-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:<unit>' --model-source unisim-gh-2020.1 --runner python --runner iverilog --runner verilator --jobs 16 > .cache/run-<unit>-gh.log 2>&1; echo "exit=$?" >> .cache/run-<unit>-gh.log
```

xsim always uses the precompiled 2025.2 library and refuses this source. Crosscheck compares each source's traces only with each other.

**A model a source does not have** (Appendix W: ROM32X1…ROM256X1 have no `unisim-gh-2020.1` row). Run the gh source only on the primitives it has (select them by name instead of `unit:<unit>`). For a missing one, that source's runners are `n/a`, with the reason "`unisim-gh-2020.1` has no <PRIM> model": write it in the primitive's README runner-support section (a line the generator renders from a per-primitive `missing_sources` table) and in the log. Record and crosscheck that primitive with `--model-source unisim-2025.2` only, so neither an `error` result nor crosscheck's `exit=4` stands for the absent model. (A per-source `n/a` field in the status file needs infra; record it as a TODO if the orchestrator wants it.)

- [ ] **Step 4: Crosscheck and write the finding stubs**

```bash
uv run xut crosscheck 'unit:<unit>' --write-findings > .cache/xc-<unit>.log 2>&1; echo "exit=$?" >> .cache/xc-<unit>.log; cat .cache/xc-<unit>.log
```

Exit codes (ruling S23): `0` clean; `3` a finding no `expected_divergence` lists; `4` incomplete evidence (an error, a fail no disagreement explains, mixed or dirty trees, no shared configuration, fewer than two traces). Handle **every** finding by its class, against the UG953 pages only (never UNISIM source):

| Class | What it means | What to do |
|---|---|---|
| `doc-vs-model` | every UNISIM simulator of a source agrees, and disagrees with a `doc:` bit | Re-read the cited page. If the **model** contradicts UG953, it is a model bug: fix it with a test in `test_<unit>_models.py`, delete the stub (it is not a finding), commit, and re-run from Step 1. Otherwise (UNISIM disagrees with the documentation): complete the stub's **Analysis** (the page, what it says, what the simulators do), keep `Status: open`, add `{finding: findings/<id>.md, cls: doc-vs-model, runners: [<every runner in the finding>]}` to the test's `expected_divergence` in `<unit>_tests.py`, and mention the finding id in that test's `gaps`. |
| `doc-gap` | the same, on an `inferred:` bit | Complete the Analysis (what UG953 omits, what the simulators do, the model's inference and its reason). Keep it open and add the `expected_divergence`. **Do not change the model to follow the simulators**: the inference stays until the documentation settles it. |
| `sim-divergence` | UNISIM simulators of one source disagree | Record it; the `expected_divergence` lists every runner involved. If Verilator is one of them, first rule out `x-dependence` and `transform-bug` (below). |
| `x-dependence` | Verilator's two X-seed runs differ | Record it; declare `verilator: "unsupported"` for the affected tests with the finding link as the reason (step 2, Task 24). |
| `transform-bug` | Icarus on the transformed model ≠ Icarus on the original | A `xut verilatorize` bug: record it, declare `verilator: "unsupported"` with the finding link, and report it to the orchestrator for an infra fix. It blocks every Verilator result of that model. |
| `known-divergence` | a listed disagreement, still reported | Nothing: it stays visible in PROGRESS.md and TODO.md while its finding is open. |
| `flow-mismatch`, `silicon-mismatch`, `nondeterminism`, `harness-error` | the hardware and non-`rtl` classes | Task A8 (and the step-4 flows plan). |

Two situations crosscheck does not classify:

- **A reject test the simulators accept** (`fail` "expected rejection, got acceptance"). UG953 lists the legal values but does not promise a runtime check. Remove that reject test from `<unit>_tests.py` and the recipe table, and add to `L0.smoke`'s `gaps`: "UNISIM (<model source>) accepts <ATTR>=<value> without rejecting it; the reject path is not exercised". Record it in the log (the step-2 Task 24 rule). This records a gap; it does not weaken a documented check.
- **A simulator that refuses a configuration UG953 allows** (an attribute check stops the run: `error`/`fail` with the model's message, python `pass`). Keep the configuration. Write `findings/<PRIM>-doc-vs-model-<level>-<name>.md` by hand from the stub format, with `Status: open`, and report it to the orchestrator (decision D13: crosscheck has no rule for it yet, so it stays an incomplete-evidence `exit=4` until infra adds one).

After the changes, regenerate and commit (Step 5), and re-run crosscheck until it exits `0` with every disagreement either absent or a `known-divergence` naming an open finding. Every finding file is linked from its primitive's README (the generator lists `findings/<PRIM>-*.md`).

- [ ] **Step 5: Commit the evidence-driven changes, re-run, record**

```bash
uv run python tests/7series/<group>/_shared/<unit>/<unit>_tests.py <PRIMS> > .cache/meta.log 2>&1; cat .cache/meta.log
git add tests/7series/<group> findings && git commit -m "<unit>: crosscheck findings and expected divergences" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Skip that commit if Step 4 changed nothing. If it changed any tree-hashed input, re-run Steps 2–4 for the affected primitives, so every result carries the new tree hash. Then:

```bash
uv run xut status record --unit <unit> > .cache/status-<unit>.log 2>&1; cat .cache/status-<unit>.log
uv run xut status record --unit <unit> --model-source unisim-gh-2020.1 >> .cache/status-<unit>.log 2>&1; cat .cache/status-<unit>.log
git diff --stat status/7series > .cache/status-diff.log 2>&1; cat .cache/status-diff.log
git add status/7series && git commit -m "<unit>: record <PRIMS> results and coverage" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected in each `status/7series/<PRIM>.yaml`:
- `results` keys `<level>/<runner>/<flow>`: `pass` on `rtl` for every declared runner; `not-run` on `vivado`, `yosys`, `openxc7`, `vpr` for simulators and on every `hw/<flow>` (until Task A8 and step 4); `unsupported` where declared;
- `results_by_model_source.unisim-gh-2020.1` filled, `measured.model_sources` listing both;
- `coverage.uncovered` exactly the bins that open a `gaps` entry (usually none);
- `findings` the open findings' ids.

`record` warnings ("declares … but no configuration … reached it") are bugs in a declaration: fix the `exercises`, never the recipe's reach guard.

- [ ] **Step 6: Lint, tests, log, per-task review**

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-pytest-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run pytest -n 4 --dist loadfile -m "not slow" > .cache/pytest.log 2>&1; echo "exit=$?" >> .cache/pytest.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
git status --porcelain > .cache/git-status.log 2>&1; cat .cache/git-status.log
```

Expected: the suite passes (read the summary line at the end of `.cache/pytest.log`); lint has no errors (warnings as in Task A3, Step 2); only committed changes remain, and `status/PROGRESS.md` is not modified. Write `log/<ts>-unit-7series-<unit>-results.md`: the crosscheck matrix (pasted from the log), every finding and how it was handled, the run durations against the estimate, and the lint warnings. Commit it with `<unit>: log the full run, findings and status`. Run the per-task review on the local commits (reviewer (a), then reviewer (b)); fix must-fix items in new commits.

---

### Task A7: The unit PR and the two-reviewer gate

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin unit/7series/<unit> > .cache/push.log 2>&1; cat .cache/push.log
gh pr create -R mithro/xilinx-unittests --base main --head unit/7series/<unit> --title "<unit>: <PRIMS>" --body-file .cache/pr-<unit>.md > .cache/pr.log 2>&1; cat .cache/pr.log
```

The body (`.cache/pr-<unit>.md`, never committed) states: the primitives and their UG953 pages; the test counts per primitive and style; the results matrix; every finding with its class and status; every `unsupported` declaration and its reason; the per-task review outcomes; the hardware declarations and what Task A8 will run; and it ends with the line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. A unit stacked on an open infra branch uses `--base infra/<topic>`.

- [ ] **Step 2: The review gate** (spec §13.4, AGENTS.md §12). Two fresh reviewers, one after the other: (a) with `docs/review/code-quality.md`, (b) with `docs/review/correctness.md`. Each posts one review with `gh pr review <N> --comment --body-file <file>`, marking each item **[must-fix]** or **[nit]** and ending with `VERDICT: approve` or `VERDICT: changes-requested`. Reviewer (b) reads the UG953 pages itself and checks every claim, every `doc:` page, every `inferred:` reason and the clean-room rule. Fix every must-fix in new commits (never amend or force-push reviewed history), push, and ask for re-review until both approve.

- [ ] **Step 3: Merge (orchestrator).** The merge gate: `xut lint` passes, CI is green, both reviewers approve with no open must-fix. The orchestrator rebase-merges and then, on `main`:

```bash
uv run xut status generate > .cache/status-gen.log 2>&1; cat .cache/status-gen.log
git add status/PROGRESS.md status/TODO.md status/LOG.md && git commit -m "status: regenerate" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task A8: Hardware follow-up (after step-3 PRs A–C merge)

The step-3 plan (PR #11, `docs/superpowers/plans/2026-09-27-step3-hardware.md`) builds the stepped fabric harness, the Vivado flow and the `hw` runner, and pilots them on flops (its Task 12) and luts (its Task 13). This task is the same procedure for any unit. Until it runs, a unit's `hw` cells record `not-run`, which is honest: the tests already declare what hardware can run.

**Which tests declare `hw: "yes"`** (from the unit's first PR on, Task A3):

- vector tests whose every configuration is order-renderable (spec §5.1, S8′): stepped clocks only, no GSR/GTS/GRESTORE event, no x/z stimulus, no `simultaneous` events, no pad-class or inout port, every model-internal delay shorter than the event gap (`min_event_gap_ps`); and a primitive that spec §7.3 does not place on an IOB/ILOGIC/OLOGIC/IDELAY/BUFIO/BUFR site (the table's pad-site row);
- with `flows` listing `vivado` (and `yosys`, `openxc7`, `vpr` for step 4).

**Which stay `hw: "unsupported"`, and the reason each carries:**

| Situation | Reason |
|---|---|
| a GSR pulse (flops `L1.gsr_init`, luts `L1.gsr_transparent`) | "GSR pulses need the GSR-immune harness state of spec §7.2" (`HW_GSR`). The power-on INIT value **is** tested on hardware: every slot runs from configuration. |
| sv and cocotb tests | simulation-only (`SV_HW`, `CO_HW`); a frozen cocotb seed becomes a vector test that runs on hardware |
| reject tests | "rejection of an illegal attribute is a simulation-model check" (`HW_REJ`) |
| a `mode=free` clock (MMCM/PLL input clocks) | "free-running clocks need real-time rendering (spec §5.1 S8′)" until a later step defines it |
| a pad-class or inout port (the io units, XADC analog pins) | "pad-class port: needs the pad harness of spec §7.3" until an io-harness plan builds it |
| a primitive that spec §7.3 places on IOB/ILOGIC/OLOGIC/IDELAY/BUFIO/BUFR sites, **whatever its catalog port classes**: IDDR, IDDR_2CLK, ODDR, ISERDESE2, OSERDESE2, IDELAYE2, ODELAYE2, IDELAYCTRL, BUFIO, BUFR, BUFMR, and the IBUF/OBUF/IOBUF families | `unitkit.HW_PAD` ("the primitive sits on IOB/ILOGIC/OLOGIC/IDELAY/BUFIO/BUFR sites: it needs the pad harness of spec §7.3") until P5. The rule goes by primitive class, not by pad-class ports: IDDR's ports are all `data`/`clock`/`async`, so the validator alone would call its stimuli renderable (ruling S53, correctness review M5). |
| a `clock_out` port | none yet: the wrapper refuses it until the clock observers of spec §5.4 exist (Appendix W: bufg, regional_clk, mmcm_pll) |
| GTS/GRESTORE, JTAG glbl signals | sim-only (spec §5.2) |
| an attribute value illegal on the harness's fabric sites | `config_exclusions.hw` with the UG953 page, the test keeps `hw: "yes"` (flops `IS_D_INVERTED=1`) |
| LVDS/differential outputs | "3.3 V banks on the Arty A7" (spec §7.3) |
| configuration primitives | as spec §7.4's table (STARTUPE2 shared with the harness, ICAPE2 without IPROG, JTAG through the Pi, DNA/eFUSE values read by the host) |

A test declared `"yes"` whose individual configuration is not renderable is still visible: the `hw` runner records that configuration as a `skip` with the validator's reason.

- [ ] **Step 0: The gate.** All of: step-3 PRs A–C merged; board access working (`uv run xut doctor > .cache/doctor.log 2>&1; cat .cache/doctor.log` lists `hw` among the available runners); the fpgas.online sessions (ten64.welland.mithis.com, desktop.buddy.mithis.com) have confirmed the Welland Artys are free and the lock name in `hw/rigs.yaml` is theirs; the unit's first PR merged. Otherwise stop, log which gate failed, and report "blocked".
- [ ] **Step 1: A fresh worktree** on `unit/7series/<unit>` from `origin/main` (the old remote branch deleted by the orchestrator after the merge), as in Task A1, Step 1.
- [ ] **Step 2: Check the declarations** in `<unit>_tests.py` against the table above; commit any change with `<unit>: declare the hw runner for the renderable vector tests`.
- [ ] **Step 3: Prove it in simulation first**

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-hwsim-<unit>-$(date +%s) -p MemoryMax=16G -p MemorySwapMax=0 -- \
  uv run xut hw sim 'unit:<unit>' --sim iverilog --jobs 8 > .cache/hwsim-<unit>.log 2>&1; echo "exit=$?"
```

Expected `exit=0`. A failure is a harness bug: report it and stop.
- [ ] **Step 4: Baseline, bitstreams, the hardware run.** Exactly step-3 Task 12, Steps 4–6, with `unit:<unit>`:

```bash
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-run-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:<unit>' --jobs 16 > .cache/run-<unit>-rtl.log 2>&1; echo "exit=$?"
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-hwbuild-$(date +%s) -p MemoryMax=8G -p MemorySwapMax=0 -- \
  uv run xut hw build 'unit:<unit>' --jobs 4 > .cache/hwbuild-<unit>.log 2>&1; echo "exit=$?"
flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope --slice=vivado.slice --unit=xut-run-hw-$(date +%s) -p MemoryMax=32G -p MemorySwapMax=0 -- \
  uv run xut run 'unit:<unit>' --flow vivado --runner hw --jobs 3 > .cache/run-<unit>-hw.log 2>&1; echo "exit=$?"
```

Estimate the builds first: one bitstream holds at most 64 slots and 28 DUT clocks (spec §7.1 rev 3.6), so a test needs ceil(configurations ÷ 64) bitstreams at 20–40 minutes each over 4 Vivado slots, then 3 repeats × 20–40 s per job over the free rigs. Report at the cadence the estimate gives.
- [ ] **Step 5: Crosscheck and classify** as step-3 Task 12, Step 7: `silicon-mismatch` is re-run on another rig with `--hw-rig <other> --hw-repeats 5` before it is a finding, then analysed against UG953 and listed as `{cls: silicon-mismatch, runners: [hw], flows: [vivado]}`; `nondeterminism` is re-run with `--hw-repeats 10` and reported as a possible harness margin bug first; `harness-error` stops the task (infra). A `flow-mismatch` from the post-flow DUT check is a toolchain finding against Vivado, never against the primitive.
- [ ] **Step 6: Commit, record, log, PR** as step-3 Task 12, Steps 8–9: `L*/hw/vivado` results appear, the GSR tests' `hw` cells are `unsupported`, and the PR is "`<unit>`: hardware results".

---

## Part B: the luts unit (branch `unit/7series/luts`)

`<unit>` = `luts`, `<group>` = `clb`, `<PRIMS>` = `LUT1 LUT2 LUT3 LUT4 LUT5 LUT6 LUT6_2 CFGLUT5`. Worktree `../xilinx-unittests-worktrees/unit-7series-luts`. Every shared file uses the stem `luts` (`luts_recipes.py`, `luts_tests.py`, `test_luts_models.py`, `luts_x_tb.svh`, …), so Part A's commands apply unchanged.

**Clean room.** Everything below is from UG953 v2026.1: CFGLUT5 pp. 348–349, LUT1 pp. 488–489, LUT2 pp. 491–492, LUT3 pp. 494–495, LUT4 pp. 497–499, LUT5 pp. 500–502, LUT6 pp. 504–507, LUT6_2 pp. 509–512. Nothing was taken from UNISIM.

**What UG953 documents, and what it leaves open** (the intake, Task A1 Step 2, done while writing this plan):

- **LUT1–LUT6**: a complete logic table per primitive: O = INIT[i] with i = {I<n-1>..I0} (LUT1 p489, LUT2 p492, LUT3 p495, LUT4 p498, LUT5 p501 (its output column is labelled "LO"), LUT6 pp. 504–506). The Introduction (p488, 491, 494, 497, 500, 504) says INIT defaults to zero, "driving the output to a zero regardless of the input values (acting as a ground)". INIT's allowed values are a range (`2'h0 to 2'h3` … `16'h0000 to 16'hffff`) or "Any 32/64-bit HEX value": not enumerated, so one bin `attr:INIT` each (needs Task P1). The primitives have no clock and no GSR text.
- **LUT6_2** (pp. 509–512): the logic table (pp. 510–511) gives O6 = INIT[{I5..I0}] and O5 = INIT[{I4..I0}] (I5 does not reach O5); p509 says the lower 32 bits drive O5, INIT defaults to zero, and gives the example 64'hFFFFFFFFFFFFFFFE (O6 a 6-input OR, O5 a 5-input OR).
- **CFGLUT5** (pp. 348–349): INIT (32 bits, default all zeroes) is shifted in serially from CDI, synchronously, while CE (active-High) is High; O6 is the 5-input function of the loaded INIT; O5 the "4-LUT output"; CDO cascades to the next CFGLUT5's CDI, "32-bits per LUT"; IS_CLK_INVERTED selects the active clock level. p348 refers to O5/O6 tables that **are not in the 2026.1 section**, and gives **no shift direction** and **no CDO bit**. The model infers them (decision D5); every such bit is `inferred:`, so a disagreement is a `doc-gap`, never a mask, and (rulings S52, S53) such a bit credits no claim: only contents the model **knows** are uniform whatever the order credit CFGLUT5's claims, and `L1.edge_polarity` is a configuration whose every sample is order-free. Two `doc-gap` findings record the missing documentation from the start (Task B1).
- **Portability** (`status/PORTABILITY.md`, both sources): LUT1–LUT6 and LUT6_2 are `yes`/`yes`, verilatorize `unchanged`. CFGLUT5 is iverilog `yes`, verilator `no: verilatorize: CFGLUT5: ... trigger cone contains NBA-written reg ... (ruling S28)`, verilatorize `unsupported`: every CFGLUT5 test declares `verilator: "unsupported"` (`CFG_VL`) until the srl/CFGLUT5 recovery TODO of ruling S29(2) is done.
- **Hardware class**: no pad, inout, `clock_out` or `drp` port; CFGLUT5's CLK is a stepped clock like a flop's. Every vector test is renderable except the two GSR tests (`HW_GSR`) and the reject tests (`HW_REJ`).
- **Legality**: every INIT value of the declared width is legal; nothing else to model. The only illegal values are non-HEX literals (x digits): `L0.illegal_init`.
- **Not claims**: LUT1–LUT5's statements on grouping several LUTs into one LUT6 (p488, 491, 494, 497, 500) are Vivado packing rules for many instances (Task A1); the overrides say so in a comment.
- **Size**: 88 tests (64 vector, 16 sv, 8 cocotb); 706 vector configurations (LUT1 12, LUT2 26, LUT3 46, LUT4 64, LUT5 98, LUT6 164, LUT6_2 168, CFGLUT5 128), 23 sv and 32 cocotb configurations.

Claim numbering: LUTn `C1` logic table, `C2` zero default. LUT6_2 `C1` O6, `C2` O5, `C3` zero default, `C4` the OR example. CFGLUT5 `C1` O6, `C2` O5, `C3` CE-High shift, `C4` CE-Low hold, `C5` CDO cascade, `C6` INIT at start-up, `C7` IS_CLK_INVERTED.

### Task B1: Overrides and claims (Task A1)

**Files:**
- Create: `catalog/7series/{LUT1,LUT2,LUT3,LUT4,LUT5,LUT6,LUT6_2,CFGLUT5}.overrides.yaml`
- Modify: `status/7series/{LUT1,...,CFGLUT5}.yaml` (stub refresh)
- Create: `findings/CFGLUT5-doc-gap-L1-projections.md`, `findings/CFGLUT5-doc-gap-L1-partial_shift.md` (ruling S52)

- [ ] **Step 1: Worktree** (Task A1, Step 1, with `<unit>` = `luts`; from `origin/infra/unit-prereqs` if P1 has not merged).

- [ ] **Step 2: Write the eight overrides.** No attribute override is needed: every INIT `allowed` is correctly non-enumerated and CFGLUT5's `IS_CLK_INVERTED` is already `[1'b0, 1'b1]`. No crosses: UG953 documents no interaction between INIT and IS_CLK_INVERTED. No port is async or gate, so no `active` level.

`catalog/7series/LUT1.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: claims layered over the generated LUT1.yaml.
# Clean room: every fact below is from UG953 v2026.1 (LUT1, pp. 488-489).
#
# Attributes: no override. INIT's generated `allowed` (p489) is not an
# enumerated list, so INIT has the one bin attr:INIT (spec §9); its sampling plan is
# recorded in test.yaml (spec §4.2). Crosses: none (one attribute).
#
# Not claims: the p488 statements on grouping LUT1 with other LUTs into one LUT6
# describe how Vivado packs several primitives, not a behaviour or a configuration
# rule of one instance (plan Task A1).
claims:
  - {id: LUT1.C1, page: 489, provenance: "doc:489", text: "O is INIT[i], where i is the binary number {I0} (logic table)."}
  - {id: LUT1.C2, page: 488, provenance: "doc:488", text: "INIT defaults to zero, so O is 0 for every input value (a ground)."}
```

`catalog/7series/LUT2.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: claims layered over the generated LUT2.yaml.
# Clean room: every fact below is from UG953 v2026.1 (LUT2, pp. 491-492).
#
# Attributes: no override. INIT's generated `allowed` (p492) is not an
# enumerated list, so INIT has the one bin attr:INIT (spec §9); its sampling plan is
# recorded in test.yaml (spec §4.2). Crosses: none (one attribute).
#
# Not claims: the p491 statements on grouping LUT2 with other LUTs into one LUT6
# describe how Vivado packs several primitives, not a behaviour or a configuration
# rule of one instance (plan Task A1).
claims:
  - {id: LUT2.C1, page: 492, provenance: "doc:492", text: "O is INIT[i], where i is the binary number {I1,I0} (logic table)."}
  - {id: LUT2.C2, page: 491, provenance: "doc:491", text: "INIT defaults to zero, so O is 0 for every input value (a ground)."}
```

`catalog/7series/LUT3.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: claims layered over the generated LUT3.yaml.
# Clean room: every fact below is from UG953 v2026.1 (LUT3, pp. 494-495).
#
# Attributes: no override. INIT's generated `allowed` (p495) is not an
# enumerated list, so INIT has the one bin attr:INIT (spec §9); its sampling plan is
# recorded in test.yaml (spec §4.2). Crosses: none (one attribute).
#
# Not claims: the p494 statements on grouping LUT3 with other LUTs into one LUT6
# describe how Vivado packs several primitives, not a behaviour or a configuration
# rule of one instance (plan Task A1).
claims:
  - {id: LUT3.C1, page: 495, provenance: "doc:495", text: "O is INIT[i], where i is the binary number {I2,I1,I0} (logic table)."}
  - {id: LUT3.C2, page: 494, provenance: "doc:494", text: "INIT defaults to zero, so O is 0 for every input value (a ground)."}
```

`catalog/7series/LUT4.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: claims layered over the generated LUT4.yaml.
# Clean room: every fact below is from UG953 v2026.1 (LUT4, pp. 497-499).
#
# Attributes: no override. INIT's generated `allowed` (p499) is not an
# enumerated list, so INIT has the one bin attr:INIT (spec §9); its sampling plan is
# recorded in test.yaml (spec §4.2). Crosses: none (one attribute).
#
# Not claims: the p497 statements on grouping LUT4 with other LUTs into one LUT6
# describe how Vivado packs several primitives, not a behaviour or a configuration
# rule of one instance (plan Task A1).
claims:
  - {id: LUT4.C1, page: 498, provenance: "doc:498", text: "O is INIT[i], where i is the binary number {I3,I2,I1,I0} (logic table)."}
  - {id: LUT4.C2, page: 497, provenance: "doc:497", text: "INIT defaults to zero, so O is 0 for every input value (a ground)."}
```

`catalog/7series/LUT5.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: claims layered over the generated LUT5.yaml.
# Clean room: every fact below is from UG953 v2026.1 (LUT5, pp. 500-502).
#
# Attributes: no override. INIT's generated `allowed` (p502) is not an
# enumerated list, so INIT has the one bin attr:INIT (spec §9); its sampling plan is
# recorded in test.yaml (spec §4.2). Crosses: none (one attribute).
#
# Not claims: the p500 statements on grouping LUT5 with other LUTs into one LUT6
# describe how Vivado packs several primitives, not a behaviour or a configuration
# rule of one instance (plan Task A1).
#
# Doc note: the p501 logic table labels its output column "LO"; the port table
# (p502) and the rest of the section name the output O, which is what is modelled.
claims:
  - {id: LUT5.C1, page: 501, provenance: "doc:501", text: "O is INIT[i], where i is the binary number {I4,I3,I2,I1,I0} (logic table)."}
  - {id: LUT5.C2, page: 500, provenance: "doc:500", text: "INIT defaults to zero, so O is 0 for every input value (a ground)."}
```

`catalog/7series/LUT6.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: claims layered over the generated LUT6.yaml.
# Clean room: every fact below is from UG953 v2026.1 (LUT6, pp. 504-507).
#
# Attributes: no override. INIT's generated `allowed` (p507) is not an
# enumerated list, so INIT has the one bin attr:INIT (spec §9); its sampling plan is
# recorded in test.yaml (spec §4.2). Crosses: none (one attribute).
#
# The logic table runs over pp. 504-506; claims cite its first page.
claims:
  - {id: LUT6.C1, page: 504, provenance: "doc:504", text: "O is INIT[i], where i is the binary number {I5,I4,I3,I2,I1,I0} (logic table)."}
  - {id: LUT6.C2, page: 504, provenance: "doc:504", text: "INIT defaults to zero, so O is 0 for every input value (a ground)."}
```

`catalog/7series/LUT6_2.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: claims layered over the generated LUT6_2.yaml.
# Clean room: every fact below is from UG953 v2026.1 (LUT6_2, pp. 509-512).
#
# Attributes: no override. INIT ("Any 64-bit HEX value", p512) stays the one
# non-enumerated bin attr:INIT (spec §9). Crosses: none (one attribute).
# The logic table (O5 and O6 columns) runs over pp. 510-511; claims cite p510.
claims:
  - {id: LUT6_2.C1, page: 510, provenance: "doc:510", text: "O6 is INIT[i], where i is the binary number {I5,I4,I3,I2,I1,I0} (logic table)."}
  - {id: LUT6_2.C2, page: 510, provenance: "doc:510", text: "O5 is INIT[i], i = {I4,I3,I2,I1,I0}: the lower 32 INIT bits drive O5 and I5 does not affect it (logic table; p509)."}
  - {id: LUT6_2.C3, page: 509, provenance: "doc:509", text: "INIT defaults to zero, so O5 and O6 are 0 for every input value."}
  - {id: LUT6_2.C4, page: 509, provenance: "doc:509", text: "INIT=64'hFFFFFFFFFFFFFFFE makes O6 a 6-input OR and O5 a 5-input OR of I4-I0."}
```

`catalog/7series/CFGLUT5.overrides.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# luts work unit: corrections and claims layered over the generated CFGLUT5.yaml.
# Clean room: every fact below is from UG953 v2026.1 (CFGLUT5, pp. 348-349).
#
# Doc notes (recorded, not modelled):
# - p348 says O5/O6 usage is shown in "the following tables", but the 2026.1 section
#   contains no logic table; nor does it give the shift direction or which INIT bit
#   reaches CDO. The golden model infers them (inferred: provenance, plan decision D5).
# - p349: the VHDL template's generic is spelled INT, not INIT.
#
# Attributes: no override. INIT ("Any 32-bit HEX value", p349) stays the one
# non-enumerated bin attr:INIT; IS_CLK_INVERTED's generated `allowed` is already the
# 1-bit pair of p349's "1'b0 to 1'b1". Crosses: none (UG953 documents no interaction
# between INIT and IS_CLK_INVERTED).
ports:
  # The extractor cut the p348 function text at a table line break; a paraphrase.
  CDO: {doc_function: "Reconfiguration data cascade output; connect it to the CDI of the next CFGLUT5."}
claims:
  - {id: CFGLUT5.C1, page: 348, provenance: "doc:348", text: "O6 is the 5-input function of I0-I4 given by the INIT value currently loaded."}
  - {id: CFGLUT5.C2, page: 348, provenance: "doc:348", text: "O5 is the 4-LUT output: a 4-input function of the same inputs, using a subset of the loaded INIT."}
  - {id: CFGLUT5.C3, page: 348, provenance: "doc:348", text: "With CE High, each active CLK edge shifts CDI serially into INIT, changing the function at run time."}
  - {id: CFGLUT5.C4, page: 348, provenance: "doc:348", text: "CE is an active-High reconfiguration clock enable: with CE Low, CLK edges leave INIT unchanged."}
  - {id: CFGLUT5.C5, page: 348, provenance: "doc:348", text: "CDO carries the reconfiguration data out, so a CDO-to-CDI chain passes 32 bits per LUT."}
  - {id: CFGLUT5.C6, page: 349, provenance: "doc:349", text: "INIT, all zeroes by default, is the function loaded at start-up."}
  - {id: CFGLUT5.C7, page: 349, provenance: "doc:349", text: "IS_CLK_INVERTED=1 makes CLK active-Low: the falling edge is the active edge."}
```

- [ ] **Step 3: Validate** (Task A1, Step 4, with `'LUT1 LUT2 LUT3 LUT4 LUT5 LUT6 LUT6_2 CFGLUT5'`). Expected:

```
LUT1 2 claims 7 bins
LUT2 2 claims 10 bins
LUT3 2 claims 13 bins
LUT4 2 claims 16 bins
LUT5 2 claims 19 bins
LUT6 2 claims 22 bins
LUT6_2 4 claims 25 bins
CFGLUT5 7 claims 36 bins
```

(LUTn: `port:O`, three bins per input, `attr:INIT`, two claims. CFGLUT5: 26 port bins, `attr:INIT`, both `IS_CLK_INVERTED` values, seven claims.)

- [ ] **Step 4: Write the two CFGLUT5 `doc-gap` stubs** (ruling S52). UG953 omits the O5/O6 tables and the shift direction, so the findings exist before any run. Their ids are the ones crosscheck gives a `doc-gap` of the tests that pin each order (`<PRIM>-<cls>-<level>-<name>`), so a later disagreement is appended to them as an `- Also seen:` line instead of a new file. The `Flow / model source` line deliberately names no model source, so crosscheck appends one line per source it sees. They stay `Status: open` until UG953 documents the order, whatever UNISIM shows.

`findings/CFGLUT5-doc-gap-L1-projections.md`:

```markdown
# CFGLUT5: doc-gap in 7series.CFGLUT5.L1.projections

- Class: doc-gap
- Test: 7series.CFGLUT5.L1.projections
- Flow / model source: rtl / (none yet: written by hand before the first run, ruling S52)
- Runners: xsim, iverilog
- First seen: UG953 v2026.1 review, before any simulation
- Status: open

## Evidence

UG953 v2026.1 p348 says O5 and O6 can be used as two 4-input functions, or as a 5-input
and a 4-input function, "see the following tables". The CFGLUT5 section (pp. 348-349) has
no table, so it does not say which INIT bit an I4..I0 value selects on O6, or which bits
and inputs O5 uses.

The order UNISIM shows is recorded here by Task B6 of the unit playbook, for each model
source (`unisim-2025.2`, `unisim-gh-2020.1`):

- O6 index order: (to be recorded)
- O5 bits and inputs: (to be recorded)

## Analysis

The golden model infers O6 = INIT[{I4..I0}], as in the LUT5 logic table (p501), and
O5 = INIT[{I3..I0}], the lower half, as for LUT6_2's O5 (p509). Both are tagged
`inferred:`. Rulings S52 and S53: a read whose value depends on this order credits no
claim; only contents known to be uniform whatever the order (all 0 or all 1) credit
CFGLUT5.C1/C2, and L1.edge_polarity credits every claim from such reads alone. This finding stays open until the
documentation gives the tables, whatever UNISIM shows. The model is not changed to follow
a simulator (AGENTS.md §8).
```

`findings/CFGLUT5-doc-gap-L1-partial_shift.md`:

```markdown
# CFGLUT5: doc-gap in 7series.CFGLUT5.L1.partial_shift

- Class: doc-gap
- Test: 7series.CFGLUT5.L1.partial_shift
- Flow / model source: rtl / (none yet: written by hand before the first run, ruling S52)
- Runners: xsim, iverilog
- First seen: UG953 v2026.1 review, before any simulation
- Status: open

## Evidence

UG953 v2026.1 p348 says a new INIT is shifted in serially through CDI while CE is High,
and that CDO cascades to the next CFGLUT5's CDI (32 bits per LUT). It gives no shift
direction: which INIT bit CDI enters, and which INIT bit drives CDO.

The order UNISIM shows is recorded here by Task B6 of the unit playbook, for each model
source (`unisim-2025.2`, `unisim-gh-2020.1`):

- the INIT bit CDI enters: (to be recorded)
- the INIT bit on CDO: (to be recorded)

## Analysis

The golden model infers that CDI enters INIT[0], that each shift moves INIT[i] to
INIT[i+1], and that INIT[31] drives CDO. The inference is tagged `inferred:`. Rulings S52
and S53: an output whose value depends on it credits no claim; CFGLUT5.C3/C5/C7 are
credited only where the contents are known to be uniform whatever the direction (uniform
since power-on with equal bits shifted in, or after 32 equal shifts). This finding stays open until the documentation
states the direction, whatever UNISIM shows.
```

- [ ] **Step 5: Refresh the stubs, commit, log** (Task A1, Steps 5–6): `luts: add catalog overrides with behavioural claims for LUT1-LUT6, LUT6_2, CFGLUT5`, then `luts: add doc-gap findings for CFGLUT5's undocumented bit order (ruling S52)` (`git add findings/CFGLUT5-*.md`), then `log/<ts>-unit-7series-luts-claims.md` with the intake above.

---

### Task B2: Golden models (Task A2)

**Files:**
- Create: `models/xut_models/7series/_common/luts.py`, `models/xut_models/7series/{lut1,lut2,lut3,lut4,lut5,lut6,lut6_2,cfglut5}.py`
- Create: `tests/7series/clb/_shared/luts/test_luts_models.py`

**Interfaces:**
- Produces: `_common.luts.Lut` (`N`, `INTRO_PAGE`, `TABLE_PAGE`), `DualLut`, `CfgLut5`; `MODEL` in each primitive module.
- Consumes (tests only): `luts_recipes.KINDS`, `lit`, `ones`, `projection` from Task B3's recipes. Write `luts_recipes.py`'s top part (everything above `class LutDriver`) first, so the model tests can import it; Task B3 completes the file.

Model decisions (the Review Focus 1 items a reviewer checks):

- **LUTn/LUT6_2 outputs are `doc:`**: the table page for an explicit INIT (claim C1, LUT6_2 C1/C2), the Introduction page when INIT was not set (the zero default decides it: claim C2, LUT6_2 C3, never C1). LUT6_2's C4 is hit only for INIT = 64'hFFFFFFFFFFFFFFFE.
- **GSR on a LUT** (decision D6): UG953 names none. While GSR is asserted the table is taken to hold, tagged `inferred:UG953_names_no_GSR_effect_on_a_LUT;...`, and no claim is credited (S44). `L1.gsr_transparent` compares that inference with UNISIM.
- **CFGLUT5 bit order** (decision D5): O6 = INIT[{I4..I0}] as in the LUT5 table (p501); O5 = INIT[{I3..I0}], the lower half, as LUT6_2's O5 is (p509); a shift moves CDI into INIT[0] and INIT[31] drives CDO. Each carries its own `inferred:` reason. Where the loaded contents are all 0 or all 1 the order cannot matter, and the bit is `doc:348`.
- **CFGLUT5 order-free knowledge** (ruling S53, correctness review M1): the model never decides "order-independent" from `contents`, which is computed under the inferred order (INIT=1 plus 31 one-shifts, or INIT=7fffffff plus one, looks all ones only under that order). It tracks `known`, the uniform value the contents hold whatever the order: set at power-on for a uniform INIT; kept by a documented shift of the same value; lost by any other shift, a shift under GSR, or a GSR pulse whose "keep" and "reload INIT" readings could differ; and re-established by 32 equal documented shifts in a row, which replace every bit in any order. A bit is `doc:348` only while `known` is set.
- **CFGLUT5 claims** (rulings S52, S53, S55): a claim is credited only while `known` is set and no GSR inference applies, and (S55, correctness re-review M6) only on an event whose documented outcome depends on the claimed rule: C1/C2 on such a read; C3 (and C7 when inverted) on the CE-High active edge that sets `known` to a **new** value (shifting the value the contents already hold changes nothing a never-shifting model would not show); C4 on a CE-Low active edge whose CDI **differs** from `known` (with an equal CDI, a CE-ignoring model shows the same bits); C5 on a CDO read after a 32-shift run that **flipped** `known` (a stuck CDO would still show the old value); C6 at power-on for a uniform INIT (the all-zeroes default included). Every other read is exercised, tagged `inferred:`, and credits nothing. **Every claim has a pure configuration** (all samples order-free): `L1.edge_polarity` credits C1–C7 and both `IS_CLK_INVERTED` bins, and `L1.default_init` C1/C2/C6; so `coverage.uncovered` stays empty whatever order UNISIM shows, unless a documented bit fails. None moves to `gaps`.
- **CFGLUT5 under GSR** (decision D6): UG953 names no GSR effect. The loaded function is taken to be kept and CE shifts to continue. Every output whose value depends on that inference (GSR asserted, or a GSR pulse that met contents different from INIT, until 32 later documented shifts have replaced every bit) carries `inferred:UG953_names_no_GSR_effect_on_CFGLUT5;...` and credits nothing.

- [ ] **Step 1: Write the failing tests** `tests/7series/clb/_shared/luts/test_luts_models.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Claim-by-claim tests of the luts golden models (clean-room, UG953 v2026.1).

The page numbers are literals here, never read from the model, so a wrong ``PAGE`` in a
model fails a test (step-2 review mutant M6).
"""

import random

import pytest
from luts_recipes import KINDS, ones, projection
from luts_recipes import lit as _lit

from xut_models.base import ModelContractError, ModelUnsupported
from xut_models.registry import get

LUTN = [f"LUT{n}" for n in range(1, 7)]
#: prim -> (Introduction page: the zero default, Logic Table page)
PAGES = {
    "LUT1": (488, 489),
    "LUT2": (491, 492),
    "LUT3": (494, 495),
    "LUT4": (497, 498),
    "LUT5": (500, 501),
    "LUT6": (504, 504),
    "LUT6_2": (509, 510),
}


def fresh(prim, **attrs):
    m = get("7series", prim)(attrs)
    m.power_on()
    for p in m.inputs():
        if p not in m.CLOCKS:
            m.set_input(p, 0)
    m.glbl("GSR", 0)
    return m


def drive(m, n, a):
    for i in range(n):
        m.set_input(f"I{i}", (a >> i) & 1)


def lit(prim, v):
    return _lit(KINDS[prim], v)


@pytest.mark.parametrize("prim", LUTN)
def test_c1_logic_table_every_address(prim):
    k = KINDS[prim]
    init = random.Random(prim).getrandbits(k.width)
    m = fresh(prim, INIT=lit(prim, init))
    for a in range(1 << k.n):
        drive(m, k.n, a)
        o = m.outputs()["O"]
        assert o.bits == str((init >> a) & 1), a
        assert o.prov == f"doc:{PAGES[prim][1]}"
    assert m.claims_hit == {f"{prim}.C1"}


@pytest.mark.parametrize(("prim", "j"), [(p, j) for p in LUTN for j in range(KINDS[p].n)])
def test_c1_input_order_projection(prim, j):
    k = KINDS[prim]
    m = fresh(prim, INIT=lit(prim, projection(k, j)))
    for a in range(1 << k.n):
        drive(m, k.n, a)
        assert m.outputs()["O"].bits == str((a >> j) & 1)


@pytest.mark.parametrize("prim", LUTN)
def test_c2_default_is_ground(prim):
    k = KINDS[prim]
    m = fresh(prim)
    for a in range(1 << k.n):
        drive(m, k.n, a)
        o = m.outputs()["O"]
        assert (o.bits, o.prov) == ("0", f"doc:{PAGES[prim][0]}")
    assert m.claims_hit == {f"{prim}.C2"}  # never C1: the default decided it


@pytest.mark.parametrize("prim", LUTN)
def test_explicit_zero_is_c1_not_c2(prim):
    m = fresh(prim, INIT=lit(prim, 0))
    assert m.outputs()["O"].bits == "0"
    assert m.claims_hit == {f"{prim}.C1"}


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2"])
def test_gsr_is_inferred_and_credits_nothing(prim):
    k = KINDS[prim]
    m = fresh(prim, INIT=lit(prim, ones(k)))
    m.glbl("GSR", 1)
    for a in range(1 << k.n):
        drive(m, k.n, a)
        for o in m.outputs().values():
            assert o.bits == "1" and o.prov.startswith("inferred:")
    assert m.claims_hit == set()
    m.glbl("GSR", 0)
    assert all(o.prov.startswith("doc:") for o in m.outputs().values())


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2", "CFGLUT5"])
def test_guards(prim):
    m = get("7series", prim)({})
    for call in (lambda: m.outputs(), lambda: m.set_input("I0", 1), lambda: m.glbl("GSR", 0)):
        with pytest.raises(ModelContractError):
            call()
    m.power_on()
    with pytest.raises(ModelContractError):
        m.set_input("I9", 0)
    with pytest.raises(ModelContractError):
        m.set_input("I0", 2)
    with pytest.raises(ModelUnsupported):
        m.glbl("GTS", 1)


def test_cfglut5_clock_edge_guards():
    m = get("7series", "CFGLUT5")({})
    with pytest.raises(ModelContractError):
        m.clock_edge("CLK", True)  # before power_on
    m.power_on()
    with pytest.raises(ModelContractError):
        m.clock_edge("CE", True)  # not a clock port
    with pytest.raises(ModelContractError):
        m.set_input("CLK", 1)  # a clock is driven with clock_edge


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2", "CFGLUT5"])
def test_init_wider_than_the_table_is_a_contract_error(prim):
    k = KINDS[prim]
    with pytest.raises(ModelContractError):
        get("7series", prim)({"INIT": 1 << k.width})


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2"])
def test_a_lut_has_no_clock(prim):
    with pytest.raises(ModelContractError):
        fresh(prim).clock_edge("C", True)


# -- LUT6_2 ------------------------------------------------------------------------------


def test_lut6_2_c1_c2_o6_full_o5_lower_half_ignoring_i5():
    init = random.Random("LUT6_2").getrandbits(64)
    m = fresh("LUT6_2", INIT=lit("LUT6_2", init))
    for a in range(64):
        drive(m, 6, a)
        out = m.outputs()
        assert out["O6"].bits == str((init >> a) & 1)
        assert out["O5"].bits == str((init >> (a & 31)) & 1)
        assert out["O5"].prov == out["O6"].prov == "doc:510"
    assert m.claims_hit == {"LUT6_2.C1", "LUT6_2.C2"}


def test_lut6_2_c3_default_and_c4_example():
    m = fresh("LUT6_2")
    assert {o.bits for o in m.outputs().values()} == {"0"}
    assert m.claims_hit == {"LUT6_2.C3"}
    m = fresh("LUT6_2", INIT="64'hFFFFFFFFFFFFFFFE")
    for a in range(64):
        drive(m, 6, a)
        out = m.outputs()
        assert out["O6"].bits == str(int(a != 0))  # 6-input OR
        assert out["O5"].bits == str(int(a & 31 != 0))  # 5-input OR of I4-I0
    assert m.claims_hit == {"LUT6_2.C1", "LUT6_2.C2", "LUT6_2.C4"}


def test_lut6_2_c4_not_hit_for_another_init():
    m = fresh("LUT6_2", INIT="64'hFFFFFFFFFFFFFFFC")
    m.outputs()
    assert "LUT6_2.C4" not in m.claims_hit


# -- CFGLUT5 -----------------------------------------------------------------------------

NON_UNIFORM = 0x1234_5678  # a pattern whose reads depend on the inferred bit order
ONES = 0xFFFF_FFFF


def cfg(init=None, **attrs):
    if init is not None:
        attrs["INIT"] = lit("CFGLUT5", init)
    return fresh("CFGLUT5", **attrs)


def edge(m, rising):
    m.clock_edge("CLK", rising)


def shift(m, bits, ce=1):
    """One full CLK cycle (rise, then fall) per bit, CE held; CE Low afterwards."""
    m.set_input("CE", ce)
    for b in bits:
        m.set_input("CDI", b)
        edge(m, True)
        edge(m, False)
    m.set_input("CE", 0)


def load(m, value):
    shift(m, [(value >> i) & 1 for i in reversed(range(32))])


def table(m):
    out = []
    for a in range(32):
        drive(m, 5, a)
        o = m.outputs()
        out.append((o["O6"].bits, o["O5"].bits))
    return out


def provs(m):
    return {o.prov for o in m.outputs().values()}


def test_cfglut5_non_uniform_power_on_is_read_but_credits_nothing():
    """S52: the reads follow the inferred order (C1/C2 are exercised) but credit nothing,
    and nor does power-on (C6): every value observed depends on the order."""
    init = random.Random("CFGLUT5").getrandbits(32) | 1  # never uniform
    m = cfg(init)
    for a, (o6, o5) in enumerate(table(m)):
        assert o6 == str((init >> a) & 1) and o5 == str((init >> (a & 15)) & 1)
    assert m.outputs()["O6"].prov.startswith("inferred:CFGLUT5_p348")
    assert m.claims_hit == set()


@pytest.mark.parametrize(("init", "bit"), [(0, "0"), (ONES, "1"), (None, "0")])
def test_cfglut5_uniform_contents_are_documented_and_credit_c1_c2_c6(init, bit):
    m = cfg(init)  # None: INIT unset, the all-zeroes default (p349)
    assert m.claims_hit == {"CFGLUT5.C6"}
    for o6, o5 in table(m):
        assert (o6, o5) == (bit, bit)
    for o in m.outputs().values():
        assert (o.bits, o.prov) == (bit, "doc:348")
    assert m.claims_hit == {"CFGLUT5.C1", "CFGLUT5.C2", "CFGLUT5.C6"}  # no C5: no shift yet


def test_cfglut5_31_ones_after_init_1_is_not_known_uniform():
    """Correctness review M1, counterexample 1: INIT=1 then 31 ones is all ones only under
    the inferred order (the other direction leaves 0xFFFFFFFE)."""
    m = cfg(1)
    shift(m, [1] * 31)
    assert m.contents == ONES and m.known is None
    assert provs(m) == {
        "inferred:CFGLUT5_p348_cites_O5/O6_tables_it_does_not_contain;"
        "O6_is_INIT[{I4..I0}]_as_in_the_LUT5_logic_table_(p501)",
        "inferred:O5_is_the_4-LUT_output_(p348);"
        "O5_is_INIT[{I3..I0}]_(the_lower_half)_as_for_LUT6_2's_O5_(p509)",
        "inferred:p348_gives_no_shift_direction;CDI_enters_INIT[0]_and_INIT[31]_drives_CDO",
    }
    assert m.claims_hit == set()


def test_cfglut5_one_shift_into_7fffffff_credits_nothing():
    """Counterexample 2: INIT=7fffffff then one 1 (the other direction gives bfffffff);
    a following CE-Low edge credits no C4 either."""
    m = cfg(0x7FFF_FFFF)
    shift(m, [1])
    assert m.contents == ONES and m.known is None
    table(m)
    edge(m, True)
    edge(m, False)
    assert m.claims_hit == set()


def test_cfglut5_32_equal_shifts_make_any_contents_known_uniform():
    m = cfg(NON_UNIFORM)
    shift(m, [1] * 31)
    assert m.known is None and m.claims_hit == set()
    shift(m, [1])
    assert m.known == 1 and "CFGLUT5.C3" in m.claims_hit
    assert {o.bits for o in m.outputs().values()} == {"1"}
    assert provs(m) == {"doc:348"}
    assert {"CFGLUT5.C1", "CFGLUT5.C2"} <= m.claims_hit
    # no C5: CDO's old value was not known, so a stuck CDO might agree (ruling S55)
    assert "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_same_value_shift_credits_no_c3_or_c7():
    """S55: shifting the value the contents already hold changes nothing observable."""
    for inverted in (0, 1):
        m = cfg(ONES, IS_CLK_INVERTED=f"1'b{inverted}")
        m.claims_hit.clear()
        shift(m, [1] * 40)
        assert m.known == 1 and m.shifts == 40
        assert not {"CFGLUT5.C3", "CFGLUT5.C7"} & m.claims_hit


def test_cfglut5_ce_low_edge_with_cdi_equal_to_known_credits_no_c4():
    m = cfg(ONES)
    m.claims_hit.clear()
    m.set_input("CE", 0)
    m.set_input("CDI", 1)  # equal to the contents: ignoring CE would show nothing
    edge(m, True)
    assert "CFGLUT5.C4" not in m.claims_hit
    m.set_input("CDI", 0)  # opposite: ignoring CE would flip a documented bit
    edge(m, False)
    edge(m, True)
    assert m.claims_hit == {"CFGLUT5.C4"}


def test_cfglut5_32_same_value_shifts_credit_no_c5():
    m = cfg(0)
    shift(m, [0] * 32)
    m.outputs()
    assert m.known == 0 and "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_c3_c5_credit_on_the_flip_to_the_opposite_uniform_value():
    m = cfg(0)
    shift(m, [1] * 31)
    assert m.claims_hit == {"CFGLUT5.C6"}  # still order-dependent: nothing yet
    shift(m, [1])
    m.outputs()
    assert {"CFGLUT5.C3", "CFGLUT5.C5"} <= m.claims_hit


def test_cfglut5_an_opposite_bit_loses_known_uniform():
    m = cfg(ONES)
    shift(m, [1, 1])
    assert m.known == 1  # equal bits keep it
    shift(m, [0])
    assert m.known is None and m.outputs()["O6"].prov != "doc:348"


def test_cfglut5_reload_to_non_uniform_credits_no_c3():
    m = cfg(0xF0F0_F0F0)
    load(m, NON_UNIFORM)
    assert [o6 for o6, _ in table(m)] == [str((NON_UNIFORM >> a) & 1) for a in range(32)]
    assert m.claims_hit == set()


@pytest.mark.parametrize(("init", "credited"), [(ONES, True), (NON_UNIFORM, False)])
def test_cfglut5_c4_ce_low_holds_credited_only_when_known_uniform(init, credited):
    m = cfg(init)
    before = table(m)
    m.claims_hit.clear()
    m.set_input("CE", 0)
    for b in (1, 0, 1):
        m.set_input("CDI", b)
        edge(m, True)
        edge(m, False)
    assert m.claims_hit == ({"CFGLUT5.C4"} if credited else set())
    assert table(m) == before


@pytest.mark.parametrize("inverted", [0, 1])
def test_cfglut5_inactive_edge_with_ce_high_changes_nothing(inverted):
    """Correctness review M3: from known-uniform contents, the inactive edge with CE High
    and the opposite CDI leaves every address and CDO at the old value, doc:348."""
    m = cfg(0, IS_CLK_INVERTED=f"1'b{inverted}")
    if inverted:  # the inactive edge is the rise
        m.set_input("CE", 1)
        m.set_input("CDI", 1)
        edge(m, True)
    else:  # the inactive edge is the fall: rise first with CE Low
        edge(m, True)
        m.set_input("CE", 1)
        m.set_input("CDI", 1)
        edge(m, False)
    m.set_input("CE", 0)
    assert m.shifts == 0 and m.known == 0
    assert set(table(m)) == {("0", "0")} and provs(m) == {"doc:348"}


def test_cfglut5_c7_falling_edge_only():
    m = cfg(0, IS_CLK_INVERTED="1'b1")
    m.set_input("CE", 1)
    m.set_input("CDI", 1)
    edge(m, True)
    assert m.shifts == 0
    for _ in range(31):
        edge(m, False)
        edge(m, True)
    assert "CFGLUT5.C7" not in m.claims_hit  # 31 shifts: a mix, order-dependent
    edge(m, False)  # the 32nd: all ones, whatever the order
    assert m.known == 1 and m.outputs()["O6"].bits == "1"
    assert {"CFGLUT5.C3", "CFGLUT5.C7", "CFGLUT5.C5"} <= m.claims_hit


def test_cfglut5_cdo_order_is_inferred_and_random_data_credits_nothing():
    bits = [random.Random(i).randrange(2) for i in range(64)]
    m = cfg(NON_UNIFORM)
    m.set_input("CE", 1)
    seen = []
    for b in bits:
        m.set_input("CDI", b)
        edge(m, True)
        edge(m, False)
        seen.append(m.outputs()["CDO"].bits)
    old = [str((NON_UNIFORM >> i) & 1) for i in reversed(range(31))]  # INIT[30]..INIT[0]
    assert seen[:31] == old  # the inferred order (D5)
    assert seen[31:] == [str(b) for b in bits[:33]]
    assert "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_c5_not_hit_before_32_shifts():
    m = cfg(ONES)
    shift(m, [1] * 31)  # known-uniform all along, but no CDI bit has reached CDO yet
    m.outputs()
    assert m.known == 1 and "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_gsr_after_reload_is_inferred_until_32_more_shifts():
    m = cfg(NON_UNIFORM)
    load(m, 0xFFFF_0000)
    m.claims_hit.clear()
    m.glbl("GSR", 1)
    m.glbl("GSR", 0)
    assert table(m)[16] == ("1", "0")  # kept, not reloaded (inferred)
    assert all(o.prov.startswith("inferred:UG953_names_no_GSR") for o in m.outputs().values())
    shift(m, [0] * 31)
    assert m.outputs()["O6"].prov.startswith("inferred:UG953_names_no_GSR")
    assert m.claims_hit == set()  # S44: an inferred rule credits nothing
    shift(m, [0])
    assert provs(m) == {"doc:348"}  # 32 equal shifts: all zero whatever happened
    assert "CFGLUT5.C3" in m.claims_hit


def test_cfglut5_gsr_needs_no_gsr_inference_while_untouched():
    """No shift since power-on: "keep" and "reload INIT" agree, so no GSR tag."""
    m = cfg(0x0F0F_0F0F)
    m.glbl("GSR", 1)
    m.glbl("GSR", 0)
    assert not m.outputs()["O6"].prov.startswith("inferred:UG953_names_no_GSR")


def test_cfglut5_gsr_needs_no_gsr_inference_for_init_s_own_uniform_value():
    m = cfg(ONES)
    shift(m, [1] * 3)
    m.glbl("GSR", 1)
    m.glbl("GSR", 0)
    assert provs(m) == {"doc:348"}


def test_cfglut5_shift_under_gsr_credits_nothing():
    m = cfg(0)
    m.glbl("GSR", 1)
    m.claims_hit.clear()
    shift(m, [0])  # stays uniform, but under GSR: an inference decides it
    m.glbl("GSR", 0)
    assert m.claims_hit == set()
    assert m.outputs()["O6"].prov.startswith("inferred:UG953_names_no_GSR")
```

Run it (Task A2, Step 1). Expected: every test fails with `LookupError: no golden model for 7series/<PRIM>`.

- [ ] **Step 2: Write `models/xut_models/7series/_common/luts.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Clean-room golden models of the 7-series LUTs: LUT1-LUT6, LUT6_2 and CFGLUT5.

Written from UG953 v2026.1 only (CFGLUT5 pp. 348-349, LUT1 pp. 488-489, LUT2 pp. 491-492,
LUT3 pp. 494-495, LUT4 pp. 497-499, LUT5 pp. 500-502, LUT6 pp. 504-507, LUT6_2
pp. 509-512); no UNISIM source was consulted. Claim numbers match
catalog/7series/<PRIM>.overrides.yaml:

  LUTn    C1 logic table: O = INIT[{I<n-1>..I0}]    C2 INIT defaults to 0: O = 0
  LUT6_2  C1 O6 = INIT[{I5..I0}]    C2 O5 = INIT[{I4..I0}] (lower half; I5 unused)
          C3 INIT defaults to 0     C4 the p509 example 64'hFFFFFFFFFFFFFFFE (two ORs)
  CFGLUT5 C1 O6 follows the loaded INIT and I0-I4   C2 O5 is the 4-LUT output
          C3 CE High: an active CLK edge shifts CDI in   C4 CE Low: INIT unchanged
          C5 CDO cascades the shifted data (32 bits per LUT)
          C6 INIT is the start-up function   C7 IS_CLK_INVERTED=1: falling edge active

Provenance (AGENTS.md §8, spec §3):
- The LUTn and LUT6_2 logic tables are complete, so their outputs are ``doc:``.
- UG953 names no GSR effect on any LUT. While GSR is asserted a LUT keeps following its
  logic table, tagged ``inferred:`` (_GSR_LUT); that output credits no claim (ruling S44).
- The CFGLUT5 section refers to O5/O6 tables it does not contain and gives no shift
  direction, so the bit order is inferred (_O6_ORDER, _O5_ORDER, _SHIFT) and those bits
  are ``inferred:`` (a disagreement is a doc-gap).
- Ruling S52 (after S44): an output whose value depends on the inferred order credits no
  claim, even under a documented rule. The model therefore tracks what it knows
  *whatever the order*: the contents are known-uniform (all 0 or all 1) only when they
  were uniform at power-on and every bit shifted in since equals that value, or when the
  last 32 documented shifts all carried one value. Only then is a CFGLUT5 bit ``doc:348``
  and a CFGLUT5 claim credited; the contents computed under the inferred order are never
  used to decide that (ruling S53, correctness review M1).
- Ruling S55 (the general form of S32): a claim credits only on an event whose observable
  outcome depends on the claimed rule, i.e. a model that breaks the rule would show a
  different documented bit there. So C3/C7 credit only on the edge that sets ``known`` to a
  new value (a shift that changes nothing observable proves nothing), C4 only on a CE-Low
  edge whose CDI differs from ``known``, and C5 only on a CDO read after a 32-shift run
  flipped ``known`` from one uniform value to the other.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from xut_models.base import Model, ModelContractError, ModelUnsupported, Out, bit_attr

_GSR_LUT = (
    "inferred:UG953_names_no_GSR_effect_on_a_LUT;"
    "the_logic_table_is_taken_to_hold_while_GSR_is_asserted"
)
_O6_ORDER = (
    "inferred:CFGLUT5_p348_cites_O5/O6_tables_it_does_not_contain;"
    "O6_is_INIT[{I4..I0}]_as_in_the_LUT5_logic_table_(p501)"
)
_O5_ORDER = (
    "inferred:O5_is_the_4-LUT_output_(p348);"
    "O5_is_INIT[{I3..I0}]_(the_lower_half)_as_for_LUT6_2's_O5_(p509)"
)
_SHIFT = "inferred:p348_gives_no_shift_direction;CDI_enters_INIT[0]_and_INIT[31]_drives_CDO"
_GSR_CFG = (
    "inferred:UG953_names_no_GSR_effect_on_CFGLUT5;"
    "the_loaded_function_is_taken_to_be_kept_and_CE_shifts_to_continue"
)


def _init_value(prim: str, attrs: Mapping[str, str | int], width: int) -> int:
    v = bit_attr(attrs.get("INIT", 0))
    if not 0 <= v < 1 << width:
        raise ModelContractError(f"{prim}: INIT={attrs.get('INIT')!r} does not fit {width} bits")
    return v


class _Powered(Model):
    """Shared guards: the model API is used only after ``power_on`` (step-2 review R5)."""

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        super().__init__(attrs)
        self.pin = dict.fromkeys(self.inputs(), 0)
        self.gsr = 0
        self._powered_on = False

    def _require_power(self, what: str) -> None:
        if not self._powered_on:
            raise ModelContractError(f"{self.PRIM}: {what} before power_on")

    def _address(self, n: int) -> int:
        return sum(self.pin[f"I{i}"] << i for i in range(n))

    def power_on(self) -> None:
        self._powered_on = True
        self.gsr = 1

    def glbl(self, signal: str, value: int) -> None:
        self._require_power("glbl")
        if signal != "GSR":
            raise ModelUnsupported(f"{self.PRIM}: UG953 describes no {signal} effect")
        self.gsr = value

    def set_input(self, port: str, value: int) -> None:
        self._require_power("set_input")
        if port not in self.pin or port in self.CLOCKS:
            raise ModelContractError(f"{self.PRIM}: not a data input port: {port!r}")
        if value not in (0, 1):
            raise ModelContractError(f"{self.PRIM}: {port}={value!r} is not 0 or 1")
        self.pin[port] = value


class Lut(_Powered):
    """LUT1-LUT6: one output, O = INIT[{I<N-1>..I0}] (the logic table)."""

    N: ClassVar[int]  # number of inputs
    INTRO_PAGE: ClassVar[int]  # Introduction: INIT defaults to zero (a ground)
    TABLE_PAGE: ClassVar[int]  # Logic Table
    OUTPUTS: ClassVar[dict[str, int]] = {"O": 1}

    @classmethod
    def inputs(cls) -> dict[str, int]:
        return {f"I{i}": 1 for i in range(cls.N)}

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        super().__init__(attrs)
        self.explicit_init = "INIT" in self.attrs
        self.init = _init_value(self.PRIM, self.attrs, 1 << self.N)

    def clock_edge(self, port: str, rising: bool) -> None:
        raise ModelContractError(f"{self.PRIM} has no clock: {port!r}")

    def _lookup(self, n: int, claim: int, default_claim: int) -> Out:
        """INIT bit ``{I<n-1>..I0}``: ``claim`` for an explicit INIT, ``default_claim``
        when INIT was not set (the documented zero default decides the bit)."""
        bit = str((self.init >> self._address(n)) & 1)
        if self.gsr:
            return Out(bit, _GSR_LUT)  # inferred: no claim (ruling S44)
        if not self.explicit_init:
            self.hit(f"{self.PRIM}.C{default_claim}")
            return Out(bit, f"doc:{self.INTRO_PAGE}")
        self.hit(f"{self.PRIM}.C{claim}")
        return Out(bit, f"doc:{self.TABLE_PAGE}")

    def outputs(self) -> dict[str, Out]:
        self._require_power("outputs")
        return {"O": self._lookup(self.N, 1, 2)}


class DualLut(Lut):
    """LUT6_2: O6 = INIT[{I5..I0}], O5 = INIT[{I4..I0}] (p509-510)."""

    N = 6
    OUTPUTS: ClassVar[dict[str, int]] = {"O5": 1, "O6": 1}
    OR_EXAMPLE: ClassVar[int] = 0xFFFF_FFFF_FFFF_FFFE  # p509

    def outputs(self) -> dict[str, Out]:
        self._require_power("outputs")
        o6 = self._lookup(6, 1, 3)
        o5 = self._lookup(5, 2, 3)
        if self.explicit_init and self.init == self.OR_EXAMPLE and not self.gsr:
            self.hit(f"{self.PRIM}.C4")
        return {"O5": o5, "O6": o6}


def _uniform_bit(value: int, width: int) -> int | None:
    """0 or 1 when ``value`` is all 0 or all 1 over ``width`` bits, else None."""
    return 0 if value == 0 else 1 if value == (1 << width) - 1 else None


class CfgLut5(_Powered):
    """CFGLUT5: a 32-bit INIT, read like a LUT5 (O6) and a LUT4 (O5), reloaded serially
    from CDI while CE is High, one bit per active CLK edge (p348-349)."""

    PAGE: ClassVar[int] = 348  # Introduction and ports: every CFGLUT5 doc: bit
    CLOCKS: ClassVar[tuple[str, ...]] = ("CLK",)
    OUTPUTS: ClassVar[dict[str, int]] = {"CDO": 1, "O5": 1, "O6": 1}
    WIDTH: ClassVar[int] = 32

    @classmethod
    def inputs(cls) -> dict[str, int]:
        return {"CDI": 1, "CE": 1, "CLK": 1, **{f"I{i}": 1 for i in range(5)}}

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        super().__init__(attrs)
        self.init = _init_value(self.PRIM, self.attrs, self.WIDTH)
        self.inv_clk = bit_attr(self.attrs.get("IS_CLK_INVERTED", 0))
        self.contents = self.init  # under the inferred order (D5)
        self.shifts = 0  # documented shifts since power-on (none under GSR)
        #: the uniform value the contents hold whatever the shift order, or None
        self.known: int | None = None
        #: (value, count) of the latest run of equal documented shifts, and the ``known``
        #: value when that run started
        self._run: tuple[int | None, int] = (None, 0)
        self._run_from: int | None = None
        #: CDO now shows a bit a 32-shift run carried in over the opposite uniform value
        self._cascaded = False
        self._untouched = True  # no shift at all since power-on
        #: the contents depend on the GSR inference until 32 later documented shifts
        #: have replaced every bit (-1: never; else the shift count at that moment)
        self._gsr_mark = -1

    # -- helpers -----------------------------------------------------------------------
    def _gsr_dependent(self) -> bool:
        return self.gsr == 1 or (self._gsr_mark >= 0 and self.shifts - self._gsr_mark < self.WIDTH)

    def _order_free(self) -> bool:
        """What an output shows cannot depend on the inferred order (ruling S52)."""
        return self.known is not None and not self._gsr_dependent()

    def _credit(self, claim: int) -> None:
        if self._order_free():
            self.hit(f"{self.PRIM}.C{claim}")

    def _read(self, index: int, order: str, claim: int | None) -> Out:
        bit = str((self.contents >> index) & 1)
        if self._gsr_dependent():
            return Out(bit, _GSR_CFG)  # an inferred rule decides it: no claim (S44)
        if claim is not None:
            self._credit(claim)
        return Out(bit, f"doc:{self.PAGE}" if self.known is not None else order)

    def _lose_order_free_state(self) -> None:
        self.known = None
        self._run = (None, 0)
        self._run_from = None
        self._cascaded = False

    # -- Model API ---------------------------------------------------------------------
    def power_on(self) -> None:
        super().power_on()
        self.contents = self.init
        self.known = _uniform_bit(self.init, self.WIDTH)
        if self.known is not None:  # INIT is the start-up function (p349); uniform only
            self.hit(f"{self.PRIM}.C6")

    def glbl(self, signal: str, value: int) -> None:
        super().glbl(signal, value)
        if not value:
            return
        # "keep the contents" and "reload INIT" agree only if nothing was shifted since
        # power-on, or the contents are known-uniform with INIT's own uniform value.
        same = self._untouched or (
            self.known is not None and self.known == _uniform_bit(self.init, self.WIDTH)
        )
        if not same:
            self._gsr_mark = self.shifts
            self._lose_order_free_state()

    def clock_edge(self, port: str, rising: bool) -> None:
        self._require_power("clock_edge")
        if port not in self.CLOCKS:
            raise ModelContractError(f"{self.PRIM}: not a clock port: {port!r}")
        if rising == bool(self.inv_clk):
            return  # not the active edge
        if not self.pin["CE"]:
            if self.known is not None and self.pin["CDI"] != self.known:
                self._credit(4)  # CE Low held back a shift that would have shown (S55)
            return
        cdi = self.pin["CDI"]
        self.contents = ((self.contents << 1) | cdi) & ((1 << self.WIDTH) - 1)
        self._untouched = False
        if self.gsr:
            self._gsr_mark = self.shifts  # shifting under GSR is itself an inference
            self._lose_order_free_state()
            return
        self.shifts += 1
        before = self.known
        value, count = self._run
        if value != cdi:
            self._run_from = before  # a new run starts from this order-free state
        self._run = (cdi, count + 1 if value == cdi else 1)
        if self.known is not None and cdi != self.known:
            self.known = None
            self._cascaded = False
        if self._run[1] >= self.WIDTH:
            self.known = cdi  # 32 equal shifts replace every bit, whatever the order
        if self.known is not None and before != self.known:
            # the shift that made the new uniform value certain: a model that did not
            # shift, or shifted on the wrong edge, shows the old contents here (S55)
            self._credit(3)
            if self.inv_clk:
                self._credit(7)
            if self._run_from is not None and self._run_from != cdi:
                self._cascaded = True  # CDO flipped from the old uniform value

    def outputs(self) -> dict[str, Out]:
        self._require_power("outputs")
        # C5 is the cascade: CDO now carries a bit that came in on CDI (32 bits per LUT) and
        # differs from what the loaded contents showed, so a stuck CDO would fail (S55).
        cascade = 5 if self._cascaded else None
        return {
            "CDO": self._read(self.WIDTH - 1, _SHIFT, cascade),
            "O5": self._read(self._address(4), _O5_ORDER, 2),
            "O6": self._read(self._address(5), _O6_ORDER, 1),
        }
```

- [ ] **Step 3: Write the eight primitive modules**

`models/xut_models/7series/lut1.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""LUT1 golden model: UG953 v2026.1 pp. 488-489 (clean-room)."""

from ._common.luts import Lut


class LUT1(Lut):
    PRIM = "LUT1"
    N = 1
    INTRO_PAGE = 488  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 489  # Logic Table


MODEL = LUT1
```

`models/xut_models/7series/lut2.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""LUT2 golden model: UG953 v2026.1 pp. 491-492 (clean-room)."""

from ._common.luts import Lut


class LUT2(Lut):
    PRIM = "LUT2"
    N = 2
    INTRO_PAGE = 491  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 492  # Logic Table


MODEL = LUT2
```

`models/xut_models/7series/lut3.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""LUT3 golden model: UG953 v2026.1 pp. 494-495 (clean-room)."""

from ._common.luts import Lut


class LUT3(Lut):
    PRIM = "LUT3"
    N = 3
    INTRO_PAGE = 494  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 495  # Logic Table


MODEL = LUT3
```

`models/xut_models/7series/lut4.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""LUT4 golden model: UG953 v2026.1 pp. 497-499 (clean-room)."""

from ._common.luts import Lut


class LUT4(Lut):
    PRIM = "LUT4"
    N = 4
    INTRO_PAGE = 497  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 498  # Logic Table


MODEL = LUT4
```

`models/xut_models/7series/lut5.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""LUT5 golden model: UG953 v2026.1 pp. 500-502 (clean-room)."""

from ._common.luts import Lut


class LUT5(Lut):
    PRIM = "LUT5"
    N = 5
    INTRO_PAGE = 500  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 501  # Logic Table


MODEL = LUT5
```

`models/xut_models/7series/lut6.py` (the logic table runs over pp. 504–506; the Introduction and the table's first rows share p504):

```python
# SPDX-License-Identifier: Apache-2.0
"""LUT6 golden model: UG953 v2026.1 pp. 504-507 (clean-room)."""

from ._common.luts import Lut


class LUT6(Lut):
    PRIM = "LUT6"
    N = 6
    INTRO_PAGE = 504  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 504  # Logic Table


MODEL = LUT6
```

`models/xut_models/7series/lut6_2.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""LUT6_2 golden model: UG953 v2026.1 pp. 509-512 (clean-room)."""

from ._common.luts import DualLut


class LUT6_2(DualLut):  # noqa: N801 - the primitive's own name
    PRIM = "LUT6_2"
    INTRO_PAGE = 509  # the zero default, the lower half feeding O5, the OR example
    TABLE_PAGE = 510  # Logic Table (pp. 510-511)


MODEL = LUT6_2
```

`models/xut_models/7series/cfglut5.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""CFGLUT5 golden model: UG953 v2026.1 pp. 348-349 (clean-room)."""

from ._common.luts import CfgLut5


class CFGLUT5(CfgLut5):
    PRIM = "CFGLUT5"


MODEL = CFGLUT5
```

- [ ] **Step 4: Run the tests and lint** (Task A2, Step 3). Expected: `97 passed`, no skips; ruff clean. Four tests pin ruling S55's deciding events: a same-value shift credits no C3/C7, a CE-Low edge with CDI equal to the contents credits no C4, 32 same-value shifts credit no C5, and the flip to the opposite uniform value credits C3 and C5.

- [ ] **Step 5: Commit** the models with the file their tests import (the top part of `luts_recipes.py`):

```bash
git add models/xut_models/7series tests/7series/clb/_shared/luts/test_luts_models.py tests/7series/clb/_shared/luts/luts_recipes.py && git commit -m "luts: add clean-room LUT1-LUT6, LUT6_2 and CFGLUT5 golden models (UG953 pp. 348-349, 488-512)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git status --porcelain > .cache/git-status.log 2>&1; cat .cache/git-status.log
```

Expected: the commit's own model tests pass at that commit, and `git status` shows nothing under `models/` or `_shared/luts/test_luts_models.py`.

---

### Task B3: Recipes, the file generator and the guards (Task A3)

**Files:**
- Create: `tests/7series/clb/_shared/luts/luts_recipes.py` (complete it), `luts_tests.py`, `test_luts_tests.py`
- Create (generated by `luts_tests.py`, committed): for every primitive `test.yaml`, `README.md`, `vectors/gen.py`, `cocotb/cocotb_<prim>_random.py`, and for LUT1–LUT6/LUT6_2 `sv/tb_<prim>_x.sv`, `sv/tb_<prim>_gsr.sv`

**Interfaces:**
- Produces (`luts_recipes`): `LutKind`, `KINDS`, `BIN`, `RANDOM_INITS` and the other named tuning constants, `lit`, `ones`, `projection`, `init_samples`, `random_inits`, `LutDriver` (`address`, `read`, `sweep`, `walk`), `CfgLutDriver` (`shift`, `load`), the recipes, `generators(prim)`
- Produces (`luts_tests`): `tests_for(kind)`, `render(prim)`, `UNIT`, `main(prims)`, `ROOT`, `GROUP_DIR`
- Consumes: `xut.unitkit` (Task P1)

The recipes, by test. A configuration is read with an exhaustive `sweep` (power-on read at address 0, then 1 … 2^n − 1 in binary order, then back to 0, so every input is driven both ways by a real `set`) unless the row says otherwise. "Pure" marks a configuration whose every sample is order-free (ruling S53: the only CFGLUT5 configurations that can credit a claim whatever UNISIM's order is):

| Test | Primitives | Configurations | What it pins |
|---|---|---|---|
| `L0.smoke` | all | default (INIT unset), all ones, one seeded random; CFGLUT5: both `IS_CLK_INVERTED` values set explicitly, plus one reload bit | elaboration, defaults vs UNISIM defaults; no C3 (one shifted bit never sets a new known value, ruling S55) |
| `L0.illegal_init` | all | INIT with every digit `x` | the runtime reject path (kept only if the simulators reject it: Task A6) |
| `L1.default_init` | all | INIT unset (pure) | the zero default (C2/C3/C6; CFGLUT5 also C1/C2) |
| `L1.projections` | all | INIT with O = I<j>, and its complement, for every input | the logic table's input order (CFGLUT5: the inferred order) |
| `L1.gsr_transparent` | LUT1–LUT6, LUT6_2 | one random INIT; GSR pulsed while inputs move | the D6 inference, `hw` unsupported |
| `L1.o5_lower_half` | LUT6_2 | lower half = I0 projection with upper half = complement; lower 0 / upper 1; random | O5 ignores I5 (C2) |
| `L1.doc_example` | LUT6_2 | 64'hFFFFFFFFFFFFFFFE | UG953's OR example (C4) |
| `L1.edge_polarity` | CFGLUT5 | both `IS_CLK_INVERTED` values × all zeros / all ones (all pure): sweep; the **inactive** edge alone with CE High and the opposite CDI, then sweep and CDO; the active edge with CE Low and the opposite CDI (ruling S55: a CE-ignoring simulator would shift it in); 32 opposite shifts with no read between; sweep | C1–C7 and both `IS_CLK_INVERTED` bins, order-free; a simulator that shifts on both edges, ignores `IS_CLK_INVERTED`, ignores CE, never shifts or has a stuck CDO fails a documented bit |
| `L1.ce_low_holds` | CFGLUT5 | random, I0 projection, all ones (pure); 8 CE-Low cycles with CDI toggling | C4 |
| `L1.reconfigure` | CFGLUT5 | zero → random, ones → I2 projection, random → random, ones → zero (pure); a 32-bit reload between sweeps | C3, C5; the inferred order |
| `L1.cdo_cascade` | CFGLUT5 | random data; all ones then 32 zeros and 32 ones; 64 shifts with CDO sampled after each, then a sweep | C5; the inferred CDO bit |
| `L1.partial_shift` | CFGLUT5 | 1, 5, 16 and 31 shifts | the inferred shift order (doc-gap if wrong) |
| `L1.is_clk_inverted` | CFGLUT5 | `IS_CLK_INVERTED=1'b1`, uniform INITs; samples after every edge | C7, step by step |
| `L1.shift_while_reading` | CFGLUT5 | two random; an address held while 8 bits shift in, 4 times | the function changing in use |
| `L1.gsr_after_reconfig` | CFGLUT5 | reload, GSR, with and without shifts under it | the D6 inference, `hw` unsupported |
| `L2.init_sweep` | all | spec §4.2: every value (≤ 4-bit INIT) or all zeros, all ones, walking ones, walking zeros | every INIT bit alone, set and clear |
| `L2.init_random` | LUT3–LUT6, LUT6_2, CFGLUT5 | 16 seeded random INITs, each swept then read at 2^n random addresses | multi-bit input changes |
| `L2.random` | CFGLUT5 | 8 random INITs × both clock senses; 400 random reloads and reads | ordering effects |

- [ ] **Step 1: Complete `tests/7series/clb/_shared/luts/luts_recipes.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Stimulus recipes shared by the luts work unit (LUT1-LUT6, LUT6_2, CFGLUT5).

Each recipe takes a GenContext and a LutKind and yields .xvec files built with VecBuilder,
so every file satisfies the spec §5.1 class rules by construction. Recipes only drive
inputs and place samples: expected values come from the golden model (python runner).

INIT sampling (spec §4.2, recorded per test in test.yaml ``attr_sampling``):
- an INIT of at most 4 bits (LUT1, LUT2) is covered exhaustively, every value;
- a wider INIT by its boundary values (all 0, all 1) and walking ones and walking zeros
  (every bit position) in L2.init_sweep, and by ``RANDOM_INITS`` seeded random values
  (the test's seed) in L2.init_random;
- every kind also by the input projections (INIT such that O = I<j>, and complements) in
  L1.projections, which pin the logic table's input-to-address order one input at a time.
Configurations are read with an exhaustive sweep of the inputs (``sweep``), except
where a recipe says otherwise (``l1_cdo_cascade`` reads CDO after every shift).

Ruling S52 (CFGLUT5): a read whose value depends on the inferred bit order credits no
claim, and a configuration credits a claim only when it passes on a simulator. So every
CFGLUT5 claim and bin has a *pure* configuration, all of whose samples are
order-independent (known-uniform contents): ``l1_default_init`` and ``l1_edge_polarity``.
The unit's guard ``test_every_exercised_bin_has_a_pure_configuration`` checks it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import partial
from random import Random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xut.formats.xvec import Vec
    from xut.stimgen import GenContext

Gen = Iterator["Vec"]

RANDOM_INITS = 16
#: L2.random (CFGLUT5): configurations, steps per configuration, and the chance that a
#: step is a one-bit reload rather than a read, and that such a reload has CE High
RANDOM_CONFIGS = 8
RANDOM_STEPS = 400
RELOAD_P = 0.4
CE_HIGH_P = 0.8
#: L1.ce_low_holds: the CDI values driven through CE-Low cycles
CE_LOW_CDI = (1, 0, 1, 1, 0, 1, 0, 0)


@dataclass(frozen=True)
class LutKind:
    prim: str
    n: int  # LUT inputs I0..I<n-1>
    width: int  # INIT bits
    outputs: tuple[str, ...]
    reconfig: bool  # CFGLUT5: CDI/CE/CLK reload INIT at run time


KINDS = {
    **{f"LUT{n}": LutKind(f"LUT{n}", n, 1 << n, ("O",), False) for n in range(1, 7)},
    "LUT6_2": LutKind("LUT6_2", 6, 64, ("O5", "O6"), False),
    "CFGLUT5": LutKind("CFGLUT5", 5, 32, ("CDO", "O5", "O6"), True),
}
BIN = ("1'b0", "1'b1")


def lit(k: LutKind, value: int) -> str:
    """``value`` as INIT's sized hex literal (``64'h000000000000000f``)."""
    return f"{k.width}'h{value:0{(k.width + 3) // 4}x}"


def ones(k: LutKind) -> int:
    return (1 << k.width) - 1


def projection(k: LutKind, j: int) -> int:
    """The INIT for which the addressed bit equals input I<j> (O = I<j>)."""
    return sum(1 << a for a in range(1 << k.n) if (a >> j) & 1) & ones(k)


def init_samples(k: LutKind) -> list[tuple[str, int]]:
    """``(name, INIT)`` per spec §4.2: every value of a <= 4-bit INIT; otherwise the
    boundaries, walking ones and walking zeros (``random_inits`` adds the random ones)."""
    if k.width <= 4:
        return [(f"v{v:x}", v) for v in range(1 << k.width)]
    out = [("zeros", 0), ("ones", ones(k))]
    out += [(f"w1_{i}", 1 << i) for i in range(k.width)]
    return out + [(f"w0_{i}", ones(k) ^ (1 << i)) for i in range(k.width)]


def random_inits(k: LutKind, rng: Random) -> list[tuple[str, int]]:
    """RANDOM_INITS distinct seeded random values, none a boundary or walking value."""
    out: list[tuple[str, int]] = []
    seen = {v for _, v in init_samples(k)}
    while len(out) < RANDOM_INITS:
        v = rng.getrandbits(k.width)
        if v not in seen:
            seen.add(v)
            out.append((f"r{len(out)}", v))
    return out


class LutDriver:
    """One configuration of a LUT kind, driven by address."""

    def __init__(self, ctx: GenContext, k: LutKind, cfg: str, **attrs: str) -> None:
        self.k = k
        self.b = ctx.dut(cfg, **attrs)

    def address(self, a: int) -> None:
        """All LUT inputs at once (one atomic input change, ruling S6)."""
        self.b.set(**{f"I{i}": (a >> i) & 1 for i in range(self.k.n)})

    def read(self, a: int) -> None:
        self.address(a)
        self.b.sample()

    def sweep(self) -> None:
        """Every address in binary order, then back to 0: each input is driven both
        ways by a real ``set`` (the power-on 0 does not count, ruling S19)."""
        self.b.sample()  # the power-on read: address 0 with nothing driven yet
        for a in range(1, 1 << self.k.n):
            self.read(a)
        self.read(0)

    def walk(self, rng: Random, steps: int) -> None:
        """Random addresses: several inputs change at once, in random order."""
        for _ in range(steps):
            self.read(rng.randrange(1 << self.k.n))

    def build(self) -> Vec:
        return self.b.build()


class CfgLutDriver(LutDriver):
    """A CFGLUT5 configuration: LUT reads plus serial reloads through CDI/CE/CLK."""

    def shift(self, bits: Iterable[int], *, ce: int = 1, sample: bool = False) -> None:
        """One full CLK cycle per bit (rise, then fall: one active edge whatever
        IS_CLK_INVERTED is), with CE and CDI set before it."""
        for bit in bits:
            self.b.set(CE=ce, CDI=bit)
            self.b.cycle("CLK", sample=sample)

    def load(self, value: int) -> None:
        """Shift in all 32 bits of ``value``, most significant first, then drop CE.
        Under any shift direction, 32 shifts replace the whole INIT (p348: 32 bits per
        LUT); ``value`` ends up in INIT as written only under the model's inferred order."""
        self.shift([(value >> i) & 1 for i in reversed(range(self.k.width))])
        self.b.set(CE=0)


def _config(ctx: GenContext, k: LutKind, cfg: str, init: int | None, **extra: str) -> LutDriver:
    """A driver for one configuration (INIT unset when ``init`` is None)."""
    cls = CfgLutDriver if k.reconfig else LutDriver
    attrs = {} if init is None else {"INIT": lit(k, init)}
    return cls(ctx, k, cfg, **attrs, **extra)


def _cfglut(ctx: GenContext, k: LutKind, cfg: str, init: int, **extra: str) -> CfgLutDriver:
    """A CFGLUT5 driver with an explicit INIT (the CFGLUT5-only recipes)."""
    return CfgLutDriver(ctx, k, cfg, INIT=lit(k, init), **extra)


# -- every kind --------------------------------------------------------------------------


def l0_smoke(ctx: GenContext, k: LutKind) -> Gen:
    """Elaborates with the default and two sampled INITs, one sweep each (CFGLUT5: both
    IS_CLK_INVERTED values set explicitly, and one reload bit)."""
    rnd = ctx.rng.getrandbits(k.width)
    cfgs = [("default", None, {}), ("ones", ones(k), {}), ("rand", rnd, {})]
    if k.reconfig:
        cfgs[1] = ("ones_clk0", ones(k), {"IS_CLK_INVERTED": BIN[0]})
        cfgs[2] = ("rand_clk1", rnd, {"IS_CLK_INVERTED": BIN[1]})
    for cfg, init, extra in cfgs:
        f = _config(ctx, k, cfg, init, **extra)
        f.sweep()
        if isinstance(f, CfgLutDriver):
            f.shift([1], sample=True)
            f.b.set(CE=0, CDI=0)
            f.b.sample()
        yield f.build()


def l0_illegal_init(ctx: GenContext, k: LutKind) -> Gen:
    """INIT with x digits is not a HEX value (UG953 attribute table): expect=reject."""
    b = ctx.dut(
        "init_x",
        allow_illegal=True,
        expect="reject",
        illegal=["INIT"],
        INIT=f"{k.width}'b{'x' * k.width}",
    )
    b.sample()
    yield b.build()


def l1_default_init(ctx: GenContext, k: LutKind) -> Gen:
    f = _config(ctx, k, "default", None)
    f.sweep()
    yield f.build()


def l1_projections(ctx: GenContext, k: LutKind) -> Gen:
    """O = I<j> and O = ~I<j> for every input: a swapped input pair fails at once."""
    for j in range(k.n):
        for name, init in ((f"p{j}", projection(k, j)), (f"n{j}", ones(k) ^ projection(k, j))):
            f = _config(ctx, k, name, init)
            f.sweep()
            yield f.build()


def l1_gsr_transparent(ctx: GenContext, k: LutKind) -> Gen:
    """A GSR pulse while the inputs move: the model infers the table still holds
    (UG953 names no GSR effect on a LUT), so a disagreement is a doc-gap finding."""
    f = _config(ctx, k, "rand", ctx.rng.getrandbits(k.width))
    for a in (0, (1 << k.n) - 1):
        f.read(a)
    f.b.glbl("GSR", 1)
    f.b.sample()
    f.walk(ctx.rng, 8)
    f.b.glbl("GSR", 0)
    f.b.sample()
    f.sweep()
    yield f.build()


def l2_init_sweep(ctx: GenContext, k: LutKind) -> Gen:
    """Spec §4.2 INIT sampling, each value read exhaustively."""
    for name, init in init_samples(k):
        f = _config(ctx, k, name, init)
        f.sweep()
        yield f.build()


def l2_init_random(ctx: GenContext, k: LutKind) -> Gen:
    """Seeded random INITs, each swept and then read at 2**n random addresses."""
    for name, init in random_inits(k, ctx.rng):
        f = _config(ctx, k, name, init)
        f.sweep()
        f.walk(ctx.rng, 1 << k.n)
        yield f.build()


# -- LUT6_2 ------------------------------------------------------------------------------

#: LUT6_2's O5 reads the lower half of INIT (p509)
O5_HALF = (1 << 32) - 1


def l1_o5_lower_half(ctx: GenContext, k: LutKind) -> Gen:
    """For each {I4..I0}, I5 low then high: O5 must not move; O6 moves to the upper half."""
    upper = ones(k) ^ O5_HALF
    p0 = projection(k, 0)
    cases = (
        ("lo_p0_hi_n0", (p0 & O5_HALF) | ((ones(k) ^ p0) & upper)),  # O5 = I0; O6 = I0 ^ I5
        ("lo_zero_hi_ones", upper),  # O5 = 0; O6 = I5
        ("rand", ctx.rng.getrandbits(k.width)),
    )
    half = 1 << (k.n - 1)
    for name, init in cases:
        f = _config(ctx, k, name, init)
        f.b.sample()
        for a in range(half):
            f.read(a)
            f.read(a | half)
        f.read(0)
        yield f.build()


def l1_doc_example(ctx: GenContext, k: LutKind) -> Gen:
    """p509: INIT=64'hFFFFFFFFFFFFFFFE gives a 6-input OR on O6 and a 5-input OR on O5."""
    f = _config(ctx, k, "or6_or5", ones(k) ^ 1)
    f.sweep()
    yield f.build()


# -- CFGLUT5 -----------------------------------------------------------------------------


def l1_edge_polarity(ctx: GenContext, k: LutKind) -> Gen:
    """The pure CFGLUT5 test (ruling S52): every sample is order-independent.

    For each IS_CLK_INVERTED value and each uniform INIT: sweep; apply only the
    *inactive* edge with CE High and the opposite CDI, then sweep (and CDO): nothing may
    change (a simulator that shifts on both edges, or ignores IS_CLK_INVERTED, fails a
    documented bit here); take the active edge with CE Low (C4); shift the opposite value
    in 32 times with no read in between, then sweep: the whole function has flipped,
    whatever the shift direction (C3, C5, C7 when inverted). The CE-Low active edge sees
    the opposite CDI, so a simulator that ignores CE would flip a documented bit (S55)."""
    for inverted in (0, 1):
        for init in (0, ones(k)):
            bit = init & 1
            f = _cfglut(
                ctx,
                k,
                f"clk{inverted}_{'ones' if bit else 'zeros'}",
                init,
                IS_CLK_INVERTED=BIN[inverted],
            )
            f.sweep()
            if inverted:  # rising is inactive: CE High, opposite CDI, rise only
                f.b.set(CE=1, CDI=1 - bit)
                f.b.edge("CLK", True)
                f.b.set(CE=0)
                f.sweep()
                f.b.edge("CLK", False)  # the active edge, CE Low: holds
            else:  # rising is active: take it with CE Low (opposite CDI), then the fall
                f.b.set(CDI=1 - bit)  # so a CE-ignoring simulator would shift (S55)
                f.b.edge("CLK", True)
                f.b.set(CE=1, CDI=1 - bit)
                f.b.edge("CLK", False)
                f.b.set(CE=0)
                f.sweep()
            f.b.sample()
            f.shift([1 - bit] * k.width)
            f.b.set(CE=0, CDI=0)
            f.sweep()
            yield f.build()


def l1_ce_low_holds(ctx: GenContext, k: LutKind) -> Gen:
    """CE Low: CDI toggles and CLK runs, but the function and CDO stay put. Only the
    all-ones configuration credits C4: the others' reads depend on the inferred bit
    order (ruling S52)."""
    cases = (("rand", ctx.rng.getrandbits(k.width)), ("p0", projection(k, 0)), ("ones", ones(k)))
    for name, init in cases:
        f = _cfglut(ctx, k, name, init)
        f.sweep()
        f.shift(CE_LOW_CDI, ce=0, sample=True)
        f.sweep()
        yield f.build()


def l1_reconfigure(ctx: GenContext, k: LutKind) -> Gen:
    """Load a new function through CDI and read it back exhaustively. The first three
    test the inferred order; ``ones_to_zero`` is order-independent throughout."""
    pairs = [
        ("zero_to_rand", 0, ctx.rng.getrandbits(k.width)),
        ("ones_to_p2", ones(k), projection(k, 2)),
        ("rand_to_rand", ctx.rng.getrandbits(k.width), ctx.rng.getrandbits(k.width)),
        ("ones_to_zero", ones(k), 0),
    ]
    for name, init, new in pairs:
        f = _cfglut(ctx, k, name, init)
        f.sweep()
        f.load(new)
        f.sweep()
        yield f.build()


def l1_cdo_cascade(ctx: GenContext, k: LutKind) -> Gen:
    """Two chains of shifts, CDO sampled after each, then a sweep: the old INIT leaves on
    CDO, then the first shifted-in bits follow ``k.width`` shifts later. Random data tests
    the inferred order (which INIT bit reaches CDO first); ``ones_zeros_ones`` flips the
    uniform contents twice."""
    w = k.width
    cases = (
        ("rand", ctx.rng.getrandbits(w), [ctx.rng.randrange(2) for _ in range(2 * w)]),
        ("ones_zeros_ones", ones(k), [0] * w + [1] * w),
    )
    for name, init, bits in cases:
        f = _cfglut(ctx, k, name, init)
        f.b.sample()
        f.shift(bits, sample=True)
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_partial_shift(ctx: GenContext, k: LutKind) -> Gen:
    """Fewer than ``k.width`` shifts leave a mix of old and new bits (order inferred)."""
    for count in (1, 5, k.width // 2, k.width - 1):
        f = _cfglut(ctx, k, f"k{count}", ctx.rng.getrandbits(k.width))
        f.shift([ctx.rng.randrange(2) for _ in range(count)])
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_is_clk_inverted(ctx: GenContext, k: LutKind) -> Gen:
    """IS_CLK_INVERTED=1: samples after each rise show no shift, after each fall one. The
    intermediate samples depend on the inferred order; ``l1_edge_polarity`` is the pure
    test of the same claim."""
    for name, init in (("zeros", 0), ("ones", ones(k))):
        f = _cfglut(ctx, k, name, init, IS_CLK_INVERTED=BIN[1])
        f.read(k.width - 1)
        f.shift([1 - (init & 1)] * k.width, sample=True)
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_shift_while_reading(ctx: GenContext, k: LutKind) -> Gen:
    """An address is held while 8 bits shift in, 4 times: the function changes at run
    time while it is being used."""
    for name in ("a", "b"):
        f = _cfglut(ctx, k, name, ctx.rng.getrandbits(k.width))
        for _ in range(4):
            f.address(ctx.rng.randrange(1 << k.n))
            f.shift([ctx.rng.randrange(2) for _ in range(8)], sample=True)
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_gsr_after_reconfig(ctx: GenContext, k: LutKind) -> Gen:
    """Reload, then pulse GSR, with and without shifting under it. UG953 names no GSR
    effect on CFGLUT5: the model infers the loaded function is kept (no claim, S44)."""
    for name, shift_under_gsr in (("keep", False), ("shift", True)):
        init = ctx.rng.getrandbits(k.width)
        f = _cfglut(ctx, k, name, init)
        f.load(init ^ ones(k))
        f.sweep()
        f.b.glbl("GSR", 1)
        f.b.sample()
        if shift_under_gsr:
            f.shift([1, 0, 1], sample=True)
            f.b.set(CE=0)
        f.b.glbl("GSR", 0)
        f.sweep()
        yield f.build()


def l2_random(ctx: GenContext, k: LutKind) -> Gen:
    """Seeded random mixes of reloads (CE 0/1, random CDI) and reads, both clock senses."""
    rng = ctx.rng
    for i in range(RANDOM_CONFIGS):
        inv = i % 2
        f = _cfglut(ctx, k, f"r{i}_clk{inv}", rng.getrandbits(k.width), IS_CLK_INVERTED=BIN[inv])
        f.sweep()
        for _ in range(RANDOM_STEPS):
            if rng.random() < RELOAD_P:
                f.shift([rng.randrange(2)], ce=int(rng.random() < CE_HIGH_P), sample=True)
            else:
                f.read(rng.randrange(1 << k.n))
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def generators(prim: str) -> dict[str, Callable[[GenContext], Gen]]:
    """test.yaml function name -> generator, for vectors/gen.py of each primitive."""
    k = KINDS[prim]
    table = {
        "l0_smoke": l0_smoke,
        "l0_illegal_init": l0_illegal_init,
        "l1_default_init": l1_default_init,
        "l1_projections": l1_projections,
        "l2_init_sweep": l2_init_sweep,
    }
    if k.width > 4:
        table["l2_init_random"] = l2_init_random
    if k.reconfig:
        table |= {
            "l1_edge_polarity": l1_edge_polarity,
            "l1_ce_low_holds": l1_ce_low_holds,
            "l1_reconfigure": l1_reconfigure,
            "l1_cdo_cascade": l1_cdo_cascade,
            "l1_partial_shift": l1_partial_shift,
            "l1_is_clk_inverted": l1_is_clk_inverted,
            "l1_shift_while_reading": l1_shift_while_reading,
            "l1_gsr_after_reconfig": l1_gsr_after_reconfig,
            "l2_random": l2_random,
        }
    else:
        table["l1_gsr_transparent"] = l1_gsr_transparent
    if prim == "LUT6_2":
        table |= {"l1_o5_lower_half": l1_o5_lower_half, "l1_doc_example": l1_doc_example}
    return {name: partial(fn, k=k) for name, fn in table.items()}
```

- [ ] **Step 2: Write `tests/7series/clb/_shared/luts/luts_tests.py`.** It builds on `xut.unitkit` and copies nothing; `render(prim)` returns every generated file of a primitive, the sv wrappers (Task B4) and the cocotb modules (Task B5) included, so the drift guard covers them all.

```python
# SPDX-License-Identifier: Apache-2.0
"""Single source of the luts unit's generated files: each primitive's test.yaml,
README.md, vectors/gen.py, cocotb module and (LUT1-LUT6, LUT6_2) sv wrappers.

    uv run python tests/7series/clb/_shared/luts/luts_tests.py [PRIM ...]

The shared pieces come from ``xut.unitkit`` (ruling S53). test_luts_tests.py fails when a
committed file differs from this rendering. The stem ``luts`` is the unit's name, so it is
unique across units: pytest's default import mode puts every ``_shared/<unit>`` module in
one flat namespace, where two units' ``recipes.py`` would collide.
"""

from __future__ import annotations

import functools
import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from luts_recipes import BIN, KINDS, RANDOM_INITS, LutKind, generators, lit, ones, projection

from xut import unitkit
from xut.unitkit import CO_HW, CO_PY, CO_XS, HW_GSR, HW_REJ, SV_HW, SV_PY, VL_REJ, X_VL, Reason
from xut_models.base import Out

if TYPE_CHECKING:
    from xut.catalog.model import CatalogEntry

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
FAMILY = "7series"
GROUP_DIR = ROOT / "tests" / FAMILY / "clb"
GENERATOR = "tests/7series/clb/_shared/luts/luts_tests.py"
#: prim -> (first page, last page) of its UG953 v2026.1 section
PAGES = {
    "LUT1": (488, 489),
    "LUT2": (491, 492),
    "LUT3": (494, 495),
    "LUT4": (497, 499),
    "LUT5": (500, 502),
    "LUT6": (504, 507),
    "LUT6_2": (509, 512),
    "CFGLUT5": (348, 349),
}
TITLE = {
    **{f"LUT{n}": f"{n}-input look-up table" for n in range(1, 7)},
    "LUT6_2": "6-input, 2-output look-up table",
    "CFGLUT5": "5-input look-up table, reconfigurable at run time",
}
CFG_VL: Reason = (
    "unsupported",
    "status/PORTABILITY.md: verilatorize cannot transform CFGLUT5 (a forced reg's trigger "
    "cone crosses a non-blocking-written reg, ruling S28); no Verilator result until the "
    "srl/CFGLUT5 recovery of ruling S29(2)",
)
NO_X = "no x/z on any input (sv_x_inputs covers x)"
NO_TIMING = "propagation delay is not measured (timing is out of scope, spec §2)"
#: Ruling S52: a CFGLUT5 read whose value depends on the inferred bit order credits nothing
S52 = (
    "claims: reads that depend on CFGLUT5's inferred bit order are exercised but credit "
    "nothing (ruling S52; findings/CFGLUT5-doc-gap-L1-projections.md)"
)
#: tests whose twin (LUT6/LUT6_2, LUT5/CFGLUT5) has a test of the same name
SHARED_WITH_TWIN = (
    "smoke", "illegal_init", "default_init", "projections", "init_sweep", "init_random",
    "sv_x_inputs", "sv_gsr_midsim", "cocotb_random",
)  # fmt: skip
TWIN = {"LUT6": "LUT6_2", "LUT6_2": "LUT6", "LUT5": "CFGLUT5", "CFGLUT5": "LUT5"}


@functools.cache
def _entry(prim: str) -> CatalogEntry:
    from xut.catalog.model import load_entry

    return load_entry(FAMILY, prim, ROOT)


def _bins(prim: str, port: str, *events: str) -> list[str]:
    return unitkit.class_bins(_entry(prim), port, *events)


def _inputs(k: LutKind) -> list[str]:
    return [b for i in range(k.n) for b in _bins(k.prim, f"I{i}")]


def _outs(k: LutKind) -> list[str]:
    return [f"port:{o}" for o in k.outputs]


def _claims(k: LutKind, *ns: int) -> list[str]:
    return unitkit.claims(k.prim, *ns)


def _runners(k: LutKind, **over: Reason) -> unitkit.Declared:
    """CFGLUT5 is never run on Verilator (CFG_VL)."""
    return unitkit.runners(**({**over, "verilator": CFG_VL} if k.reconfig else over))


def _sampling(k: LutKind) -> dict[str, list]:
    if k.width <= 4:
        return {"INIT": [f"every {k.width}-bit value ({1 << k.width})"]}
    return {
        "INIT": ["all zeros", "all ones", f"walking ones x{k.width}", f"walking zeros x{k.width}"]
    }


def _cocotb_configs(k: LutKind) -> list[dict]:
    rng = random.Random(f"{FAMILY}.{k.prim}.L2.cocotb_random")
    cfgs = [{"cfg": "default", "attrs": {}}, {"cfg": "ones", "attrs": {"INIT": lit(k, ones(k))}}]
    for i in range(2):
        attrs = {"INIT": lit(k, rng.getrandbits(k.width))}
        if k.reconfig:
            attrs["IS_CLK_INVERTED"] = BIN[i]
        cfgs.append({"cfg": f"rand{i}", "attrs": attrs})
    return cfgs


Add = Callable[..., None]


def tests_for(k: LutKind) -> list[tuple[dict, str]]:
    prim, out = k.prim, []

    def add(
        level: str,
        name: str,
        style: str,
        source: str,
        exercises: Sequence[str],
        why: str,
        *,
        gaps: Sequence[str],
        related: Sequence[str] = (),
        **kw: object,
    ) -> None:
        twin = [f"{FAMILY}.{TWIN[prim]}.{level}.{name}"] if prim in TWIN else []
        rel = [*(twin if name in SHARED_WITH_TWIN else []), *related]
        kw.setdefault("declared", _runners(k))
        e = unitkit.entry(
            FAMILY, prim, level, name, style, source, exercises, gaps=gaps, related=rel, **kw
        )
        out.append((e, why))

    # C1 (LUT6_2/CFGLUT5: C1, C2) is credited by an explicit INIT's reads; the default's
    # claim by INIT unset. CFGLUT5 reads of an arbitrary INIT credit nothing (ruling S52).
    table = _claims(k, 1, 2) if len(k.outputs) > 1 else _claims(k, 1)
    default = _claims(k, {"LUT6_2": 3, "CFGLUT5": 6}.get(prim, 2))
    ordered = [] if k.reconfig else table
    s52 = [S52] if k.reconfig else []
    shift_bins = (
        [*_bins(prim, "CDI"), *_bins(prim, "CE"), *_bins(prim, "CLK")] if k.reconfig else []
    )
    clk_attrs = [f"attr:IS_CLK_INVERTED={v}" for v in BIN] if k.reconfig else []
    base = [*_outs(k), *_inputs(k)]
    add(
        "L0",
        "smoke",
        "vector",
        "vectors/gen.py:l0_smoke",
        [*base, "attr:INIT", *table, *default, *shift_bins, *clk_attrs,],
        "Elaborates with the default INIT and two sampled ones and reads every address: the "
        "minimum any toolchain must get right. The default configuration sets no attribute, "
        "so the model's documented default meets the simulators' own.",
        sampling={
            "INIT": ["unset (default)", "all ones", "1 seeded random"],
            **({"IS_CLK_INVERTED": [0, 1]} if k.reconfig else {}),
        },
        gaps=["one sweep per configuration", NO_X,
              "illegal values are tried only by L0.illegal_init", *s52],
        related=[f"{FAMILY}.{prim}.L0.illegal_init"],
    )  # fmt: skip
    add(
        "L0",
        "illegal_init",
        "vector",
        "vectors/gen.py:l0_illegal_init",
        [],
        f"An INIT with x digits is not the HEX value UG953 asks for (p{PAGES[prim][1]}); the "
        "simulation must reject it (expect=reject), the runtime-rejection path of spec §4.1.",
        declared=_runners(k, verilator=VL_REJ, hw=HW_REJ),
        gaps=["only an all-x INIT is tried; an over-wide literal is refused by xut wrap",
              "whether UNISIM rejects it is observed, not documented (Task A6 rule)"],
        related=[f"{FAMILY}.{prim}.L0.smoke"],
    )  # fmt: skip
    add(
        "L1",
        "default_init",
        "vector",
        "vectors/gen.py:l1_default_init",
        [*base, *default, *(table if k.reconfig else [])],
        "INIT unset: every address reads 0 (a ground, per the Introduction); a flow that "
        "drops or mangles the default fails here.",
        gaps=["the default is the only value; explicit zero is in L2.init_sweep", NO_X],
    )
    add(
        "L1",
        "projections",
        "vector",
        "vectors/gen.py:l1_projections",
        [*base, "attr:INIT", *ordered],
        "INIT chosen so the output equals one input (and its complement), for every input: "
        "pins the input-to-address order of the logic table; a swapped pair fails at once.",
        sampling={"INIT": [f"projection of I<j> and its complement, j = 0..{k.n - 1}"]},
        gaps=["single-input functions only; general INITs are in L2", NO_X, *s52],
    )
    if k.reconfig:
        _cfglut5_tests(k, add, base, shift_bins)
    else:
        add(
            "L1",
            "gsr_transparent",
            "vector",
            "vectors/gen.py:l1_gsr_transparent",
            [*base, "attr:INIT", *table],
            "Inputs move while GSR is asserted. UG953 names no GSR effect on a LUT, so the "
            "model infers the table holds (inferred:, no claim, ruling S44): a disagreement "
            "is a doc-gap finding, never masked.",
            declared=_runners(k, hw=HW_GSR),
            gaps=["claims are credited only by the sweeps before and after the pulse",
                  "one GSR pulse, one configuration"],
            related=[f"{FAMILY}.{prim}.L1.sv_gsr_midsim"],
        )  # fmt: skip
    if prim == "LUT6_2":
        add(
            "L1",
            "o5_lower_half",
            "vector",
            "vectors/gen.py:l1_o5_lower_half",
            [*base, "attr:INIT", *_claims(k, 1, 2)],
            "Each I4..I0 is read with I5 low then high: O5 must not move (lower 32 bits "
            "only) while O6 switches to the upper half.",
            sampling={"INIT": ["lower: I0 projection, upper: its complement",
                               "lower zero, upper ones", "1 seeded random"]},
            gaps=[NO_X],
        )  # fmt: skip
        add(
            "L1",
            "doc_example",
            "vector",
            "vectors/gen.py:l1_doc_example",
            [*base, "attr:INIT", *_claims(k, 1, 2, 4)],
            "UG953's own example (p509): 64'hFFFFFFFFFFFFFFFE is a 6-input OR on O6 and a "
            "5-input OR on O5.",
            sampling={"INIT": ["64'hFFFFFFFFFFFFFFFE"]},
            gaps=["one INIT", NO_X],
        )
    add(
        "L2",
        "init_sweep",
        "vector",
        "vectors/gen.py:l2_init_sweep",
        [*base, "attr:INIT", *table],
        "Spec §4.2 INIT sampling ("
        + ("every value" if k.width <= 4 else "boundaries, walking ones and zeros")
        + "), each read at every address: every INIT bit is seen alone, set and clear.",
        sampling=_sampling(k),
        gaps=["the addresses are visited in binary order (L2.init_random adds random order)",
              NO_X, NO_TIMING, *s52],
        related=[f"{FAMILY}.{prim}.L1.projections"],
    )  # fmt: skip
    if k.width > 4:
        add(
            "L2",
            "init_random",
            "vector",
            "vectors/gen.py:l2_init_random",
            [*base, "attr:INIT", *ordered],
            "Seeded random INITs, each swept and then read at random addresses, where "
            "several inputs change at once.",
            sampling={"INIT": [f"{RANDOM_INITS} seeded random (the test's seed)"]},
            gaps=["one seed per run; a failing seed is frozen by hand (xut freeze-seed is "
                  "deferred)", NO_X, *s52],
            related=[f"{FAMILY}.{prim}.L2.cocotb_random"],
        )  # fmt: skip
    _sim_tests(k, add, table, default, ordered, clk_attrs)
    return out


def _sim_tests(
    k: LutKind, add: Add, table: list[str], default: list[str], ordered: list[str],
    clk_attrs: list[str],
) -> None:  # fmt: skip
    """The sv and cocotb tests (simulation only)."""
    prim = k.prim
    sv = f"sv/tb_{prim.lower()}"
    ports = [f"port:{p['name']}" for p in _entry(prim).ports]
    rand = lit(k, random.Random(prim).getrandbits(k.width))
    cfgs = (
        [{"cfg": "ones", "attrs": {"INIT": lit(k, ones(k))}}]
        if k.reconfig
        else [{"cfg": "rand", "attrs": {"INIT": rand}},
              {"cfg": "p0", "attrs": {"INIT": lit(k, projection(k, 0))}}]
    )  # fmt: skip
    add(
        "L1",
        "sv_x_inputs",
        "sv",
        f"{sv}_x.sv",
        # CFGLUT5: only the uniform (order-free) checks decide a claim (ruling S52)
        [*ports, "attr:INIT", *(_claims(k, 1, 2, 4) if k.reconfig else table)],
        "Documented reads are checked (an all-ones function; CE Low holds). x on I, CDI "
        "and CE is recorded as checkpoints, compared between simulators."
        if k.reconfig
        else "Every defined address is checked against the logic table; x on each input, "
        "where the two INIT bits it selects agree and where they differ, is recorded as "
        "checkpoints: UG953 does not define x behaviour, so crosscheck compares simulators.",
        declared=_runners(k, python=SV_PY, verilator=X_VL, hw=SV_HW),
        flows=["rtl"],
        gaps=["x behaviour is undocumented: checkpoints only, never checks", "no z inputs"],
        configs=cfgs,
    )
    add(
        "L1",
        "sv_gsr_midsim",
        "sv",
        f"{sv}_gsr.sv",
        [*ports, "attr:INIT", *(_claims(k, 1, 2, 3, 5, 6) if k.reconfig else table)],
        "32 zero shifts replace the whole function whatever the shift order; GSR is then "
        "pulsed, its effect recorded as checkpoints, and 32 one shifts are checked."
        if k.reconfig
        else "The logic table is checked before and after a GSR pulse; the output while GSR "
        "is asserted is a checkpoint (UG953 names no GSR effect on a LUT).",
        declared=_runners(k, python=SV_PY, hw=SV_HW),
        flows=["rtl"],
        gaps=["the GSR effect is undocumented: checkpoints only", "one configuration"],
        configs=cfgs[:1],
        related=[f"{FAMILY}.{prim}.L1.{'gsr_after_reconfig' if k.reconfig else 'gsr_transparent'}"],
    )
    co = _cocotb_configs(k)
    add(
        "L2",
        "cocotb_random",
        "cocotb",
        f"cocotb/cocotb_{prim.lower()}_random.py",
        [*ports, "attr:INIT", *ordered, *default, *clk_attrs],
        "Long model-checked random sessions on Icarus"
        + ("" if k.reconfig else " and Verilator")
        + "; a failing seed is frozen into a vector test that also runs on xsim and hardware.",
        declared=_runners(k, python=CO_PY, xsim=CO_XS, hw=CO_HW),
        flows=["rtl"],
        gaps=["no GSR mid-session", f"{len(co)} configurations", NO_X],
        configs=co,
    )


def _cfglut5_tests(k: LutKind, add: Add, base: list[str], shift_bins: list[str]) -> None:
    prim, rel = k.prim, [f"{FAMILY}.{k.prim}.L1.reconfigure"]
    clk_attrs = [f"attr:IS_CLK_INVERTED={v}" for v in BIN]
    add(
        "L1",
        "edge_polarity",
        "vector",
        "vectors/gen.py:l1_edge_polarity",
        [*base, *shift_bins, "attr:INIT", *clk_attrs, *_claims(k, 1, 2, 3, 4, 5, 6, 7)],
        "The pure CFGLUT5 test: every sample is order-independent (uniform contents). The "
        "inactive edge with CE High must change nothing, for both IS_CLK_INVERTED values "
        "(a both-edges or wrong-edge simulator fails a documented bit); 32 shifts of the "
        "opposite value then flip the whole function. It credits every claim whatever the "
        "inferred bit order turns out to be.",
        sampling={"INIT": ["all zeros", "all ones"], "IS_CLK_INVERTED": [0, 1]},
        gaps=["only uniform contents: the bit order is left to the other tests", NO_X],
        related=rel,
    )
    add(
        "L1",
        "ce_low_holds",
        "vector",
        "vectors/gen.py:l1_ce_low_holds",
        [*base, *_bins(prim, "CDI"), *_bins(prim, "CLK"), "attr:INIT", *_claims(k, 1, 2, 4)],
        "CE Low with CDI toggling and CLK running: the function and CDO do not move.",
        gaps=["CE is never raised here (see reconfigure)", "only the all-ones configuration "
              "credits C4; the others' reads depend on the inferred order (ruling S52)", NO_X],
        related=rel,
    )  # fmt: skip
    add(
        "L1",
        "reconfigure",
        "vector",
        "vectors/gen.py:l1_reconfigure",
        [*base, *shift_bins, "attr:INIT", *_claims(k, 1, 2, 3, 5)],
        "A new 32-bit function is shifted in through CDI and read back at every address.",
        gaps=["the read-back order relies on the inferred shift direction (a disagreement is "
              "a doc-gap); only ones_to_zero credits C3 and C5 (ruling S52)", NO_X],
    )  # fmt: skip
    add(
        "L1",
        "cdo_cascade",
        "vector",
        "vectors/gen.py:l1_cdo_cascade",
        ["port:CDO", *shift_bins, "attr:INIT", *_claims(k, 3, 5)],
        "64 shifts with CDO sampled after each: the old INIT leaves on CDO, then the first "
        "shifted-in bits arrive 32 shifts later, as a CDO-to-CDI chain needs.",
        gaps=["which INIT bit reaches CDO first is inferred; only ones_zeros_ones credits "
              "(ruling S52)",
              "documented bits bound the chain length only from above: a chain shorter than "
              "32 bits shows only on inferred bits; the two-LUT chain is an L3 design",
              NO_X],
        related=rel,
    )  # fmt: skip
    add(
        "L1",
        "partial_shift",
        "vector",
        "vectors/gen.py:l1_partial_shift",
        [*base, *shift_bins, "attr:INIT"],
        "1, 5, 16 and 31 shifts leave a mix of old and new bits: pins the shift order.",
        gaps=["the order is inferred; a disagreement is a doc-gap "
              "(findings/CFGLUT5-doc-gap-L1-partial_shift.md)", S52, NO_X],
        related=rel,
    )  # fmt: skip
    add(
        "L1",
        "is_clk_inverted",
        "vector",
        "vectors/gen.py:l1_is_clk_inverted",
        [*base, *_bins(prim, "CDI", "1"), *_bins(prim, "CE"), *_bins(prim, "CLK"),
         "attr:INIT", "attr:IS_CLK_INVERTED=1'b1", *_claims(k, 3, 7)],
        "IS_CLK_INVERTED=1: samples after each rise show no shift, after each fall one.",
        sampling={"IS_CLK_INVERTED": [1], "INIT": ["all zeros", "all ones"]},
        gaps=["the intermediate samples depend on the inferred order; L1.edge_polarity is "
              "the order-free test of the same claim", NO_X],
        related=[f"{FAMILY}.{prim}.L1.edge_polarity"],
    )  # fmt: skip
    add(
        "L1",
        "shift_while_reading",
        "vector",
        "vectors/gen.py:l1_shift_while_reading",
        [*base, *shift_bins, "attr:INIT"],
        "An address is held while bits shift in, so the function changes while in use.",
        gaps=[S52, NO_X],
        related=rel,
    )
    add(
        "L1",
        "gsr_after_reconfig",
        "vector",
        "vectors/gen.py:l1_gsr_after_reconfig",
        [*base, *shift_bins, "attr:INIT"],
        "GSR after a reload, with and without shifts under it. UG953 names no GSR effect "
        "on CFGLUT5: the model infers the function is kept (inferred:, no claim, S44).",
        declared=_runners(k, hw=HW_GSR),
        gaps=["the GSR outcome is inferred; a disagreement is a doc-gap, never masked"],
        related=[f"{FAMILY}.{prim}.L1.sv_gsr_midsim"],
    )
    add(
        "L2",
        "random",
        "vector",
        "vectors/gen.py:l2_random",
        [*base, *shift_bins, "attr:INIT", *clk_attrs],
        "Seeded random mixes of reloads (CE 0/1, random CDI) and reads, both clock senses.",
        sampling={"INIT": ["8 seeded random"], "IS_CLK_INVERTED": [0, 1]},
        gaps=["one seed per run", "no GSR (L1.gsr_after_reconfig)", S52, NO_X],
        related=[f"{FAMILY}.{prim}.L2.cocotb_random"],
    )


# --- rendering -------------------------------------------------------------------------


def render_test_yaml(k: LutKind) -> str:
    doc = {
        "primitive": k.prim,
        "family": FAMILY,
        "work_unit": "luts",
        "doc_refs": [
            {"guide": "UG953", "version": "2026.1", "section": k.prim, "page": PAGES[k.prim][0]}
        ],
        "tests": [e for e, _ in tests_for(k)],
    }
    return unitkit.dump_test_yaml(doc, GENERATOR)


def render_readme(k: LutKind) -> str:
    first, last = PAGES[k.prim]
    overview = (
        f"{k.prim} reads a {k.width}-bit INIT at the address formed by its inputs; "
        + (
            "CE-enabled CLK edges shift a new INIT in through CDI, and CDO cascades it. "
            if k.reconfig
            else "it has no clock and no state. "
        )
        + f"Behavioural claims are in `catalog/7series/{k.prim}.overrides.yaml`."
    )
    oracle = [
        f"Vector tests: the clean-room golden model `models/xut_models/7series/"
        f"{k.prim.lower()}.py` (shared logic in `_common/luts.py`), written from UG953 alone. "
        "Every expected bit carries `doc:<page>` or `inferred:<reason>`.",
        "sv tests: self-checks of documented behaviour only; x and GSR cases are "
        "checkpoints compared between simulators by `xut crosscheck`.",
        "cocotb: the same golden model, step by step.",
        "References: UNISIM on xsim, Icarus"
        + (
            " (Verilator: see runner support)."
            if k.reconfig
            else " and Verilator (the model is unchanged by `xut verilatorize`)."
        ),
    ]
    return unitkit.render_readme(
        prim=k.prim,
        title=TITLE[k.prim],
        reference=f"UG953 v2026.1, section {k.prim}, pages {first}–{last} (CLB / LUT). Work "
        "unit: `luts`. GENERATED by `_shared/luts/luts_tests.py`.",
        overview=overview,
        tests=tests_for(k),
        oracle=oracle,
        known_gaps=[f"{NO_TIMING}."],
        root=ROOT,
    )


def _gen_py(prim: str) -> str:
    return (
        "# SPDX-License-Identifier: Apache-2.0\n"
        f'"""{prim} vector generators (test.yaml: source: vectors/gen.py:<name>).\n\n'
        'The recipes live in tests/7series/clb/_shared/luts/luts_recipes.py.\n"""\n\n'
        "import luts_recipes\n\n"
        f'globals().update(luts_recipes.generators("{prim}"))\n'
    )


def _cocotb_py(prim: str) -> str:
    p = prim.lower()
    return (
        "# SPDX-License-Identifier: Apache-2.0\n"
        f'"""{FAMILY}.{prim}.L2.cocotb_random: random {prim} session vs the golden model."""\n\n'
        "import cocotb\n"
        "from luts_cocotb import random_session\n\n\n"
        "@cocotb.test()\n"
        f"async def {p}_random(dut: object) -> None:\n"
        f'    await random_session(dut, "{prim}", steps=2000)\n'
    )


def _sv_wrapper(k: LutKind, kind: str) -> str:
    """A LUT1-LUT6/LUT6_2 sv test: defines, then the shared body (CFGLUT5's own sv tests
    are written by hand: its ports differ)."""
    body = {"x": "sv_x_inputs", "gsr": "sv_gsr_midsim"}[kind]
    ins = ", ".join(f".I{i}(I[{i}])" for i in range(k.n))
    outs = ".O6(O), .O5(O5)" if len(k.outputs) > 1 else ".O(O)"
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        f"// {FAMILY}.{k.prim}.L1.{body} (body: _shared/luts/luts_{kind}_tb.svh)",
        f"`define LUT_TB tb_{k.prim.lower()}_{kind}",
        f"`define LUT_N {k.n}",
        *(["`define LUT_DUAL"] if len(k.outputs) > 1 else []),
        f"`define LUT_INST {k.prim} #(.INIT(INIT)) dut ({outs}, {ins});",
        f'`include "luts_{kind}_tb.svh"',
        "",
    ]
    return "\n".join(lines)


def render(prim: str) -> dict[str, str]:
    """Every generated file of ``prim``, by its path relative to the primitive's directory."""
    k = KINDS[prim]
    files = {
        "test.yaml": render_test_yaml(k),
        "README.md": render_readme(k),
        "vectors/gen.py": _gen_py(prim),
        f"cocotb/cocotb_{prim.lower()}_random.py": _cocotb_py(prim),
    }
    if not k.reconfig:
        files |= {f"sv/tb_{prim.lower()}_{kind}.sv": _sv_wrapper(k, kind) for kind in ("x", "gsr")}
    return files


# --- mutants (ruling S55) ------------------------------------------------------------------
# One model variant per credited claim, breaking exactly that claim's rule; the unit's
# guard asserts each fails a documented bit in a configuration that credits the claim.


def _address_flipped(base: type) -> type:
    """Logic table read at the neighbouring address: the input order is wrong (C1)."""

    class AddressFlipped(base):
        def _address(self, n: int) -> int:
            return super()._address(n) ^ 1

    return AddressFlipped


def _default_ones(base: type) -> type:
    """An unset INIT reads as all ones, not the documented zero (the default claim)."""

    class DefaultOnes(base):
        def __init__(self, attrs: dict) -> None:
            super().__init__(attrs)
            if not self.explicit_init:
                self.init = (1 << (1 << self.N)) - 1

    return DefaultOnes


def _output_replaced(port: str, value: Callable[[object], int]) -> Callable[[type], type]:
    """``port`` shows ``value(model)`` instead of the documented bit."""

    def factory(base: type) -> type:
        class Replaced(base):
            def outputs(self) -> dict:
                out = super().outputs()
                return {**out, port: Out(str(value(self)), out[port].prov)}

        Replaced.__name__ = f"{port}Replaced"
        return Replaced

    return factory


def _clock_edge_with_ce(ce: int | None) -> Callable[[type], type]:
    """CE forced to ``ce`` on every edge (0: never shifts; 1: ignores CE)."""

    def factory(base: type) -> type:
        class ForcedCe(base):
            def clock_edge(self, port: str, rising: bool) -> None:
                kept = self.pin["CE"]
                self.pin["CE"] = ce
                super().clock_edge(port, rising)
                self.pin["CE"] = kept

        return ForcedCe

    return factory


def _init_ignored(base: type) -> type:
    """The start-up contents are all zeros whatever INIT says (C6)."""

    class InitIgnored(base):
        def power_on(self) -> None:
            super().power_on()
            self.contents = 0

    return InitIgnored


def _inversion_ignored(base: type) -> type:
    """IS_CLK_INVERTED has no effect: the rising edge is always active (C7)."""

    class InversionIgnored(base):
        def __init__(self, attrs: dict) -> None:
            super().__init__(attrs)
            self.inv_clk = 0

    return InversionIgnored


def mutants(prim: str) -> dict[str, Callable[[type], type]]:
    """{claim id: mutant factory} for ``prim``: every claim a vector test credits."""
    if prim == "CFGLUT5":
        return {
            "CFGLUT5.C1": _output_replaced("O6", lambda m: 0),  # O6 ignores the contents
            "CFGLUT5.C2": _output_replaced("O5", lambda m: 0),  # O5 ignores the contents
            "CFGLUT5.C3": _clock_edge_with_ce(0),  # never shifts
            "CFGLUT5.C4": _clock_edge_with_ce(1),  # ignores CE
            "CFGLUT5.C5": _output_replaced("CDO", lambda m: (m.init >> 31) & 1),  # CDO stuck
            "CFGLUT5.C6": _init_ignored,
            "CFGLUT5.C7": _inversion_ignored,
        }
    if prim == "LUT6_2":
        upper = _output_replaced("O5", lambda m: (m.init >> (32 + m._address(5))) & 1)
        return {
            "LUT6_2.C1": _output_replaced("O6", lambda m: (m.init >> (m._address(6) ^ 1)) & 1),
            "LUT6_2.C2": upper,  # O5 reads the upper 32 bits
            "LUT6_2.C3": _default_ones,
            "LUT6_2.C4": upper,  # the p509 example's 5-input OR on O5 breaks with it
        }
    return {f"{prim}.C1": _address_flipped, f"{prim}.C2": _default_ones}


UNIT = unitkit.Unit(
    name="luts",
    family=FAMILY,
    root=ROOT,
    group_dir=GROUP_DIR,
    prims=tuple(KINDS),
    render=render,
    generators=generators,
    mutants=mutants,
)


def main(prims: list[str]) -> None:
    for prim in prims or list(KINDS):
        d = GROUP_DIR / prim
        for rel, text in render(prim).items():
            path = d / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        print(f"wrote {len(render(prim))} files under {d.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
```

`luts_tests.mutants(prim)` is the unit's mutant table for `UnitGuards`' failing-mutant guard (ruling S55), one factory per claim a vector test credits: LUTn C1 reads the neighbouring address (a bit-order mutant), C2 reads an unset INIT as all ones; LUT6_2 C1 likewise on O6, C2 and C4 read O5 from the upper 32 bits, C3 is the all-ones default; CFGLUT5 C1/C2 pin O6/O5 to 0, C3 never shifts (CE forced Low), C4 ignores CE (CE forced High), C5 holds CDO at INIT[31], C6 ignores INIT, C7 ignores `IS_CLK_INVERTED`.

- [ ] **Step 3: Write the guards** `tests/7series/clb/_shared/luts/test_luts_tests.py`: `unitkit`'s set (the failing-mutant guard included), plus the unit's own checks (CFGLUT5 never declares Verilator; the both-edges and wrong-edge mutants fail documented bits of `L1.edge_polarity`, ruling S53, correctness review M3; the reversed INIT order, a second bit-order mutant, fails a C1-crediting configuration of every LUTn and LUT6_2, ruling S55):

```python
# SPDX-License-Identifier: Apache-2.0
"""The luts unit's guards: xut.unitkit's set, plus the unit's own invariants."""

import zlib

import pytest
from luts_recipes import KINDS, generators
from luts_tests import UNIT
from luts_tests import tests_for as _tests_for  # aliased: pytest would collect "tests_for"

from xut.unitkit import UnitGuards, mutant_fails
from xut_models.registry import get


class TestLutsUnit(UnitGuards):
    unit = UNIT


def test_cfglut5_never_declares_verilator():
    for e, _ in _tests_for(KINDS["CFGLUT5"]):
        assert e["runners"]["verilator"] == "unsupported", e["id"]
        assert "ruling S28" in e["unsupported_reasons"]["verilator"], e["id"]


def _edge_polarity_mismatches(model_cls: type) -> int:
    """Documented (doc:) bits on which ``model_cls`` disagrees with the golden model over
    every configuration of CFGLUT5's L1.edge_polarity."""
    from xut.golden import replay
    from xut.stimgen import GenContext
    from xut.wrap import build_map

    golden = _CFGLUT5
    test_id = "7series.CFGLUT5.L1.edge_polarity"
    ctx = GenContext("7series", "CFGLUT5", zlib.crc32(test_id.encode()), UNIT.root)
    bad = 0
    for vec in generators("CFGLUT5")["l1_edge_polarity"](ctx):
        m = build_map(ctx.specs[vec.cfg])
        want, _ = replay(golden, vec, m)
        got, _ = replay(model_cls, vec, m)
        for label, ports in want.samples.items():
            for port, bits in ports.items():
                if want.prov[label][port].startswith("doc:") and got.samples[label][port] != bits:
                    bad += 1
    return bad


_CFGLUT5 = get("7series", "CFGLUT5")


class _BothEdges(_CFGLUT5):
    """A simulator that shifts on every CLK edge."""

    def clock_edge(self, port, rising):
        super().clock_edge(port, not bool(self.inv_clk))


class _IgnoresInversion(_CFGLUT5):
    """A simulator that ignores IS_CLK_INVERTED."""

    def __init__(self, attrs):
        super().__init__(attrs)
        self.inv_clk = 0


@pytest.mark.parametrize("mutant", [_BothEdges, _IgnoresInversion])
def test_edge_mutants_fail_documented_bits(mutant):
    """Correctness review M3: L1.edge_polarity catches these on doc: bits, so a wrong-edge
    simulator is a doc-vs-model finding, not folded into the bit-order doc-gap."""
    assert _edge_polarity_mismatches(mutant) > 0


def test_the_golden_model_agrees_with_itself():
    assert _edge_polarity_mismatches(_CFGLUT5) == 0


def _init_reversed(base: type) -> type:
    """INIT read end to end, bit 2^n - 1 - a for address a: the other bit order (C1)."""

    class InitReversed(base):
        def _address(self, n: int) -> int:
            return super()._address(n) ^ ((1 << n) - 1)

    return InitReversed


@pytest.mark.parametrize("prim", [p for p in KINDS if not KINDS[p].reconfig])
def test_the_reversed_init_order_fails_a_c1_crediting_configuration(prim):
    """Ruling S55, the LUT INIT bit-order mutants: the unit's C1 mutant (neighbouring
    addresses swapped) is in UnitGuards; the reversed order must be caught as well."""
    mutant = _init_reversed(get("7series", prim))
    vector = [c for c in TestLutsUnit()._cases(prim) if c.style == "vector"]
    assert any(mutant_fails(c, UNIT.root, f"{prim}.C1", mutant) for c in vector)
```

- [ ] **Step 4: Generate and check** (Task A3, Steps 2–3). Expected:
- `luts_tests.py` prints `wrote 6 files under tests/7series/clb/<PRIM>` for LUT1–LUT6 and LUT6_2, and `wrote 4 files` for CFGLUT5 (its sv testbenches are Task B4's hand-written ones). The `test.yaml` files hold LUT1 9 tests, LUT2 9, LUT3–LUT6 10 each, LUT6_2 12 and CFGLUT5 18 (88). The sv wrappers name `luts_x_tb.svh`/`luts_gsr_tb.svh`, which Task B4 adds: the Task A4 run needs them, the generator does not.
- `pytest tests/7series/clb/_shared/luts`: `164 passed` (97 model tests; 56 `UnitGuards` cases, seven guards × eight primitives; eleven unit checks). The reach, purity and mutant guards replay all 706 vector configurations (once, cached) in about 25 s.
- `xut lint`: no errors. Expected warnings: `portability-agreement` for the 7 `L1.sv_x_inputs` and 7 `L0.illegal_init` tests of LUT1–LUT6/LUT6_2 that declare `verilator: "unsupported"` for an x stimulus or an x attribute (decision D12). CFGLUT5's declarations match its `no` row and raise none.
- `xut run 'unit:luts' --runner python`: `exit=0`; 64 vector tests `pass`, 24 sv/cocotb tests `skip` (`SV_PY`, `CO_PY`). `L1.gsr_transparent` and `L1.gsr_after_reconfig` stimuli are `hw_renderable no` ("glbl GSR on hardware needs the GSR-immune harness …"); every other vector stimulus is `hw_renderable yes`.

The start of the generated `tests/7series/clb/LUT3/test.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# GENERATED by tests/7series/clb/_shared/luts/luts_tests.py; edit that file.
primitive: LUT3
family: 7series
work_unit: luts
doc_refs:
- guide: UG953
  version: '2026.1'
  section: LUT3
  page: 494
tests:
- id: 7series.LUT3.L0.smoke
  level: L0
  style: vector
  source: vectors/gen.py:l0_smoke
  exercises:
  - port:O
  - port:I0
  - port:I0:0
  - port:I0:1
  …
```

- [ ] **Step 5: Commit** (Task A3, Step 4): `luts: add shared stimulus recipes, the file generator and its guards`, then `luts: add the generated LUT1-LUT6, LUT6_2 and CFGLUT5 test files`.

---

### Task B4: sv tests (Task A4)

**Files:**
- Create: `tests/7series/clb/_shared/luts/luts_x_tb.svh`, `luts_gsr_tb.svh`
- Create: `tests/7series/clb/CFGLUT5/sv/tb_cfglut5_x.sv`, `tb_cfglut5_gsr.sv` (hand-written: CFGLUT5's ports fit no shared body)
- Generated already (Task B3): the 14 LUT wrappers `tests/7series/clb/{LUT1..LUT6,LUT6_2}/sv/tb_<prim>_{x,gsr}.sv`

What each test checks (documented) and records (checkpoints):

| Test | Checks | Checkpoints |
|---|---|---|
| LUTn/LUT6_2 `sv_x_inputs` | every address reads INIT[address] (O5: INIT[address mod 32]) | x on each input where the two INIT bits it selects agree (`X<k>.same`) and differ (`X<k>.diff`); every input x (`Xall`) |
| LUTn/LUT6_2 `sv_gsr_midsim` | every address before GSR rises and after it falls | the output when GSR rises, at every address while it is high, when it falls |
| CFGLUT5 `sv_x_inputs` | all-ones INIT reads 1 on O6/O5/CDO everywhere, before and after CE-Low cycles with CDI = x | x on each I input; one CE-High shift of x read everywhere; CE = x |
| CFGLUT5 `sv_gsr_midsim` | all ones at start; after 32 zero shifts every address reads 0; after 32 one shifts, 1 | every address while GSR is high and after it falls |

The CFGLUT5 checks hold whatever the (undocumented) bit order is: uniform contents, and 32 shifts that replace every bit.

- [ ] **Step 1: Write the shared bodies**

`tests/7series/clb/_shared/luts/luts_x_tb.svh`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// X-input test shared by the luts unit (LUT1-LUT6, LUT6_2; spec §4.3 sv style).
// The including file defines LUT_TB (the module name), LUT_N (the input count) and
// LUT_INST (one instance of the primitive on I[LUT_N-1:0] and O; LUT6_2 puts O6 on O and
// O5 on O5, and also defines LUT_DUAL). INIT is a module parameter (test.yaml configs).
// Checked (documented, the logic table): every defined address reads INIT[address]
// (claim C1; for LUT6_2 also O5 = INIT[address mod 32], claim C2).
// Checkpoints only (UG953 does not define x behaviour): for each input k, x on I[k] where
// the two INIT bits it selects agree (X<k>.same) and where they differ (X<k>.diff), then
// x on every input (Xall). xut crosscheck compares them between simulators.
`timescale 1ps / 1ps
module `LUT_TB #(
    parameter [(1 << `LUT_N) - 1:0] INIT = {(1 << `LUT_N){1'b0}}
);
`include "xut_trace.svh"
  // No declaration initialiser: a combinational UNISIM model can miss one at time 0.
  // The inputs get their first value by a time-0 non-blocking update instead, as in the
  // vector testbench, after every model process is waiting.
  reg [`LUT_N-1:0] I;
  wire O;
`ifdef LUT_DUAL
  wire O5;
`endif
  `LUT_INST

  integer a, k;
  reg same_done, diff_done;

  task automatic point(input integer kk, input reg same);
    begin
      xut_open;
`ifdef LUT_DUAL
      if (same) $fdisplay(xut_fd, "X%0d.same  O6=%b O5=%b", kk, O, O5);
      else $fdisplay(xut_fd, "X%0d.diff  O6=%b O5=%b", kk, O, O5);
`else
      if (same) $fdisplay(xut_fd, "X%0d.same  O=%b", kk, O);
      else $fdisplay(xut_fd, "X%0d.diff  O=%b", kk, O);
`endif
    end
  endtask

  initial begin
    I <= {`LUT_N{1'b0}};
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    for (a = 0; a < (1 << `LUT_N); a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("O.a", a, O, INIT[a])
`ifdef LUT_DUAL
      `XUT_CHECKN("O5.a", a, O5, INIT[a%32])
`endif
    end
    for (k = 0; k < `LUT_N; k = k + 1) begin
      same_done = 1'b0;
      diff_done = 1'b0;
      for (a = 0; a < (1 << `LUT_N); a = a + 1) begin
        if (((a >> k) & 1) == 0 && !same_done && INIT[a] == INIT[a|(1<<k)]) begin
          same_done = 1'b1;
          I = a;
          I[k] = 1'bx;
          #1000;
          point(k, 1'b1);
        end
        if (((a >> k) & 1) == 0 && !diff_done && INIT[a] != INIT[a|(1<<k)]) begin
          diff_done = 1'b1;
          I = a;
          I[k] = 1'bx;
          #1000;
          point(k, 1'b0);
        end
      end
    end
    I = {`LUT_N{1'bx}};
    #1000;
    xut_open;
`ifdef LUT_DUAL
    $fdisplay(xut_fd, "Xall  O6=%b O5=%b", O, O5);
`else
    $fdisplay(xut_fd, "Xall  O=%b", O);
`endif
    xut_finish;
  end
endmodule
```

`tests/7series/clb/_shared/luts/luts_gsr_tb.svh`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// GSR mid-simulation test shared by the luts unit (LUT1-LUT6, LUT6_2; spec §4.3 sv style).
// The including file defines LUT_TB, LUT_N, LUT_INST and (LUT6_2) LUT_DUAL, as for
// luts_x_tb.svh. INIT is a module parameter (test.yaml configs).
// Checked (documented, the logic table): every address before GSR rises and after it falls.
// Checkpoints only (UG953 names no GSR effect on a LUT): the output when GSR rises
// (G.rise), at every address walked while it is high (G.a<n>) and when it falls (G.fall).
`timescale 1ps / 1ps
module `LUT_TB #(
    parameter [(1 << `LUT_N) - 1:0] INIT = {(1 << `LUT_N){1'b0}}
);
`include "xut_trace.svh"
  // No declaration initialiser: a combinational UNISIM model can miss one at time 0.
  // The inputs get their first value by a time-0 non-blocking update instead, as in the
  // vector testbench, after every model process is waiting.
  reg [`LUT_N-1:0] I;
  wire O;
`ifdef LUT_DUAL
  wire O5;
`endif
  `LUT_INST

  integer a;

  task automatic point(input integer n);  // G.a<n>: address n while GSR is high
    begin
      xut_open;
`ifdef LUT_DUAL
      $fdisplay(xut_fd, "G.a%0d  O6=%b O5=%b", n, O, O5);
`else
      $fdisplay(xut_fd, "G.a%0d  O=%b", n, O);
`endif
    end
  endtask

  task automatic edge_point(input reg rise);  // G.rise / G.fall
    begin
      xut_open;
`ifdef LUT_DUAL
      if (rise) $fdisplay(xut_fd, "G.rise  O6=%b O5=%b", O, O5);
      else $fdisplay(xut_fd, "G.fall  O6=%b O5=%b", O, O5);
`else
      if (rise) $fdisplay(xut_fd, "G.rise  O=%b", O);
      else $fdisplay(xut_fd, "G.fall  O=%b", O);
`endif
    end
  endtask

  task automatic check_all(input reg after);
    integer b;
    begin
      for (b = 0; b < (1 << `LUT_N); b = b + 1) begin
        I = b;
        #1000;
        if (after) begin
          `XUT_CHECKN("post.O.a", b, O, INIT[b])
        end else begin
          `XUT_CHECKN("pre.O.a", b, O, INIT[b])
        end
`ifdef LUT_DUAL
        if (after) begin
          `XUT_CHECKN("post.O5.a", b, O5, INIT[b%32])
        end else begin
          `XUT_CHECKN("pre.O5.a", b, O5, INIT[b%32])
        end
`endif
      end
    end
  endtask

  initial begin
    I <= {`LUT_N{1'b0}};
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    check_all(1'b0);
    I = {`LUT_N{1'b1}};
    #1000;
    glbl.GSR_int = 1'b1;
    #1000;
    edge_point(1'b1);
    for (a = 0; a < (1 << `LUT_N); a = a + 1) begin
      I = a;
      #1000;
      point(a);
    end
    glbl.GSR_int = 1'b0;
    #1000;
    edge_point(1'b0);
    check_all(1'b1);
    xut_finish;
  end
endmodule
```

The generated wrappers look like this one, `tests/7series/clb/LUT6_2/sv/tb_lut6_2_x.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.LUT6_2.L1.sv_x_inputs (body: _shared/luts/luts_x_tb.svh)
`define LUT_TB tb_lut6_2_x
`define LUT_N 6
`define LUT_DUAL
`define LUT_INST LUT6_2 #(.INIT(INIT)) dut (.O6(O), .O5(O5), .I0(I[0]), .I1(I[1]), .I2(I[2]), .I3(I[3]), .I4(I[4]), .I5(I[5]));
`include "luts_x_tb.svh"
```

- [ ] **Step 2: Write the CFGLUT5 testbenches**

`tests/7series/clb/CFGLUT5/sv/tb_cfglut5_x.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.CFGLUT5.L1.sv_x_inputs. INIT is a module parameter; test.yaml sets it to all
// ones, so every documented check below holds whatever the (undocumented) bit order is.
// Checked (documented): every address reads 1 on O6, O5 and CDO (C1, C2); CE Low with
// CDI = x and CLK running leaves that unchanged (C4).
// Checkpoints only (UG953 does not define x behaviour): x on each I input (I<k>.x), one
// CE-High shift of CDI = x read at every address (S.a<n>), then CE = x (E.a0, E.a31).
`timescale 1ps / 1ps
module tb_cfglut5_x #(
    parameter [31:0] INIT = 32'hFFFF_FFFF
);
`include "xut_trace.svh"
  // Inputs start x and get their first values by a time-0 non-blocking update, as in
  // the vector testbench (a declaration initialiser can race the model at time 0).
  reg [4:0] I;
  reg CDI, CE, CLK;
  wire CDO, O5, O6;
  CFGLUT5 #(.INIT(INIT)) dut (
      .CDO(CDO), .O5(O5), .O6(O6), .CDI(CDI), .CE(CE), .CLK(CLK),
      .I0(I[0]), .I1(I[1]), .I2(I[2]), .I3(I[3]), .I4(I[4])
  );

  integer a, k;

  task automatic cycle;
    begin
      #4000 CLK = 1'b1;
      #5000 CLK = 1'b0;
      #1000;
    end
  endtask

  task automatic check_ones(input reg after_hold);
    integer b;
    begin
      for (b = 0; b < 32; b = b + 1) begin
        I = b;
        #1000;
        if (after_hold) begin
          `XUT_CHECKN("hold.O6.a", b, O6, 1'b1)
          `XUT_CHECKN("hold.O5.a", b, O5, 1'b1)
          `XUT_CHECKN("hold.CDO.a", b, CDO, 1'b1)
        end else begin
          `XUT_CHECKN("init.O6.a", b, O6, 1'b1)
          `XUT_CHECKN("init.O5.a", b, O5, 1'b1)
          `XUT_CHECKN("init.CDO.a", b, CDO, 1'b1)
        end
      end
    end
  endtask

  initial begin
    I <= 5'd0;
    CDI <= 1'b0;
    CE <= 1'b0;
    CLK <= 1'b0;
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    check_ones(1'b0);
    CE = 1'b0;  // C4: CE Low holds, even with CDI = x
    CDI = 1'bx;
    cycle;
    cycle;
    cycle;
    check_ones(1'b1);
    xut_open;
    for (k = 0; k < 5; k = k + 1) begin
      I = 5'd0;
      I[k] = 1'bx;
      #1000;
      $fdisplay(xut_fd, "I%0d.x  O6=%b O5=%b CDO=%b", k, O6, O5, CDO);
    end
    CE = 1'b1;  // one shift of an x bit
    cycle;
    CE = 1'b0;
    CDI = 1'b0;
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      $fdisplay(xut_fd, "S.a%0d  O6=%b O5=%b CDO=%b", a, O6, O5, CDO);
    end
    CE = 1'bx;  // CE = x with CDI = 0
    cycle;
    CE = 1'b0;
    I = 5'd0;
    #1000;
    $fdisplay(xut_fd, "E.a0  O6=%b O5=%b CDO=%b", O6, O5, CDO);
    I = 5'd31;
    #1000;
    $fdisplay(xut_fd, "E.a31  O6=%b O5=%b CDO=%b", O6, O5, CDO);
    xut_finish;
  end
endmodule
```

`tests/7series/clb/CFGLUT5/sv/tb_cfglut5_gsr.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.CFGLUT5.L1.sv_gsr_midsim. INIT is a module parameter; test.yaml sets all ones.
// Checked (documented, whatever the undocumented bit order): all ones read 1 everywhere
// (C1, C6); 32 CE-High shifts of 0 replace the whole function, so every address then
// reads 0 (C3); 32 shifts of 1 after the GSR pulse read 1 everywhere again.
// Checkpoints only (UG953 names no GSR effect on CFGLUT5): every address while GSR is
// high (G.hi.a<n>) and after it falls (G.lo.a<n>): is INIT reloaded, or the zeros kept?
`timescale 1ps / 1ps
module tb_cfglut5_gsr #(
    parameter [31:0] INIT = 32'hFFFF_FFFF
);
`include "xut_trace.svh"
  // Inputs start x and get their first values by a time-0 non-blocking update, as in
  // the vector testbench (a declaration initialiser can race the model at time 0).
  reg [4:0] I;
  reg CDI, CE, CLK;
  wire CDO, O5, O6;
  CFGLUT5 #(.INIT(INIT)) dut (
      .CDO(CDO), .O5(O5), .O6(O6), .CDI(CDI), .CE(CE), .CLK(CLK),
      .I0(I[0]), .I1(I[1]), .I2(I[2]), .I3(I[3]), .I4(I[4])
  );

  integer a;

  task automatic cycle;
    begin
      #4000 CLK = 1'b1;
      #5000 CLK = 1'b0;
      #1000;
    end
  endtask

  task automatic reload(input reg bit_value);
    integer s;
    begin
      CE = 1'b1;
      CDI = bit_value;
      for (s = 0; s < 32; s = s + 1) cycle;
      CE = 1'b0;
    end
  endtask

  initial begin
    I <= 5'd0;
    CDI <= 1'b0;
    CE <= 1'b0;
    CLK <= 1'b0;
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("init.O6.a", a, O6, 1'b1)
    end
    reload(1'b0);
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("zero.O6.a", a, O6, 1'b0)
      `XUT_CHECKN("zero.O5.a", a, O5, 1'b0)
      `XUT_CHECKN("zero.CDO.a", a, CDO, 1'b0)
    end
    glbl.GSR_int = 1'b1;
    #1000;
    xut_open;
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      $fdisplay(xut_fd, "G.hi.a%0d  O6=%b O5=%b CDO=%b", a, O6, O5, CDO);
    end
    glbl.GSR_int = 1'b0;
    #1000;
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      $fdisplay(xut_fd, "G.lo.a%0d  O6=%b O5=%b CDO=%b", a, O6, O5, CDO);
    end
    reload(1'b1);
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("one.O6.a", a, O6, 1'b1)
    end
    xut_finish;
  end
endmodule
```

- [ ] **Step 3: Run** (Task A4, Step 2, with `'unit:luts'`). Expected:
- LUT1–LUT6, LUT6_2: `sv_gsr_midsim` `pass` on iverilog, xsim, verilator and iverilog-vz; `sv_x_inputs` `pass` on iverilog and xsim, `skip` (`X_VL`) on verilator and iverilog-vz.
- CFGLUT5: both `pass` on iverilog and xsim, `skip` (`CFG_VL`) on verilator and iverilog-vz.
- `XUT_CHECKS` per configuration: LUTn `sv_x_inputs` 2^n (LUT6_2 128), `sv_gsr_midsim` 2 × 2^n (LUT6_2 256); CFGLUT5 192 and 160.

- [ ] **Step 4: Commit** with `luts: add shared GSR and X-input sv testbenches and the CFGLUT5 ones`.

---

### Task B5: cocotb session (Task A5)

**Files:**
- Create: `tests/7series/clb/_shared/luts/luts_cocotb.py`
- Generated already (Task B3): `tests/7series/clb/<PRIM>/cocotb/cocotb_<prim>_random.py` (8)

- [ ] **Step 1: Write the session**

```python
# SPDX-License-Identifier: Apache-2.0
"""Constrained-random cocotb session shared by the luts unit (spec §4.3 cocotb style).

Runs inside the xut-sim container. Every input is driven to 0 first (ruling S37(2)), then
the power-on value is compared right after GSR releases (step-2 review: never leave the
first comparison to luck). Each step then changes a random subset of the LUT inputs at
once, or (CFGLUT5) runs one CLK cycle with random CE and CDI, applies the same events to
the golden model and compares every output. Every comparison point is written to
trace.xtr. When a seed fails, freeze it: copy the session into vectors/frozen/<seed>.xvec
as a new vector test (xut freeze-seed is deferred).
"""

import os
import random

from luts_recipes import KINDS

from xut.cocotb_dut import XutDut
from xut_models.registry import get

#: the chance a step is a CFGLUT5 reload (one CLK cycle), and that the reload has CE High
RELOAD_P = 0.3
CE_HIGH_P = 0.7
#: the chance each LUT input changes in an input step
MOVE_P = 0.5


async def random_session(dut: object, prim: str, steps: int = 2000) -> None:
    k = KINDS[prim]
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    model = get("7series", prim)(x.attrs)
    rng = random.Random(int(os.environ["XUT_SEED"]))
    model.power_on()
    idle = {p: 0 for p in model.inputs() if p not in model.CLOCKS}
    await x.set(**idle)
    for p, v in idle.items():
        model.set_input(p, v)
    await x.settle()  # 120 ns: glbl releases GSR at 100 ns
    model.glbl("GSR", 0)
    errors: list[str] = []
    n = 0

    def check() -> None:
        nonlocal n
        exp = model.outputs()
        x.sample(f"S{n}", {p: o.prov for p, o in exp.items()})
        for p, o in exp.items():
            got = x.get(p)
            # The luts models never emit a don't-care; keep the guard for spec §5.3.
            if o.bits != "-" and got != o.bits:
                errors.append(f"S{n}: {p}={got}, model {o.bits} ({o.prov})")
        n += 1

    check()  # the power-on value (C2/C3/C6), before the first draw can change it
    for _ in range(steps):
        if k.reconfig and rng.random() < RELOAD_P:
            ports = {"CE": int(rng.random() < CE_HIGH_P), "CDI": rng.randrange(2)}
            await x.set(**ports)
            for p, v in ports.items():
                model.set_input(p, v)
            for rising in (True, False):
                await x.edge("CLK", rising)
                model.clock_edge("CLK", rising)
                check()
            continue
        moved = [i for i in range(k.n) if rng.random() < MOVE_P] or [rng.randrange(k.n)]
        ports = {f"I{i}": rng.randrange(2) for i in moved}
        await x.set(**ports)
        for p, v in ports.items():
            model.set_input(p, v)
        check()
    x.close()
    assert not errors, f"{len(errors)} mismatch(es); first: {errors[:5]}"
```

A generated module, `tests/7series/clb/CFGLUT5/cocotb/cocotb_cfglut5_random.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""7series.CFGLUT5.L2.cocotb_random: random CFGLUT5 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def cfglut5_random(dut: object) -> None:
    await random_session(dut, "CFGLUT5", steps=2000)
```

- [ ] **Step 2: Run** (Task A5, Step 2). Expected: LUT1–LUT6 and LUT6_2 `pass` on iverilog, verilator and iverilog-vz; CFGLUT5 `pass` on iverilog, `skip` (`CFG_VL`) on verilator and iverilog-vz; every test `skip` (`CO_XS`) on xsim. Each configuration's trace holds 2001 samples for a LUT (2000 steps plus the power-on comparison) and more for CFGLUT5 (a reload step samples after both edges).

- [ ] **Step 3: Commit** with `luts: add the shared cocotb random session`.

---

### Task B6: Full run, crosscheck, findings and status (Task A6)

- [ ] **Step 1: Estimate.** 706 vector configurations + 23 sv + 32 cocotb. xsim dominates: (706 + 23) × about 15 s ÷ 4 slots ≈ 45 minutes. Verilator: about 630 builds (CFGLUT5 excluded) × 30–40 s ÷ 16 ≈ 20–25 minutes, in parallel with xsim. Expect 45–60 minutes in total: under 4 hours, so report every 5 minutes, with the remaining time and the finish clock-time, from the `progress:` lines. The `unisim-gh-2020.1` run (python, iverilog, verilator) takes about 25 minutes more.

- [ ] **Step 2: Run, crosscheck, handle findings, record** exactly as Task A6, Steps 1–6, with `<unit>` = `luts`. What to expect, and what is **not** to be "fixed":

- **Record the order UNISIM shows** (ruling S52) in the two Task B1 findings, per model source, under their `(to be recorded)` lines. If crosscheck reports no disagreement on `L1.projections`, `L1.partial_shift`, `L1.cdo_cascade` and `L2.init_sweep`, UNISIM follows the inferred order: write that ("UNISIM <source> on iverilog and xsim: O6 = INIT[{I4..I0}] … as inferred; tests … agree"). If it disagrees, crosscheck appends `- Also seen:` lines to these two files and writes stubs for the other affected tests; describe the order the evidence points to (the mismatching points name the address, the output and the expected bit). Either way the findings stay open, the model is not changed, and `expected_divergence` entries (if any) name these findings.
- The LUT1–LUT6/LUT6_2 logic tables are complete, so a disagreement there is `doc-vs-model`: re-read the table page first (a model bug is fixed with a test); otherwise it is a finding against UNISIM.
- `L1.gsr_transparent` and `L1.gsr_after_reconfig` compare the D6 inferences: a disagreement is a `doc-gap`. Write it up, list it, keep the inference.
- CFGLUT5's O5/O6/CDO bit order is inferred (D5): if every simulator disagrees with it, crosscheck reports `doc-gap` on `L1.projections`, `L1.partial_shift`, `L1.cdo_cascade`, `L2.init_sweep` and others. That is one root cause; write one analysis and reference it from each test's finding (each has its own id: `CFGLUT5-doc-gap-<level>-<name>`). Never change the order to match: UG953 does not state it (the clean-room rule).
- **A mismatch on a `doc:` bit of `L1.edge_polarity`** is not the order: it is a clock-edge or `IS_CLK_INVERTED` divergence (`doc-vs-model`), analysed on its own, never folded into the order finding.
- `L0.illegal_init`: apply the reject-test rule of Task A6 if the simulators accept an all-x INIT.
- The sv checkpoints (x and GSR) are compared between iverilog and xsim only (Verilator is unsupported for them): a difference is a `sim-divergence`.
- **Expected `coverage.uncovered`**: empty for every primitive when every documented bit agrees. The order-dependent CFGLUT5 configurations fail if UNISIM's order differs from D5, and then credit nothing (spec §9, S21/S23), but every CFGLUT5 claim and bin is also reached by a pure configuration (`L1.edge_polarity`, `L1.default_init`), which the guard `test_every_exercised_bin_has_a_pure_configuration` pins, so coverage does not depend on the order. P1 is what lets `attr:INIT` be credited at all.

- [ ] **Step 3: Log** `log/<ts>-unit-7series-luts-results.md` and commit it.

---

### Task B7: The luts PR (Task A7)

Title "luts: LUT1-LUT6, LUT6_2 and CFGLUT5". The body also states: the D5/D6 inferences, rulings S52/S53/S55's effect on CFGLUT5's claims (known-uniform tracking, the pure `L1.edge_polarity`, credit only on deciding events, a failing mutant per claim), the two open CFGLUT5 `doc-gap` findings; the CFGLUT5 Verilator declaration and the S29(2) TODO; that every vector test declares `hw: "yes"` except the two GSR tests and the reject tests, pending Task B8.

---

### Task B8: luts on hardware (Task A8; step-3 Task 13)

Run Task A8 with `<unit>` = `luts` once step-3 PRs A–C and the luts PR have merged. This is the step-3 plan's Task 13; its LUT6 smoke design (step-3 Task 11) is the stand-in until then.

- The declarations need no change: every vector test is `hw: "yes"` with `flows` including `vivado`, except `L1.gsr_transparent`, `L1.gsr_after_reconfig` (`HW_GSR`) and `L0.illegal_init` (`HW_REJ`); sv and cocotb tests are `SV_HW`/`CO_HW`. No luts primitive is site-constrained (`HW_PAD` does not apply).
- CFGLUT5's CLK is a stepped clock: one BUFG per slot. Its 13 hardware tests fit one or two bitstreams each (≤ 64 slots).
- Bitstreams: step 3 packs per test, at most 64 slots each, so `L2.init_sweep` of LUT6 and LUT6_2 (130 configurations) needs 3 bitstreams each, and the unit about 54 in all (LUT1 4, LUT2 4, LUT3 5, LUT4 5, LUT5 6, LUT6 7, LUT6_2 9, CFGLUT5 14). At 20–40 minutes each over 4 Vivado slots that is about 4.5–9 hours: report every 15 minutes. If that is too long, ask the orchestrator for the cross-test packing step 3 left for later (its ambiguity 10) rather than dropping configurations.
- A `silicon-mismatch` on CFGLUT5's inferred bit order is still a finding against the golden model's inference: it is evidence, recorded with both boards' results; it does not change the model (silicon is the ground truth for the *finding*, UG953 for the *model*).

---

## Appendix W: the fan-out worksheet

The approved order starts luts, latches, muxf, carry, srl, lutram, rom, ddr_regs, bufg; the rest follows spec §16 step 5's group order and is **provisional** (the orchestrator sets it). Portability cells are from the 2026-09-27 smoke run of PR #10 (both model sources), before ruling S51 re-labelled model attribute checks as `no: config:`; **re-read `status/PORTABILITY.md` on `main` at intake** (Task A1, Step 2.3), because it is regenerated after every infra merge.

Infra that later units need, beyond Task P1 (each is an `infra/*` branch the unit stacks on or waits for, AGENTS.md §13):

- **P2 `smoke_attrs`** (ruling S51.5): an overrides key giving the portability smoke run a legal configuration, so a `no: config:` row becomes a real verdict. Needed by bram, dsp, mmcm_pll (and possibly xadc). Until then the unit declares `"yes"`, lives with the lint warning, and its own L0 proves elaboration.
- **P3 clock observers** (spec §5.4): the wrapper refuses a `clock_out` port until they exist, so vector and cocotb tests of bufg, regional_clk and mmcm_pll cannot be generated; their sv tests can be written first.
- **P4 DRP transactions** (spec §5.5): mmcm_pll and xadc.
- **P5 the pad harness** (spec §7.3) for hardware: ddr_regs, every io unit, BUFIO/BUFR, gt_buf.
- **P6 real-time rendering** of free-running clocks for hardware: mmcm_pll, IDELAYCTRL's REFCLK.
- **The srl/CFGLUT5 recovery** of ruling S29(2) (verilatorize: a trigger cone that crosses a non-blocking-written reg, S28): until it lands, SRL16E, SRLC32E and CFGLUT5 have no Verilator results.

| # | Unit (group) | Primitives | Portability at intake (iverilog / verilator) | Hardware class | Notes for the unit |
|---|---|---|---|---|---|
| 1 | luts (clb) | LUT1–LUT6, LUT6_2, CFGLUT5 | all yes / yes, except CFGLUT5 verilator no (S28) | renderable (no clock; CFGLUT5 stepped CLK) | Part B. Needs P1. |
| 2 | latches (register) | LDCE, LDPE | yes / yes (transformed, equiv pass) | renderable; G is `gate` class, CLR/PRE `async` | Closest to flops: copy its structure. Declare `active` levels for G, CLR and PRE; the gate transparency (Q follows D while G and GE are active) needs checks at gate edges and in the transparent window; GSR tests `HW_GSR`. |
| 3 | muxf (clb) | MUXF7, MUXF8 | yes / yes (unchanged) | renderable if a stand-alone MUXF7/F8 places; check UG953 for a rule that its inputs must come from LUTs/MUXF7s | Combinational, like luts; exhaustive over I0, I1, S. A placement rule UG953 states is a claim listed in `gaps` for simulation and a `config_exclusions.hw`/`unsupported` reason on hardware. |
| 4 | carry (clb) | CARRY4 | yes / yes (transformed, pass) | renderable | 4-bit `DI`/`S` buses: per-bit `port:<P>[i]:0/1` bins. Exhaustive over CI/CYINIT and the buses is 2^10 per configuration: sample by walking bits plus seeded random, and document the choice in `attr_sampling`/`gaps`. |
| 5 | srl (clb) | SRL16E, SRLC32E | yes / no (S28, as CFGLUT5) | renderable (stepped CLK) | Every test `verilator: "unsupported"` with the S28/S29(2) reason (as luts' `CFG_VL`). INIT is non-enumerated (P1). Shift direction and Q/Q31 taps: read UG953's own tables; do not reuse CFGLUT5's inference. |
| 6 | lutram (clb) | 12 RAM* | yes / yes; RAM32X1S_1, RAM32X2S, RAM64X1S_1 gated on a transformed child (equiv pass) | renderable (stepped WCLK) | `_1` variants write on the falling edge. Multi-bit addresses and INITs (P1). A gated row's Verilator results depend on its child's equivalence verdict: re-read the row if the child's equiv changes. |
| 7 | rom (clb) | ROM32X1, ROM64X1, ROM128X1, ROM256X1 | 2025.2 only: yes / yes (unchanged); no gh-2020.1 row | renderable | Check at intake whether the gh-2020.1 source has these models; if not, that source's runners are `n/a` for them, with the reason, as Task A6 Step 3 says (run and record the gh source only for primitives it has). |
| 8 | ddr_regs (register) | IDDR, IDDR_2CLK, ODDR | yes / yes (transformed, pass) | site-constrained (spec §7.3): hw `unsupported` (`HW_PAD`) until P5 | `S`/`R` are `async` under `SRTYPE="ASYNC"` and `data` under `"SYNC"`: declare the per-configuration class (AGENTS.md catalog notes). Both clock edges; DDR_CLK_EDGE modes. |
| 9 | bufg (clock) | BUFG, BUFGCE, BUFGCE_1, BUFGCTRL, BUFGMUX, BUFGMUX_1, BUFGMUX_CTRL | yes / BUFG, BUFGCE yes; BUFGCTRL family no (Verilator smoke timeout; several gated on BUFGCTRL) | clock observers first (P3) | Blocked on P3 for vector and cocotb tests; write the sv tests first. BUFGCTRL's S0/S1/CE0/CE1 are `async` with a glitch-free switching claim set. |
| 10 | bram (blockram) | RAMB18E1, RAMB36E1 | no: config (READ_WIDTH/WRITE_WIDTH attribute check) / no (verilatorize: nested generate) | renderable (stepped clocks) | Needs P1 (INIT_xx, INITP_xx) and P2. A legality model for READ_WIDTH × WRITE_WIDTH × RAM_MODE (declared crosses, legal pairs only). Verilator unsupported until nested generates are handled. |
| 11 | bram_fifo (blockram) | FIFO18E1, FIFO36E1 | yes / yes, but equiv error (SIM_DEVICE) | renderable | Equivalence `error` blocks Verilator: declare it unsupported (lint rule `verilatorize-equiv`). Flag latencies are ranges in UG953: property checks (spec §3), CDC in L3. |
| 12 | dsp (arithmetic) | DSP48E1 | no: config (ACASCREG vs AREG) / no; equiv error | renderable | The attribute rules are the legality model; the spec §4.2 crosses (AREG/BREG × ACASCREG × INMODE). Needs P1, P2. |
| 13 | regional_clk (clock) | BUFH, BUFHCE, BUFIO, BUFMR, BUFMRCE, BUFR | yes / BUFHCE, BUFMRCE no (gated BUFGCTRL timeout) | P3; BUFIO, BUFR and BUFMR are site-constrained: hw `unsupported` (`HW_PAD`) until P5 | BUFR's divide modes; BUFMR/BUFMRCE drive BUFIO/BUFR in L3 designs. |
| 14 | mmcm_pll (clock) | MMCME2_ADV, MMCME2_BASE, PLLE2_ADV, PLLE2_BASE | no: config (CLKIN periods) / no (S28; MMCME2 also an `@*` refusal) | P6 and P3; hw `unsupported` meanwhile | Needs free-running clocks (`mode=free`), clock observers (P3), DRP (P4) and smoke_attrs (P2). Largest unit; last among clocks. |
| 15 | ibuf (io) | 9 IBUF* | yes / IBUFDS, IBUFDS_IBUFDISABLE, IBUFDS_INTERMDISABLE no (z-compare of an internal net, S38) | P5 (`HW_PAD`) | `pad`-class inputs are wired as data in simulation; the pad harness is hardware-only. |
| 16 | obuf (io) | OBUF, OBUFDS, OBUFT, OBUFTDS | yes / yes | P5 (`HW_PAD`); differential outputs `unsupported` on the Arty (3.3 V banks) | OBUFT's tristate output is observed as z in 4-state simulators only (x/z not observable on Verilator and hw, spec §5.6). |
| 17 | iobuf (io) | 9 IOBUF* | yes / 6 of 9 no (z-compare on the inout or an internal net, S38) | P5 (`HW_PAD`) | `inout` ports split into drive_en/drive_val/obs (spec §5.1); bins drive0/drive1/release. |
| 18 | weak_drivers (io) | KEEPER, PULLDOWN, PULLUP | yes / no (strength specifiers) | P5 | Strength resolution is visible only on 4-state simulators; design the checks around resolved values. |
| 19 | dci (io) | DCIRESET | yes / yes | check whether the Arty has DCI-capable banks; else `unsupported` | Small. |
| 20 | delay (io) | IDELAYCTRL, IDELAYE2, ODELAYE2 | yes / yes (IDELAYE2, ODELAYE2 transformed, pass) | site-constrained: `HW_PAD` until P5; P6 (200 MHz REFCLK) | `min_event_gap_ps` about 2.4 ns (spec §5.1); tap state through CNTVALUEOUT, never absolute delay (spec §2). |
| 21 | serdes (io) | ISERDESE2, OSERDESE2 | no / no (secureip `B_*SERDESE2` missing) | site-constrained: `HW_PAD` until P5 | Only xsim can run them; iverilog and verilator are `unsupported` (secureip). |
| 22 | phy_fifo (io) | IN_FIFO, OUT_FIFO | no / no (secureip) | P5 | xsim only, as serdes. |
| 23 | config_jtag (configuration) | BSCANE2, CAPTUREE2 | yes / BSCANE2 no (tristate construct) | host-driven JTAG (spec §7.4) | JTAG glbl signals are sim-only; the hw path drives JTAG from the Pi. |
| 24 | config_id (configuration) | DNA_PORT, EFUSE_USR, USR_ACCESSE2 | yes / yes | host-read values (spec §7.4) | The runner passes the board's DNA/eFUSE as `SIM_DNA_VALUE`/`SIM_EFUSE_VALUE`; USR_ACCESSE2's value comes from a bitstream option. |
| 25 | config_icap (configuration) | ICAPE2, FRAME_ECCE2, STARTUPE2 | ICAPE2 no / no; STARTUPE2 yes / no (strength) | spec §7.4: IPROG forbidden; STARTUPE2 shared with the harness | ICAPE2's Icarus failure is a syntax error in the model (`other`). |
| 26 | xadc (advanced) | XADC | yes / yes | P4, analog pad pins, tolerances | Readings compared within tolerances (spec §7.4): property checks. `SIM_MONITOR_FILE` may need P2. |
| 27 | gt_buf (advanced) | IBUFDS_GTE2 | yes / yes | check whether the Arty's package bonds out GT reference-clock pins; else `unsupported` | Small. |

---

## Decisions on spec gaps (made while writing this plan)

The orchestrator ruled on PR #12: D4 is overruled by ruling S52 and refined by S53, D16 is confirmed, D1–D3 and D5–D15 are accepted; D17–D19 record ruling S53, and D20 ruling S55.

- **D1. `attr:<A>` for non-enumerated attributes was unreachable** (spec §9 names the bin; the python runner never produced it). Task P1 adds `xut.golden.coverage_reach`, which names bins exactly as `coverage_bins` does, and the python runner records it. Units with such attributes stack on P1.
- **D2. Parallelism and the heavy lock.** `xut run --jobs 16` in a 32G scope, not the 24 AGENTS.md §10.1 permits: 32G + 16 × 4G containers = 96G stays inside the project's 100G share, as the step-3 plan's budget (ruling S49 I5) requires; `--jobs 24` would reach 128G with the scope. Whole-suite pytest is `-n 4` in a 32G scope (96G after step 3, when a worker may start a 16G Vivado child); the unit's own tests run single-process, unscoped. Ruling S53 (correctness review M4): a budget is per command, so two agents' commands at once could reach 192G. Every heavy command therefore takes the one host-wide lock `$XDG_RUNTIME_DIR/xut-heavy.lock` (`flock … systemd-run …`), and Task P1 writes it into AGENTS.md §10.1.
- **D3. ANN exemption for unit tests** (`tests/**/test_*.py`), in P1: the flops unit's open TODO, and the stated intent of the existing `tools/tests/**` exemption.
- **D4 — overruled by ruling S52** (on PR #12, following S44). A CFGLUT5 output whose value depends on the inferred bit order (O6/O5 indexing, the shift direction, the bit on CDO) is decided by an inferred rule and credits nothing, even though the reconfiguration rule is documented. CFGLUT5.C1–C7 are credited only by order-independent outputs: uniform contents (all 0 or all 1, `doc:348`). Ruling S53 (correctness review M1–M3) sharpens it: order-free knowledge is tracked explicitly (`known`), never read off the contents computed under the inferred order; every credited claim has a **pure** configuration (all samples order-free), because a configuration with one mismatching inferred bit fails and credits nothing; and `L1.edge_polarity` applies the inactive edge alone from uniform contents, so a both-edges or wrong-edge simulator fails a documented bit. `L1.edge_polarity` is pure and credits C1–C7, so none moves to `gaps`, and a guard pins it. Two `doc-gap` stubs record the missing documentation (`findings/CFGLUT5-doc-gap-L1-projections.md`: the O5/O6 tables; `findings/CFGLUT5-doc-gap-L1-partial_shift.md`: the shift direction and the CDO bit), and Task B6 records there the order UNISIM shows.
- **D5. CFGLUT5's undocumented bit order**: O6 = INIT[{I4..I0}] (the LUT5 table, p501), O5 = INIT[{I3..I0}] (the lower half, as LUT6_2's O5, p509), CDI shifts into INIT[0], INIT[31] drives CDO; all-0 and all-1 contents are order-free and `doc:348`. Each inference carries its own reason. Checked in UG953 2026.1 text; the implementer confirms against the PDF (and the 2025.2 edition) that the "following tables" are really absent, and records it.
- **D6. GSR on LUTs and CFGLUT5.** UG953 names no GSR effect on any LUT. LUT outputs keep following the table while GSR is asserted; CFGLUT5 keeps its loaded function and keeps shifting. Both are `inferred:` and credit nothing (S44); `L1.gsr_transparent`/`L1.gsr_after_reconfig` and the sv GSR tests compare them with UNISIM.
- **D7. sv time-0 inputs.** Testbench input regs get their first value by a time-0 non-blocking assignment, not a declaration initialiser. Found while checking this plan's testbenches on Icarus: LUT6's output stayed x at the first check with a declaration initialiser, which raised no event for the combinational model. This is a testbench rule, not a finding; the vector testbench already works this way.
- **D8. Reject tests.** Every unit keeps its documented-illegal reject configurations; if both 4-state simulators accept one, the step-2 Task 24 rule applies (remove it, record the gap, log it). The flops unit observed UNISIM accepting `INIT=1'bx` on FD*; luts' all-x INIT may meet the same.
- **D9. INIT sampling for LUTs**: every value for an INIT of at most 4 bits (LUT1, LUT2); otherwise boundaries plus walking ones and zeros at every position (L2.init_sweep) and 16 seeded random values (L2.init_random); input projections in L1. `attr_sampling` records the plan as strings, which the schema allows.
- **D10. `hw: "yes"` from the first PR.** Vector tests declare the hardware runner (with flows `vivado`, `yosys`, `openxc7`, `vpr`) from the start, as flops does; status shows `not-run` until step 3's runner and step 4's flows exist, which keeps the TODO visible.
- **D11. `no: config:` rows keep `"yes"`** until P2 (`smoke_attrs`) exists: the lint rule makes them a warning, not an error, because the row says nothing about the simulator (ruling S51).
- **D12. Expected lint warnings.** Tests declaring `verilator: "unsupported"` for a property of the test (an x stimulus, an x attribute) draw a `portability-agreement` warning when the model's row says it runs; the lint message itself names an x stimulus as a valid reason. The unit lists them in its log instead of changing them.
- **D13. A simulator refusing a UG953-legal configuration** has no crosscheck class. The unit keeps the configuration, writes a `doc-vs-model` finding by hand and reports it; crosscheck exits 4 for that test until infra adds a rule.
- **D14. CFGLUT5's Verilator reason** cites the table (`status/PORTABILITY.md`), the refusal (ruling S28) and the recovery TODO (ruling S29(2)), without UNISIM's internal signal names.
- **D15. The portability table is read on `main` at intake**, never from a build directory: it is regenerated after every infra merge, and S51 changed its labels after the run Appendix W quotes.
- **D16. A unit refreshes its own never-recorded status stubs** with `xut status init --refresh-bins` after adding claims, and commits only its own files. AGENTS.md §7 reserves the command for the orchestrator on `main`, but adding claims makes the infra stub-invariant test fail on the unit branch, and the flops unit refreshed its own stubs the same way (commit 115f0cc). **Confirmed on PR #12.** Task P1 amends AGENTS.md §7 (infra-owned) to say so; the flops unit's 115f0cc is covered retroactively.
- **D17. `xut.unitkit`** (ruling S53, code-quality review M1). Generic metadata and guard code lives in infra, in Task P1, not in each unit: the standard reasons, test entries, bin names, the YAML dumper, the README skeleton, `vector_reach` (the python runner's `generate` and `replay_config`, not a copy) and `UnitGuards`. Units import it and never copy it or the flops code. The flops unit migrates in its own later PR (a TODO in P1's log). File stems are the unit name (`luts_recipes.py`, …), unique across units because pytest's default import mode shares one flat namespace (code-quality review M2).
- **D18. Site-constrained primitives are `hw: "unsupported"` by class** (ruling S53, correctness review M5): IDDR, IDDR_2CLK, ODDR, ISERDESE2, OSERDESE2, IDELAYE2, ODELAYE2, IDELAYCTRL, BUFIO, BUFR, BUFMR and the IBUF/OBUF/IOBUF families carry `unitkit.HW_PAD` until the pad harness (P5), even where no catalog port is pad-class and the validator would call the stimulus renderable.
- **D19. A model a source lacks is `n/a` on that source** (Task A6 Step 3): the unit runs, records and crosschecks that source only for the primitives it has, and gives the reason in the README and the log (the rom unit on `unisim-gh-2020.1`).
- **D20. Credit only on deciding events; a failing mutant per claim** (ruling S55, correctness re-review M6). A claim credits only on an event whose documented outcome depends on its rule: CFGLUT5 C3/C7 on the edge that sets `known` to a new value, C4 on a CE-Low edge whose CDI differs from `known`, C5 after a 32-shift run that flipped `known`. `L0.smoke` no longer exercises C3, and `L1.edge_polarity` drives the opposite CDI before its CE-Low edge. Generally (Part A, A2/A3): every claim a vector test exercises has a named mutant in the unit's `mutants(prim)` table (`{claim: mutant_model_factory}`, `Unit.mutants`), and `xut.unitkit.UnitGuards` (P1) asserts, through `mutant_fails`, that it fails a documented bit in at least one configuration crediting the claim. luts has one per claim (LUT INIT bit-order and default mutants, LUT6_2's O5-from-the-upper-32 mutant, CFGLUT5's never-shifting, CE-ignoring, CDO-stuck, INIT-ignoring and inversion-ignoring mutants), plus a reversed-INIT-order check.

---

## Self-review against the spec and the writing-plans checklist

**Spec coverage.**

- **§3 clean room and provenance**: Global Constraints, Task A2's rules, the luts model decisions (S52, D5, D6), the reviewer (b) checks in Task A7.
- **§4.1 levels**: L0 smoke and reject tests, L1 one test per claim, L2 exhaustive/sampled/random and cocotb; L3 stays with the integ branches (spec §16 step 5).
- **§4.2 sampling**: Task A3's rules; luts D9; crosses pairwise over legal pairs (legality model).
- **§4.3 styles**: vector (A3), sv (A4, with the common-subset and checkpoint rules), cocotb (A5, with seed freezing).
- **§5.1 classes and S8′**: `VecBuilder` enforces the classes; hardware declarations follow the renderability conditions (A3, A8).
- **§5.3 `-`**: only doc-declared undefined (A2).
- **§6.2**: portability cases per cell (A1 Step 2.3), `iverilog-vz` following Verilator, transform-bug handling (A6).
- **§7**: Task A8 (the hardware follow-up), with the step-3 plan's commands; §7.2 GSR, §7.3 pad harness, §7.4 configuration primitives in its table.
- **§8**: every finding class has a row in Task A6; `expected_divergence` never masks; exit codes 0/3/4.
- **§9**: reach-confirmed exercises, bins accounted, pure crediting and a failing mutant per claim (`UnitGuards`, A3), per-configuration crediting (A6 Step 5), P1 for non-enumerated attributes.
- **§11**: tree hash (A6 Step 1), both model sources recorded, generated files never committed.
- **§12**: the README generator carries every template section.
- **§13**: worktrees, owned paths, small prefixed commits, one PR per branch, stacking, the two-reviewer gate, the two-agent limit.
- **§14**: no silent skips: every non-`"yes"` runner has a reason; errors are not failures.
- **§16 step 5**: the order (Appendix W).

**Placeholder scan.** Part A's `<unit>`, `<group>`, `<PRIMS>`, `<PRIM>`, `<prim>`, `<ts>` and `<N>` are the plan's declared parameters, filled in Part B for luts and by the orchestrator's brief for later units. Every Part B code block is complete, and was run (see Global Constraints). The generated wrappers (gen.py, sv, cocotb) come from `luts_tests.render`, and one of each kind is shown in full.

**Type and name consistency.** `LutKind(prim, n, width, outputs, reconfig)`, `KINDS`, `lit`, `ones`, `projection`, `init_samples`, `random_inits`, `LutDriver`, `CfgLutDriver`, `generators`, `tests_for`, `render`, `UNIT`, `GROUP_DIR`, `ROOT`, `random_session`, `coverage_reach`, `attr_bins`, `replay_config`, `mutants`, `unitkit.entry`/`runners`/`class_bins`/`vector_reach`/`mutant_fails`/`Unit`/`UnitGuards`: used identically in every task. Claim numbers match between the overrides (B1), the model (B2), the model tests and the generator's `exercises` (B3).

**Rulings applied**: S6 (co-timed sets), S12/S13b (reject configurations), S15 (sv checks and checkpoints), S19/S21/S23/S33 (bins and crediting), S28/S29(2) (CFGLUT5 and srl Verilator), S30 (no inferred `-`), S32/S44/S52/S53/S55 (claim crediting, known-uniform tracking, pure configurations, deciding events and mutants), S36 (macro wrapping), S37 (cocotb driving), S38 (no z), S49 (memory budget), S51 (`config` rows), S53 (`xut.unitkit`, one stem, the heavy lock, the pad-site rule).
