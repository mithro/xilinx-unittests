# Step 2 — Core Infra and Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the simulation core and prove it end to end on one work unit:

- one pinned simulator container (Icarus, Verilator, cocotb);
- the `.xvec` stimulus and `.xtr` trace formats, with generator-side validation of the port-class rules;
- the DUT wrapper generator (`xut wrap`) and one generic vector testbench;
- the golden-model base API;
- the `python`, `xsim`, `iverilog` and `verilator` runners, plus `xut run`;
- `xut verilatorize` with its mandatory Icarus equivalence check;
- `xut crosscheck` with the §8 finding classes;
- the portability table (`status/PORTABILITY.md`);
- the pilot: the `flops` unit (FDRE first, then FDSE, FDCE, FDPE) at L0–L2 in all three styles (vector, sv, cocotb).

After this step, fan-out work units can write tests against a working runner matrix. Hardware (step 3) and the non-`rtl` flows (step 4) plug into interfaces defined here.

**Architecture:**

- Everything a runner consumes is generated per *test configuration* (primitive + attribute set):
  - `xut_dut.v`, the wrapper;
  - `xut_dut.map.json`, the port → bit map;
  - `xut_cfg.vh`, the widths;
  - `stim.memh`, the compiled stimulus.
- The generic testbench `tools/xut/hdl/xut_vector_tb.sv` is identical for every primitive. It replays a word-per-operation memory image and writes raw samples. Python turns the raw samples into `.xtr` using the map.
- Expected traces come from the `python` runner, which replays the same `.xvec` through a clean-room golden model. Every expected bit carries a provenance tag, which `crosscheck` uses to tell `doc-vs-model` from `doc-gap`.
- Runners share one `Runner` base. Each writes `build/<flow>/<runner>/<model-source>/<test-id>/{trace.xtr,result.json,run.log}` and never skips silently.
- `iverilog` and `verilator` run inside the `xut-sim` container via an `Executor`. `xsim` runs on the host in a `bash` subshell that sources Vivado.
- `xut verilatorize` analyses UNISIM models with pyslang. It rewrites each procedural `assign`/`deassign` with the shadow-register transform by splicing text at AST source ranges (never regex). A generated equivalence stimulus then compares original and transformed models on Icarus.

**Tech Stack:**

- Everything from step 1: Python ≥ 3.12, uv, click, PyYAML, jsonschema, pyslang 11.0.0, pytest, ruff.
- Docker, with image `xut-sim:1` built from `debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a`:
  - apt `iverilog=12.0-2+b1`;
  - Verilator **v5.048 built from the upstream git tag** (`https://github.com/verilator/verilator`, tag `v5.048`, commit `d0aa828c217410fffc73d92077b6f4f54830357c`) in a multi-stage build on the same pinned base;
  - pip `cocotb==2.0.1` in a venv (Python 3.13).
- Vivado 2025.2 xsim (`xvlog`/`xelab`/`xsim`) with the precompiled `unisims_ver` library.

**Spec:** `docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md` (rev 3.1). Read §§4, 5, 6 (especially 6.2), 8, 9, 11, 12, 13 and 16 step 2.

**Prerequisite:** the step-1 PR (#2, "bootstrap") is merged into `main`. This plan consumes these step-1 interfaces:

- `xut.paths`: `repo_root`, `cache_dir`, `VIVADO_UNISIM`, `VIVADO_RETARGET`, `submodule_unisim`;
- `xut.catalog.model`: `CatalogEntry`, `load_entry`;
- `xut.catalog.portclass`: `default_class`;
- `xut.catalog.unisim`: `parse_module`, `HdlModule`, `_is_benign`;
- `xut.workunits`: `load_units`, `owned_paths`, `unit_for_branch`, `WorkUnit`;
- `xut.status`: `RESULT_VALUES`, `load_status`, `coverage_bins`, `render_*`, `current_branch`;
- `xut.lint`: `LintIssue` and its `check_*` functions;
- `xut.doctor`: `Check`, `run_checks`;
- the schemas in `tools/xut/schemas/`, the templates in `docs/templates/`, and AGENTS.md.

`xut.status`, `xut.lint` and `xut.doctor` come from step-1 Tasks 6–9, which were not implemented when this plan was written.

- [ ] **Step 0 (before Task 1): verify the step-1 interfaces on `main`**

```bash
cd /home/tim/github/f4pga/xilinx-unittests && git fetch origin && git checkout main && git pull --ff-only
uv run xut lint --help > .cache/step0.log 2>&1
uv run xut status generate --help >> .cache/step0.log 2>&1
uv run xut doctor >> .cache/step0.log 2>&1
uv run python -c "from xut.lint import LintIssue; from xut.doctor import Check, run_checks; from xut.status import current_branch, coverage_bins, RESULT_VALUES, load_status; from xut.workunits import owned_paths, unit_for_branch; print('step-1 interfaces OK', RESULT_VALUES)" >> .cache/step0.log 2>&1
cat .cache/step0.log
```

Expected: three help/doctor outputs and `step-1 interfaces OK (...)`. If a name differs, adapt this plan's calls to the merged code (not the semantics), and note the mapping in the first log entry.

## Global Constraints

- Every source file (`.py .v .sv .svh .vh .yaml .sh .tcl .toml`, Dockerfile, workflows) starts with an `SPDX-License-Identifier: Apache-2.0` comment line. Generated HDL (`xut_dut.v`, `xut_cfg.vh`, transformed models) also carries it. Markdown is exempt.
- AMD PDFs, AMD prose and UNISIM source are never committed. Transformed UNISIM copies live only in `build/verilatorized/<model-source>/`. `build/` is already in `.gitignore`.
- Generated files `status/PROGRESS.md`, `status/TODO.md`, `status/LOG.md` and `status/PORTABILITY.md` are never committed on branches. Only the orchestrator commits them on `main`, as `status: regenerate`.
- Commit subjects are prefixed `<area>: ` (`infra: `, `formats: `, `runners: `, `verilatorize: `, `flops: `, `status: `, `docs: `). Make small commits after every change. Every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Pass it as a second `-m`, as the commit commands below do.
- Never use `2>/dev/null`. Never pipe a command into `grep`/`tail`. Capture output to a log file (`cmd > .cache/x.log 2>&1`), then inspect the log file.
- Vivado is only ever sourced in a subshell: `bash -c 'source /opt/xilinx/Vivado/2025.2/settings64.sh && ...'`. The xsim runner writes an `xsim.sh` script and runs it with `bash xsim.sh > run.log 2>&1`.
- Long runs (the portability smoke run, full `xut run` passes) follow the global progress-reporting rule:
  - run in the background, logging to a file;
  - watch with a Monitor that reads the log's `progress: done=N total=M elapsed_s=E` lines, which `xut` prints on every completion;
  - report remaining time and finish clock-time at the stated cadence.
- **Stdlib-only modules.** `tools/xut/formats/*` and `models/xut_models/**` use only the standard library. They are imported inside the container by cocotb tests, where xut's dependencies are not installed.
- Containers run with `--network=none`, as the invoking uid:gid, with the repository mounted at `/work` and model sources mounted read-only under `/models/`.
- **Clean room.** Nobody working on `models/xut_models/7series/**` opens any UNISIM `.v` file for the primitive being modelled. Only UG953 text is used: `uv run xut fetch-docs`, then read `.cache/docs/ug953-2026.1.txt`.
- Worktrees live under `../xilinx-unittests-worktrees/<branch-with-dashes>`. **One PR per branch, always**, as in the table below.

### Branches and PRs

| Branch | Branched from | Worktree | Tasks | PR (base) |
|---|---|---|---|---|
| `infra/sim-formats` | `origin/main` | `infra-sim-formats` | 1–5 | **PR A** "infra: sim formats — container, formats, wrapper, validation" (base `main`) |
| `infra/sim-runners` | `infra/sim-formats` | `infra-sim-runners` | 6–11 | **PR B** "infra: sim runners — golden-model API, testbench, runners, xut run" (base `infra/sim-formats` until A merges, then `main`) |
| `infra/verilatorize` | `infra/sim-runners` | `infra-verilatorize` | 12–16 | **PR C** "infra: verilatorize, verilator runner, portability table" (base `infra/sim-runners` until B merges, then `main`) |
| `infra/crosscheck` | `infra/sim-runners` | `infra-crosscheck` | 17–18 | **PR D** "infra: crosscheck, status record, shared unit test paths" (base `infra/sim-runners` until B merges, then `main`) |
| `unit/7series/flops` | `origin/main` after A–D merge | `unit-7series-flops` | 19–27 | **PR E** "flops: FDRE/FDSE/FDCE/FDPE pilot" (base `main`), one PR for the whole unit |

- **Merge order** is A → B → {C, D} → E.
- **Stacked PRs.** A child PR's base is its parent branch while the parent's PR is open; `gh pr create --base <parent-branch>`. After the parent merges (rebase-merge), the **orchestrator** rebases the child onto `main`, re-runs its tests, force-pushes it with `git push --force-with-lease`, and retargets the PR: `gh pr edit <N> --base main`. That force-push is sanctioned only for the orchestrator, and only on its own feature branches; Task 1 amends AGENTS.md to say so.
- **Two review levels.** *Per-task reviews* happen on local commits, through the subagent-driven-development workflow: after each task, a reviewer checks that task's commits and writes a report file (not a PR comment), and must-fix items are addressed before the next task. The *PR-level gate* of spec §13.4 (two fresh reviewers with the `docs/review/` prompts, posting `gh pr review`) happens once, when the branch's PR opens. On the unit branch the single PR E is that gate.
- **Two-agent limit** (spec §13.5). With one implementer running, reviewers (a) and (b) run **sequentially**, never together.
- **Expected conflict.** Tasks 16 (C) and 18 (D) both edit `status.py`, `lint.py`, `test_lint.py` and `cli.py`. Whichever merges second gets a rebase conflict; the orchestrator resolves it during the rebase onto `main` and re-runs the tests.
- The pilot touches **only** `flops`-owned paths (spec §13). Task 18 adds `tests/<family>/<group>/_shared/<unit>/**` to a unit's owned paths, so the four flops can share test code.

## Review Focus

1. **The shadow-register transform must fail loudly, never silently mis-transform** (spec §6.2 rule 4).
   - The fixtures in Task 13 must pin all ten listed cases.
   - They must also pin every refusal path:
     - `force`/`release`;
     - a select as the lvalue of an `assign`;
     - an override expression that reads a block-local variable or `X` itself;
     - `X` read after its `assign`/`deassign` in the same block without an intervening delay;
     - an ANSI `output reg`;
     - a construct inside a macro expansion;
     - a signal in a trigger cone whose driver cannot be resolved (undriven, or driven by an unknown module's output);
     - generate conditions whose configurations cannot be enumerated.
   - Tracing must cross gate primitives, continuous assigns and same-file sub-instances (fixtures `BUFVZ`, `VZSUB`).
   - Analysis and rewrite cover **every** generate branch. `check_clean` elaborates the result under every generate configuration, and the equivalence check runs for the default plus every configuration a test uses (`VZGEN`).
   - `deassign` is guarded and wrapped (`begin if (X__ovr_sel != 0) begin X__base = X; X__ovr_sel = 0; end end`, spec §6.2 rev 3.1). The outer `begin … end` stops a following `else` binding to the guard (`VZIFELSE`). Packed ranges are preserved (`VZRANGE`).
   - The Icarus equivalence check (Task 14) is the backstop. Reviewers must confirm that a mismatch makes the Verilator result `error` (a `transform-bug`), not a pass.
2. **Golden models are clean-room.**
   - Task 20's model cites a UG953 page for every behaviour. Anything UG953 does not state is `inferred:` (clock edges while GSR is active), or is `-` (undefined) when UG953 is silent on a conflict (GSR versus an active CLR/PRE).
   - The model's attribute defaults come from UG953, not from UNISIM. The wrapper instantiates only explicitly-set attributes, so the model default and the UNISIM default are cross-checked for free.
3. **Class-rule validation in the stimulus generator** (Task 5).
   - A `sample` never shares its time with a change.
   - Every sample is at least `gap_ps` (1 ns) after the last change, which clears the UNISIM clock-to-Q delay.
   - Async/gate changes are at least `async_sep_ps` from any clock edge (including computed free-clock edges).
   - Any `simultaneous` event makes the file `hw_renderable no`.
   - The `VecBuilder` must only ever emit valid files. A test checks every builder output with `validate`.
4. **No silent skips** (spec §14).
   - Every (test, runner) pair that `xut run` selects writes a `result.json`: declared-unsupported and unavailable runners give `skip` with a reason.
   - cocotb runs on both Icarus and Verilator (spec §4.3). Verilator v5.048 is built from source because cocotb 2.0.1 refuses Verilator < 5.036 (the apt 5.032 is too old). Task 1 has a positive container test that a cocotb smoke test runs on Verilator, and the Verilator runner runs cocotb tests with the same paired X seeds as other styles.
5. **Model identity and like-for-like comparison** (spec §6.2).
   - Every `result.json` and trace header names its model source.
   - `crosscheck` never compares UNISIM traces across model sources.
   - `xsim` always uses the precompiled `unisims_ver` library (`unisim-2025.2`), and refuses `--model-source unisim-gh-2020.1`.
   - The iverilog-on-transformed companion (`iverilog-vz`) uses the same model source as the Verilator run it guards.

---

## File Structure

```
containers/sim/Dockerfile                    xut-sim image (Task 1)
tools/xut/container.py                       DockerExecutor / NativeExecutor, image digest, tool versions
tools/xut/modelsrc.py                        ModelSource: unisim-2025.2 | unisim-gh-2020.1
tools/xut/formats/__init__.py
tools/xut/formats/xvec.py                    .xvec grammar, parser, writer          (stdlib only)
tools/xut/formats/xtr.py                     .xtr grammar, parser, writer, compare  (stdlib only)
tools/xut/wrap.py                            DutSpec, DutMap, xut_dut.v / map.json / xut_cfg.vh
tools/xut/validate.py                        port-class rules, hw_renderable
tools/xut/stimgen.py                         VecBuilder, GenContext
tools/xut/golden.py                          replay a Vec through a golden model -> expected Trace + Reach
tools/xut/stimcompile.py                     Vec -> stim.memh / stim.vh / labels.json; raw.txt -> Trace
tools/xut/hdl/xut_vector_tb.sv               the generic vector testbench
tools/xut/hdl/xut_trace.svh                  checkpoint/self-check macros for sv tests
tools/xut/hdl/cocotb_run.py                  in-container cocotb launcher
tools/xut/cocotb_dut.py                      cocotb helper: map-aware drive/sample/trace (container only)
tools/xut/testspec.py                        test.yaml discovery -> TestCase
tools/xut/runners/__init__.py                RUNNERS registry
tools/xut/runners/base.py                    Runner, RunContext, RunResult, result.json
tools/xut/runners/python.py                  golden-model runner (vector expected traces)
tools/xut/runners/iverilog.py                iverilog (+ iverilog-vz) runner, vector/sv/cocotb styles
tools/xut/runners/xsim.py                    xsim runner (host, subshell)
tools/xut/runners/verilator.py               verilator runner, two X-seed runs
tools/xut/run.py                             `xut run` orchestration
tools/xut/verilatorize/__init__.py
tools/xut/verilatorize/analyze.py            forced regs, triggers, enablers (pyslang AST)
tools/xut/verilatorize/rewrite.py            shadow-register transform
tools/xut/verilatorize/equiv.py              equivalence stimulus + Icarus check
tools/xut/verilatorize/driver.py             transform a model source dir, manifest.json
tools/xut/portability.py                     smoke run, PORTABILITY.md
tools/xut/crosscheck.py                      finding classification, matrix, findings stubs
tools/xut/schemas/result.schema.json
tools/xut/schemas/test.schema.json           (modified: source, configs, expected_divergence, ...)
tools/tests/test_*.py                        tool tests; fixtures under tools/tests/fixtures/
tools/tests/fixtures/verilatorize/*.v        our own toy models for the transform
models/xut_models/__init__.py                (infra)
models/xut_models/base.py                    Model, Out, ModelUnsupported, bit_attr   (infra)
models/xut_models/registry.py                get(family, prim)                         (infra)
models/xut_models/7series/__init__.py        (infra)
models/xut_models/7series/_common/__init__.py (infra)
models/xut_models/7series/_common/flops.py   SdrFlop shared model                      (flops)
models/xut_models/7series/fd{r,s,c,p}e.py    per-primitive models                      (flops)
catalog/7series/FD{R,S,C,P}E.overrides.yaml  claims, allowed-value fixes               (flops)
tests/7series/register/_shared/flops/        flop_recipes.py, flops_cocotb.py, flop_*_tb.svh (flops)
tests/7series/register/_shared/flops/        also flop_tests.py, test_flop_models.py, test_flop_tests.py (flops)
tests/7series/register/FD{R,S,C,P}E/         test.yaml, README.md, vectors/, sv/, cocotb/ (flops)
status/7series/FD{R,S,C,P}E.yaml             (flops)
```

Run directory layout (never committed):

```
build/<flow>/<runner>/<model-source>/<test-id>/result.json    aggregate over configs
build/<flow>/<runner>/<model-source>/<test-id>/trace.xtr      all configs; labels are "<cfg>/<label>"
build/<flow>/<runner>/<model-source>/<test-id>/run.log        all configs' logs concatenated
build/<flow>/<runner>/<model-source>/<test-id>/cfg-<cfg>/     per-config work dir (dut/, stim.*, raw.txt, logs)
build/verilatorized/<model-source>/<MODEL>.v, manifest.json, equiv/<MODEL>/
build/portability/<model-source>.json
build/crosscheck/<test-id>.json
```

---

### Task 1: Simulator container and executor

**Files:**
- Create: `containers/sim/Dockerfile`, `tools/xut/container.py`, `tools/xut/modelsrc.py`, `tools/tests/test_container.py`, `tools/tests/test_modelsrc.py`
- Modify: `tools/xut/paths.py`, `tools/xut/cli.py`, `tools/xut/doctor.py`, `pyproject.toml` (pytest markers), `.github/workflows/ci.yml`, `AGENTS.md`

**Interfaces:**
- Produces:
  - `xut.container.SIM_IMAGE = "xut-sim:1"`
  - `Executor` (Protocol), with:
    - `run(argv: list[str], cwd: Path, log: Path, timeout_s: int, env: dict[str, str] | None = None) -> int`, which appends to `log` and raises `RunTimeout` on timeout;
    - `guest(path: Path) -> str`.
  - `DockerExecutor(image=SIM_IMAGE, root=None, mounts: tuple[Mount, ...] = ())`
  - `NativeExecutor()`
  - `executor_for(model_source) -> Executor`, which returns `NativeExecutor` when `XUT_NATIVE=1`
  - `image_digest(image) -> str | None`
  - `sim_tool_versions(executor, workdir) -> dict[str, str]`
  - CLI `xut container build` and `xut container versions`
  - `xut.modelsrc.ModelSource` (frozen: `name, src`), with properties `unisims`, `retarget`, `glbl`
  - `model_sources() -> dict[str, ModelSource]`
  - `resolve(name: str = "auto") -> ModelSource`
  - `xut.paths.VIVADO_ROOT`, `VIVADO_SRC`, `VIVADO_SETTINGS`, `submodule_src()`

- [ ] **Step 1: Create the worktree and branch**

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git fetch origin && git worktree add ../xilinx-unittests-worktrees/infra-sim-formats -b infra/sim-formats origin/main
cd ../xilinx-unittests-worktrees/infra-sim-formats
mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
git config core.hooksPath tools/hooks
```

- [ ] **Step 2: Write `containers/sim/Dockerfile`**

```dockerfile
# SPDX-License-Identifier: Apache-2.0
# xut-sim: the one simulator container of spec §16 step 2 (spec rev 3.1).
# Bump SIM_IMAGE in tools/xut/container.py whenever this file changes.
ARG BASE=debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a

# ---- stage 1: Verilator from the upstream tag (cocotb 2.0.1 needs >= 5.036) ----
FROM ${BASE} AS verilator
ARG VERILATOR_TAG=v5.048
ARG VERILATOR_SHA=d0aa828c217410fffc73d92077b6f4f54830357c
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git ca-certificates autoconf g++ make flex bison help2man perl python3 \
      libfl2 libfl-dev zlib1g zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "$VERILATOR_TAG" https://github.com/verilator/verilator /src/verilator \
 && cd /src/verilator \
 && test "$(git rev-parse HEAD)" = "$VERILATOR_SHA" \
 && autoconf \
 && ./configure --prefix=/opt/verilator \
 && make -j"$(nproc)" \
 && make install \
 && rm -rf /src/verilator

# ---- stage 2: the runtime image ----
FROM ${BASE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      iverilog=12.0-2+b1 \
      g++ make perl \
      python3 python3-venv libpython3.13 \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=verilator /opt/verilator /opt/verilator
RUN python3 -m venv /opt/cocotb \
 && /opt/cocotb/bin/pip install --no-cache-dir cocotb==2.0.1
ENV PATH=/opt/verilator/bin:/opt/cocotb/bin:$PATH \
    VERILATOR_ROOT=/opt/verilator/share/verilator \
    PYTHONDONTWRITEBYTECODE=1
LABEL org.opencontainers.image.source=https://github.com/mithro/xilinx-unittests \
      org.opencontainers.image.licenses=Apache-2.0 \
      org.xut.verilator.tag=v5.048 \
      org.xut.verilator.commit=d0aa828c217410fffc73d92077b6f4f54830357c
```

The `test "$(git rev-parse HEAD)" = "$VERILATOR_SHA"` line makes the build fail if the tag ever moves.

Two supply-chain hardenings, both cheap and done in this task:
- **cocotb with hashes.** Run `pip download cocotb==2.0.1 --no-deps -d .cache/wheels` and `pip hash .cache/wheels/*` inside the base image. Write `containers/sim/requirements-cocotb.txt` (`cocotb==2.0.1 --hash=sha256:…`, one line per platform wheel and the sdist), `COPY` it, and install with `pip install --require-hashes -r`.
- **The pinned iverilog.** If `iverilog=12.0-2+b1` ever leaves the live trixie mirror, point both stages' apt sources at `snapshot.debian.org` for the base digest's date (the build then keeps working unchanged). Record the snapshot timestamp in the Dockerfile comment when that happens. `VERILATOR_ROOT` matches the `--prefix` install layout; if `verilator --version` or `verilator --getenv VERILATOR_ROOT` disagrees in Step 3, fix the `ENV` line to what the installed `verilator` reports.

- [ ] **Step 3: Build the image and record versions**

The Verilator source build takes about 5–10 minutes on this 88-CPU host. Expected under 10 minutes, so run it in the background and report every 60 s from the build log: the `#N [verilator 5/5]` step lines give the progress, and `make` prints compile lines.

```bash
docker build -t xut-sim:1 containers/sim > .cache/container-build.log 2>&1; echo "exit=$?"
tail -n 5 .cache/container-build.log
docker run --rm --network=none xut-sim:1 bash -c 'iverilog -V; verilator --version; cocotb-config --version; python3 --version' > .cache/container-versions.log 2>&1
cat .cache/container-versions.log
```

Expected:
- `exit=0`;
- the versions log has `Icarus Verilog version 12.0 (stable)`, a `Verilator 5.048 …` line, `2.0.1` and `Python 3.13.x`;
- record the exact Verilator version line and the image digest in the log entry.

(`iverilog -V` exits non-zero when no source is given. The log is what matters.)

- [ ] **Step 4: Extend `tools/xut/paths.py`**

Append:

```python
VIVADO_ROOT = Path("/opt/xilinx/Vivado/2025.2")
VIVADO_SRC = VIVADO_ROOT / "data/verilog/src"  # unisims/, retarget/, glbl.v
VIVADO_SETTINGS = VIVADO_ROOT / "settings64.sh"


def submodule_src() -> Path:
    return repo_root() / "third_party/XilinxUnisimLibrary/verilog/src"
```

- [ ] **Step 5: Write the failing tests**

`tools/tests/test_modelsrc.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from xut import modelsrc
from xut.modelsrc import ModelSource


def _fake_src(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    (d / "unisims").mkdir(parents=True)
    (d / "glbl.v").write_text("module glbl; endmodule\n")
    return d


def test_resolve_auto_prefers_vivado(tmp_path, monkeypatch):
    v, g = _fake_src(tmp_path, "viv"), _fake_src(tmp_path, "gh")
    monkeypatch.setattr(modelsrc, "_candidates", lambda: [("unisim-2025.2", v), ("unisim-gh-2020.1", g)])
    assert modelsrc.resolve("auto").name == "unisim-2025.2"
    assert modelsrc.resolve("unisim-gh-2020.1").src == g


def test_resolve_falls_back_to_submodule(tmp_path, monkeypatch):
    g = _fake_src(tmp_path, "gh")
    monkeypatch.setattr(modelsrc, "_candidates",
                        lambda: [("unisim-2025.2", tmp_path / "missing"), ("unisim-gh-2020.1", g)])
    assert modelsrc.resolve("auto").name == "unisim-gh-2020.1"


def test_resolve_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(modelsrc, "_candidates", lambda: [])
    with pytest.raises(LookupError, match="no UNISIM model source"):
        modelsrc.resolve("auto")


def test_retarget_optional(tmp_path):
    ms = ModelSource("x", _fake_src(tmp_path, "s"))
    assert ms.retarget is None
    (ms.src / "retarget").mkdir()
    assert ms.retarget == ms.src / "retarget"
```

`tools/tests/test_container.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from xut.container import SIM_IMAGE, DockerExecutor, Mount, NativeExecutor, image_digest
from xut.paths import repo_root


def test_docker_argv_maps_paths(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    root = repo_root()
    ex = DockerExecutor(root=root, mounts=(Mount(Path("/opt/m"), "/models/m"),))
    work = root / "build" / "x"
    rc = ex.run(["iverilog", "-V"], cwd=work, log=tmp_path / "l.log", timeout_s=5)
    assert rc == 0
    argv = calls[0]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in argv
    assert f"{root}:/work" in argv
    assert "/opt/m:/models/m:ro" in argv
    assert argv[argv.index("-w") + 1] == "/work/build/x"
    assert argv[-2:] == ["iverilog", "-V"]
    assert f"{os.getuid()}:{os.getgid()}" in argv


def test_guest_path_outside_mounts_raises(tmp_path):
    ex = DockerExecutor(root=repo_root())
    with pytest.raises(ValueError, match="not visible in the container"):
        ex.guest(Path("/etc/passwd"))


def test_native_executor_identity(tmp_path):
    ex = NativeExecutor()
    assert ex.guest(tmp_path) == str(tmp_path)
    rc = ex.run(["true"], cwd=tmp_path, log=tmp_path / "t.log", timeout_s=5)
    assert rc == 0


needs_image = pytest.mark.skipif(
    shutil.which("docker") is None or image_digest(SIM_IMAGE) is None,
    reason=f"{SIM_IMAGE} not built (run: uv run xut container build)",
)


@pytest.mark.container
@needs_image
def test_pinned_versions(tmp_path):
    from xut.container import sim_tool_versions

    v = sim_tool_versions(DockerExecutor(root=repo_root()), repo_root())
    assert v["iverilog"].startswith("Icarus Verilog version 12.0")
    assert v["verilator"].startswith("Verilator 5.048")
    assert v["cocotb"] == "2.0.1"


SMOKE_V = """// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module smoke_dff (input wire clk, input wire d, output reg q);
  always @(posedge clk) q <= #100 d;
endmodule
"""
SMOKE_TEST = """# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def smoke(dut):
    dut.clk.value = 0
    dut.d.value = 1
    await Timer(1, "ns")
    dut.clk.value = 1
    await Timer(1, "ns")
    assert int(dut.q.value) == 1
"""
SMOKE_RUN = """# SPDX-License-Identifier: Apache-2.0
import sys
from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner

sim = sys.argv[1]
r = get_runner(sim)
args = ["--timing"] if sim == "verilator" else []
r.build(sources=["smoke_dff.v"], hdl_toplevel="smoke_dff", build_args=args,
        timescale=("1ps", "1ps"), build_dir=f"sim_{sim}")
res = r.test(hdl_toplevel="smoke_dff", test_module="cocotb_smoke", build_dir=f"sim_{sim}",
             test_dir=".")
total, failed = get_results(res)
print(f"XUT_COCOTB total={total} failed={failed}")
sys.exit(1 if failed or not total else 0)
"""


@pytest.mark.container
@needs_image
@pytest.mark.parametrize("sim", ["icarus", "verilator"])
def test_cocotb_smoke_runs(sim):
    """cocotb 2.0.1 must run on both simulators (spec §4.3; Verilator v5.048, spec rev 3.1)."""
    work = repo_root() / "build" / "cocotb-smoke"
    work.mkdir(parents=True, exist_ok=True)
    (work / "smoke_dff.v").write_text(SMOKE_V)
    (work / "cocotb_smoke.py").write_text(SMOKE_TEST)
    (work / "smoke_run.py").write_text(SMOKE_RUN)
    log = work / f"{sim}.log"
    log.unlink(missing_ok=True)
    rc = DockerExecutor(root=repo_root()).run(["python3", "smoke_run.py", sim], cwd=work,
                                              log=log, timeout_s=600, env={"PYTHONPATH": "."})
    assert rc == 0, log.read_text()
    assert "XUT_COCOTB total=1 failed=0" in log.read_text()


@pytest.mark.container
@needs_image
def test_verilator_still_rejects_procedural_deassign(tmp_path):
    """Pins why `xut verilatorize` (spec §6.2) exists. If Verilator ever accepts the
    Verilog-1995 procedural assign/deassign, stop and raise it with the owner before Task 12."""
    work = repo_root() / "build" / "vl-deassign"
    work.mkdir(parents=True, exist_ok=True)
    (work / "toy.v").write_text(
        "// SPDX-License-Identifier: Apache-2.0\n"
        "module toy (input c, input d, input clr, output q);\n"
        "  reg r;\n  assign q = r;\n"
        "  always @(clr) if (clr) assign r = 1'b0; else deassign r;\n"
        "  always @(posedge c) r <= d;\nendmodule\n")
    log = work / "lint.log"
    log.unlink(missing_ok=True)
    rc = DockerExecutor(root=repo_root()).run(["verilator", "--lint-only", "toy.v"], cwd=work,
                                              log=log, timeout_s=120)
    assert rc != 0 and "deassign" in log.read_text()
```

Run: `uv run pytest tools/tests/test_modelsrc.py tools/tests/test_container.py -v > .cache/pytest.log 2>&1; tail -n 15 .cache/pytest.log`

Expected: FAIL (`ModuleNotFoundError: xut.container`).

- [ ] **Step 6: Implement `tools/xut/modelsrc.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""UNISIM model sources (spec §6.2 "Model identity")."""

from dataclasses import dataclass
from pathlib import Path

from xut.paths import VIVADO_SRC, submodule_src


@dataclass(frozen=True)
class ModelSource:
    name: str  # "unisim-2025.2" | "unisim-gh-2020.1"
    src: Path  # holds unisims/, glbl.v and optionally retarget/

    @property
    def unisims(self) -> Path:
        return self.src / "unisims"

    @property
    def retarget(self) -> Path | None:
        r = self.src / "retarget"
        return r if r.is_dir() else None

    @property
    def glbl(self) -> Path:
        return self.src / "glbl.v"

    @property
    def search(self) -> list[Path]:
        return [self.unisims] + ([self.retarget] if self.retarget else [])


def _candidates() -> list[tuple[str, Path]]:
    return [("unisim-2025.2", VIVADO_SRC), ("unisim-gh-2020.1", submodule_src())]


def model_sources() -> dict[str, ModelSource]:
    return {
        n: ModelSource(n, p)
        for n, p in _candidates()
        if (p / "unisims").is_dir() and (p / "glbl.v").is_file()
    }


def resolve(name: str = "auto") -> ModelSource:
    have = model_sources()
    if name == "auto":
        if not have:
            raise LookupError("no UNISIM model source: install Vivado 2025.2 or init the submodule")
        return next(iter(have.values()))
    if name not in have:
        raise LookupError(f"model source {name!r} unavailable (have: {sorted(have)})")
    return have[name]
```

- [ ] **Step 7: Implement `tools/xut/container.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Run simulator commands inside the pinned xut-sim container (or natively in CI)."""

import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from xut.paths import repo_root

SIM_IMAGE = "xut-sim:1"


class RunTimeout(RuntimeError):
    pass


@dataclass(frozen=True)
class Mount:
    host: Path
    guest: str
    ro: bool = True


class Executor(Protocol):
    def run(self, argv: list[str], cwd: Path, log: Path, timeout_s: int,
            env: dict[str, str] | None = None) -> int: ...

    def guest(self, path: Path) -> str: ...


def _append(log: Path):
    log.parent.mkdir(parents=True, exist_ok=True)
    return log.open("a")


class NativeExecutor:
    """Tools on PATH (used inside CI's xut-sim job, where XUT_NATIVE=1)."""

    def guest(self, path: Path) -> str:
        return str(path)

    def run(self, argv, cwd, log, timeout_s, env=None) -> int:
        with _append(log) as f:
            f.write(f"$ {' '.join(argv)}\n")
            f.flush()
            try:
                p = subprocess.run(argv, cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                                   timeout=timeout_s, env={**os.environ, **(env or {})})
            except subprocess.TimeoutExpired as e:
                raise RunTimeout(f"timeout after {timeout_s}s: {argv[0]}") from e
        return p.returncode


class DockerExecutor:
    def __init__(self, image: str = SIM_IMAGE, root: Path | None = None,
                 mounts: tuple[Mount, ...] = ()):
        self.image, self.root, self.mounts = image, (root or repo_root()).resolve(), mounts

    def guest(self, path: Path) -> str:
        p = Path(path).resolve()
        if p.is_relative_to(self.root):
            return "/work/" + str(p.relative_to(self.root)) if p != self.root else "/work"
        for m in self.mounts:
            if p.is_relative_to(m.host):
                rel = p.relative_to(m.host)
                return m.guest if str(rel) == "." else f"{m.guest}/{rel}"
        raise ValueError(f"{p} is not visible in the container (mount it first)")

    def argv(self, argv: list[str], cwd: Path, name: str, env: dict[str, str] | None) -> list[str]:
        out = ["docker", "run", "--rm", "--name", name, "--network=none",
               "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
               "-v", f"{self.root}:/work"]
        for m in self.mounts:
            out += ["-v", f"{m.host}:{m.guest}{':ro' if m.ro else ''}"]
        for k, v in (env or {}).items():
            out += ["-e", f"{k}={v}"]
        out += ["-w", self.guest(cwd), self.image, *argv]
        return out

    def run(self, argv, cwd, log, timeout_s, env=None) -> int:
        name = f"xut-{uuid.uuid4().hex[:12]}"
        full = self.argv(argv, Path(cwd), name, env)
        with _append(log) as f:
            f.write(f"$ {' '.join(argv)}   [container {self.image} {name}]\n")
            f.flush()
            try:
                p = subprocess.run(full, stdout=f, stderr=subprocess.STDOUT, timeout=timeout_s)
            except subprocess.TimeoutExpired as e:
                subprocess.run(["docker", "kill", name], stdout=f, stderr=subprocess.STDOUT)
                raise RunTimeout(f"timeout after {timeout_s}s: {argv[0]}") from e
        return p.returncode


def executor_for(model_source) -> Executor:
    if os.environ.get("XUT_NATIVE") == "1":
        return NativeExecutor()
    mounts = ()
    if not model_source.src.resolve().is_relative_to(repo_root().resolve()):
        mounts = (Mount(model_source.src.resolve(), f"/models/{model_source.name}"),)
    return DockerExecutor(mounts=mounts)


def image_digest(image: str = SIM_IMAGE) -> str | None:
    p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                       capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


_VERSIONS: dict[str, dict[str, str]] = {}
_VERSIONS_LOCK = threading.Lock()


def sim_tool_versions(ex: Executor, workdir: Path) -> dict[str, str]:
    """First line of each tool's version output (recorded in result.json).

    Computed once per process and image, under a lock, with a private log file: runner
    jobs are threads (xut run --jobs N), so a shared log file would race (review #9)."""
    key_img = getattr(ex, "image", "native")
    with _VERSIONS_LOCK:
        if key_img in _VERSIONS:
            return dict(_VERSIONS[key_img])
        workdir.mkdir(parents=True, exist_ok=True)
        out = {}
        for key, argv in (("iverilog", ["iverilog", "-V"]),
                          ("verilator", ["verilator", "--version"]),
                          ("cocotb", ["cocotb-config", "--version"])):
            log = workdir / f".versions-{uuid.uuid4().hex}.log"
            ex.run(argv, cwd=workdir, log=log, timeout_s=60)
            lines = [ln for ln in log.read_text().splitlines()[1:] if ln.strip()]
            out[key] = lines[0].strip() if lines else "unknown"
            log.unlink()
        _VERSIONS[key_img] = out
        return dict(out)
```

`iverilog -V` with no input prints its banner first, then an error. Taking the first non-command line gives `Icarus Verilog version 12.0 (stable) ()`.

- [ ] **Step 8: Add CLI commands, pytest markers, the doctor check and CI**

In `tools/xut/cli.py`:

```python
@main.group("container")
def container_grp() -> None:
    """The pinned simulator container (containers/sim)."""


@container_grp.command("build")
def container_build_cmd() -> None:
    """docker build -t xut-sim:<n> containers/sim (log: .cache/container-build.log)."""
    import subprocess

    from xut.container import SIM_IMAGE, image_digest
    from xut.paths import cache_dir, repo_root

    log = cache_dir() / "container-build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as f:
        rc = subprocess.run(["docker", "build", "-t", SIM_IMAGE, str(repo_root() / "containers/sim")],
                            stdout=f, stderr=subprocess.STDOUT).returncode
    if rc:
        raise click.ClickException(f"docker build failed (exit {rc}); see {log}")
    click.echo(f"{SIM_IMAGE} {image_digest(SIM_IMAGE)}")


@container_grp.command("versions")
def container_versions_cmd() -> None:
    """Print the pinned tool versions inside xut-sim."""
    from xut.container import DockerExecutor, sim_tool_versions
    from xut.paths import repo_root

    work = repo_root() / "build"
    work.mkdir(exist_ok=True)
    for k, v in sim_tool_versions(DockerExecutor(), work).items():
        click.echo(f"{k}: {v}")
```

In `pyproject.toml`, under `[tool.pytest.ini_options]`:

```toml
markers = [
  "container: needs the xut-sim image (uv run xut container build)",
  "vivado: needs Vivado 2025.2 at /opt/xilinx/Vivado/2025.2",
]
```

In `tools/xut/doctor.py`:
- Add a check `sim-container`: `image_digest(SIM_IMAGE) is not None`.
- It enables `("iverilog", "verilator", "cocotb")`.
- The detail is the digest, or `run: uv run xut container build`.
- Change the existing `docker` check's `enables` to `()`, because the container check now carries the runners.
- Add a test to `tools/tests/test_doctor.py`: with a probe that reports docker OK but no image, `iverilog` is not in the available runners.

In `.github/workflows/ci.yml`, add a second job:

```yaml
  sim:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with: {submodules: true}
      - uses: astral-sh/setup-uv@v3
      - run: uv venv && uv pip install -e '.[dev]'
      - run: uv run xut container build
      - run: uv run pytest -v -m container
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest tools/tests -v > .cache/pytest.log 2>&1; tail -n 20 .cache/pytest.log`

Expected: all pass. That includes the `container` tests (pinned versions, cocotb smoke on Icarus **and** Verilator, the deassign pin), because the image was built in Step 3.

- [ ] **Step 10: Amend AGENTS.md (branch and PR rules)**

Add to the "One branch per work unit" section of `AGENTS.md`:

- One PR per branch, always. Never push work for a later PR onto a branch whose PR is open.
- A stacked branch is created from its parent branch, and its PR's base is the parent (`gh pr create --base <parent>`) until the parent merges.
- After a parent merges, only the orchestrator rebases the child onto `main`, re-runs its tests, pushes with `git push --force-with-lease` (only on its own feature branches; never on `main`, never over someone else's branch), and retargets the PR with `gh pr edit <N> --base main`. This is the only sanctioned force-push; the rule against force-pushing reviewed history still applies to everyone else.
- Reviewers run sequentially under the two-agent limit.

```bash
git add AGENTS.md && git commit -m "docs: AGENTS.md — one PR per branch, stacked-PR bases, orchestrator-only force-with-lease" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 11: Commit**

```bash
uv run ruff format tools && uv run ruff check tools > .cache/ruff.log 2>&1; cat .cache/ruff.log
git add containers tools pyproject.toml .github
git commit -m "infra: add pinned xut-sim container, executors and model sources" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The `.xvec` stimulus format

**Files:**
- Create: `tools/xut/formats/__init__.py`, `tools/xut/formats/xvec.py`, `tools/tests/test_xvec.py`

**Interfaces:**
- Produces:
  - `free_runs(vec)` and `free_clock_edges(vec) -> list[Event]`: the single definition of free-running clock edges used by validation, golden replay and the testbench compiler (review #6)
  - `xut.formats.xvec.Vec` (with properties `prim, cfg, nin, nout, nclk, settle_ps, seed, attrs, expect`, and `clock(name)`)
  - `Clock`, `Event`, `XvecError`
  - `loads(text) -> Vec`, `dumps(vec) -> str`, `load(path) -> Vec`, `dump(vec, path) -> None`
  - `decode_value(text, width, line=None) -> str`, `encode_value(bits) -> str`, `digest(vec) -> str` (sha256 of `dumps`)

The grammar is the module docstring below. It extends the spec §5.3 example with these resolutions:

- Events at `t < settle_ps` are allowed only as `t=0 set …` **initialisation** lines. They give inputs a defined value while `glbl` holds GSR, so an inverted control pin such as `IS_CLR_INVERTED=1` is not left active during power-up.
- The header carries the configuration as `attr.<NAME>=<literal>` keys, so a frozen `.xvec` (from a cocotb seed) describes itself.
- `expect=reject` marks an L0 illegal-attribute test: the simulation must end without `XUT_DONE`.
- `async_sep_ps` is the declared minimum separation between an async/gate change and any clock edge (spec §5.1).

- [ ] **Step 1: Write the failing tests** at `tools/tests/test_xvec.py`

```python
# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.formats.xvec import Event, XvecError, decode_value, dumps, encode_value, loads

SPEC_EXAMPLE = """\
# xut-vec 2  prim=FDCE cfg=init1 nin=4 nout=1 nclk=1 settle_ps=120000 seed=17
clock  clk0  period=10000 phase=0 duty=50 mode=stepped   # or mode=free
t=120000  set   in[3:0]=0x1          # data
t=121000  edge  clk0 r
t=125000  set   in[2]=1              # async: alone in its event
t=126000  sample S1
"""


def test_spec_example_parses():
    v = loads(SPEC_EXAMPLE)
    assert (v.prim, v.cfg, v.nin, v.nout, v.nclk, v.settle_ps, v.seed) == ("FDCE", "init1", 4, 1, 1, 120000, 17)
    assert v.clocks[0].mode == "stepped" and v.clocks[0].period == 10000
    assert v.events[0] == Event(120000, "set", "in", 0, 3, "0001")
    assert v.events[1] == Event(121000, "edge", "clk0", value="r")
    assert v.events[2] == Event(125000, "set", "in", 2, 2, "1")
    assert v.events[3] == Event(126000, "sample", "S1")


def test_roundtrip_is_canonical():
    v = loads(SPEC_EXAMPLE)
    assert loads(dumps(v)) == v
    assert dumps(loads(dumps(v))) == dumps(v)


def test_attrs_expect_and_hw_line():
    text = ("# xut-vec 2  prim=FDRE cfg=a nin=3 nout=1 nclk=1 settle_ps=120000 seed=1 "
            "attr.INIT=1'b1 expect=reject\n"
            'hw_renderable no reason="t=130000: simultaneous events"\n'
            "clock clk0 period=10000 phase=0 duty=50 mode=stepped\n"
            "t=0 set in[2]=1\n"
            "t=130000 end\n")
    v = loads(text)
    assert v.attrs == {"INIT": "1'b1"} and v.expect == "reject"
    assert v.hw_renderable is False and v.hw_reason == "t=130000: simultaneous events"
    assert loads(dumps(v)) == v


@pytest.mark.parametrize("text,width,bits", [
    ("0x1", 4, "0001"), ("5", 3, "101"), ("0b1x0z", 4, "1x0z"), ("0bx", 1, "x"),
    ("0x00f", 4, "1111"), ("0", 2, "00"),
])
def test_decode_value(text, width, bits):
    assert decode_value(text, width) == bits


@pytest.mark.parametrize("text,width", [("0x1f", 4), ("0b10", 1), ("0xg", 4), ("abc", 4), ("0bx0", 1),
                                        ("0x-1", 4), ("0x+1", 4), ("0x1_0", 8), ("-1", 4)])
def test_decode_value_rejects(text, width):
    with pytest.raises(XvecError):
        decode_value(text, width)


@pytest.mark.parametrize("bits,text", [("1", "1"), ("0001", "0x1"), ("1x", "0b1x"), ("000", "0x0")])
def test_encode_value(bits, text):
    assert encode_value(bits) == text
    assert decode_value(text, len(bits)) == bits


H = "# xut-vec 2  prim=P cfg=c nin=4 nout=1 nclk=1 settle_ps=100 seed=0\nclock clk0 period=10 phase=0 duty=50 mode=stepped\n"


@pytest.mark.parametrize("body,msg", [
    ("t=100 set in[4]=1\n", "out of range"),
    ("t=200 sample A\nt=100 sample B\n", "backwards"),
    ("t=100 edge clk1 r\n", "undeclared clock"),
    ("t=100 sample A\nt=200 sample A\n", "duplicate label"),
    ("t=50 sample A\n", "precede settle_ps"),
    ("t=100 simultaneous sample A\n", "simultaneous"),
    ("t=100 end\nt=200 sample A\n", "'end' must be the last"),
    ("t=100 frob x\n", "unknown op"),
    ("bogus\n", "unrecognised line"),
    ("t=100 set in[1:2]=0\n", "msb < lsb"),
])
def test_errors(body, msg):
    with pytest.raises(XvecError, match=msg):
        loads(H + body)


def test_missing_header_key():
    with pytest.raises(XvecError, match="lacks seed"):
        loads("# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=0 settle_ps=0\n")


def test_wrong_version():
    with pytest.raises(XvecError, match="version 1"):
        loads("# xut-vec 1  prim=P\n")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tools/tests/test_xvec.py -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log`

Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `tools/xut/formats/__init__.py`** (one line: the SPDX header and a docstring, `"""Stimulus and trace file formats (standard library only)."""`) **and `tools/xut/formats/xvec.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The ``.xvec`` stimulus format (spec §5.3). Standard library only.

Grammar (``#`` starts a comment everywhere except the header line)::

    file      := header NL { line NL }
    header    := "# xut-vec 2" { SP key "=" token }
                 required: prim cfg nin nout nclk settle_ps seed
                 optional: async_sep_ps expect attr.<NAME>
    line      := [ directive ] [ "#" comment ]
    directive := "clock" SP clk SP "period=" INT SP "phase=" INT SP "duty=" INT
                     SP "mode=" ( "stepped" | "free" )
               | "hw_renderable" SP ( "yes" | "no" SP "reason=" QUOTED )
               | "t=" INT [ SP "simultaneous" ] SP op
    op        := "set" SP "in[" INT [ ":" INT ] "]=" value
               | "edge" SP clk SP ( "r" | "f" )
               | "glbl" SP ( "GSR" | "GTS" | "GRESTORE" ) "=" ( "0" | "1" )
               | "sample" SP label
               | "clock_start" SP clk | "clock_stop" SP clk
               | "end"
    clk       := "clk" INT                     (index into the wrapper's clk vector)
    value     := "0x" HEX+ | "0b" ( "0"|"1"|"x"|"z" )+ | DECIMAL
    label     := [A-Za-z0-9_./-]+

Times are integer picoseconds and never decrease. Before ``settle_ps`` only
``t=0 set`` initialisation lines may appear. ``in[msb:lsb]`` values are stored
MSB-first as characters of ``01xz``. Class rules (spec §5.1) are checked by
``xut.validate``, not here: this module is syntax and self-consistency only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = "xut-vec"
VERSION = 2
REQUIRED = ("prim", "cfg", "nin", "nout", "nclk", "settle_ps", "seed")
INT_KEYS = ("nin", "nout", "nclk", "settle_ps", "seed", "async_sep_ps")
HEADER_ORDER = REQUIRED + ("async_sep_ps", "expect")

_HEADER = re.compile(r"^#\s*xut-vec\s+(\d+)\b(.*)$")
_KV = re.compile(r'([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|\S+)')
_CLOCK = re.compile(
    r"^clock\s+(clk(\d+))\s+period=(\d+)\s+phase=(\d+)\s+duty=(\d+)\s+mode=(stepped|free)$"
)
_HW = re.compile(r'^hw_renderable\s+(?:(yes)|no\s+reason="((?:[^"\\]|\\.)*)")$')
_EVENT = re.compile(r"^t=(\d+)\s+(?:(simultaneous)\s+)?(\w+)(?:\s+(.*))?$")
_SET = re.compile(r"^in\[(\d+)(?::(\d+))?\]=(\S+)$")
_EDGE = re.compile(r"^(clk\d+)\s+([rf])$")
_GLBL = re.compile(r"^(GSR|GTS|GRESTORE)=([01])$")
_LABEL = re.compile(r"^[A-Za-z0-9_./-]+$")


class XvecError(ValueError):
    """Syntax or self-consistency error, with the 1-based line number when known."""

    def __init__(self, msg: str, line: int | None = None):
        super().__init__(f"line {line}: {msg}" if line else msg)
        self.line = line


@dataclass(frozen=True)
class Clock:
    name: str
    index: int
    period: int
    phase: int
    duty: int
    mode: str  # "stepped" | "free"


@dataclass(frozen=True)
class Event:
    t: int
    op: str  # set | edge | glbl | sample | clock_start | clock_stop | end
    target: str = ""  # set: "in"; edge/clock_*: clock name; glbl: signal; sample: label
    lsb: int = 0
    msb: int = 0
    value: str = ""  # set: MSB-first 01xz; edge: r|f; glbl: 0|1
    simultaneous: bool = False


@dataclass
class Vec:
    header: dict[str, str]
    clocks: list[Clock] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    hw_renderable: bool | None = None
    hw_reason: str = ""

    @property
    def prim(self) -> str:
        return self.header["prim"]

    @property
    def cfg(self) -> str:
        return self.header["cfg"]

    @property
    def nin(self) -> int:
        return int(self.header["nin"])

    @property
    def nout(self) -> int:
        return int(self.header["nout"])

    @property
    def nclk(self) -> int:
        return int(self.header["nclk"])

    @property
    def settle_ps(self) -> int:
        return int(self.header["settle_ps"])

    @property
    def seed(self) -> int:
        return int(self.header["seed"])

    @property
    def expect(self) -> str | None:
        return self.header.get("expect")

    @property
    def attrs(self) -> dict[str, str]:
        return {k[5:]: v for k, v in self.header.items() if k.startswith("attr.")}

    def clock(self, name: str) -> Clock:
        for c in self.clocks:
            if c.name == name:
                return c
        raise KeyError(name)


def decode_value(text: str, width: int, line: int | None = None) -> str:
    """Return ``text`` as exactly ``width`` MSB-first characters of ``01xz``."""
    t = text.lower()
    if t.startswith("0b"):
        bits = t[2:]
        if not bits or set(bits) - set("01xz"):
            raise XvecError(f"bad binary value {text!r}", line)
    elif t.startswith("0x"):
        if not re.fullmatch(r"[0-9a-f]+", t[2:]):  # int() would accept "-1", "+1", "1_0"
            raise XvecError(f"bad hex value {text!r}", line)
        bits = format(int(t[2:], 16), "b")
    elif re.fullmatch(r"[0-9]+", t):
        bits = format(int(t), "b")
    else:
        raise XvecError(f"bad value {text!r}", line)
    if len(bits) > width and set(bits[: len(bits) - width]) != {"0"}:
        raise XvecError(f"value {text!r} does not fit in {width} bit(s)", line)
    return bits[-width:].rjust(width, "0")


def encode_value(bits: str) -> str:
    if set(bits) <= {"0", "1"}:
        return bits if len(bits) == 1 else f"0x{int(bits, 2):x}"
    return "0b" + bits


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def _quote(v: str) -> str:
    if v and not re.search(r'[\s"#]', v):
        return v
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _event(vec: Vec, t: int, op: str, arg: str, sim: bool, labels: set[str], n: int) -> Event:
    declared = {c.name for c in vec.clocks}
    if op == "set":
        m = _SET.match(arg)
        if not m:
            raise XvecError(f"bad set target {arg!r}", n)
        msb = int(m.group(1))
        lsb = int(m.group(2)) if m.group(2) is not None else msb
        if lsb > msb:
            raise XvecError(f"in[{msb}:{lsb}]: msb < lsb", n)
        if msb >= vec.nin:
            raise XvecError(f"in[{msb}] out of range (nin={vec.nin})", n)
        return Event(t, "set", "in", lsb, msb, decode_value(m.group(3), msb - lsb + 1, n), sim)
    if op == "edge":
        m = _EDGE.match(arg)
        if not m or m.group(1) not in declared:
            raise XvecError(f"edge on undeclared clock {arg!r}", n)
        return Event(t, "edge", m.group(1), value=m.group(2), simultaneous=sim)
    if op == "glbl":
        m = _GLBL.match(arg)
        if not m:
            raise XvecError(f"bad glbl event {arg!r}", n)
        return Event(t, "glbl", m.group(1), value=m.group(2), simultaneous=sim)
    if op == "sample":
        if not _LABEL.match(arg):
            raise XvecError(f"bad sample label {arg!r}", n)
        if arg in labels:
            raise XvecError(f"duplicate label {arg!r}", n)
        labels.add(arg)
        return Event(t, "sample", arg, simultaneous=sim)
    if op in ("clock_start", "clock_stop"):
        if arg not in declared or vec.clock(arg).mode != "free":
            raise XvecError(f"{op} needs a declared mode=free clock, got {arg!r}", n)
        return Event(t, op, arg, simultaneous=sim)
    if op == "end":
        if arg:
            raise XvecError("'end' takes no argument", n)
        return Event(t, "end", simultaneous=sim)
    raise XvecError(f"unknown op {op!r}", n)


def _check_structure(vec: Vec) -> None:
    ev = vec.events
    for i, e in enumerate(ev):
        if e.op == "end" and i != len(ev) - 1:
            raise XvecError("'end' must be the last event")
        if e.simultaneous and sum(1 for o in ev if o.t == e.t) < 2:
            raise XvecError(f"t={e.t}: 'simultaneous' on an event that is alone at its time")


def loads(text: str) -> Vec:
    lines = text.splitlines()
    if not lines:
        raise XvecError("empty file")
    m = _HEADER.match(lines[0])
    if not m:
        raise XvecError("first line must be '# xut-vec 2 ...'", 1)
    if int(m.group(1)) != VERSION:
        raise XvecError(f"unsupported xut-vec version {m.group(1)}", 1)
    header = {k: _unquote(v) for k, v in _KV.findall(m.group(2))}
    missing = [k for k in REQUIRED if k not in header]
    if missing:
        raise XvecError(f"header lacks {', '.join(missing)}", 1)
    for k in INT_KEYS:
        if k in header and not header[k].isdigit():
            raise XvecError(f"header {k} must be a non-negative integer", 1)
    vec = Vec(header)
    labels: set[str] = set()
    last_t = 0
    for n, raw in enumerate(lines[1:], start=2):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if c := _CLOCK.match(line):
            name, idx, period, phase, duty, mode = c.groups()
            if int(idx) >= vec.nclk or any(k.name == name for k in vec.clocks):
                raise XvecError(f"clock {name}: index out of range or declared twice", n)
            if int(period) <= 0 or not 0 < int(duty) < 100:
                raise XvecError(f"clock {name}: period must be > 0 and 0 < duty < 100", n)
            vec.clocks.append(Clock(name, int(idx), int(period), int(phase), int(duty), mode))
            continue
        if h := _HW.match(line):
            vec.hw_renderable = h.group(1) == "yes"
            vec.hw_reason = _unquote(f'"{h.group(2)}"') if h.group(2) is not None else ""
            continue
        e = _EVENT.match(line)
        if not e:
            raise XvecError(f"unrecognised line {raw.strip()!r}", n)
        t, sim, op, arg = int(e.group(1)), bool(e.group(2)), e.group(3), (e.group(4) or "").strip()
        if t < last_t:
            raise XvecError(f"time goes backwards ({t} < {last_t})", n)
        if t < vec.settle_ps and not (t == 0 and op == "set"):
            raise XvecError(f"only 't=0 set' initialisation may precede settle_ps={vec.settle_ps}", n)
        last_t = t
        vec.events.append(_event(vec, t, op, arg, sim, labels, n))
    _check_structure(vec)
    return vec


def _fmt(e: Event) -> str:
    head = f"t={e.t}" + (" simultaneous" if e.simultaneous else "")
    if e.op == "set":
        rng = str(e.msb) if e.msb == e.lsb else f"{e.msb}:{e.lsb}"
        return f"{head}  set in[{rng}]={encode_value(e.value)}"
    if e.op == "edge":
        return f"{head}  edge {e.target} {e.value}"
    if e.op == "glbl":
        return f"{head}  glbl {e.target}={e.value}"
    if e.op == "end":
        return f"{head}  end"
    return f"{head}  {e.op} {e.target}"


def dumps(vec: Vec) -> str:
    keys = [k for k in HEADER_ORDER if k in vec.header]
    keys += sorted(k for k in vec.header if k not in HEADER_ORDER)
    out = [f"# {MAGIC} {VERSION}  " + " ".join(f"{k}={_quote(vec.header[k])}" for k in keys)]
    if vec.hw_renderable is not None:
        reason = vec.hw_reason.replace("#", "no.").replace('"', "'")
        out.append("hw_renderable yes" if vec.hw_renderable else f'hw_renderable no reason="{reason}"')
    for c in vec.clocks:
        out.append(f"clock {c.name} period={c.period} phase={c.phase} duty={c.duty} mode={c.mode}")
    out += [_fmt(e) for e in vec.events]
    return "\n".join(out) + "\n"


def load(path: Path) -> Vec:
    return loads(Path(path).read_text())


def dump(vec: Vec, path: Path) -> None:
    Path(path).write_text(dumps(vec))


def digest(vec: Vec) -> str:
    return hashlib.sha256(dumps(vec).encode()).hexdigest()


def free_runs(vec: Vec) -> list[tuple[Clock, int, int | None]]:
    """(clock, start, stop) for every mode=free clock. A free clock with no clock_start
    runs from max(0, phase); stop is None when it runs to the end of the file."""
    runs, open_ = [], {}
    for c in vec.clocks:
        if c.mode == "free" and not any(e.op == "clock_start" and e.target == c.name
                                        for e in vec.events):
            open_[c.name] = max(0, c.phase)
    for e in vec.events:
        if e.op == "clock_start":
            open_[e.target] = e.t
        elif e.op == "clock_stop" and e.target in open_:
            runs.append((vec.clock(e.target), open_.pop(e.target), e.t))
    return runs + [(vec.clock(n), t0, None) for n, t0 in open_.items()]


def free_clock_edges(vec: Vec) -> list[Event]:
    """THE definition of free-clock edges, shared by xut.validate, xut.golden and
    xut.stimcompile (review #6): a rise at start + k*period, a fall period*duty/100
    later, nothing at or after a clock_stop (validate requires a stop to fall strictly
    inside a low phase, which is exactly where the testbench's generator stops), and
    nothing after the last event."""
    end = vec.events[-1].t if vec.events else 0
    out: list[Event] = []
    for c, start, stop in free_runs(vec):
        limit = end if stop is None else stop - 1
        high, t = c.period * c.duty // 100, start
        while t <= limit:
            out.append(Event(t, "edge", c.name, value="r"))
            if t + high <= limit:
                out.append(Event(t + high, "edge", c.name, value="f"))
            t += c.period
    return sorted(out, key=lambda e: e.t)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tools/tests/test_xvec.py -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format tools && uv run ruff check tools > .cache/ruff.log 2>&1; cat .cache/ruff.log
git add tools && git commit -m "formats: add .xvec stimulus grammar, parser and canonical writer" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The `.xtr` trace format and trace comparison

**Files:**
- Create: `tools/xut/formats/xtr.py`, `tools/tests/test_xtr.py`

**Interfaces:**
- Produces:
  - `xut.formats.xtr.Trace` (`header: dict`, `samples: dict[label, dict[port, bits]]`, `prov: dict[label, dict[port, str]]`, with `kind` and `add(label, values, prov=None)`)
  - `Mismatch` (frozen: `label, port, bit, expected, actual, prov, kind`)
  - `XtrError`
  - `loads`, `dumps`, `load`, `dump`
  - `compare(expected, actual, *, x_observable=True) -> list[Mismatch]`
  - `diff(a, b, *, a_x=True, b_x=True) -> list[Mismatch]`
  - `concat(parts: list[tuple[str, Trace]], header: dict) -> Trace`, which prefixes labels with `<cfg>/`

Line form, which resolves spec §5.3's "written per bit and grouped by port in a readable form":

```
# xut-trace 2  runner=iverilog flow=rtl model=unisim-2025.2 seed=17 prim=FDRE cfg=init1
S1  Q=1
S2  DO=0000_0000_1111_xxxx DOP=00
```

- Bits are MSB-first. Every 4 bits from the LSB end are separated by `_`, and the parser ignores `_`.
- Expected traces (`kind=expected`) may also contain `-` (don't care) and end with `| <port>=<provenance> ...`, e.g. `S1  Q=1  | Q=doc:375`. A provenance token has no whitespace (`inferred:doc_silent_on_GSR_vs_CLR`).
- The per-bit don't-care mask of spec §5.3 is therefore the set of `-` positions. Only the golden model writes it.

- [ ] **Step 1: Write the failing tests** at `tools/tests/test_xtr.py`

```python
# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.formats.xtr import Mismatch, Trace, XtrError, compare, concat, diff, dumps, loads

EXP = """\
# xut-trace 2  runner=python flow=rtl model=golden seed=17 kind=expected prim=FDRE cfg=a
S0  Q=0  | Q=doc:375
S1  Q=-  | Q=inferred:doc_silent_on_GSR_vs_CLR
S2  Q=1 DO=0000_1111  | Q=doc:375 DO=doc:375
"""


def _act(q0="0", q1="1", q2="1", do="00001111"):
    t = Trace({"runner": "iverilog", "flow": "rtl", "model": "unisim-2025.2", "seed": "17"})
    t.add("S0", {"Q": q0})
    t.add("S1", {"Q": q1})
    t.add("S2", {"Q": q2, "DO": do})
    return t


def test_parse_expected_with_prov_and_grouping():
    t = loads(EXP)
    assert t.kind == "expected"
    assert t.samples["S2"] == {"Q": "1", "DO": "00001111"}
    assert t.prov["S1"]["Q"] == "inferred:doc_silent_on_GSR_vs_CLR"
    assert loads(dumps(t)).samples == t.samples


def test_dumps_groups_by_four():
    assert "DO=0000_1111" in dumps(_act())
    assert "Q=1" in dumps(_act())


def test_dont_care_masks_and_match():
    assert compare(loads(EXP), _act()) == []


def test_x_where_defined_fails():
    m = compare(loads(EXP), _act(q2="x"))
    assert m == [Mismatch("S2", "Q", 0, "1", "x", "doc:375")]


def test_bit_index_is_lsb_zero():
    m = compare(loads(EXP), _act(do="00011111"))
    assert [(x.port, x.bit) for x in m] == [("DO", 4)]


def test_missing_and_extra_samples():
    a = _act()
    del a.samples["S0"]
    a.add("S9", {"Q": "0"})
    kinds = sorted(x.kind for x in compare(loads(EXP), a))
    assert kinds == ["extra-sample", "missing-sample"]


def test_diff_respects_x_observability():
    a, b = _act(q2="x"), _act(q2="1")
    assert diff(a, b) != []                    # both 4-state: x vs 1 differs
    assert diff(a, b, b_x=False) == []         # b is 2-state: cannot observe x
    assert diff(_act(q2="0"), b, b_x=False) != []


def test_actual_trace_rejects_dont_care():
    with pytest.raises(XtrError, match="'-'"):
        loads("# xut-trace 2  runner=x flow=rtl model=m seed=0\nS0  Q=-\n")


def test_concat_prefixes_labels():
    t = concat([("cfgA", _act()), ("cfgB", _act())], {"runner": "iverilog", "flow": "rtl",
                                                        "model": "m", "seed": "1"})
    assert list(t.samples)[:2] == ["cfgA/S0", "cfgA/S1"] and "cfgB/S2" in t.samples
```

- [ ] **Step 2: Run the tests and confirm they fail** (ImportError)

- [ ] **Step 3: Implement `tools/xut/formats/xtr.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The ``.xtr`` trace format (spec §5.3). Standard library only.

    file   := header NL { line NL }
    header := "# xut-trace 2" { SP key "=" token }
              keys: runner flow model seed, optionally kind(actual|expected) prim cfg ...
    line   := label { SP+ port "=" bits } [ SP+ "|" { SP+ port "=" provenance } ] [ "#" ... ]
    bits   := MSB-first chars of "01xz" (plus "-" = don't care in kind=expected); "_" ignored

Only the golden model writes "-" and provenance. A bit may be "-" only where
the model declares the documentation leaves it undefined.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = "xut-trace"
VERSION = 2
_HEADER = re.compile(r"^#\s*xut-trace\s+(\d+)\b(.*)$")
_KV = re.compile(r"([A-Za-z_][\w.]*)=(\S+)")
_LABEL = re.compile(r"^[A-Za-z0-9_./-]+$")
_PORT = re.compile(r"^([A-Za-z_][\w$]*)=([01xz_-]+)$")


class XtrError(ValueError):
    pass


@dataclass(frozen=True)
class Mismatch:
    label: str
    port: str
    bit: int  # LSB = 0; -1 for whole-sample/port problems
    expected: str
    actual: str
    prov: str | None = None
    kind: str = "value"  # value | missing-sample | missing-port | extra-sample

    def __str__(self) -> str:
        where = f"{self.label} {self.port}" + (f"[{self.bit}]" if self.bit >= 0 else "")
        tag = f" ({self.prov})" if self.prov else ""
        return f"{where}: expected {self.expected}, got {self.actual}{tag} [{self.kind}]"


@dataclass
class Trace:
    header: dict[str, str]
    samples: dict[str, dict[str, str]] = field(default_factory=dict)
    prov: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.header.get("kind", "actual")

    def add(self, label: str, values: dict[str, str], prov: dict[str, str] | None = None) -> None:
        if label in self.samples:
            raise XtrError(f"duplicate label {label!r}")
        self.samples[label] = dict(values)
        if prov:
            self.prov[label] = dict(prov)


def _group(bits: str) -> str:
    if len(bits) <= 4:
        return bits
    head = len(bits) % 4
    parts = ([bits[:head]] if head else []) + [bits[i:i + 4] for i in range(head, len(bits), 4)]
    return "_".join(parts)


def _token(prov: str) -> str:
    """Provenance is one whitespace-free token in the file ("inferred:a b" -> "inferred:a_b")."""
    return "_".join(prov.split())


def loads(text: str) -> Trace:
    lines = text.splitlines()
    m = _HEADER.match(lines[0]) if lines else None
    if not m or int(m.group(1)) != VERSION:
        raise XtrError("first line must be '# xut-trace 2 ...'")
    t = Trace(dict(_KV.findall(m.group(2))))
    allowed = set("01xz") | ({"-"} if t.kind == "expected" else set())
    for n, raw in enumerate(lines[1:], start=2):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        values_part, _, prov_part = line.partition("|")
        toks = values_part.split()
        if not toks or not _LABEL.match(toks[0]):
            raise XtrError(f"line {n}: missing or bad label")
        values = {}
        for tok in toks[1:]:
            pm = _PORT.match(tok)
            if not pm:
                raise XtrError(f"line {n}: bad value {tok!r}")
            bits = pm.group(2).replace("_", "")
            if set(bits) - allowed:
                raise XtrError(f"line {n}: '-' only allowed in kind=expected traces")
            values[pm.group(1)] = bits
        prov = {}
        for tok in prov_part.split():
            port, eq, tag = tok.partition("=")
            if not eq or not tag:
                raise XtrError(f"line {n}: bad provenance token {tok!r}")
            prov[port] = tag
        t.add(toks[0], values, prov or None)
    return t


def dumps(t: Trace) -> str:
    out = [f"# {MAGIC} {VERSION}  " + " ".join(f"{k}={v}" for k, v in t.header.items())]
    for label, ports in t.samples.items():
        line = label + "  " + " ".join(f"{p}={_group(b)}" for p, b in ports.items())
        if label in t.prov:
            line += "  | " + " ".join(f"{p}={_token(v)}" for p, v in t.prov[label].items())
        out.append(line)
    return "\n".join(out) + "\n"


def load(path: Path) -> Trace:
    return loads(Path(path).read_text())


def dump(t: Trace, path: Path) -> None:
    Path(path).write_text(dumps(t))


def compare(expected: Trace, actual: Trace, *, x_observable: bool = True) -> list[Mismatch]:
    """Expected (golden, may hold '-') against one runner's actual trace."""
    out: list[Mismatch] = []
    for label, ports in expected.samples.items():
        got = actual.samples.get(label)
        if got is None:
            out.append(Mismatch(label, "*", -1, "sample", "missing", None, "missing-sample"))
            continue
        for port, exp in ports.items():
            prov = expected.prov.get(label, {}).get(port)
            act = got.get(port)
            if act is None or len(act) != len(exp):
                out.append(Mismatch(label, port, -1, exp, act or "missing", prov, "missing-port"))
                continue
            for i, (e, a) in enumerate(zip(reversed(exp), reversed(act), strict=True)):
                if e == "-" or (e in "xz" and not x_observable):
                    continue
                if e != a:
                    out.append(Mismatch(label, port, i, e, a, prov))
    for label in actual.samples:
        if label not in expected.samples:
            out.append(Mismatch(label, "*", -1, "none", "sample", None, "extra-sample"))
    return out


def diff(a: Trace, b: Trace, *, a_x: bool = True, b_x: bool = True) -> list[Mismatch]:
    """Two actual traces. A position where one side shows x/z and the other runner
    cannot observe x/z (2-state) is not comparable and is skipped (spec §5.6)."""
    out: list[Mismatch] = []
    for label in a.samples.keys() | b.samples.keys():
        pa, pb = a.samples.get(label), b.samples.get(label)
        if pa is None or pb is None:
            out.append(Mismatch(label, "*", -1, "present" if pa else "missing",
                                "present" if pb else "missing", None, "missing-sample"))
            continue
        for port in pa.keys() | pb.keys():
            va, vb = pa.get(port), pb.get(port)
            if va is None or vb is None or len(va) != len(vb):
                out.append(Mismatch(label, port, -1, va or "missing", vb or "missing", None,
                                    "missing-port"))
                continue
            for i, (ca, cb) in enumerate(zip(reversed(va), reversed(vb), strict=True)):
                if ca == cb or (ca in "xz" and not b_x) or (cb in "xz" and not a_x):
                    continue
                out.append(Mismatch(label, port, i, ca, cb))
    return sorted(out, key=lambda m: (m.label, m.port, m.bit))


def concat(parts: list[tuple[str, Trace]], header: dict[str, str]) -> Trace:
    t = Trace(dict(header))
    for cfg, part in parts:
        for label, ports in part.samples.items():
            t.add(f"{cfg}/{label}", ports, part.prov.get(label))
    return t
```

Provenance is stored as one whitespace-free token per port. `dumps` turns the spaces in `inferred:<reason>` into `_`, so the file stays line-oriented. `crosscheck` needs only the `doc:`/`inferred:` prefix.

- [ ] **Step 4: Run the tests** — expect all to pass.

- [ ] **Step 5: Commit** with `formats: add .xtr trace format with don't-care masks and x-aware comparison`.

---

### Task 4: DUT wrapper generator (`xut wrap`)

**Files:**
- Create: `tools/xut/wrap.py`, `tools/tests/test_wrap.py`, `tools/tests/fixtures/wrap/FDRE_init1.v` (the expected wrapper text)
- Modify: `tools/xut/cli.py`

**Interfaces:**
- Consumes: `CatalogEntry`, `load_entry` (step 1); `HdlModule` (step 1); `default_class` (step 1)
- Produces:
  - `xut.wrap.PortSpec` (frozen: `name, direction, width, cls`)
  - `DutSpec` (frozen: `prim, family, cfg, ports, attrs: tuple[tuple[str, str], ...], raw_clock_out=False`)
  - `Bit` (frozen: `vec, bit, port, index, cls, role`)
  - `DutMap`, with:
    - fields `prim, family, cfg, attrs, nclk, nin, nout, bits`;
    - methods `of(vec)`, `port_bits(vec, port, role="")`, `clock_name(port)`, `clock_port(name)`, `in_ports()`, `out_ports()`, `to_json()`, `from_json(text)`, `load(path)`.
  - `WrapError`
  - `literal_value(lit: str) -> int`
  - `render_attr(attr: dict, value) -> str`
  - `spec_from_catalog(entry, cfg, attrs, *, allow_illegal=False) -> DutSpec`
  - `spec_from_hdl(mod, cfg, attrs, *, raw_clock_out=False) -> DutSpec`
  - `build_map(spec) -> DutMap`
  - `render_wrapper(spec, m) -> str`, `render_cfg_vh(m) -> str`, `render_cocotb_top(m) -> str`
  - `write_dut(spec, out_dir, *, cocotb_top=False) -> DutMap`, which writes `xut_dut.v`, `xut_dut.map.json` and `xut_cfg.vh` (and `xut_cocotb_top.v`)
  - CLI `xut wrap PRIM --cfg NAME --attr NAME=VALUE ... --out DIR [--cocotb-top]`

Rules (spec §5.1, §5.2):

- **Bit order.** Ports are taken in catalog order.
  - `clock`-class inputs go to `clk`; other inputs go to `in_vec`; outputs go to `out_vec`.
  - A port's LSB takes the lowest free bit.
  - An `inout` port P adds `P` role `drive_en` bits, then `drive_val` bits, to `in_vec`, and `obs` bits to `out_vec`.
- **Vector widths** are `max(1, n)`. `map.json` records the true `n`.
- **Attributes.**
  - Only explicitly-given attributes appear in the instance. The primitive's own defaults apply to the rest, and the golden model uses the *documented* defaults, so a default mismatch between UNISIM and UG953 surfaces as a finding.
  - A value outside an enumerated `allowed` list is rejected unless `allow_illegal=True` (for L0 rejection tests).
- **Classes the wrapper cannot realise yet.**
  - A `clock_out` port raises `WrapError` naming §5.4 (clock observers belong to a later step), unless `raw_clock_out=True`. That flag is for equivalence and portability smoke runs only: it samples the clock output directly.
  - `drp` and `pad` ports are wired like `data`, and their class is recorded in the map. The DRP transaction layer (§5.5) and the pad harness (§7.3) build on that record.
- **Keep attributes.** The instance carries `(* DONT_TOUCH = "TRUE", KEEP_HIERARCHY = "TRUE", keep *)`.

- [ ] **Step 1: Write the expected FDRE wrapper** `tools/tests/fixtures/wrap/FDRE_init1.v`

```verilog
// SPDX-License-Identifier: Apache-2.0
// GENERATED by xut wrap: prim=FDRE cfg=init1. Do not edit.
`timescale 1ps / 1ps
module xut_dut (
  input  wire [0:0] clk,
  input  wire [2:0] in_vec,
  output wire [0:0] out_vec
);
  (* DONT_TOUCH = "TRUE", KEEP_HIERARCHY = "TRUE", keep *)
  FDRE #(
    .INIT(1'b1)
  ) dut (
    .Q(out_vec[0]),
    .C(clk[0]),
    .CE(in_vec[0]),
    .D(in_vec[1]),
    .R(in_vec[2])
  );
endmodule
```

- [ ] **Step 2: Write the failing tests** at `tools/tests/test_wrap.py`

```python
# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path

import pyslang
import pytest

from xut.catalog.model import load_entry
from xut.catalog.unisim import HdlModule, HdlPort
from xut.paths import repo_root
from xut.wrap import (DutMap, PortSpec, DutSpec, WrapError, build_map, literal_value,
                      render_wrapper, spec_from_catalog, spec_from_hdl, write_dut)

FIX = Path(__file__).parent / "fixtures" / "wrap"


def _fdre():
    return load_entry("7series", "FDRE", repo_root())


def test_fdre_wrapper_text_matches_golden():
    spec = spec_from_catalog(_fdre(), "init1", {"INIT": "1'b1"})
    assert render_wrapper(spec, build_map(spec)) == (FIX / "FDRE_init1.v").read_text()


def test_fdre_map_bits():
    m = build_map(spec_from_catalog(_fdre(), "init1", {"INIT": 1}))
    assert (m.nclk, m.nin, m.nout) == (1, 3, 1)
    assert [(b.port, b.bit, b.cls) for b in m.of("in")] == [("CE", 0, "data"), ("D", 1, "data"),
                                                           ("R", 2, "data")]
    assert m.clock_name("C") == "clk0" and m.clock_port("clk0") == "C"
    assert m.attrs == {"INIT": "1'b1"}
    assert DutMap.from_json(m.to_json()) == m


def test_attr_rendering_and_allowed_check():
    e = _fdre()
    assert spec_from_catalog(e, "c", {"IS_C_INVERTED": 1}).attrs == (("IS_C_INVERTED", "1'b1"),)
    with pytest.raises(WrapError, match="unknown attribute"):
        spec_from_catalog(e, "c", {"NOPE": 1})


def test_literal_value():
    assert literal_value("1'b1") == 1
    assert literal_value("8'hA5") == 0xA5
    assert literal_value("4'd9") == 9
    assert literal_value("7") == 7


def _toy(ports):
    return HdlModule("TOYIO", Path("TOYIO.v"), [HdlPort(*p) for p in ports], [])


def test_inout_split_and_obs():
    spec = spec_from_hdl(_toy([("IO", "inout", 2), ("I", "input", 1), ("O", "output", 1)]), "d", {})
    m = build_map(spec)
    assert [(b.port, b.role, b.index) for b in m.of("in")] == [
        ("IO", "drive_en", 0), ("IO", "drive_en", 1), ("IO", "drive_val", 0), ("IO", "drive_val", 1),
        ("I", "", 0)]
    assert [(b.port, b.role) for b in m.of("out")] == [("IO", "obs"), ("IO", "obs"), ("O", "")]
    text = render_wrapper(spec, m)
    assert "assign IO__io[0] = in_vec[0] ? in_vec[2] : 1'bz;" in text
    assert "assign out_vec[0] = IO__io[0];" in text


def test_clock_out_needs_observers():
    mod = HdlModule("BUFG", Path("BUFG.v"), [HdlPort("O", "output", 1), HdlPort("I", "input", 1)], [])
    with pytest.raises(WrapError, match="§5.4"):
        build_map(spec_from_hdl(mod, "d", {}))
    m = build_map(spec_from_hdl(mod, "d", {}, raw_clock_out=True))
    assert [b.cls for b in m.of("out")] == ["clock_out"]


def test_written_wrapper_elaborates_with_stub(tmp_path):
    m = write_dut(spec_from_catalog(_fdre(), "init1", {"INIT": "1'b1"}), tmp_path, cocotb_top=True)
    assert json.loads((tmp_path / "xut_dut.map.json").read_text())["format"] == "xut-map 1"
    assert "`define XUT_NIN 3" in (tmp_path / "xut_cfg.vh").read_text()
    stub = ("module FDRE #(parameter [0:0] INIT = 1'b0)(output Q, input C, CE, D, R); endmodule\n"
            "module glbl; wire GSR; endmodule\n")
    comp = pyslang.ast.Compilation()
    for text in (stub, (tmp_path / "xut_dut.v").read_text(),
                 (tmp_path / "xut_cocotb_top.v").read_text()):
        comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromText(text))
    errors = [d for d in comp.getAllDiagnostics() if d.isError()]
    assert errors == [], pyslang.DiagnosticEngine.reportAll(comp.sourceManager, errors)
    assert m.nin == 3
```

- [ ] **Step 3: Run the tests and confirm they fail** (ImportError)

- [ ] **Step 4: Implement `tools/xut/wrap.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""DUT wrapper generator (spec §5.2): one ``xut_dut`` per test configuration."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from xut.catalog.model import CatalogEntry
from xut.catalog.portclass import default_class
from xut.catalog.unisim import HdlModule

MAP_FORMAT = "xut-map 1"
HEADER = "// SPDX-License-Identifier: Apache-2.0\n"


class WrapError(ValueError):
    pass


@dataclass(frozen=True)
class PortSpec:
    name: str
    direction: str
    width: int
    cls: str


@dataclass(frozen=True)
class DutSpec:
    prim: str
    family: str
    cfg: str
    ports: tuple[PortSpec, ...]
    attrs: tuple[tuple[str, str], ...]
    raw_clock_out: bool = False


@dataclass(frozen=True)
class Bit:
    vec: str  # clk | in | out
    bit: int
    port: str
    index: int
    cls: str
    role: str = ""  # "" | drive_en | drive_val | obs


@dataclass
class DutMap:
    prim: str
    family: str
    cfg: str
    attrs: dict[str, str]
    nclk: int
    nin: int
    nout: int
    bits: list[Bit] = field(default_factory=list)

    def of(self, vec: str) -> list[Bit]:
        return [b for b in self.bits if b.vec == vec]

    def port_bits(self, vec: str, port: str, role: str = "") -> list[Bit]:
        return [b for b in self.of(vec) if b.port == port and b.role == role]

    def clock_name(self, port: str) -> str:
        (b,) = self.port_bits("clk", port)
        return f"clk{b.bit}"

    def clock_port(self, name: str) -> str:
        return self.of("clk")[int(name[3:])].port

    def in_ports(self) -> list[str]:
        return list(dict.fromkeys(b.port for b in self.of("in") if b.role == ""))

    def out_ports(self) -> list[str]:
        return list(dict.fromkeys(b.port for b in self.of("out")))

    def cls_of(self, port: str) -> str:
        return next(b.cls for b in self.bits if b.port == port)

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps({"format": MAP_FORMAT, **d}, indent=1) + "\n"

    @classmethod
    def from_json(cls, text: str) -> DutMap:
        d = json.loads(text)
        if d.pop("format", None) != MAP_FORMAT:
            raise WrapError(f"not an {MAP_FORMAT} file")
        d["bits"] = [Bit(**b) for b in d["bits"]]
        return cls(**d)

    @classmethod
    def load(cls, path: Path) -> DutMap:
        return cls.from_json(Path(path).read_text())


_LIT = re.compile(r"^\s*(\d*)\s*'\s*([sS]?)([bBoOdDhH])\s*([0-9a-fA-F_xXzZ]+)\s*$")


def literal_value(lit: str | int) -> int:
    if isinstance(lit, int):
        return lit
    m = _LIT.match(str(lit))
    if not m:
        return int(str(lit), 10)
    radix = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(3).lower()]
    return int(m.group(4).replace("_", ""), radix)


def render_attr(a: dict, value) -> str:
    kind, width = a["kind"], a.get("width")
    if kind == "bits":
        if isinstance(value, int):
            return f"{width}'b{value:0{width}b}" if width <= 64 else f"{width}'h{value:x}"
        if "'" not in str(value):
            raise WrapError(f"attribute {a['name']}: bit-vector value needs a sized literal")
        return str(value)
    if kind == "string":
        return '"' + str(value).strip('"') + '"'
    if kind == "integer":
        return str(int(value))
    if kind == "real":
        return repr(float(value))
    raise WrapError(f"attribute {a['name']}: unknown kind {kind!r}")


def _check_allowed(prim: str, a: dict, lit: str) -> None:
    allowed = a.get("allowed") or []
    if not allowed or any(" to " in v or re.fullmatch(r"\d+-\d+", v) for v in allowed):
        return  # not an enumeration
    if a["kind"] == "bits":
        ok = any(literal_value(v) == literal_value(lit) for v in allowed if "'" in v or v.isdigit())
    elif a["kind"] == "string":
        ok = lit.strip('"') in [v.strip('"') for v in allowed]
    else:
        ok = lit in allowed
    if not ok:
        raise WrapError(f"{prim}.{a['name']}={lit} is not one of {allowed} (use allow_illegal)")


def spec_from_catalog(entry: CatalogEntry, cfg: str, attrs: dict, *,
                      allow_illegal: bool = False) -> DutSpec:
    known = {a["name"]: a for a in entry.attributes}
    unknown = sorted(set(attrs) - set(known))
    if unknown:
        raise WrapError(f"{entry.name}: unknown attribute(s) {unknown}")
    rendered = []
    for a in entry.attributes:
        if a["name"] in attrs:
            lit = render_attr(a, attrs[a["name"]])
            if not allow_illegal:
                _check_allowed(entry.name, a, lit)
            rendered.append((a["name"], lit))
    ports = tuple(PortSpec(p["name"], p["direction"], p["width"], p["cls"]) for p in entry.ports)
    return DutSpec(entry.name, entry.family, cfg, ports, tuple(rendered))


def spec_from_hdl(mod: HdlModule, cfg: str, attrs: dict, *, raw_clock_out: bool = False,
                  family: str = "7series") -> DutSpec:
    ports = tuple(PortSpec(p.name, p.direction, p.width, default_class(mod.name, p.name, p.direction))
                  for p in mod.ports)
    return DutSpec(mod.name, family, cfg, ports, tuple((k, str(v)) for k, v in attrs.items()),
                   raw_clock_out)


def build_map(spec: DutSpec) -> DutMap:
    bits: list[Bit] = []
    n = {"clk": 0, "in": 0, "out": 0}

    def add(vec: str, p: PortSpec, role: str = "") -> None:
        for i in range(p.width):
            bits.append(Bit(vec, n[vec], p.name, i, p.cls, role))
            n[vec] += 1

    for p in spec.ports:
        if p.cls == "clock_out" and not spec.raw_clock_out:
            raise WrapError(f"{spec.prim}.{p.name}: clock outputs need the clock observers of "
                            "spec §5.4, which are not implemented yet")
        if p.direction == "inout":
            add("in", p, "drive_en")
            add("in", p, "drive_val")
            add("out", p, "obs")
        elif p.direction == "input":
            add("clk" if p.cls == "clock" else "in", p)
        else:
            add("out", p)
    return DutMap(spec.prim, spec.family, spec.cfg, dict(spec.attrs), n["clk"], n["in"], n["out"], bits)


def _slice(sig: str, idx: list[int]) -> str:
    if len(idx) == 1:
        return f"{sig}[{idx[0]}]"
    if idx == list(range(idx[0], idx[-1] + 1)):
        return f"{sig}[{idx[-1]}:{idx[0]}]"
    return "{" + ", ".join(f"{sig}[{i}]" for i in reversed(idx)) + "}"


def render_wrapper(spec: DutSpec, m: DutMap) -> str:
    w = lambda k: max(1, k)  # noqa: E731
    out = [HEADER.rstrip("\n"),
           f"// GENERATED by xut wrap: prim={spec.prim} cfg={spec.cfg}. Do not edit.",
           "`timescale 1ps / 1ps",
           "module xut_dut (",
           f"  input  wire [{w(m.nclk) - 1}:0] clk,",
           f"  input  wire [{w(m.nin) - 1}:0] in_vec,",
           f"  output wire [{w(m.nout) - 1}:0] out_vec",
           ");"]
    conns = []
    for p in spec.ports:
        if p.direction == "inout":
            en = m.port_bits("in", p.name, "drive_en")
            val = m.port_bits("in", p.name, "drive_val")
            obs = m.port_bits("out", p.name, "obs")
            out.append(f"  wire [{p.width - 1}:0] {p.name}__io;")
            for i in range(p.width):
                out.append(f"  assign {p.name}__io[{i}] = in_vec[{en[i].bit}] ? "
                           f"in_vec[{val[i].bit}] : 1'bz;")
                out.append(f"  assign out_vec[{obs[i].bit}] = {p.name}__io[{i}];")
            conns.append((p.name, f"{p.name}__io"))
            continue
        vec = "out" if p.direction == "output" else ("clk" if p.cls == "clock" else "in")
        sig = {"clk": "clk", "in": "in_vec", "out": "out_vec"}[vec]
        conns.append((p.name, _slice(sig, [b.bit for b in m.port_bits(vec, p.name)])))
    if m.nout == 0:
        out.append("  assign out_vec = 1'b0;")
    out.append('  (* DONT_TOUCH = "TRUE", KEEP_HIERARCHY = "TRUE", keep *)')
    if spec.attrs:
        out.append(f"  {spec.prim} #(")
        out += [f"    .{k}({v})" + ("," if i < len(spec.attrs) - 1 else "")
                for i, (k, v) in enumerate(spec.attrs)]
        out.append("  ) dut (")
    else:
        out.append(f"  {spec.prim} dut (")
    out += [f"    .{k}({v})" + ("," if i < len(conns) - 1 else "") for i, (k, v) in enumerate(conns)]
    out += ["  );", "endmodule"]
    return "\n".join(out) + "\n"


def render_cfg_vh(m: DutMap) -> str:
    return (HEADER + f"// GENERATED by xut wrap: prim={m.prim} cfg={m.cfg}\n"
            f"`define XUT_NCLK {max(1, m.nclk)}\n`define XUT_NIN {max(1, m.nin)}\n"
            f"`define XUT_NOUT {max(1, m.nout)}\n")


def render_cocotb_top(m: DutMap) -> str:
    """cocotb has one toplevel, so glbl is instantiated here; UNISIM's ``glbl.GSR``
    resolves upward to this instance (IEEE 1364 upward name referencing)."""
    return (HEADER + "// GENERATED by xut wrap --cocotb-top. Do not edit.\n"
            "`timescale 1ps / 1ps\n`include \"xut_cfg.vh\"\n"
            "module xut_cocotb_top (\n"
            "  input  wire [`XUT_NCLK-1:0] clk,\n"
            "  input  wire [`XUT_NIN-1:0]  in_vec,\n"
            "  output wire [`XUT_NOUT-1:0] out_vec\n);\n"
            "  glbl glbl ();\n"
            "  xut_dut dut (.clk(clk), .in_vec(in_vec), .out_vec(out_vec));\n"
            "endmodule\n")


def write_dut(spec: DutSpec, out_dir: Path, *, cocotb_top: bool = False) -> DutMap:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m = build_map(spec)
    (out_dir / "xut_dut.v").write_text(render_wrapper(spec, m))
    (out_dir / "xut_dut.map.json").write_text(m.to_json())
    (out_dir / "xut_cfg.vh").write_text(render_cfg_vh(m))
    if cocotb_top:
        (out_dir / "xut_cocotb_top.v").write_text(render_cocotb_top(m))
    return m
```

**Implementer note.** `test_written_wrapper_elaborates_with_stub` compiles `xut_cocotb_top.v`, which does `` `include "xut_cfg.vh" ``. Give pyslang the include directory: build the tree with `SyntaxTree.fromText(text, sourceManager, ...)` using a `SourceManager` with `addUserDirectories(str(tmp_path))`. Alternatively, inline the include in the test before parsing. Keep the test's intent: zero pyslang errors.

- [ ] **Step 5: Add the CLI**

```python
@main.command("wrap")
@click.argument("prim")
@click.option("--cfg", default="default", show_default=True)
@click.option("--attr", "attrs", multiple=True, help="NAME=VALUE (Verilog literal), repeatable")
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--cocotb-top", is_flag=True, help="also write xut_cocotb_top.v")
@click.option("--allow-illegal", is_flag=True, help="permit values outside the allowed list (L0)")
def wrap_cmd(prim, cfg, attrs, out, cocotb_top, allow_illegal) -> None:
    """Generate xut_dut.v, xut_dut.map.json and xut_cfg.vh for one configuration."""
    from xut.catalog.model import load_entry
    from xut.paths import repo_root
    from xut.wrap import spec_from_catalog, write_dut

    pairs = dict(a.split("=", 1) for a in attrs)
    spec = spec_from_catalog(load_entry("7series", prim, repo_root()), cfg, pairs,
                             allow_illegal=allow_illegal)
    m = write_dut(spec, out, cocotb_top=cocotb_top)
    click.echo(f"{out}: nclk={m.nclk} nin={m.nin} nout={m.nout}")
```

- [ ] **Step 6: Run the tests, then try the CLI**

```bash
uv run pytest tools/tests/test_wrap.py -v > .cache/pytest.log 2>&1; tail -n 12 .cache/pytest.log
uv run xut wrap FDRE --cfg init1 --attr "INIT=1'b1" --out build/wrap-demo > .cache/wrap.log 2>&1; cat .cache/wrap.log
diff build/wrap-demo/xut_dut.v tools/tests/fixtures/wrap/FDRE_init1.v && echo SAME
```

Expected: all tests pass, `build/wrap-demo: nclk=1 nin=3 nout=1`, then `SAME`.

- [ ] **Step 7: Commit** with `infra: add xut wrap DUT wrapper generator with port map and keep attributes`.

---

### Task 5: Port-class validation and the stimulus builder

**Files:**
- Create: `tools/xut/validate.py`, `tools/xut/stimgen.py`, `tools/tests/test_validate.py`, `tools/tests/test_stimgen.py`
- Modify: `tools/xut/cli.py` (`xut vec check`)

**Interfaces:**
- Consumes: `Vec`, `Event`, `Clock` (Task 2); `DutMap`, `spec_from_catalog`, `build_map` (Task 4); `load_entry`
- Produces:
  - `xut.validate.DEFAULT_GAP_PS = 1000`, `DEFAULT_ASYNC_SEP_PS = 1000`, `ROC_WIDTH_PS = 100_000`, `GRES_END_PS = 20_000`
  - `Report` (`errors: list[str]`, `hw_reasons: list[str]`, with `ok` and `hw_renderable`)
  - `validate(vec, m, *, min_sample_gap_ps=DEFAULT_GAP_PS) -> Report`
  - `mark(vec, report) -> None`, which sets `vec.hw_renderable` and `vec.hw_reason`
  - `xut.stimgen.DEFAULT_SETTLE_PS = 120_000`, `DEFAULT_PERIOD_PS = 10_000`
  - `VecBuilder(m, *, seed, settle_ps, period_ps, gap_ps, async_sep_ps, expect=None)`, with:
    - `init(**ports)`, `set(**ports)`, `async_(port, value)`, `glbl(sig, value)`, `edge(port, rising)`;
    - `cycle(port=None, *, n=1, sample=True)`, `sample(label=None) -> str`, `wait(ps)`;
    - the context manager `simultaneous()`;
    - `value(port) -> int`, `build() -> Vec`.
  - `BuilderError`
  - `GenContext(family, prim, seed)`, with `dut(cfg, **attrs) -> VecBuilder`, `rng` and `specs: dict[cfg, DutSpec]`
  - CLI `xut vec check FILE.xvec --map MAP.json`

Rules checked by `validate` (spec §5.1, §5.3). Each error names the time and the rule.

1. The header `prim`, `nin`, `nout` and `nclk` match the map.
2. `settle_ps ≥ ROC_WIDTH_PS + DEFAULT_GAP_PS` (glbl releases GSR at 100 ns; GRESTORE ends at 20 ns).
3. Events are grouped by time, excluding the `t=0` initialisation. In a group with more than one change:
   - clock edges;
   - `glbl` events;
   - `set` events that touch any `async`/`gate` bit (or more than one such bit in one line)

   must be alone, unless **every** event in the group is `simultaneous`.
4. A `sample` never shares its time with a change. It is at least `min_sample_gap_ps` after the previous change.
5. An `async`/`gate` change is at least `async_sep_ps` from every clock edge before or after it: the explicit `stepped` edges and the edges computed for `free` clocks. `simultaneous` events are exempt.
6. On each `stepped` clock, edges alternate `r`, `f`, `r`, … starting from the idle 0. `edge` on a `free` clock is an error.
7. `set` never touches a `clock`-class bit (such a bit cannot be in `in_vec`; this is a consistency check).

`hw_renderable` becomes `no`, with every reason listed, when any of these hold:

- there is a `simultaneous` event;
- a `set` value contains `x`/`z`;
- a `pad`-class bit is driven (it needs the §7.3 pad harness);
- there is a `glbl` event other than `GSR`, which only simulation can drive (§5.2).

The stepped-clock timeline `VecBuilder.cycle` emits (period `P`, gap `g`, start `s`):

| time | event |
|---|---|
| `s` | `edge clkK r` (alone) |
| `s+g` | `sample` |
| `s+P/2` | `edge clkK f` (alone) |
| `s+P/2+g` | `sample` |
| `s+P` | ready for the next data `set` (the next cycle's edge is ≥ `g` later) |

- [ ] **Step 1: Write the failing tests**

`tools/tests/test_validate.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.catalog.model import load_entry
from xut.formats.xvec import loads
from xut.paths import repo_root
from xut.validate import validate
from xut.wrap import build_map, spec_from_catalog

HDR = ("# xut-vec 2  prim=FDCE cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0\n"
       "clock clk0 period=10000 phase=0 duty=50 mode=stepped\n")
# FDCE catalog order Q, C, CE, CLR, D -> in: CE=0, CLR=1 (async), D=2


@pytest.fixture(scope="module")
def fdce_map():
    return build_map(spec_from_catalog(load_entry("7series", "FDCE", repo_root()), "c", {}))


def _v(body):
    return loads(HDR + body)


def test_clean_file(fdce_map):
    r = validate(_v("t=120000 set in[2]=1\nt=121000 edge clk0 r\nt=122000 sample S0\n"
                    "t=126000 edge clk0 f\nt=130000 set in[1]=1\nt=131000 sample S1\n"), fdce_map)
    assert r.errors == [] and r.hw_renderable


@pytest.mark.parametrize("body,msg", [
    ("t=121000 edge clk0 r\nt=121000 set in[2]=1\n", "must be alone"),
    ("t=121000 set in[1]=1\nt=121000 set in[2]=1\n", "must be alone"),
    ("t=121000 set in[2:1]=0x3\n", "must be alone"),
    ("t=121000 set in[2]=1\nt=121000 sample S0\n", "shares its time"),
    ("t=121000 set in[2]=1\nt=121500 sample S0\n", "after the last change"),
    ("t=121000 edge clk0 r\nt=121500 set in[1]=1\n", "from a clock edge"),
    ("t=121000 edge clk0 f\n", "alternate"),
])
def test_rule_violations(fdce_map, body, msg):
    assert any(msg in e for e in validate(_v(body), fdce_map).errors)


def test_simultaneous_allowed_but_not_hw(fdce_map):
    r = validate(_v("t=121000 simultaneous edge clk0 r\nt=121000 simultaneous set in[1]=1\n"
                    "t=123000 sample S0\n"), fdce_map)
    assert r.errors == [] and not r.hw_renderable
    assert any("simultaneous" in x for x in r.hw_reasons)


def test_x_and_glbl_make_sim_only(fdce_map):
    r = validate(_v("t=121000 set in[2]=0bx\nt=123000 glbl GTS=1\nt=125000 sample S0\n"), fdce_map)
    assert r.errors == []
    assert sorted(r.hw_reasons) == ["t=121000: x/z stimulus", "t=123000: glbl GTS is sim-only (spec §5.2)"]


def test_settle_too_short(fdce_map):
    v = loads(HDR.replace("settle_ps=120000", "settle_ps=50000"))
    assert any("settle_ps" in e for e in validate(v, fdce_map).errors)


def test_free_clock_edges_count_for_async_separation(fdce_map):
    v = loads(HDR.replace("mode=stepped", "mode=free")
              + "t=120000 clock_start clk0\nt=130200 set in[1]=1\nt=135000 sample S0\n")
    errors = validate(v, fdce_map).errors
    assert any("from a clock edge" in e for e in errors)
    assert any("t=135000: a sample shares its time" in e for e in errors)  # 135000 is a free edge


def test_free_clock_stop_must_be_in_low_phase(fdce_map):
    base = HDR.replace("mode=stepped", "mode=free") + "t=120000 clock_start clk0\n"
    assert any("low phase" in e for e in validate(loads(base + "t=122000 clock_stop clk0\n"),
                                                  fdce_map).errors)       # high phase
    assert not any("low phase" in e for e in validate(loads(base + "t=127000 clock_stop clk0\n"),
                                                      fdce_map).errors)   # low phase


def test_free_clock_edges_definition(fdce_map):
    from xut.formats.xvec import free_clock_edges

    v = loads(HDR.replace("mode=stepped", "mode=free")
              + "t=120000 clock_start clk0\nt=137000 clock_stop clk0\nt=150000 end\n")
    edges = [(e.t, e.value) for e in free_clock_edges(v)]
    assert edges == [(120000, "r"), (125000, "f"), (130000, "r"), (135000, "f")]
    # golden (Task 6) and the stimulus compiler (Task 7) are pinned to this same
    # definition by test_golden.py and test_stimcompile.py::test_free_clock_words
```

`tools/tests/test_stimgen.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.catalog.model import load_entry
from xut.formats.xvec import dumps, loads
from xut.paths import repo_root
from xut.stimgen import BuilderError, GenContext, VecBuilder
from xut.validate import validate
from xut.wrap import build_map, spec_from_catalog


def _b(prim="FDCE", **kw):
    m = build_map(spec_from_catalog(load_entry("7series", prim, repo_root()), "c", {}))
    return VecBuilder(m, seed=3, **kw), m


def test_cycle_timeline():
    b, m = _b("FDRE")
    b.set(CE=1, D=1)
    b.cycle()
    ev = [(e.t, e.op, e.target, e.value) for e in b.build().events]
    assert ev[:6] == [(120000, "set", "in", "1"), (120000, "set", "in", "1"),
                      (121000, "edge", "clk0", "r"), (122000, "sample", "S0", ""),
                      (126000, "edge", "clk0", "f"), (127000, "sample", "S1", "")]


def test_every_builder_output_validates():
    b, m = _b()
    b.init(CLR=0)
    b.set(CE=1, D=1)
    b.cycle()
    b.async_("CLR", 1)
    b.sample()
    b.async_("CLR", 0)
    b.glbl("GSR", 1)
    b.sample()
    b.glbl("GSR", 0)
    b.cycle(n=3)
    with b.simultaneous():
        b.edge("C", True)
        b.async_("CLR", 1)
    b.sample()
    v = b.build()
    r = validate(v, m)
    assert r.errors == []
    assert not r.hw_renderable
    assert loads(dumps(v)) == v


def test_set_refuses_async_ports():
    b, _ = _b()
    with pytest.raises(BuilderError, match="async_"):
        b.set(CLR=1)


def test_header_carries_attrs_and_seed():
    m = build_map(spec_from_catalog(load_entry("7series", "FDRE", repo_root()), "i1", {"INIT": 1}))
    v = VecBuilder(m, seed=9).build()
    assert v.attrs == {"INIT": "1'b1"} and v.seed == 9 and v.events[-1].op == "end"


def test_gencontext_records_specs():
    ctx = GenContext("7series", "FDRE", seed=5)
    b = ctx.dut("init1", INIT=1)
    assert "init1" in ctx.specs and b.build().cfg == "init1"
    with pytest.raises(BuilderError, match="twice"):
        ctx.dut("init1", INIT=0)
```

- [ ] **Step 2: Run the tests and confirm they fail** (ImportError)

- [ ] **Step 3: Implement `tools/xut/validate.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Port-class rules for stimulus files (spec §5.1, §5.3) and hw renderability."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from itertools import groupby

from xut.formats.xvec import Event, Vec, free_clock_edges, free_runs
from xut.wrap import DutMap

DEFAULT_GAP_PS = 1_000  # sample/change spacing; clears the UNISIM 100 ps clock-to-Q
DEFAULT_ASYNC_SEP_PS = 1_000
ROC_WIDTH_PS = 100_000  # glbl.v: GSR released after ROC_WIDTH
GRES_END_PS = 20_000  # glbl.v: GRES_START + GRES_WIDTH


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    hw_reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def hw_renderable(self) -> bool:
        return not self.hw_reasons


def _desc(e: Event) -> str:
    if e.op == "set":
        return f"set in[{e.msb}:{e.lsb}]"
    return f"{e.op} {e.target}".strip()


def _check_free_stops(vec: Vec, r: Report) -> None:
    """A clock_stop must fall strictly inside a low phase (the testbench's generator then
    stops without another edge), and a restart must wait for that low phase to end."""
    for c, start, stop in free_runs(vec):
        if stop is None:
            continue
        high, pos = c.period * c.duty // 100, (stop - start) % c.period
        if not high < pos:
            r.errors.append(f"t={stop}: clock_stop {c.name} must fall strictly inside a low phase")
        restart = next((e.t for e in vec.events if e.op == "clock_start" and e.target == c.name
                        and e.t > stop), None)
        if restart is not None and restart < stop + (c.period - pos):
            r.errors.append(f"t={restart}: clock_start {c.name} before its previous low phase ended")


def validate(vec: Vec, m: DutMap, *, min_sample_gap_ps: int = DEFAULT_GAP_PS) -> Report:
    r = Report()
    for key, want in (("nin", m.nin), ("nout", m.nout), ("nclk", m.nclk)):
        if int(vec.header[key]) != want:
            r.errors.append(f"header {key}={vec.header[key]} but the wrapper has {want}")
    if vec.prim != m.prim:
        r.errors.append(f"header prim={vec.prim} but the wrapper is {m.prim}")
    if vec.settle_ps < ROC_WIDTH_PS + DEFAULT_GAP_PS:
        r.errors.append(f"settle_ps={vec.settle_ps} < glbl ROC_WIDTH {ROC_WIDTH_PS} + margin")
    sep = int(vec.header.get("async_sep_ps", DEFAULT_ASYNC_SEP_PS))
    cls = {b.bit: b.cls for b in m.of("in")}
    _check_free_stops(vec, r)
    # Free-clock edges are changes like any other (review #6c): merged into the timeline,
    # they take part in the alone, sample-coincidence, sample-gap and async-separation rules.
    computed = free_clock_edges(vec)
    auto = {(e.t, e.target, e.value) for e in computed}
    timed = sorted([e for e in vec.events if not (e.t == 0 and e.op == "set")] + computed,
                   key=lambda e: e.t)  # stable: file order within a time
    edges = [e.t for e in timed if e.op == "edge"]
    level: dict[str, str] = {c.name: "f" for c in vec.clocks}
    last_change: int | None = None
    for t, grp in groupby(timed, key=lambda e: e.t):
        grp = list(grp)
        changes = [e for e in grp if e.op not in ("sample", "end")]
        samples = [e for e in grp if e.op == "sample"]
        if samples and changes:
            r.errors.append(f"t={t}: a sample shares its time with a change")
        for s in samples:
            if last_change is not None and t - last_change < min_sample_gap_ps:
                r.errors.append(f"t={t}: sample {s.target} is {t - last_change} ps after the last "
                                f"change (< {min_sample_gap_ps})")
        lonely = []
        for e in changes:
            if e.op in ("edge", "glbl"):
                lonely.append(e)
            elif e.op == "set":
                classes = [cls[b] for b in range(e.lsb, e.msb + 1)]
                n_async = sum(c in ("async", "gate") for c in classes)
                if n_async and (len(changes) > 1 or n_async > 1 or len(classes) > n_async):
                    lonely.append(e)
        if lonely and not all(e.simultaneous for e in changes):
            r.errors.append(f"t={t}: {', '.join(_desc(e) for e in lonely)} must be alone in its "
                            "event (spec §5.1) or every event at this time marked 'simultaneous'")
        if any(e.simultaneous for e in grp):
            r.hw_reasons.append(f"t={t}: simultaneous events")
        for e in changes:
            if e.op == "edge":
                if vec.clock(e.target).mode == "free":
                    if (e.t, e.target, e.value) not in auto:
                        r.errors.append(f"t={t}: explicit edge on free-running {e.target}")
                elif level[e.target] == e.value:
                    r.errors.append(f"t={t}: edges on {e.target} must alternate r/f from idle 0")
                level[e.target] = e.value
            elif e.op == "set":
                classes = {cls[b] for b in range(e.lsb, e.msb + 1)}
                if "clock" in classes:
                    r.errors.append(f"t={t}: set touches a clock-class bit")
                if set(e.value) - {"0", "1"}:
                    r.hw_reasons.append(f"t={t}: x/z stimulus")
                if "pad" in classes:
                    r.hw_reasons.append(f"t={t}: pad-class port needs the pad harness (spec §7.3)")
                if classes & {"async", "gate"} and not e.simultaneous:
                    i = bisect.bisect_left(edges, t)
                    near = [abs(x - t) for x in edges[max(0, i - 1): i + 1]]
                    if near and min(near) < sep:
                        r.errors.append(f"t={t}: async/gate change {min(near)} ps from a clock "
                                        f"edge (< async_sep_ps={sep})")
            elif e.op == "glbl" and e.target != "GSR":
                r.hw_reasons.append(f"t={t}: glbl {e.target} is sim-only (spec §5.2)")
        if changes:
            last_change = t
    return r


def mark(vec: Vec, report: Report) -> None:
    vec.hw_renderable = report.hw_renderable
    vec.hw_reason = "; ".join(report.hw_reasons)
```

- [ ] **Step 4: Implement `tools/xut/stimgen.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Stimulus builder: emits only .xvec files that satisfy xut.validate."""

from __future__ import annotations

import random
from contextlib import contextmanager

from xut.formats.xvec import Clock, Event, Vec
from xut.validate import DEFAULT_ASYNC_SEP_PS, DEFAULT_GAP_PS
from xut.wrap import DutMap, DutSpec, build_map, spec_from_catalog

DEFAULT_SETTLE_PS = 120_000
DEFAULT_PERIOD_PS = 10_000


class BuilderError(ValueError):
    pass


class VecBuilder:
    def __init__(self, m: DutMap, *, seed: int, settle_ps: int = DEFAULT_SETTLE_PS,
                 period_ps: int = DEFAULT_PERIOD_PS, gap_ps: int = DEFAULT_GAP_PS,
                 async_sep_ps: int = DEFAULT_ASYNC_SEP_PS, expect: str | None = None):
        if 3 * gap_ps > period_ps // 2:
            raise BuilderError("period too short for edge + sample + change spacing")
        self.m, self.seed, self.settle, self.period = m, seed, settle_ps, period_ps
        self.gap, self.sep, self.expect = gap_ps, async_sep_ps, expect
        self.t = settle_ps
        self._events: list[Event] = []
        self._vals = {p: 0 for p in m.in_ports()}
        self._last_change = 0
        self._last_edge: int | None = None
        self._n = 0
        self._sim = False

    # -- helpers -------------------------------------------------------------
    def _emit(self, op: str, target: str = "", lsb: int = 0, msb: int = 0, value: str = "") -> None:
        self._events.append(Event(self.t, op, target, lsb, msb, value, self._sim))

    def _after(self, t: int) -> None:
        self.t = max(self.t, t)

    def _put(self, port: str, value: int | str) -> None:
        bits = self.m.port_bits("in", port)
        if not bits:
            raise BuilderError(f"{self.m.prim} has no in_vec port {port!r}")
        s = value if isinstance(value, str) else format(value, f"0{len(bits)}b")
        self._emit("set", "in", bits[0].bit, bits[-1].bit, s)
        self._vals[port] = value
        self._last_change = self.t

    def _alone_start(self) -> None:
        if not self._sim:
            self._after(self._last_change + self.gap)

    def _alone_end(self) -> None:
        if not self._sim:
            self.t += self.gap

    def value(self, port: str) -> int | str:
        return self._vals[port]

    # -- API -----------------------------------------------------------------
    def init(self, **ports: int) -> None:
        """Initial input values at t=0 (spec §5.3 initialisation lines)."""
        if any(e.t > 0 for e in self._events):
            raise BuilderError("init() must come before any timed event")
        t, self.t = self.t, 0
        for p, v in ports.items():
            self._put(p, v)
        self.t, self._last_change = t, 0

    def set(self, **ports: int | str) -> None:
        """Change data-class inputs together, strictly between clock edges."""
        for p in ports:
            if self.m.cls_of(p) in ("async", "gate", "clock") and not self._sim:
                raise BuilderError(f"{p} is {self.m.cls_of(p)}-class: use async_() or edge()")
        if self._last_edge is not None and not self._sim:
            self._after(self._last_edge + self.gap)
        for p, v in ports.items():
            if self._vals.get(p) != v:
                self._put(p, v)

    def async_(self, port: str, value: int | str) -> None:
        """Change one async/gate input alone, >= async_sep_ps away from clock edges."""
        if not self._sim:
            self._alone_start()
            if self._last_edge is not None:
                self._after(self._last_edge + self.sep)
        self._put(port, value)
        self._alone_end()
        if not self._sim:
            self._after(self.t + max(0, self.sep - self.gap))

    def glbl(self, sig: str, value: int) -> None:
        self._alone_start()
        self._emit("glbl", sig, value=str(value))
        self._last_change = self.t
        self._alone_end()

    def edge(self, port: str, rising: bool) -> None:
        self._alone_start()
        self._emit("edge", self.m.clock_name(port), value="r" if rising else "f")
        self._last_edge = self._last_change = self.t
        self._alone_end()

    def sample(self, label: str | None = None) -> str:
        self._after(self._last_change + self.gap)
        label = label or f"S{self._n}"
        self._n += 1
        self._emit("sample", label)
        self.t += self.gap
        return label

    def cycle(self, port: str | None = None, *, n: int = 1, sample: bool = True) -> None:
        if port is None:
            clocks = list(dict.fromkeys(b.port for b in self.m.of("clk")))
            if len(clocks) != 1:
                raise BuilderError(f"cycle() needs a port: clocks are {clocks}")
            port = clocks[0]
        for _ in range(n):
            self._after(self._last_change + self.gap)
            start = self.t
            self.edge(port, True)
            if sample:
                self.sample()
            self._after(start + self.period // 2)
            self.edge(port, False)
            if sample:
                self.sample()
            self._after(start + self.period)

    def wait(self, ps: int) -> None:
        self.t += ps

    @contextmanager
    def simultaneous(self):
        """Events inside happen at one instant, all marked 'simultaneous' (sim only)."""
        self._after(self._last_change + self.gap)
        if self._last_edge is not None:
            self._after(self._last_edge + self.gap)
        self._sim = True
        try:
            yield
        finally:
            self._sim = False
            self.t += self.gap

    def build(self) -> Vec:
        m = self.m
        header = {"prim": m.prim, "cfg": m.cfg, "nin": str(m.nin), "nout": str(m.nout),
                  "nclk": str(m.nclk), "settle_ps": str(self.settle), "seed": str(self.seed),
                  "async_sep_ps": str(self.sep)}
        if self.expect:
            header["expect"] = self.expect
        header.update({f"attr.{k}": v for k, v in m.attrs.items()})
        clocks = [Clock(f"clk{b.bit}", b.bit, self.period, 0, 50, "stepped") for b in m.of("clk")]
        end = Event(max(self.t, self._last_change + self.gap), "end")
        return Vec(header, clocks, [*self._events, end])


class GenContext:
    """What a vector generator function receives (``def gen(ctx) -> Iterable[Vec]``)."""

    def __init__(self, family: str, prim: str, seed: int, root=None):
        from xut.paths import repo_root

        self.family, self.prim, self.seed = family, prim, seed
        self.rng = random.Random(seed)
        self.root = root or repo_root()
        self.specs: dict[str, DutSpec] = {}

    def dut(self, cfg: str, *, allow_illegal: bool = False, expect: str | None = None,
            **attrs) -> VecBuilder:
        from xut.catalog.model import load_entry

        if cfg in self.specs:
            raise BuilderError(f"configuration {cfg!r} defined twice")
        spec = spec_from_catalog(load_entry(self.family, self.prim, self.root), cfg, attrs,
                                 allow_illegal=allow_illegal)
        self.specs[cfg] = spec
        return VecBuilder(build_map(spec), seed=self.seed, expect=expect)
```

The expected timeline in `test_cycle_timeline` follows from the code:

- `set` at 120000;
- `cycle`: `_after(120000 + 1000)` → edge r at 121000, `t` = 122000;
- sample at 122000, `t` = 123000;
- `_after(121000 + 5000)` → edge f at 126000, `t` = 127000;
- sample at 127000.

`async_` leaves `t` at least `async_sep_ps` past the change, so a following `cycle` edge also respects rule 5.

- [ ] **Step 5: Add `xut vec check`**

```python
@main.group("vec")
def vec_grp() -> None:
    """Stimulus (.xvec) utilities."""


@vec_grp.command("check")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--map", "map_path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              required=True)
def vec_check_cmd(path: Path, map_path: Path) -> None:
    """Validate an .xvec against a wrapper map (spec §5.1 class rules)."""
    from xut.formats.xvec import load
    from xut.validate import validate
    from xut.wrap import DutMap

    r = validate(load(path), DutMap.load(map_path))
    for e in r.errors:
        click.echo(f"error: {e}")
    click.echo(f"hw_renderable: {'yes' if r.hw_renderable else 'no'}")
    for h in r.hw_reasons:
        click.echo(f"  reason: {h}")
    if r.errors:
        raise SystemExit(1)
```

- [ ] **Step 6: Run the tests** (`uv run pytest tools/tests/test_validate.py tools/tests/test_stimgen.py -v > .cache/pytest.log 2>&1; tail -n 20 .cache/pytest.log`). Expect all to pass.

- [ ] **Step 7: Commit**

```bash
git add tools/xut/validate.py tools/tests/test_validate.py && git commit -m "infra: validate stimulus against port-class rules and mark hw renderability" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tools/xut/stimgen.py tools/tests/test_stimgen.py tools/xut/cli.py && git commit -m "infra: add VecBuilder and GenContext stimulus builder, xut vec check" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Progress log and PR checkpoint A**

Write `log/<YYYY-MM-DDTHHMM>-infra-sim-formats-part-a.md`. Record what landed, the pytest summary line, the container digest from `uv run xut container build`, and the next steps. Commit it with `log: infra/sim-formats`.

Then:

```bash
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
git push -u origin infra/sim-formats
gh pr create --base main --title "infra: sim formats — container, formats, wrapper, validation" --body-file .cache/pr-a.md
```

`.cache/pr-a.md` summarises Tasks 1–5, lists the Review Focus items that apply (3, 4), and ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Run the review gate from spec §13.4 (reviewers sequentially). **Nothing more is pushed to `infra/sim-formats`** except review-fix commits for PR A. Task 6 starts on the stacked branch `infra/sim-runners`.

---

### Task 6: Golden-model base API and replay

**Create the stacked worktree** (PR B's branch; its base is `infra/sim-formats` until PR A merges):

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git worktree add ../xilinx-unittests-worktrees/infra-sim-runners -b infra/sim-runners infra/sim-formats
cd ../xilinx-unittests-worktrees/infra-sim-runners && mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; cat .cache/uv-install.log
```

**Files:**
- Create: `models/xut_models/__init__.py`, `models/xut_models/base.py`, `models/xut_models/registry.py`, `models/xut_models/7series/__init__.py`, `models/xut_models/7series/_common/__init__.py`, `tools/xut/golden.py`, `tools/tests/test_golden.py`
- Modify: `pyproject.toml` (the wheel packages add `models/xut_models`)

**Interfaces:**
- Produces:
  - `xut_models.base.Model` (ABC), with:
    - class attributes `PRIM, FAMILY, CLOCKS, OUTPUTS`;
    - `inputs()` (classmethod);
    - `power_on()`, `set_input(port, value)`, `clock_edge(port, rising)`, `glbl(signal, value)`, `outputs() -> dict[str, Out]`;
    - `hit(claim_id)` and `claims_hit`.
  - `Out` (frozen: `bits`, `prov`; validated)
  - `ModelUnsupported`
  - `bit_attr(v) -> int`
  - `xut_models.registry.get(family, prim) -> type[Model]`
  - `xut.golden.Reach` (`ports`, `attrs`, `claims`, with `bins() -> set[str]`)
  - `expand_free_clocks(vec) -> list[Event]`
  - `replay(model_cls, vec, m) -> tuple[Trace, Reach]`

Semantics of `replay` (it mirrors the testbench exactly):

1. Construct the model with `vec.attrs`, the **explicitly-set** attributes. The model supplies documented defaults for the rest.
2. Call `power_on()`: glbl asserts GSR from time 0.
3. Drive every `in_vec` port to 0. Then apply the `t=0` initialisation sets.
4. Walk the events in order. Before the first event at `t ≥ ROC_WIDTH_PS`, call `glbl("GSR", 0)`: glbl.v releases GSR at 100 ns. Then:
   - `set`: update the in_vec bits. Every affected port whose value changed gets `set_input(port, int)`. A value with `x`/`z` raises `ModelUnsupported`: expected traces never contain `x`, and sv tests cover x stimulus.
   - `edge`: `clock_edge(port, value == "r")`.
   - `glbl`: `glbl(sig, int(value))`.
   - `sample`: record `outputs()` as bits plus provenance.
5. Expand free clocks into edge events beforehand with the shared `free_clock_edges`.
6. Refuse (`ModelUnsupported`) any file containing `simultaneous` events (review #7). Those appear only in equivalence stimuli, which compare two simulators and never use the golden model.

- [ ] **Step 1: Write the failing tests** at `tools/tests/test_golden.py`

Use a toy model defined in the test, so these tests do not depend on the flops unit:

```python
# SPDX-License-Identifier: Apache-2.0
import importlib

import pytest

from xut.formats.xvec import loads
from xut.golden import replay
from xut.wrap import build_map, spec_from_hdl
from xut.catalog.unisim import HdlModule, HdlPort
from pathlib import Path
from xut_models.base import Model, ModelUnsupported, Out, bit_attr


class ToyDff(Model):
    PRIM = "TOYFF"
    CLOCKS = ("C",)
    OUTPUTS = {"Q": 1}

    @classmethod
    def inputs(cls):
        return {"C": 1, "D": 1}

    def power_on(self):
        self.q, self.gsr = bit_attr(self.attrs.get("INIT", 0)), 1

    def set_input(self, port, value):
        setattr(self, port.lower(), value)

    def clock_edge(self, port, rising):
        if rising and not self.gsr:
            self.q = self.d
            self.hit("TOYFF.C1")

    def glbl(self, signal, value):
        self.gsr = value

    def outputs(self):
        return {"Q": Out(str(self.q), "doc:1")}


MAP = build_map(spec_from_hdl(HdlModule("TOYFF", Path("x"), [HdlPort("Q", "output", 1),
    HdlPort("C", "input", 1), HdlPort("D", "input", 1)], []), "c", {}))
VEC = """\
# xut-vec 2  prim=TOYFF cfg=c nin=1 nout=1 nclk=1 settle_ps=120000 seed=0 attr.INIT=1'b1
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=120000 sample S0
t=121000 edge clk0 r
t=122000 sample S1
t=126000 edge clk0 f
t=127000 set in[0]=1
t=128000 edge clk0 r
t=129000 sample S2
"""


def test_replay_trace_and_reach():
    trace, reach = replay(ToyDff, loads(VEC), MAP)
    assert {k: v["Q"] for k, v in trace.samples.items()} == {"S0": "1", "S1": "0", "S2": "1"}
    assert trace.kind == "expected" and trace.prov["S2"]["Q"] == "doc:1"
    assert "claim:TOYFF.C1" in reach.bins() and "port:D" in reach.bins()
    assert "attr:INIT=1'b1" in reach.bins()


def test_simultaneous_events_are_refused():
    text = VEC.replace("t=127000 set in[0]=1\nt=128000 edge clk0 r",
                       "t=128000 simultaneous edge clk0 r\nt=128000 simultaneous set in[0]=1")
    with pytest.raises(ModelUnsupported, match="simultaneous"):
        replay(ToyDff, loads(text), MAP)


def test_x_stimulus_is_unsupported():
    with pytest.raises(ModelUnsupported):
        replay(ToyDff, loads(VEC.replace("in[0]=1", "in[0]=0bx")), MAP)


def test_out_validates_provenance():
    with pytest.raises(ValueError):
        Out("1", "because")
    with pytest.raises(ValueError):
        Out("2", "doc:3")


def test_registry_imports_digit_package():
    assert importlib.import_module("xut_models.7series") is not None
```

- [ ] **Step 2: Run the tests and confirm they fail** (ImportError)

- [ ] **Step 3: Implement `models/xut_models/base.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Golden-model base API (spec §3, §4.3). Standard library only.

A model is written clean-room from the libraries guide. Every output it
reports carries provenance: ``doc:<page>`` when the guide states the behaviour,
``inferred:<reason>`` when it had to be inferred. A bit the guide leaves
undefined is reported as ``-`` (don't care).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

_PROV = re.compile(r"^(doc:\d+|inferred:[^#|=]+)$")  # '#', '|', '=' would break .xtr lines
_LIT = re.compile(r"^\s*\d*\s*'\s*[sS]?([bBoOdDhH])\s*([0-9a-fA-F_]+)\s*$")


class ModelUnsupported(Exception):
    """The stimulus needs behaviour this model does not describe (x inputs, GTS, ...)."""


@dataclass(frozen=True)
class Out:
    bits: str  # MSB-first "0" / "1" / "-"
    prov: str  # "doc:<page>" | "inferred:<reason>"

    def __post_init__(self) -> None:
        if not self.bits or set(self.bits) - set("01-"):
            raise ValueError(f"model output bits must be 0/1/-: {self.bits!r}")
        if not _PROV.match(self.prov):
            raise ValueError(f"provenance must be doc:<page> or inferred:<reason>: {self.prov!r}")


def bit_attr(v: str | int) -> int:
    """``1'b1``, ``"1'b0"``, ``1`` or ``"1"`` -> int."""
    if isinstance(v, int):
        return v
    m = _LIT.match(str(v))
    if m:
        return int(m.group(2).replace("_", ""), {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(1).lower()])
    return int(str(v))


class Model(ABC):
    PRIM: ClassVar[str]
    FAMILY: ClassVar[str] = "7series"
    CLOCKS: ClassVar[tuple[str, ...]] = ()
    OUTPUTS: ClassVar[dict[str, int]] = {}

    def __init__(self, attrs: Mapping[str, str | int]):
        self.attrs = dict(attrs)
        self.claims_hit: set[str] = set()

    @classmethod
    @abstractmethod
    def inputs(cls) -> dict[str, int]:
        """Input port -> width (clock ports included)."""

    def hit(self, claim_id: str) -> None:
        self.claims_hit.add(claim_id)

    @abstractmethod
    def power_on(self) -> None:
        """State at time 0: glbl GSR is asserted until ROC_WIDTH."""

    @abstractmethod
    def set_input(self, port: str, value: int) -> None: ...

    @abstractmethod
    def clock_edge(self, port: str, rising: bool) -> None: ...

    def glbl(self, signal: str, value: int) -> None:
        raise ModelUnsupported(f"{self.PRIM}: glbl {signal} is not modelled")

    @abstractmethod
    def outputs(self) -> dict[str, Out]: ...
```

`models/xut_models/registry.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Find the golden model for a primitive: module xut_models.<family>.<prim lower>, attr MODEL."""

import importlib

from xut_models.base import Model


def get(family: str, prim: str) -> type[Model]:
    try:
        mod = importlib.import_module(f"xut_models.{family}.{prim.lower()}")
    except ModuleNotFoundError as e:
        raise LookupError(f"no golden model for {family}/{prim}") from e
    model = getattr(mod, "MODEL", None)
    if not (isinstance(model, type) and issubclass(model, Model) and model.PRIM == prim):
        raise LookupError(f"xut_models.{family}.{prim.lower()}.MODEL is not a {prim} Model")
    return model
```

The `7series` and `_common` packages each contain only the SPDX line and a one-line docstring. `xut_models/__init__.py` holds `"""Clean-room golden models (spec §3)."""`. `7series` is not a Python identifier, so it can only be reached with `importlib` (as the registry does) or with relative imports from inside the package.

In `pyproject.toml`: `packages = ["tools/xut", "models/xut_models"]`. Re-run `uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1`.

- [ ] **Step 4: Implement `tools/xut/golden.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Replay an .xvec through a golden model -> expected trace (spec §4.3 vector tests)."""

from __future__ import annotations

from dataclasses import dataclass, field

from xut.formats.xtr import Trace
from xut.formats.xvec import Event, Vec, free_clock_edges
from xut.validate import ROC_WIDTH_PS
from xut.wrap import DutMap
from xut_models.base import Model, ModelUnsupported


@dataclass
class Reach:
    """Bins the stimulus actually reached in the model (spec §9)."""

    ports: set[str] = field(default_factory=set)
    attrs: dict[str, str] = field(default_factory=dict)
    claims: set[str] = field(default_factory=set)

    def bins(self) -> set[str]:
        return ({f"port:{p}" for p in self.ports} | {f"attr:{k}={v}" for k, v in self.attrs.items()}
                | {f"claim:{c}" for c in self.claims})


def expand_free_clocks(vec: Vec) -> list[Event]:
    """Explicit events plus the shared free-clock edges (xvec.free_clock_edges)."""
    out = [e for e in vec.events if e.op not in ("clock_start", "clock_stop")]
    return sorted(out + free_clock_edges(vec), key=lambda e: e.t)


def _port_value(m: DutMap, bits: list[str], port: str) -> int:
    s = "".join(bits[b.bit] for b in reversed(m.port_bits("in", port)))
    if set(s) - {"0", "1"}:
        raise ModelUnsupported(f"{port}={s}: x/z stimulus is covered by sv tests, not the model")
    return int(s, 2)


def replay(model_cls: type[Model], vec: Vec, m: DutMap) -> tuple[Trace, Reach]:
    # The testbench applies every operation of one time step before the DUT wakes, so a
    # simultaneous `edge r` + `set D` captures the NEW D. File-order replay would predict
    # the old one: refuse rather than emit a silently wrong expectation (review #7).
    sim = sorted({e.t for e in vec.events if e.simultaneous})
    if sim:
        raise ModelUnsupported(f"simultaneous events at t={sim[:3]}: ordering within one time "
                               "step is not modelled (use them only for sim-vs-sim checks)")
    model = model_cls(vec.attrs)
    reach = Reach(attrs=dict(vec.attrs))
    trace = Trace({"runner": "python", "flow": "rtl", "model": "golden", "seed": str(vec.seed),
                   "kind": "expected", "prim": vec.prim, "cfg": vec.cfg})
    bits = ["0"] * m.nin
    seen: dict[str, set[int]] = {}
    model.power_on()
    for p in m.in_ports():
        model.set_input(p, 0)
    released = False
    for e in expand_free_clocks(vec):
        if not released and e.t >= ROC_WIDTH_PS:
            model.glbl("GSR", 0)
            released = True
        if e.op == "set":
            before = {p: "".join(bits[b.bit] for b in m.port_bits("in", p)) for p in m.in_ports()}
            for i, ch in enumerate(reversed(e.value)):
                bits[e.lsb + i] = ch
            for p in m.in_ports():
                if "".join(bits[b.bit] for b in m.port_bits("in", p)) != before[p]:
                    v = _port_value(m, bits, p)
                    model.set_input(p, v)
                    seen.setdefault(p, set()).add(v)
        elif e.op == "edge":
            port = m.clock_port(e.target)
            model.clock_edge(port, e.value == "r")
            reach.ports.add(port)
        elif e.op == "glbl":
            model.glbl(e.target, int(e.value))
        elif e.op == "sample":
            outs = model.outputs()
            trace.add(e.target, {p: o.bits for p, o in outs.items()},
                      {p: o.prov for p, o in outs.items()})
            reach.ports |= set(outs)
    reach.ports |= {p for p, vals in seen.items() if len(vals) > 1 or vals != {0}}
    reach.claims = set(model.claims_hit)
    return trace, reach
```

- [ ] **Step 5: Run the tests** (`uv run pytest tools/tests/test_golden.py -v > .cache/pytest.log 2>&1; tail -n 8 .cache/pytest.log`). Expect all to pass.

- [ ] **Step 6: Commit** with `infra: add golden-model base API, registry and trace replay`.

---

### Task 7: Stimulus compiler and the generic vector testbench

**Files:**
- Create: `tools/xut/stimcompile.py`, `tools/xut/hdl/xut_vector_tb.sv`, `tools/tests/test_stimcompile.py`, `tools/tests/fixtures/tb/toy_dut.v`

**Interfaces:**
- Produces:
  - `xut.stimcompile.OPS` (dict name → code)
  - `compile_vec(vec, m) -> Compiled` (`words: list[int]`, `labels: list[str]`)
  - `write_stim(vec, m, out_dir) -> Compiled`, which writes `stim.memh`, `stim.vh` and `labels.json`
  - `raw_to_trace(raw: str, labels: list[str], m, header: dict) -> Trace`
  - `TB = Path(".../hdl/xut_vector_tb.sv")`

**Operation word** (128 bits, one hex line per operation in `stim.memh`):

| bits | field |
|---|---|
| 127:120 | op: 1 SET, 2 EDGE, 3 GLBL, 4 SAMPLE, 5 CLK_HI, 6 CLK_START, 7 CLK_STOP, 15 END |
| 119:96 | idx: in_vec bit / clock index / glbl signal (0 GSR, 1 GTS, 2 GRESTORE) / sample number |
| 95:64 | val: SET 0/1/2(x)/3(z); EDGE 1/0; GLBL 0/1; CLK_HI high time ps; CLK_START low time ps |
| 63:0 | absolute time in ps |

A multi-bit `set` expands to one SET per bit, LSB first, at the same time. A free clock expands to `CLK_HI` then `CLK_START` at its `clock_start` time. If there is no `clock_start`, they go at `phase` (clamped to 0). `stim.vh` holds `` `define XUT_MAXOPS <n> ``. The testbench prints `S <n> <out_vec %b>` per sample to `raw.txt`, and `XUT_DONE` on END.

- [ ] **Step 1: Write the testbench** `tools/xut/hdl/xut_vector_tb.sv`

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// Generic vector testbench (spec §4.3, §5.3). Identical for every primitive:
// replays stim.memh (compiled from an .xvec by `xut run`) and writes raw.txt.
// Portable subset of xsim, Icarus -g2012 and Verilator --timing.
`timescale 1ps / 1ps
`include "xut_cfg.vh"
`include "stim.vh"

module xut_vector_tb;
  localparam integer NIN = `XUT_NIN;
  localparam integer NOUT = `XUT_NOUT;
  localparam integer NCLK = `XUT_NCLK;
  localparam integer MAXOPS = `XUT_MAXOPS;

  localparam [7:0] OP_SET = 8'd1, OP_EDGE = 8'd2, OP_GLBL = 8'd3, OP_SAMPLE = 8'd4,
                   OP_CLK_HI = 8'd5, OP_CLK_START = 8'd6, OP_CLK_STOP = 8'd7, OP_END = 8'd15;

  reg  [NIN-1:0]  in_vec;
  reg  [NCLK-1:0] clk_step;
  reg  [NCLK-1:0] clk_free;
  reg  [NCLK-1:0] free_en;
  wire [NCLK-1:0] clk = clk_step | clk_free;
  wire [NOUT-1:0] out_vec;

  reg [127:0] ops [0:MAXOPS-1];
  reg [63:0]  hi_ps [0:NCLK-1];
  reg [63:0]  lo_ps [0:NCLK-1];

  xut_dut dut (.clk(clk), .in_vec(in_vec), .out_vec(out_vec));

  genvar gi;
  generate
    for (gi = 0; gi < NCLK; gi = gi + 1) begin : g_free
      always begin
        wait (free_en[gi]);
        clk_free[gi] = 1'b1;
        #(hi_ps[gi]);
        clk_free[gi] = 1'b0;
        #(lo_ps[gi]);
      end
    end
  endgenerate

  function automatic [0:0] fourstate(input [1:0] v);
    case (v)
      2'd0: fourstate = 1'b0;
      2'd1: fourstate = 1'b1;
      2'd2: fourstate = 1'bx;
      default: fourstate = 1'bz;
    endcase
  endfunction

  integer fd, pc;
  reg [127:0] w;
  reg [7:0]   op;
  reg [23:0]  idx;
  reg [31:0]  val;
  reg [63:0]  t;

  initial begin
    in_vec = {NIN{1'b0}};
    clk_step = {NCLK{1'b0}};
    clk_free = {NCLK{1'b0}};
    free_en = {NCLK{1'b0}};
    $readmemh("stim.memh", ops);
    fd = $fopen("raw.txt", "w");
    for (pc = 0; pc < MAXOPS; pc = pc + 1) begin
      w = ops[pc];
      op = w[127:120];
      idx = w[119:96];
      val = w[95:64];
      t = w[63:0];
      if (t > $time) #(t - $time);
      case (op)
        OP_SET:       in_vec[idx] = fourstate(val[1:0]);
        OP_EDGE:      clk_step[idx] = val[0];
        OP_GLBL: begin
          if (idx == 0) glbl.GSR_int = val[0];
          else if (idx == 1) glbl.GTS_int = val[0];
          else glbl.GRESTORE_int = val[0];
        end
        OP_SAMPLE:    $fdisplay(fd, "S %0d %b", idx, out_vec);
        OP_CLK_HI:    hi_ps[idx] = {32'd0, val};
        OP_CLK_START: begin lo_ps[idx] = {32'd0, val}; free_en[idx] = 1'b1; end
        OP_CLK_STOP:  free_en[idx] = 1'b0;
        OP_END: begin
          $fclose(fd);
          $display("XUT_DONE t=%0t", $time);
          $finish;
        end
        default: begin
          $display("XUT_ERROR bad op %0d at pc %0d", op, pc);
          $finish;
        end
      endcase
    end
    $display("XUT_ERROR stimulus has no END operation");
    $finish;
  end
endmodule
```

Notes:
- `glbl` is compiled as a second top module. This is the spec §6 default, and all three simulators accept writes to `glbl.GSR_int` from the testbench. If Verilator rejects the cross-top reference (verified in Task 15, Step 1), the fallback is `` `define XUT_GLBL_INSTANCE ``. Under it the testbench adds `glbl glbl ();`, which UNISIM's `glbl.GSR` then resolves to by upward name lookup. Add that `ifdef` block now so both variants exist:

```systemverilog
`ifdef XUT_GLBL_INSTANCE
  glbl glbl ();
`endif
```

- `$fatal` is avoided on purpose. A missing `XUT_DONE` marks the run `error`.

- [ ] **Step 2: Write the toy DUT fixture** `tools/tests/fixtures/tb/toy_dut.v`

It exercises the testbench without UNISIM: a DFF with async clear, plus glbl-driven GSR.

```verilog
// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module xut_dut (input wire [0:0] clk, input wire [2:0] in_vec, output wire [0:0] out_vec);
  // in_vec: [0]=D [1]=CLR(async) [2]=unused
  reg q;
  always @(posedge clk[0] or posedge in_vec[1] or posedge glbl.GSR)
    if (glbl.GSR) q <= 1'b1;
    else if (in_vec[1]) q <= 1'b0;
    else q <= in_vec[0];
  assign out_vec[0] = q;
endmodule
module glbl;
  // GSR rises at 1 ps (a definite posedge) and falls at ROC_WIDTH = 100 ns, like glbl.v.
  reg GSR_int = 1'b0, GTS_int = 1'b0, GRESTORE_int = 1'b0;
  wire GSR = GSR_int;
  initial begin
    #1 GSR_int = 1'b1;
    #99999 GSR_int = 1'b0;
  end
endmodule
```

- [ ] **Step 3: Write the failing tests** `tools/tests/test_stimcompile.py`

```python
# SPDX-License-Identifier: Apache-2.0
import shutil
from pathlib import Path

import pytest

from xut.container import SIM_IMAGE, DockerExecutor, image_digest
from xut.formats.xvec import loads
from xut.paths import repo_root
from xut.stimcompile import TB, compile_vec, raw_to_trace, write_stim
from xut.wrap import Bit, DutMap

M = DutMap("TOY", "7series", "c", {}, 1, 3, 1,
           [Bit("clk", 0, "C", 0, "clock"), Bit("in", 0, "D", 0, "data"),
            Bit("in", 1, "CLR", 0, "async"), Bit("in", 2, "U", 0, "data"),
            Bit("out", 0, "Q", 0, "data")])
VEC = loads("""\
# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=120000 sample S0
t=121000 set in[2:0]=0b0x1
t=122000 edge clk0 r
t=123000 sample S1
t=125000 set in[1]=1
t=127000 sample S2
t=128000 end
""")


def test_words():
    c = compile_vec(VEC, M)
    assert c.labels == ["S0", "S1", "S2"]
    w = c.words
    assert w[0] == (4 << 120) | (0 << 96) | (0 << 64) | 120000       # SAMPLE 0
    assert w[1] == (1 << 120) | (0 << 96) | (1 << 64) | 121000       # in[0]=1
    assert w[2] == (1 << 120) | (1 << 96) | (2 << 64) | 121000       # in[1]=x
    assert w[3] == (1 << 120) | (2 << 96) | (0 << 64) | 121000       # in[2]=0
    assert w[4] == (2 << 120) | (0 << 96) | (1 << 64) | 122000       # EDGE r
    assert w[-1] >> 120 == 15


def test_free_clock_words():
    """compile_vec starts/stops the TB generator exactly where free_runs says, and the
    edges the TB then produces (rise at start, fall after high, one per period, none
    after a low-phase stop) are the free_clock_edges list; golden replays the same list."""
    from xut.formats.xvec import free_clock_edges, free_runs
    from xut.golden import expand_free_clocks

    v = loads("""\
# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=free
t=120000 clock_start clk0
t=137000 clock_stop clk0
t=150000 end
""")
    ((c, start, stop),) = free_runs(v)
    w = compile_vec(v, M).words
    ops = [(x >> 120, (x >> 96) & 0xFFFFFF, (x >> 64) & 0xFFFFFFFF, x & ((1 << 64) - 1)) for x in w]
    assert (5, 0, 5000, start) in ops and (6, 0, 5000, start) in ops   # CLK_HI, CLK_START
    assert (7, 0, 0, stop) in ops                                       # CLK_STOP
    assert [(e.t, e.value) for e in expand_free_clocks(v) if e.op == "edge"] == \
        [(e.t, e.value) for e in free_clock_edges(v)]


def test_raw_to_trace():
    t = raw_to_trace("S 0 1\nS 1 x\nS 2 0\n", ["S0", "S1", "S2"], M, {"runner": "iverilog"})
    assert {k: v["Q"] for k, v in t.samples.items()} == {"S0": "1", "S1": "x", "S2": "0"}


@pytest.mark.container
@pytest.mark.skipif(shutil.which("docker") is None or image_digest(SIM_IMAGE) is None,
                    reason="xut-sim image not built")
def test_tb_replays_on_iverilog():
    work = repo_root() / "build" / "tbtest"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    write_stim(VEC, M, work)
    (work / "xut_cfg.vh").write_text("`define XUT_NCLK 1\n`define XUT_NIN 3\n`define XUT_NOUT 1\n")
    shutil.copy(Path(__file__).parent / "fixtures/tb/toy_dut.v", work / "toy_dut.v")
    shutil.copy(TB, work / "tb.sv")
    ex, log = DockerExecutor(), work / "run.log"
    assert ex.run(["iverilog", "-g2012", "-o", "sim.vvp", "-s", "xut_vector_tb", "-s", "glbl",
                   "-I", ".", "tb.sv", "toy_dut.v"], cwd=work, log=log, timeout_s=120) == 0
    assert ex.run(["vvp", "-n", "sim.vvp"], cwd=work, log=log, timeout_s=120) == 0
    assert "XUT_DONE" in log.read_text()
    t = raw_to_trace((work / "raw.txt").read_text(), ["S0", "S1", "S2"], M, {})
    # S0: GSR preset -> 1; S1: clocked D=1 -> 1; S2: async CLR -> 0
    assert {k: v["Q"] for k, v in t.samples.items()} == {"S0": "1", "S1": "1", "S2": "0"}
```

- [ ] **Step 4: Run the tests and confirm they fail** (ImportError)

- [ ] **Step 5: Implement `tools/xut/stimcompile.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Compile an .xvec into the generic testbench's operation image, and read raw samples back."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xut.formats.xtr import Trace
from xut.formats.xvec import Vec
from xut.wrap import DutMap

TB = Path(__file__).resolve().parent / "hdl" / "xut_vector_tb.sv"
OPS = {"set": 1, "edge": 2, "glbl": 3, "sample": 4, "clk_hi": 5, "clk_start": 6,
       "clk_stop": 7, "end": 15}
_BIT = {"0": 0, "1": 1, "x": 2, "z": 3}
_GLBL = {"GSR": 0, "GTS": 1, "GRESTORE": 2}


@dataclass
class Compiled:
    words: list[int]
    labels: list[str]


def _w(op: str, idx: int, val: int, t: int) -> int:
    return (OPS[op] << 120) | (idx << 96) | (val << 64) | t


def compile_vec(vec: Vec, m: DutMap) -> Compiled:
    words, labels = [], []
    started = {e.target for e in vec.events if e.op == "clock_start"}
    for c in vec.clocks:
        if c.mode == "free" and c.name not in started:
            high = c.period * c.duty // 100
            words += [_w("clk_hi", c.index, high, max(0, c.phase)),
                      _w("clk_start", c.index, c.period - high, max(0, c.phase))]
    for e in vec.events:
        if e.op == "set":
            for i, ch in enumerate(reversed(e.value)):
                words.append(_w("set", e.lsb + i, _BIT[ch], e.t))
        elif e.op == "edge":
            words.append(_w("edge", vec.clock(e.target).index, int(e.value == "r"), e.t))
        elif e.op == "glbl":
            words.append(_w("glbl", _GLBL[e.target], int(e.value), e.t))
        elif e.op == "sample":
            words.append(_w("sample", len(labels), 0, e.t))
            labels.append(e.target)
        elif e.op == "clock_start":
            c = vec.clock(e.target)
            high = c.period * c.duty // 100
            words += [_w("clk_hi", c.index, high, e.t), _w("clk_start", c.index, c.period - high, e.t)]
        elif e.op == "clock_stop":
            words.append(_w("clk_stop", vec.clock(e.target).index, 0, e.t))
        elif e.op == "end":
            words.append(_w("end", 0, 0, e.t))
    if not words or words[-1] >> 120 != OPS["end"]:
        last = vec.events[-1].t if vec.events else vec.settle_ps
        words.append(_w("end", 0, 0, last + 1000))
    words.sort(key=lambda w: w & ((1 << 64) - 1))  # stable: keeps file order within a time
    return Compiled(words, labels)


def write_stim(vec: Vec, m: DutMap, out_dir: Path) -> Compiled:
    c = compile_vec(vec, m)
    out_dir = Path(out_dir)
    (out_dir / "stim.memh").write_text("".join(f"{w:032x}\n" for w in c.words))
    (out_dir / "stim.vh").write_text("// SPDX-License-Identifier: Apache-2.0\n"
                                     f"`define XUT_MAXOPS {len(c.words)}\n")
    (out_dir / "labels.json").write_text(json.dumps(c.labels) + "\n")
    return c


def raw_to_trace(raw: str, labels: list[str], m: DutMap, header: dict[str, str]) -> Trace:
    t = Trace(dict(header))
    width = max(1, m.nout)
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[0] != "S":
            continue
        n, bits = int(parts[1]), parts[2].lower().rjust(width, "0")[-width:]
        by_index = bits[::-1]  # by_index[i] is out_vec[i]
        values = {}
        for port in m.out_ports():
            pb = [b for b in m.of("out") if b.port == port]
            values[port] = "".join(by_index[b.bit] for b in reversed(pb))
        t.add(labels[n], values)
    return t
```

- [ ] **Step 6: Run the tests.** Expected: pass, including the container test (`S0=1` from GSR, `S1=1` clocked, `S2=0` async clear).

- [ ] **Step 7: Commit** with `infra: add stimulus compiler and generic vector testbench`.

---

### Task 8: Runner framework, test discovery, python runner and `xut run`

**Files:**
- Create: `tools/xut/testspec.py`, `tools/xut/runners/__init__.py`, `tools/xut/runners/base.py`, `tools/xut/runners/python.py`, `tools/xut/run.py`, `tools/xut/schemas/result.schema.json`, `tools/tests/test_testspec.py`, `tools/tests/test_runner_base.py`, `tools/tests/test_run_cli.py`, `tools/tests/fixtures/tests/7series/register/TOYFF/{test.yaml,README.md,vectors/gen.py}` (`gen.py` also defines `l0_reject`, used in Task 9)
- Modify: `tools/xut/schemas/test.schema.json`, `tools/xut/cli.py`

**Interfaces:**
- Consumes: Tasks 2–7
- Produces:
  - `xut.testspec.TestCase` (frozen):
    - `id, family, prim, level, style, source, test_dir, runners, flows, exercises, attr_sampling, related, gaps, expected_divergence, configs, timeout_s, sv_deviations`;
    - `source` is the string from test.yaml, relative to `test_dir`;
    - properties `group` and `shared_dirs`.
  - `discover(root) -> list[TestCase]`
  - `select(cases, patterns) -> list[TestCase]`, where a pattern is a test-id glob, a primitive name, or `unit:<name>`
  - `declared(case, runner) -> tuple[bool, str]` (supported?, reason)
  - `xut.runners.base.RunContext` (frozen: `root, flow, model_source, seed, defines, timeout_s, jobs`)
  - `ConfigResult`, `RunResult` (with `to_json()`, `write(dir)`)
  - `Runner` (ABC, with class attributes `name, x_observable, styles`):
    - `available(ctx) -> tuple[bool, str]`;
    - `tools(ctx) -> dict`;
    - `run(case, ctx) -> RunResult`, a template method;
    - `run_config(case, cfg, cfgdir, ctx) -> ConfigResult`, abstract.
  - `workdir(ctx, runner, test_id) -> Path`
  - `worst(statuses) -> str`, where `fail > error > pass > skip`
  - `load_generated(ctx, case) -> list[tuple[str, Path, Path]]`: the `(cfg, cfgdir_of_python, expected_trace)` list for vector tests, read from the python run's directory
  - `xut.runners.RUNNERS: dict[str, type[Runner]]`
  - `xut.run.run_tests(cases, runners, ctx) -> list[RunResult]`
  - CLI `xut run [SELECT...] [--runner R]... [--flow rtl] [--model-source auto] [--style S]... [--level L]... [--seed N] [--jobs N] [--timeout S]`: `--runner`, `--style` and `--level` are all `multiple=True` (a test matches if its level is any given level and its style any given style)

**`test.yaml` additions** (the schema in `tools/xut/schemas/test.schema.json` gains these; spec §11 keys stay as they are):

- `source` (required):
  - vector style: `vectors/<file>.py:<function>` (a generator) or `vectors/<file>.xvec` (frozen);
  - sv style: `sv/<file>.sv`, whose top module is the file stem;
  - cocotb style: `cocotb/<file>.py`, whose test module is the file stem.
- `configs` (sv and cocotb only): a list of `{cfg: <name>, attrs: {NAME: literal}}`. Vector tests get their configurations from the generator.
- `runners` values stay exactly as step 1's `test.schema.json` defines them: the **strings** `"yes"`, `"no"` or `"unsupported"`, always quoted in YAML. The schema's `$comment` explains why: PyYAML turns a bare `yes` into the boolean `true`, which the schema rejects.
- `unsupported_reasons` (new, optional): a map `{<runner>: "<reason>"}`. Every runner whose value is `"no"` or `"unsupported"` must have an entry, and lint (`runner-reasons`, error) enforces it. `"unsupported"` means the runner cannot run this test; `"no"` means the test is deliberately not run there, e.g. python for a self-checking sv testbench.
- A runner missing from `runners` is treated as `"no"` with the reason `not declared`, which lint flags.
- **Infra task (this task, on `infra/sim-runners`):** amend step 1's `tools/xut/schemas/test.schema.json` to add the optional keys `source`, `configs`, `unsupported_reasons`, `expected_divergence`, `timeout_s` and `sv_deviations`, keeping `runners` as the string enum and keeping its `$comment`. Update `docs/templates/test.yaml` to match. Add a schema test that bare `yes` still fails and that `unsupported_reasons` validates.
- `expected_divergence`: a list of `{finding: findings/<PRIM>-<slug>.md, cls: <finding class>, runners: [..]}`.
- `timeout_s` (optional; when absent, `--timeout`, otherwise 600).
- `config_exclusions` (new, optional): `{<runner>: {<cfg glob>: "<reason>"}}`. The runner is declared `"yes"` for the test, but configurations whose name matches a glob get a `skip` `ConfigResult` with that reason (never silent), and the test's status is the worst of the rest. This keeps e.g. the non-`IS_D_INVERTED` configurations of L0/L2 hardware-eligible (review (b) nit).
- `sv_deviations`: a list of strings (spec §4.3).

**Runner contract.**
- `Runner.run` creates `build/<flow>/<runner>/<model-source>/<test-id>/` fresh.
- If the runner is declared unsupported, unavailable, or not applicable to the style, it writes a `skip` `result.json` with the reason.
- Otherwise it calls `run_config` per configuration, each in `cfg-<cfg>/`, catching every exception as `error` with the exception text.
- It then concatenates the per-config traces into `trace.xtr` (labels `<cfg>/<label>`) and the per-config logs into `run.log`, and writes `result.json`.
- A test's status is `worst(config statuses)`. The same precedence is used by step 1's PROGRESS marks.

`result.json` (validated against `result.schema.json`):

```json
{
  "format": "xut-result 1",
  "test_id": "7series.FDRE.L1.reset_over_ce", "runner": "iverilog", "flow": "rtl", "style": "vector",
  "status": "pass", "reason": null,
  "configs": [{"cfg": "init0", "status": "pass", "reason": null,
               "stimulus_sha256": "…", "trace_sha256": "…", "mismatches": 0}],
  "model_source": "unisim-2025.2", "seeds": {"stimulus": 1234, "x": []},
  "defines": {}, "tools": {"iverilog": "Icarus Verilog version 12.0 (stable) ()"},
  "container": {"image": "xut-sim:1", "digest": "sha256:…"},
  "duration_s": 1.9, "started": "2026-09-26T10:00:00Z", "host": "big-storage",
  "x_dependence": null, "bins_reached": null, "hw": null
}
```

- `hw` is `null` until step 3, which fills in `{dna, serial, site}`.
- `bins_reached` is filled only by the `python` runner.
- `seeds.x` lists the Verilator X seeds.
- The default stimulus seed is `zlib.crc32(test_id)`, unless `--seed` is given.

**The python runner** (`name="python"`, `x_observable=True`, `styles={"vector"}`):

1. Import the generator (`source` `file.py:func`) with `importlib.util.spec_from_file_location`. While importing, put the case's `shared_dirs` (Task 18 adds `tests/<family>/<group>/_shared/<unit>`; until then an empty list) on `sys.path`.
2. Call it with a `GenContext(family, prim, seed)`. It returns an iterable of `Vec`. A frozen `.xvec` source is loaded instead, and its configuration comes from its `attr.*` header.
3. For each `Vec`:
   - `validate` it against the wrapper map. Any error makes the config `error` ("stimulus violates class rules": a generator bug).
   - `mark` hw renderability.
   - `write_dut` into `cfg-<cfg>/dut/`, then write `stim.xvec`.
   - `replay` through `registry.get(family, prim)` and write `expected.xtr`. Write the same trace to `trace.xtr` too, so the test-level `trace.xtr` (`kind=expected`) is assembled like every other runner's.
   - The config is `pass` if the model ran. `ModelUnsupported` makes it `error`.
4. Union the `Reach.bins()` into `bins_reached`.
5. Write `configs.json`, the list of **every** configuration the generator produced, including those that errored. Other runners take their configuration list from it (review #10), and `prepare_vector` returns `error "no expected trace (python: <reason>)"` for a configuration whose `expected.xtr` is missing.

**Reject tests.** For a `.xvec` with `expect=reject`, the python runner does not replay (there is no behaviour to model). It writes an empty `expected.xtr` (header only, `kind=expected`, `expect=reject`), so the other runners find the configuration and apply the reject rule of Task 9.

The python run directory is the **source of truth** for the other runners: they read `cfg-*/dut/`, `cfg-*/stim.xvec` and `cfg-*/expected.xtr` from `build/<flow>/python/<model-source>/<test-id>/`. `xut run` always runs `python` first for vector tests whenever another runner is selected.

- [ ] **Step 1: Write the TOYFF fixture test tree** (this also documents the test.yaml shape)

`tools/tests/fixtures/tests/7series/register/TOYFF/test.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
primitive: TOYFF
family: 7series
work_unit: toy
doc_refs: [{guide: UG953, version: "2026.1", section: TOYFF, page: 1}]
tests:
  - id: 7series.TOYFF.L1.capture
    level: L1
    style: vector
    source: vectors/gen.py:l1_capture
    exercises: [port:D, claim:TOYFF.C1]
    attr_sampling: {INIT: [0, 1]}
    runners: {python: "yes", xsim: "yes", iverilog: "yes", verilator: "yes", hw: "unsupported"}
    unsupported_reasons: {hw: "toy"}
    flows: [rtl]
    related: []
    gaps: []
```

`vectors/gen.py` defines `l1_capture(ctx)`, which yields one `Vec` per INIT value using `ctx.dut(...)`. `README.md` mentions the test id. The runner-base tests monkeypatch `registry.get` to return `ToyDff` (Task 6) and `load_entry` to return a hand-built TOYFF `CatalogEntry`, so the fixture needs no catalog file.

- [ ] **Step 2: Write the failing tests**

`tools/tests/test_testspec.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from xut.testspec import declared, discover, select

FIX = Path(__file__).parent / "fixtures"


def test_discover_and_select():
    cases = discover(FIX)
    assert [c.id for c in cases] == ["7series.TOYFF.L1.capture"]
    c = cases[0]
    assert (c.prim, c.level, c.style, c.group) == ("TOYFF", "L1", "vector", "register")
    assert c.source == "vectors/gen.py:l1_capture"   # kept as written in test.yaml
    assert select(cases, ["7series.TOYFF.*"]) == cases
    assert select(cases, ["TOYFF"]) == cases
    assert select(cases, ["FDRE"]) == []


def test_declared():
    c = discover(FIX)[0]
    assert declared(c, "iverilog") == (True, "")
    assert declared(c, "hw") == (False, "toy")
    assert declared(c, "iverilog-vz") == (True, "")  # follows verilator
```

`tools/tests/test_runner_base.py` checks:

- An unsupported runner writes `result.json` with `status: skip` and the declared reason. It validates against `result.schema.json`.
- A runner whose `run_config` raises produces `status: error` whose reason contains the exception text, and `run.log` exists.
- A runner whose `tools()` or `finish()` raises, or whose config writes a malformed `trace.xtr`, still leaves an `error` `result.json` (review #9).
- If the python runner errors on one of two configurations, the iverilog result has both configurations, the missing one as `error` "no expected trace" (review #10).
- `sim_tool_versions` called from 16 threads at once returns identical, non-"unknown" values (container test).
- `worst(["pass", "fail", "error"]) == "fail"`, `worst(["pass", "error"]) == "error"`, `worst(["skip", "pass"]) == "pass"` and `worst([]) == "skip"`.
- The python runner on the TOYFF fixture writes `cfg-init0/expected.xtr`, `cfg-init1/expected.xtr` and `cfg-init0/dut/xut_dut.map.json`, returns `pass`, and has `bins_reached` containing `claim:TOYFF.C1`.
- `run_tests` with `runners=["iverilog"]` on a vector case schedules `python` first. Use a fake iverilog runner class that records the order.

- [ ] **Step 3: Run the tests and confirm they fail**

- [ ] **Step 4: Implement `testspec.py`, `runners/base.py`, `runners/python.py`, `runners/__init__.py`, `run.py` and the CLI**

`tools/xut/runners/base.py` (the core; the other files follow from the interface list above):

```python
# SPDX-License-Identifier: Apache-2.0
"""Runner base: one result.json / trace.xtr / run.log per (flow, runner, test) (spec §6, §14)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import socket
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar

import json

from xut.formats import xtr
from xut.modelsrc import ModelSource
from xut.testspec import TestCase, declared

STATUSES = ("pass", "fail", "error", "skip")
_RANK = {"fail": 3, "error": 2, "pass": 1, "skip": 0}


def worst(statuses: list[str]) -> str:
    return max(statuses, key=_RANK.__getitem__) if statuses else "skip"


@dataclass(frozen=True)
class RunContext:
    root: Path
    flow: str
    model_source: ModelSource
    seed: int | None = None
    defines: dict[str, str] = field(default_factory=dict)
    timeout_s: int | None = None
    jobs: int = 1


@dataclass
class ConfigResult:
    cfg: str
    status: str
    reason: str | None = None
    stimulus_sha256: str | None = None
    trace_sha256: str | None = None
    mismatches: int = 0


@dataclass
class RunResult:
    test_id: str
    runner: str
    flow: str
    style: str
    status: str
    reason: str | None = None
    configs: list[ConfigResult] = field(default_factory=list)
    model_source: str | None = None
    seeds: dict = field(default_factory=lambda: {"stimulus": None, "x": []})
    defines: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)
    container: dict | None = None
    duration_s: float = 0.0
    started: str = ""
    host: str = field(default_factory=socket.gethostname)
    x_dependence: bool | None = None
    bins_reached: list[str] | None = None
    hw: dict | None = None

    def to_json(self) -> str:
        return json.dumps({"format": "xut-result 1", **asdict(self)}, indent=1) + "\n"

    def write(self, d: Path) -> None:
        (d / "result.json").write_text(self.to_json())


def workdir(ctx: RunContext, runner: str, test_id: str) -> Path:
    # The model source is part of the key (review (b) #5): a run against the submodule
    # never overwrites a run against Vivado's UNISIM, and crosscheck can pair like-for-like.
    return ctx.root / "build" / ctx.flow / runner / ctx.model_source.name / test_id


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def seed_for(case: TestCase, ctx: RunContext) -> int:
    import zlib

    return ctx.seed if ctx.seed is not None else zlib.crc32(case.id.encode())


class Runner(ABC):
    name: ClassVar[str]
    x_observable: ClassVar[bool] = True
    styles: ClassVar[frozenset[str]] = frozenset({"vector", "sv", "cocotb"})

    def available(self, ctx: RunContext) -> tuple[bool, str]:
        return True, ""

    def tools(self, ctx: RunContext) -> dict:
        return {}

    def container(self, ctx: RunContext) -> dict | None:
        return None

    def configs(self, case: TestCase, ctx: RunContext) -> list[str]:
        """Configuration names: every config the python run generated (its configs.json,
        errored ones included) for vector tests; test.yaml otherwise. A config without an
        expected trace is NOT dropped: prepare_vector returns error "no expected trace"
        for it, so a python failure can never shrink another runner's matrix (review #10)."""
        if case.style == "vector":
            listing = workdir(ctx, "python", case.id) / "configs.json"
            if not listing.is_file():
                raise RuntimeError("no python run for this test (configs.json missing)")
            return json.loads(listing.read_text())
        return [c["cfg"] for c in case.configs] or ["default"]

    @abstractmethod
    def run_config(self, case: TestCase, cfg: str, cfgdir: Path, ctx: RunContext) -> ConfigResult:
        """Run one configuration in cfgdir; write cfgdir/trace.xtr and cfgdir/run.log."""

    def _skip(self, case, ctx, d, reason) -> RunResult:
        r = RunResult(case.id, self.name, ctx.flow, case.style, "skip", reason,
                      model_source=ctx.model_source.name,
                      started=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
        (d / "run.log").write_text(f"skip: {reason}\n")
        r.write(d)
        return r

    def run(self, case: TestCase, ctx: RunContext) -> RunResult:
        """Template method. Every exit path writes result.json (spec §14, review #9):
        any exception outside run_config becomes an `error` result with the traceback."""
        d = workdir(ctx, self.name, case.id)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        try:
            return self._run(case, ctx, d)
        except Exception as e:
            with (d / "run.log").open("a") as f:
                f.write(traceback.format_exc())
            r = RunResult(case.id, self.name, ctx.flow, case.style, "error",
                          f"{type(e).__name__}: {e}", model_source=ctx.model_source.name,
                          started=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
            r.write(d)
            return r

    def _run(self, case: TestCase, ctx: RunContext, d: Path) -> RunResult:
        ok, why = declared(case, self.name)
        if not ok:
            return self._skip(case, ctx, d, f"declared unsupported: {why}")
        if case.style not in self.styles:
            return self._skip(case, ctx, d, f"runner {self.name} does not run {case.style} tests")
        ok, why = self.available(ctx)
        if not ok:
            return self._skip(case, ctx, d, f"runner unavailable: {why}")
        t0 = time.monotonic()
        res = RunResult(case.id, self.name, ctx.flow, case.style, "skip",
                        model_source=ctx.model_source.name, defines=dict(ctx.defines),
                        started=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
        res.seeds["stimulus"] = seed_for(case, ctx)
        parts, logs = [], []
        cfgs = self.configs(case, ctx)
        if not cfgs:
            res.status, res.reason = "error", "no configurations (did the python runner fail?)"
        for cfg in cfgs:
            cd = d / f"cfg-{cfg}"
            cd.mkdir()
            try:
                cr = self.run_config(case, cfg, cd, ctx)
            except Exception as e:  # recorded as error with the traceback in the log
                with (cd / "run.log").open("a") as f:
                    f.write(traceback.format_exc())
                cr = ConfigResult(cfg, "error", f"{type(e).__name__}: {e}")
            if (cd / "trace.xtr").is_file():
                try:
                    parts.append((cfg, xtr.load(cd / "trace.xtr")))
                except xtr.XtrError as e:
                    cr = ConfigResult(cfg, "error", f"malformed trace.xtr: {e}")
            res.configs.append(cr)
            logs.append(f"===== cfg {cfg}: {cr.status} {cr.reason or ''}\n"
                        + ((cd / "run.log").read_text() if (cd / "run.log").is_file() else ""))
        if res.configs:
            res.status = worst([c.status for c in res.configs])
            bad = [c for c in res.configs if c.status in ("fail", "error")]
            res.reason = "; ".join(f"{c.cfg}: {c.reason}" for c in bad[:5]) or None
        header = {"runner": self.name, "flow": ctx.flow, "model": ctx.model_source.name,
                  "seed": str(res.seeds["stimulus"]), "prim": case.prim, "test": case.id}
        if case.style == "vector" and self.name == "python":
            header.update(model="golden", kind="expected")
        xtr.dump(xtr.concat(parts, header), d / "trace.xtr")
        (d / "run.log").write_text("".join(logs))
        res.tools, res.container = self.tools(ctx), self.container(ctx)
        res.duration_s = round(time.monotonic() - t0, 3)
        self.finish(case, ctx, d, res)
        res.write(d)
        return res

    def finish(self, case: TestCase, ctx: RunContext, d: Path, res: RunResult) -> None:
        """Hook for runner-specific aggregate fields (x_dependence, bins_reached)."""
```

`tools/xut/testspec.py`, `declared()`:
- `iverilog-vz` inherits the `verilator` declaration, because it only exists to guard Verilator results.
- `declared(case, runner)` returns `(True, "")` for `"yes"`, and `(False, <reason from unsupported_reasons>)` for `"no"` and `"unsupported"`.
- A runner missing from `runners` gives `(False, "not declared")`.
- `TestCase.timeout_s` is `None` unless test.yaml sets it. The effective timeout is the test's value, otherwise `--timeout` (`ctx.timeout_s`), otherwise 600.

`tools/xut/run.py`, `run_tests(cases, runner_names, ctx)`:
- Schedule `python` first for every vector case, sequentially. The model is fast.
- Run the rest in a `ThreadPoolExecutor(max_workers=ctx.jobs)`. Each job is one (case, runner) pair, and the simulators run as subprocesses.
- Print `progress: done=N total=M elapsed_s=E` to stdout after each completion.
- Write `build/<flow>/summary.json`.
- Return the results.

The CLI prints a table (test id × runner → status) and exits 1 if any status is `fail` or `error`. If the selection matches no test, it prints `no tests selected (<selectors and filters>)` and exits 0: CI steps for units that have not merged yet are then harmless, and the message makes the empty selection visible.

CLI tests (`tools/tests/test_run_cli.py`): `--level L0 --level L1` selects both levels of the TOYFF fixture and not L2; `--style vector --style sv` selects both; a selector that matches nothing prints `no tests selected` and exits 0.

`--runner` defaults to every runner in `RUNNERS` except `iverilog-vz`, which is added automatically whenever `verilator` is selected.

`--model-source auto` resolves as in Task 1. The xsim runner overrides it in `available()`, as described in Task 10.

- [ ] **Step 5: Run the tests** (`uv run pytest tools/tests -v > .cache/pytest.log 2>&1; tail -n 25 .cache/pytest.log`). Expect all to pass.

- [ ] **Step 6: Commit in two pieces**

```bash
git add tools/xut/testspec.py tools/xut/schemas tools/tests/test_testspec.py tools/tests/fixtures/tests && git commit -m "infra: discover tests from test.yaml (source, configs, runner declarations)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tools && git commit -m "runners: add runner base, result.json, python golden runner and xut run" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: iverilog runner (vector and sv styles) and the sv trace include

**Files:**
- Create: `tools/xut/runners/iverilog.py`, `tools/xut/hdl/xut_trace.svh`, `tools/tests/test_runner_iverilog.py`, `tools/tests/fixtures/tests/7series/register/TOYFF/sv/tb_toyff_basic.sv`
- Modify: `tools/xut/runners/__init__.py`

**Interfaces:**
- Consumes: `executor_for`, `sim_tool_versions`, `image_digest` (Task 1); `write_stim`, `raw_to_trace`, `TB` (Task 7); `compare` (Task 3); `Runner` (Task 8)
- Produces:
  - `IverilogRunner` (`name="iverilog"`, `x_observable=True`)
  - `IverilogVzRunner` (`name="iverilog-vz"`): the same, but with the transformed-model directory first on the library path. The class stub exists here, but it is **not** added to `RUNNERS` until Task 15, so no run before then can select it and fail with `NotImplementedError`.
  - `vector_check(cfgdir, m, labels, expected, actual_header, x_observable) -> ConfigResult`, which is shared by all simulator runners
  - `sv_check(cfgdir, log_text, header) -> ConfigResult`

**Vector config run** (`cfgdir` = `build/rtl/iverilog/<model-source>/<id>/cfg-<cfg>/`):

1. Copy `dut/` and `stim.xvec` from the python run's `cfg-<cfg>/`. Then `write_stim`.
2. In the container, compile:
   `iverilog -g2012 -o sim.vvp -s xut_vector_tb -s glbl -I . -I dut -y <ms>/unisims [-y <ms>/retarget] -Y .v [-D<def>...] <TB> dut/xut_dut.v <ms>/glbl.v`
3. Run: `vvp -n sim.vvp`.
4. Judge the result:
   - compile exit ≠ 0 → `error: compile failed`;
   - `XUT_DONE` absent → `error: simulation ended early`, except that `expect=reject` in the `.xvec` turns this case into `pass` and `XUT_DONE` present into `fail`;
   - otherwise `raw.txt` → `trace.xtr` → `compare` with `expected.xtr` → `pass` or `fail`. `mismatches.txt` holds each mismatch line, and `reason` has the first three.

The paths above are container paths from `executor.guest(...)`. `ctx.defines` become `-D` flags. By default none are set (spec §6.2 pins XIL_TIMING, XIL_XECLIB, XIL_DR and XIL_ATTR_TEST undefined), and they are recorded in `result.json`.

**sv config run**:
- Compile with `-s <stem> -s glbl -I <tools/xut/hdl> -I <shared_dirs...> -I <test sv dir>` and `-P<stem>.<NAME>=<value>` for each attribute of the configuration (sv tests take attributes as top-level parameters).
- `pass` iff the log has `XUT_PASS` and no `XUT_FAIL`.
- `trace.xtr` = header + `trace.body`, which the testbench wrote through `xut_trace.svh`.

`tools/xut/hdl/xut_trace.svh` (include it *inside* the testbench module):

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// Checkpoint trace + self-check helpers for hand-written SV testbenches (spec §4.3).
// Include inside the module body. Lines written: "<label>  <port>=<bits>" (.xtr body).
`ifndef XUT_TRACE_SVH
`define XUT_TRACE_SVH
`define XUT_CHECK(label, sig, exp) \
  if ((sig) !== (exp)) begin \
    xut_errors = xut_errors + 1; \
    $display("XUT_FAIL %s: got %b expected %b at %0t", label, sig, exp, $time); \
  end
`define XUT_CHECKN(label, n, sig, exp) \
  if ((sig) !== (exp)) begin \
    xut_errors = xut_errors + 1; \
    $display("XUT_FAIL %s%0d: got %b expected %b at %0t", label, n, sig, exp, $time); \
  end
`define XUT_POINT1(label, p1, s1) $fdisplay(xut_fd, "%s  %s=%b", label, p1, s1);
`define XUT_POINT2(label, p1, s1, p2, s2) $fdisplay(xut_fd, "%s  %s=%b %s=%b", label, p1, s1, p2, s2);
`endif
integer xut_fd;
integer xut_errors;
`ifdef XUT_GLBL_INSTANCE
// Verilator fallback (Task 15, Step 1): glbl as an instance of the testbench, found by
// UNISIM's upward name lookup and by this testbench's own glbl.GSR_int writes.
glbl glbl ();
`endif
initial begin
  xut_errors = 0;
  xut_fd = $fopen("trace.body", "w");
end
task automatic xut_finish;
  begin
    $fclose(xut_fd);
    if (xut_errors == 0) $display("XUT_PASS");
    else $display("XUT_FAIL %0d check(s) failed", xut_errors);
    $finish;
  end
endtask
```

- [ ] **Step 1: Write the TOYFF sv fixture and the failing tests**

`tb_toyff_basic.sv` instantiates a toy DFF defined in the file itself, checks `Q` after one clock with `` `XUT_CHECK ``, writes two checkpoints, and calls `xut_finish`. Add a second fixture test entry `7series.TOYFF.L1.sv_basic` (style sv, `configs: [{cfg: default, attrs: {}}]`) to the fixture test.yaml.

`tools/tests/test_runner_iverilog.py` (marker `container`, skipped without the image):

- vector TOYFF, using the toy DUT without UNISIM: pass, `trace.xtr` has labels `init0/S0` …, and `result.json` records `tools.iverilog` and `container.digest`;
- corrupting one line of `cfg-init1/expected.xtr` flips the result to `fail`, with `mismatches: 1`;
- the sv fixture passes, and its `trace.xtr` holds both checkpoints;
- an sv fixture that calls `` `XUT_CHECK `` with a wrong expectation gives `fail`;
- a syntax error in the sv fixture gives `error` with reason `compile failed`;
- **reject path, end to end** (review (b) round 2, N1): a fixture test `7series.TOYFF.L0.reject` (`vectors/gen.py:l0_reject`, one config with `expect=reject` and `INIT=1'bx`, `runners: {python: "yes", iverilog: "yes", ...}`) runs python, then iverilog. The fixture's `TOYFF.v` model has `initial if (INIT !== 1'b0 && INIT !== 1'b1) begin $display("Attribute Syntax Error"); $finish; end`. Expected: python `pass` (its `cfg-init_x/` holds `dut/`, `stim.xvec`, a header-only `expected.xtr` and `configs.json` lists `init_x`); iverilog `pass` ("rejected"). With the rejection line removed from the fixture model, iverilog gives `fail` "illegal attribute was accepted".

So that the TOYFF vector test needs no UNISIM model, add a `ModelSource` fixture whose `unisims/` directory holds a `TOYFF.v` written in the test: a plain DFF with a `glbl.GSR` preset. Its `glbl.v` is `toy_dut.v`'s glbl module.

- [ ] **Step 2: Implement `tools/xut/runners/iverilog.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Icarus Verilog runner (container)."""

from __future__ import annotations

import shutil
from pathlib import Path

from xut.container import SIM_IMAGE, executor_for, image_digest, sim_tool_versions
from xut.formats import xtr, xvec
from xut.runners.base import ConfigResult, RunContext, Runner, sha256_file, workdir
from xut.stimcompile import TB, raw_to_trace, write_stim
from xut.testspec import TestCase
from xut.wrap import DutMap

HDL = Path(__file__).resolve().parent.parent / "hdl"


def vector_check(cd: Path, m: DutMap, labels: list[str], expected: xtr.Trace, header: dict,
                 x_observable: bool) -> ConfigResult:
    cfg = cd.name[4:]
    raw = cd / "raw.txt"
    if not raw.is_file():
        return ConfigResult(cfg, "error", "no raw.txt (simulation did not start)")
    actual = raw_to_trace(raw.read_text(), labels, m, header)
    xtr.dump(actual, cd / "trace.xtr")
    mm = xtr.compare(expected, actual, x_observable=x_observable)
    (cd / "mismatches.txt").write_text("".join(f"{x}\n" for x in mm))
    status = "fail" if mm else "pass"
    reason = "; ".join(str(x) for x in mm[:3]) or None
    return ConfigResult(cfg, status, reason, sha256_file(cd / "stim.xvec"),
                        sha256_file(cd / "trace.xtr"), len(mm))


def sv_check(cd: Path, log_text: str, header: dict) -> ConfigResult:
    cfg = cd.name[4:]
    body = cd / "trace.body"
    t = xtr.loads("# xut-trace 2  " + " ".join(f"{k}={v}" for k, v in header.items()) + "\n"
                  + (body.read_text() if body.is_file() else ""))
    xtr.dump(t, cd / "trace.xtr")
    if "XUT_FAIL" in log_text:
        first = next(ln for ln in log_text.splitlines() if "XUT_FAIL" in ln)
        return ConfigResult(cfg, "fail", first.strip(), None, sha256_file(cd / "trace.xtr"))
    if "XUT_PASS" not in log_text:
        return ConfigResult(cfg, "error", "testbench did not report XUT_PASS/XUT_FAIL")
    return ConfigResult(cfg, "pass", None, None, sha256_file(cd / "trace.xtr"))


class IverilogRunner(Runner):
    name = "iverilog"
    x_observable = True

    def lib_first(self, case: TestCase, cfg: str, ctx: RunContext) -> tuple[Path, ...]:
        """Library dirs searched before the model source. iverilog-vz returns the
        verilatorized dir. Returned, never stored on self: jobs run in threads."""
        return ()

    def available(self, ctx):
        if shutil.which("docker") is None and not _native():
            return False, "docker not found"
        return (image_digest(SIM_IMAGE) is not None or _native(),
                f"{SIM_IMAGE} not built: uv run xut container build")

    def tools(self, ctx):
        return sim_tool_versions(executor_for(ctx.model_source), workdir(ctx, self.name, "_v"))

    def container(self, ctx):
        return {"image": SIM_IMAGE, "digest": image_digest(SIM_IMAGE)}

    def _libs(self, ex, ctx, first: tuple[Path, ...]) -> list[str]:
        out = []
        for d in (*first, *ctx.model_source.search):
            out += ["-y", ex.guest(d)]
        return out + ["-Y", ".v"]

    def _defs(self, ctx) -> list[str]:
        return [f"-D{k}" if v == "" else f"-D{k}={v}" for k, v in ctx.defines.items()]

    def _glbl_defs(self, ctx) -> list[str]:
        return []  # Icarus and xsim keep glbl as a second top (spec §6)

    def run_config(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext) -> ConfigResult:
        ex = executor_for(ctx.model_source)
        log = cd / "run.log"
        timeout = case.timeout_s or ctx.timeout_s or 600
        glbl = ex.guest(ctx.model_source.glbl)
        first = self.lib_first(case, cfg, ctx)
        header = {"runner": self.name, "flow": ctx.flow, "model": ctx.model_source.name,
                  "prim": case.prim, "cfg": cfg}
        if case.style == "vector":
            src = workdir(ctx, "python", case.id) / f"cfg-{cfg}"
            shutil.copytree(src / "dut", cd / "dut")
            shutil.copy(src / "stim.xvec", cd / "stim.xvec")
            vec = xvec.load(cd / "stim.xvec")
            m = DutMap.load(cd / "dut" / "xut_dut.map.json")
            comp = write_stim(vec, m, cd)
            shutil.copy(TB, cd / "xut_vector_tb.sv")
            argv = ["iverilog", "-g2012", "-o", "sim.vvp", "-s", "xut_vector_tb", "-s", "glbl",
                    "-I", ".", "-I", "dut", *self._libs(ex, ctx, first), *self._defs(ctx),
                    "xut_vector_tb.sv", "dut/xut_dut.v", glbl]
            if ex.run(argv, cwd=cd, log=log, timeout_s=timeout) != 0:
                if vec.expect == "reject":  # elaboration-time rejection also counts
                    return ConfigResult(cfg, "pass", "rejected at compile/elaboration")
                return ConfigResult(cfg, "error", "compile failed")
            ex.run(["vvp", "-n", "sim.vvp"], cwd=cd, log=log, timeout_s=timeout)
            text = log.read_text()
            if vec.expect == "reject":
                ok = "XUT_DONE" not in text
                return ConfigResult(cfg, "pass" if ok else "fail",
                                    None if ok else "illegal attribute was accepted")
            if "XUT_DONE" not in text:
                return ConfigResult(cfg, "error", "simulation ended early (no XUT_DONE)")
            header["seed"] = str(vec.seed)
            return vector_check(cd, m, comp.labels, xtr.load(src / "expected.xtr"), header,
                                self.x_observable)
        # sv style
        stem = Path(str(case.source)).stem
        attrs = next((c["attrs"] for c in case.configs if c["cfg"] == cfg), {})
        incs = [HDL, *case.shared_dirs, (case.test_dir / str(case.source)).parent]
        argv = ["iverilog", "-g2012", "-o", "sim.vvp", "-s", stem, "-s", "glbl",
                *sum((["-I", ex.guest(p)] for p in incs), []),
                *[f"-P{stem}.{k}={v}" for k, v in attrs.items()],
                *self._libs(ex, ctx, first), *self._defs(ctx), *self._glbl_defs(ctx),
                ex.guest(case.test_dir / str(case.source)), glbl]
        if ex.run(argv, cwd=cd, log=log, timeout_s=timeout) != 0:
            return ConfigResult(cfg, "error", "compile failed")
        ex.run(["vvp", "-n", "sim.vvp"], cwd=cd, log=log, timeout_s=timeout)
        header["seed"] = "0"
        return sv_check(cd, log.read_text(), header)


class IverilogVzRunner(IverilogRunner):
    """Icarus on verilatorized UNISIM: guards every verilator result (spec §6.2)."""

    name = "iverilog-vz"

    def lib_first(self, case, cfg, ctx):  # wired in Task 15 (ensure_model + vz_dir)
        raise NotImplementedError("iverilog-vz is completed in Task 15")


def _native() -> bool:
    import os

    return os.environ.get("XUT_NATIVE") == "1"
```

`-P<stem>.<NAME>=<value>` is Icarus's syntax for overriding a top-level parameter. The value is the Verilog literal from `configs` (e.g. `1'b1`). That Icarus 12 accepts a *sized* literal here is not assumed: a container test compiles a two-line module with `-Ptop.P=1'b1` and checks `$display` prints 1. If it does not, convert the literal to its decimal value in the runner.

- [ ] **Step 3: Run the tests.** Expected: all pass, including the container tests. Then commit:

```bash
git add tools && git commit -m "runners: add iverilog runner (vector and sv styles) and xut_trace.svh" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: xsim runner

**Files:**
- Create: `tools/xut/runners/xsim.py`, `tools/tests/test_runner_xsim.py`
- Modify: `tools/xut/runners/__init__.py`

**Interfaces:**
- Consumes: `vector_check`, `sv_check` (Task 9); `VIVADO_SETTINGS`, `VIVADO_SRC` (Task 1)
- Produces:
  - `XsimRunner` (`name="xsim"`, `x_observable=True`)
  - `render_script(cd, files, top, incs, params, defines) -> str`

Rules:

- **Availability.**
  - The runner is available iff `VIVADO_SETTINGS` exists.
  - xsim always uses Vivado's precompiled `unisims_ver`, so its model source is **always** `unisim-2025.2`.
  - If `ctx.model_source.name != "unisim-2025.2"`, `available()` returns `(False, "xsim uses Vivado's precompiled unisims_ver (unisim-2025.2); requested <name>")`. `xut run` records that as a `skip` with the reason.
- **Script.** Each config dir gets `xsim.sh`, which is run with `bash xsim.sh > run.log 2>&1`:

```bash
# SPDX-License-Identifier: Apache-2.0
# GENERATED by xut (xsim runner). Vivado is sourced only in this subshell.
set -e
cd "$(dirname "$0")"
bash -c 'source /opt/xilinx/Vivado/2025.2/settings64.sh && \
  xvlog -sv -i . -i dut {INCS} {DEFS} {FILES} /opt/xilinx/Vivado/2025.2/data/verilog/src/glbl.v && \
  xelab -L unisims_ver -L unimacro_ver --timescale 1ps/1ps --debug off {GENERICS} -s xut_snap work.{TOP} work.glbl && \
  xsim xut_snap -R'
```

  - `{DEFS}` holds `-d NAME[=VAL]` flags and `{GENERICS}` holds `-generic_top NAME=VAL` (sv configs).
  - `{FILES}` is `xut_vector_tb.sv dut/xut_dut.v` for vector tests, or the sv source for sv tests.
  - `set -e` plus the `&&` chain make a compile failure exit non-zero. It is classified as `error: compile failed` when `xsim xut_snap -R` never ran (no `INFO: [XSIM` line and no `XUT_` marker in the log).
- **Tool version.** `tools()` runs `bash -c 'source … && xsim -version'` into a log and records the first line.
- **Style.** `cocotb` is not in `styles` (cocotb has no xsim backend, spec §4.3), so cocotb tests get `skip` "runner xsim does not run cocotb tests".

- [ ] **Step 1: Write the tests** (marker `vivado`, skipped without Vivado):
  - TOYFF vector → pass. The toy `TOYFF.v` is compiled with xvlog as an extra file, because xsim's `unisims_ver` has no TOYFF. Add the fixture model file to `{FILES}` when the test's model-source fixture provides one: `XsimRunner(extra_files=[...])`, a test-only constructor argument.
  - sv fixture → pass.
  - `render_script` output contains `source /opt/xilinx/Vivado/2025.2/settings64.sh` **only inside** `bash -c '...'`. Assert that the text before the first `bash -c` does not contain `settings64`.
  - With the model source `unisim-gh-2020.1`, `available()` is false with the reason above.

- [ ] **Step 2: Implement.** Reuse the copying, stim writing and checking code from `IverilogRunner.run_config` by moving its shared part into a helper `prepare_vector(cd, case, cfg, ctx) -> (vec, m, compiled, expected, header)` in `runners/base.py`. Refactor `IverilogRunner` to use it in the same commit.

- [ ] **Step 3: Run the tests** (`uv run pytest tools/tests -m "vivado or not vivado" -v > .cache/pytest.log 2>&1; tail -n 20 .cache/pytest.log`). Expected: all pass on the host.

- [ ] **Step 4: Commit** with `runners: add xsim runner (Vivado sourced in a subshell, precompiled unisims_ver)`.

---

### Task 11: cocotb style

**Files:**
- Create: `tools/xut/hdl/cocotb_run.py`, `tools/xut/cocotb_dut.py`, `tools/tests/fixtures/tests/7series/register/TOYFF/cocotb/cocotb_toyff.py`, `tools/tests/test_runner_cocotb.py`
- Modify: `tools/xut/runners/iverilog.py` (the cocotb branch; the Verilator cocotb branch lands in Task 15)

**Interfaces:**
- Produces:
  - `xut.cocotb_dut.XutDut(dut, map_path, trace_path, header=None)`, with:
    - `attrs: dict[str, str]`, the configuration's attributes from the map;
    - `in_ports: list[str]`;
    - async methods `settle()`, `set(**ports)`, `edge(port, rising)`, `cycle(port, n=1)`, `gsr(value)`;
    - `value(port) -> int`, the current driven value of an input (from the shadow);
    - `get(port) -> str`, `sample(label, prov=None)`, `close()`.
    - `header` defaults to `{"runner": <XUT_RUNNER env>, "flow": "rtl", "model": <XUT_MODEL env>, "seed": <XUT_SEED env>}`; the runner sets those variables. This is exactly the surface `flops_cocotb.random_session` uses (review #8).

    It is used only inside the container, and imports `cocotb` and `xut.formats.xtr` only.
  - `tools/xut/hdl/cocotb_run.py`, the in-container launcher:
    `python3 cocotb_run.py --sim icarus|verilator --work <dir> --module <stem> --test-dir <dir> --unisims <dir> [--retarget <dir>] --glbl <file> --seed N [--shared <dir>]...`

**cocotb run** (iverilog runner, `style == "cocotb"`):

1. For each config: `write_dut(spec, cd/"dut", cocotb_top=True)` from the catalog entry and the config's attributes.
2. In the container, run `python3 /work/tools/xut/hdl/cocotb_run.py ...` with:
   - `PYTHONPATH=/work/tools:/work/models:<test cocotb dir>:<shared dirs>`;
   - `XUT_MAP=dut/xut_dut.map.json`, `XUT_TRACE=trace.xtr` and `XUT_SEED=<seed>`.
3. The launcher uses `cocotb_tools.runner.get_runner(<sim>)`:
   - `build(sources=[dut/xut_dut.v, dut/xut_cocotb_top.v, <glbl>], includes=[dut], hdl_toplevel="xut_cocotb_top", build_args=<per-sim>, timescale=("1ps", "1ps"), build_dir=<cd>/sim_build)`, where `build_args` is `["-y", unisims, "-Y", ".v"]` for Icarus, and for Verilator `["--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style", "--x-assign", "unique", "--x-initial", "unique", "-y", <vz_dir>, "-y", unisims, "+libext+.v"]`;
   - `test(test_module=<stem>, hdl_toplevel="xut_cocotb_top", seed=<seed>, build_dir=..., test_dir=<cd>, plusargs=<per-sim>)`; for Verilator the plusargs are `+verilator+seed+<x-seed> +verilator+rand+reset+2`.
4. It exits 0 iff the returned `results.xml` has no failures.
5. The runner then classifies: exit 0 → `pass`; a failure in `results.xml` → `fail` with the first failure message; no `results.xml` → `error`.

`XutDut.gsr(v)` writes `dut.glbl.GSR_int.value = v`. `set(**ports)` keeps a Python-int shadow of `in_vec` and writes the whole vector. `get(port)` reads `out_vec` and slices it with the map, lower-cased (`01xz`).

Runner scope for cocotb:
- `iverilog`: yes.
- `verilator`: yes, via the Verilator runner (Task 15), which reuses this launcher with `--sim verilator` against the verilatorized models and runs each configuration twice with the paired X seeds. `test_cocotb_smoke_runs[verilator]` (Task 1) pins that cocotb 2.0.1 works with the v5.048 build.
- `xsim`: `skip`, because the runner does not support the style.

- [ ] **Step 1: Write the fixture cocotb module and the test.** The TOYFF cocotb module drives D over 20 cycles, compares against `ToyDff` imported from a fixture package on `--shared`, and samples every cycle. The test (marker `container`) expects `pass`, and a `trace.xtr` with 20 samples per config.

- [ ] **Step 2: Implement `cocotb_run.py`, `cocotb_dut.py` and the runner branch.** Run the tests.

- [ ] **Step 3: Commit** with `runners: add cocotb style on iverilog (in-container launcher, map-aware XutDut)`.

- [ ] **Step 4: Progress log, lint, and PR checkpoint B**

```bash
uv run pytest -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
```

Write `log/<ts>-infra-sim-runners.md` and commit it. Then:

```bash
git push -u origin infra/sim-runners
gh pr create --base infra/sim-formats --title "infra: sim runners — golden-model API, testbench, runners, xut run" --body-file .cache/pr-b.md
```

The body ends with the Claude Code line and states "stacked on #<PR A>". Run the review gate (sequential reviewers). When PR A merges, the orchestrator rebases this branch onto `main`, re-runs the tests, pushes with `--force-with-lease` and runs `gh pr edit <N> --base main`.

---

### Task 12: `xut verilatorize` — AST analysis (forced regs, triggers, enablers)

**Files:**
- Create: `tools/xut/verilatorize/__init__.py`, `tools/xut/verilatorize/analyze.py`, `tools/tests/test_vz_analyze.py`, `tools/tests/fixtures/verilatorize/*.v` (listed below), `tools/tests/fixtures/verilatorize/glbl.v`

**Interfaces:**
- Consumes: pyslang 11.0.0; `_is_benign` (step 1, `xut.catalog.unisim`)
- Produces:
  - `xut.verilatorize.analyze.TransformError(model, msg)`, with attribute `model`
  - `Span` (frozen: `start, end`)
  - `ForcedReg`, with fields `name, width, signed, decl_name, decl_end, is_port, overrides: list[tuple[Span, Span]], deassigns: list[Span], writes: set[Span], sensitivity, triggers, enablers`
  - `Analysis` (`model, path, text, endmodule, forced`, plus properties `triggers` and `enablers`)
  - `has_procedural_assign(path) -> bool`, a syntax-level scan (no elaboration)
  - `generate_configs(path, module, choices=None, limit=64) -> list[dict[str, str]]`: parameter-override sets that together elaborate **every** generate branch (always including `{}`, the defaults)
  - `analyze(path, module, glbl, choices=None) -> Analysis`: runs the walker once per `generate_configs` entry and takes the union, so spans in every generate branch are rewritten (controller ruling on review #3)

**Create the worktree** (stacked on `infra/sim-runners`; PR base `infra/sim-runners` until PR B merges):

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git worktree add ../xilinx-unittests-worktrees/infra-verilatorize -b infra/verilatorize infra/sim-runners
cd ../xilinx-unittests-worktrees/infra-verilatorize && mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1
```

pyslang 11.0.0 API used here was verified while writing this plan:

- `StatementKind.ProceduralAssign` (`.assignment`, `.isForce`) and `ProceduralDeassign` (`.lvalue`, `.isRelease`); their `sourceRange` **includes** the trailing `;`.
- `StatementKind.Timed` (`.timing`, `.stmt`); `TimingControlKind.EventList` (`.events`); `SignalEvent` (`.expr`, `.edge`, `EdgeKind.PosEdge/NegEdge/None_`).
- `Conditional` (`.conditions[i].expr`, `.ifTrue`, `.ifFalse`); `Case` (`.expr`, `.items[i].expressions`, `.items[i].stmt`, `.defaultCase`); `Block` (`.body`); `ExpressionStatement` (`.expr`).
- `ExpressionKind.Assignment` (`.left`, `.right`, `.isNonBlocking`, `.timingControl`); `ElementSelect` (`.value`, `.selector`); `RangeSelect` (`.value`, `.left`, `.right`); `Concatenation` (`.operands`); `Call` (`.subroutine`, `.arguments`, `.isSystemCall`); `HierarchicalValue` (`.symbol.hierarchicalPath == "glbl.GSR"`).
- `Variable`/`Net` `.initializer`; `Variable.location.offset` is the identifier; `Variable.syntax.parent` is the `DataDeclaration`, whose `sourceRange` includes the `;`.
- `instance.body.definition.syntax.endmodule.location.offset`; `sourceRange.start.buffer == instance.body.location.buffer` is `False` inside macro expansions and includes.
- `Port.internalSymbol`.

Check any other attribute with `dir()` before using it.

**Fixtures** (our own toy modules, never UNISIM copies). Each starts with the SPDX line and `` `timescale 1ps/1ps ``.

| File / module | Case (spec §6.2 list) | Expected triggers / enablers |
|---|---|---|
| `vz_single.v` / `VZSINGLE` | single writer | `{CLR}` / `{}` |
| `vz_multi.v` / `VZMULTI` | multiple writers (two forcing blocks, overrides `1'b1` and `D`) | `{A, B}` / `{}` |
| `vz_retain.v` / `VZRETAIN` | `deassign` value retention | `{S}` / `{}` |
| `vz_nonconst.v` / `VZNONCONST` | non-constant override (`assign r = A & B;`) | `{S}` / `{}` |
| `vz_trig.v` / `VZTRIG` | multiple triggers `@(gsr_in or CLR or PRE)` | `{glbl.GSR, CLR, PRE}` / `{}` |
| `vz_select.v` / `VZSEL` | bit/part-select writes (`v[0] <=`, `v[2:1] <=`) | `{R}` / `{}` |
| `vz_task.v` / `VZTASK` | task-body writes (`task load; ... r = val; ...`) | `{R}` / `{}` |
| `vz_shift.v` / `VZSHIFT` | self-referencing writes (`data <= {data[2:0], D}`) | `{R}` / `{}` |
| `vz_delay.v` / `VZDELAY` | non-blocking writes with delays (`q <= #100 D`) | `{R}` / `{}` |
| `vz_async.v` / `VZASYNC` | interaction with async CLR (`always @(posedge C or posedge CLR)`) | `{glbl.GSR}` / `{}` |
| `vz_cone.v` / `MMCMVZ` | fan-in cone through a registered stage (the spec's RST\|PWRDWN example) | `{RST, PWRDWN}` / `{CLKIN1}` |
| `vz_gate.v` / `BUFVZ` | triggers reached only through gate primitives, BUFR-style: `buf b0 (clr_in, CLR); not n0 (gsr_n, gsr_in_raw); and a0 (gsr_in, ~gsr_n, 1'b1);` with `always @(gsr_in or clr_in)` | `{glbl.GSR, CLR}` / `{}` |
| `vz_sub.v` / `VZSUB` | a trigger reached through a same-file sub-instance (`VZSUB_INV u (.o(clr_n), .i(CLR));`, `always @(clr_n)`) | `{CLR}` / `{}` |
| `vz_ifelse.v` / `VZIFELSE` | the `deassign` is the then-arm of `if (C2) deassign q; else assign q = E;` (dangling-else guard, Task 13) | `{C2, E}` / `{}` |
| `vz_generate.v` / `VZGEN` | the forced reg written in **both** arms of `generate if (IS_C_INVERTED) ... else ...` (posedge vs negedge capture), with `parameter [0:0] IS_C_INVERTED = 1'b0` | `{R}` / `{}` |

Two representative fixtures, verbatim (the others follow the one-line description in the table):

```verilog
// SPDX-License-Identifier: Apache-2.0
// vz_trig.v — several triggers, glbl.GSR among them.
`timescale 1ps/1ps
module VZTRIG (output Q, input C, input D, input CLR, input PRE);
  reg q;
  wire gsr_in = glbl.GSR;
  assign Q = q;
  always @(gsr_in or CLR or PRE)
    if (gsr_in) assign q = 1'b0;
    else if (CLR) assign q = 1'b0;
    else if (PRE) assign q = 1'b1;
    else deassign q;
  always @(posedge C) q <= D;
endmodule
```

```verilog
// SPDX-License-Identifier: Apache-2.0
// vz_cone.v — the forcing block is sensitive to rst_int, a register fed by RST|PWRDWN.
`timescale 1ps/1ps
module MMCMVZ (output LOCKED, input CLKIN1, input RST, input PWRDWN);
  wire rst_input = RST | PWRDWN;
  reg rst_int;
  reg locked;
  assign LOCKED = locked;
  always @(posedge CLKIN1 or posedge rst_input)
    if (rst_input) rst_int <= 1'b1;
    else rst_int <= 1'b0;
  always @(rst_int)
    if (rst_int) assign locked = 1'b0;
    else deassign locked;
  always @(posedge CLKIN1) locked <= 1'b1;
endmodule
```

**Refusal fixtures.** Each must raise `TransformError` whose message contains the quoted text:

| File / module | Construct | Message contains |
|---|---|---|
| `vz_bad_force.v` / `VZFORCE` | `force q = 1'b0; ... release q;` | `force/release` |
| `vz_bad_select.v` / `VZBADSEL` | `assign q[0] = 1'b1;` (procedural) | `select or concatenation` |
| `vz_bad_local.v` / `VZLOCAL` | `always @(S) begin : blk integer i; i = 1; if (S) assign r = i; end` | `reads local` |
| `vz_bad_self.v` / `VZSELF` | `assign r = ~r;` | `reads r` |
| `vz_bad_rao.v` / `VZRAO` | `always @(S) begin assign r = 1'b0; x = r; end` | `read after its procedural assign` |
| `vz_bad_ansi.v` / `VZANSI` | `module VZANSI (output reg Q, input S);` with `always @(S) if (S) assign Q = 1'b0; else deassign Q;` | `ANSI output reg` |
| `vz_bad_macro.v` / `VZMACRO` | `` `define FORCE_R assign r = 1'b0 `` then `` always @(S) if (S) `FORCE_R; else deassign r; `` | `macro expansion` |
| `vz_bad_undriven.v` / `VZUNDRIVEN` | `always @(en) if (en) assign r = 1'b0; else deassign r;` where `en` is a `wire` with no driver at all | `cannot resolve the driver of en` |
| `vz_bad_blackbox.v` / `VZBLACKBOX` | `SOMETHING_UNKNOWN u (.o(en), .i(S));` (module not in the file) feeding the forcing block | `driven by an instance output` |
| `vz_bad_nestgen.v` / `VZNESTGEN` | `generate if (P) begin if (Q) always ... assign r ...; end endgenerate` (a nested generate condition) | `nested generate conditions` |
| `vz_bad_genparam.v` / `VZBADGEN` | `generate if (WIDTH > DEPTH)` with integer parameters and no literal to derive candidate values from | `cannot enumerate generate configurations` |

Generate branches are no longer a refusal: `analyze` covers every branch (`VZGEN`). Task 13's `check_clean` then elaborates the rewrite under every generate configuration, so a missed rename in any branch fails loudly (`test_missed_rename_is_caught`).

`tools/tests/fixtures/verilatorize/glbl.v` is a copy of the toy glbl module from `tools/tests/fixtures/tb/toy_dut.v` (Task 7), with its SPDX header.

- [ ] **Step 1: Write the failing tests** `tools/tests/test_vz_analyze.py`

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from xut.verilatorize.analyze import (TransformError, analyze, generate_configs,
                                     has_procedural_assign)

FIX = Path(__file__).parent / "fixtures" / "verilatorize"
GLBL = FIX / "glbl.v"

CASES = {
    "vz_single.v": ("VZSINGLE", {"CLR"}, set()),
    "vz_multi.v": ("VZMULTI", {"A", "B"}, set()),
    "vz_retain.v": ("VZRETAIN", {"S"}, set()),
    "vz_nonconst.v": ("VZNONCONST", {"S"}, set()),
    "vz_trig.v": ("VZTRIG", {"glbl.GSR", "CLR", "PRE"}, set()),
    "vz_select.v": ("VZSEL", {"R"}, set()),
    "vz_task.v": ("VZTASK", {"R"}, set()),
    "vz_shift.v": ("VZSHIFT", {"R"}, set()),
    "vz_delay.v": ("VZDELAY", {"R"}, set()),
    "vz_async.v": ("VZASYNC", {"glbl.GSR"}, set()),
    "vz_cone.v": ("MMCMVZ", {"RST", "PWRDWN"}, {"CLKIN1"}),
    "vz_gate.v": ("BUFVZ", {"glbl.GSR", "CLR"}, set()),
    "vz_sub.v": ("VZSUB", {"CLR"}, set()),
    "vz_generate.v": ("VZGEN", {"R"}, set()),
    "vz_ifelse.v": ("VZIFELSE", {"C2", "E"}, set()),
}


@pytest.mark.parametrize("fname", sorted(CASES))
def test_triggers_and_enablers(fname):
    module, trig, en = CASES[fname]
    a = analyze(FIX / fname, module, GLBL)
    assert set(a.triggers) == trig
    assert set(a.enablers) == en


def test_multi_writer_overrides_in_source_order():
    a = analyze(FIX / "vz_multi.v", "VZMULTI", GLBL)
    (x,) = a.forced.values()
    exprs = [a.text[e.start:e.end] for _, e in x.overrides]
    assert exprs == ["1'b1", "D"] and len(x.deassigns) == 2


def test_select_and_task_writes_are_collected():
    sel = analyze(FIX / "vz_select.v", "VZSEL", GLBL).forced["v"]
    t = analyze(FIX / "vz_task.v", "VZTASK", GLBL).forced["r"]
    assert len(sel.writes) == 2 and len(t.writes) == 1


def test_self_referencing_read_is_not_a_write():
    x = analyze(FIX / "vz_shift.v", "VZSHIFT", GLBL).forced["data"]
    text = (FIX / "vz_shift.v").read_text()
    assert [text[s.start:s.end] for s in x.writes] == ["data"]  # only the lvalue


@pytest.mark.parametrize("fname,module,msg", [
    ("vz_bad_force.v", "VZFORCE", "force/release"),
    ("vz_bad_select.v", "VZBADSEL", "select or concatenation"),
    ("vz_bad_local.v", "VZLOCAL", "reads local"),
    ("vz_bad_self.v", "VZSELF", "reads r"),
    ("vz_bad_rao.v", "VZRAO", "read after its procedural assign"),
    ("vz_bad_ansi.v", "VZANSI", "ANSI output reg"),
    ("vz_bad_macro.v", "VZMACRO", "macro expansion"),
    ("vz_bad_undriven.v", "VZUNDRIVEN", "cannot resolve the driver of en"),
    ("vz_bad_blackbox.v", "VZBLACKBOX", "driven by an instance output"),
    ("vz_bad_genparam.v", "VZBADGEN", "cannot enumerate generate configurations"),
    ("vz_bad_nestgen.v", "VZNESTGEN", "nested generate conditions"),
])
def test_refusals(fname, module, msg):
    with pytest.raises(TransformError, match=msg):
        analyze(FIX / fname, module, GLBL)


def test_prescan():
    assert has_procedural_assign(FIX / "vz_single.v")
    assert not has_procedural_assign(GLBL)


def test_generate_configs_cover_both_arms():
    assert generate_configs(FIX / "vz_generate.v", "VZGEN") == [{}, {"IS_C_INVERTED": "1'b1"}]
    a = analyze(FIX / "vz_generate.v", "VZGEN", GLBL)
    text = a.text
    # the writes in BOTH generate arms are collected, not only the default elaboration's
    assert len(a.forced["r"].writes) == 2
    assert all(text[w.start:w.end] == "r" for w in a.forced["r"].writes)
```

- [ ] **Step 2: Run the tests and confirm they fail** (ImportError)

- [ ] **Step 3: Implement `tools/xut/verilatorize/analyze.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""AST analysis for `xut verilatorize` (spec §6.2).

Finds every procedurally-forced reg X (target of a procedural ``assign``) and:
  * the spans to rewrite: declaration identifier, ordinary lvalue writes,
    each ``assign X = e_k;`` and each ``deassign X;``;
  * its triggers: roots (primitive inputs or glbl.*) of the full transitive
    fan-in cone of the sensitivity lists of the blocks that force it. The cone
    crosses continuous assigns, combinational logic and registered stages;
  * its enablers: clocks met while crossing registered stages (edge events of a
    block that the write itself does not read).
Anything it cannot prove it handles raises TransformError naming the model.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pyslang
from pyslang import ast

from xut.catalog.unisim import _is_benign

_SK, _EK, _TK, _SY = ast.StatementKind, ast.ExpressionKind, ast.TimingControlKind, ast.SymbolKind
_EDGES = (ast.EdgeKind.PosEdge, ast.EdgeKind.NegEdge, ast.EdgeKind.BothEdges)
_DELAYS = (_TK.Delay, _TK.Delay3, _TK.OneStepDelay, _TK.CycleDelay)
_SYNTAX_FORCE = {pyslang.syntax.SyntaxKind.ProceduralAssignStatement,
                 pyslang.syntax.SyntaxKind.ProceduralDeassignStatement}
_CONSTANT_SYMBOLS = (_SY.Parameter, _SY.Specparam, _SY.EnumValue, _SY.Genvar)
# Gate primitives: how many leading terminals are outputs (buf/not may have several).
_MULTI_OUT = ("buf", "not")


class TransformError(Exception):
    def __init__(self, model: str, msg: str):
        super().__init__(f"{model}: {msg}")
        self.model = model


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass
class ForcedReg:
    name: str
    dims: str  # declaration text between the type keyword and the name, e.g. "signed [4:1] "
    decl_name: Span
    decl_end: int
    is_port: bool
    overrides: list[tuple[Span, Span]] = field(default_factory=list)  # (statement, rhs), source order
    deassigns: list[Span] = field(default_factory=list)
    writes: set[Span] = field(default_factory=set)
    sensitivity: set[str] = field(default_factory=set)
    triggers: set[str] = field(default_factory=set)
    enablers: set[str] = field(default_factory=set)


@dataclass
class Analysis:
    model: str
    path: Path
    text: str
    endmodule: int
    forced: dict[str, ForcedReg]

    @property
    def triggers(self) -> list[str]:
        return sorted(set().union(*(f.triggers for f in self.forced.values())))

    @property
    def enablers(self) -> list[str]:
        return sorted(set().union(*(f.enablers for f in self.forced.values())) - set(self.triggers))


@dataclass(frozen=True)
class _Driver:
    reads: frozenset[str]
    clocks: frozenset[str]


@dataclass(frozen=True)
class _Ctx:
    edges: frozenset[str]
    levels: frozenset[str]


def _syntax_kinds(node, out: set) -> set:
    out.add(node.kind)
    for c in node:
        if isinstance(c, pyslang.syntax.SyntaxNode):
            _syntax_kinds(c, out)
    return out


def has_procedural_assign(path: Path) -> bool:
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    return bool(_syntax_kinds(tree.root, set()) & _SYNTAX_FORCE)


class _Walker:
    def __init__(self, model: str, inst, text: str):
        self.model, self.inst, self.body, self.text = model, inst, inst.body, text
        self.buffer = inst.body.location.buffer
        self.prefix = inst.body.hierarchicalPath + "."
        self.inputs = {p.name for p in self.body.portList
                       if p.direction in (ast.ArgumentDirection.In, ast.ArgumentDirection.InOut)}
        self.forced_names: set[str] = set()
        self.drivers: dict[str, list[_Driver]] = defaultdict(list)
        self.opaque: set[str] = set()
        self.regs: dict[str, ForcedReg] = {}
        self._stack: list = []

    # ---- helpers -------------------------------------------------------------
    def err(self, msg: str) -> TransformError:
        return TransformError(self.model, msg)

    def key(self, sym) -> str:
        path = sym.hierarchicalPath
        return path[len(self.prefix):] if path.startswith(self.prefix) else path

    def span(self, node) -> Span:
        r = node.sourceRange
        if r.start.buffer != self.buffer or r.end.buffer != self.buffer:
            raise self.err(f"construct at offset {r.start.offset} is inside a macro expansion "
                           "or include; the transform only rewrites the model's own text")
        return Span(r.start.offset, r.end.offset)

    def reads(self, node, out: set[str]) -> set[str]:
        def v(n):
            k = n.kind
            if k in (_EK.NamedValue, _EK.HierarchicalValue):
                if n.symbol.kind not in _CONSTANT_SYMBOLS:
                    out.add(self.key(n.symbol))
            elif k == _EK.Call and not n.isSystemCall and n.subroutine not in self._stack:
                self._stack.append(n.subroutine)
                n.subroutine.body.visit(v)
                self._stack.pop()
            return ast.VisitAction.Advance

        node.visit(v)
        return out

    def lvalues(self, e) -> list:
        k = e.kind
        if k == _EK.NamedValue:
            return [e]
        if k == _EK.HierarchicalValue:
            return []
        if k in (_EK.ElementSelect, _EK.RangeSelect):
            return self.lvalues(e.value)
        if k == _EK.Concatenation:
            return [n for op in e.operands for n in self.lvalues(op)]
        if k == _EK.Conversion:
            return self.lvalues(e.operand)
        raise self.err(f"unsupported lvalue form {k}")

    def select_reads(self, e, out: set[str]) -> None:
        k = e.kind
        if k == _EK.ElementSelect:
            self.reads(e.selector, out)
            self.select_reads(e.value, out)
        elif k == _EK.RangeSelect:
            self.reads(e.left, out)
            self.reads(e.right, out)
            self.select_reads(e.value, out)
        elif k == _EK.Concatenation:
            for op in e.operands:
                self.select_reads(op, out)

    def rvalue_names(self, stmt) -> set[str]:
        """Names a statement reads (lvalue roots of its assignments excluded)."""
        lv: set[int] = set()
        names: list[tuple[str, int]] = []

        def v(n):
            k = n.kind
            if k == _EK.Assignment:
                lv.update(x.sourceRange.start.offset for x in self.lvalues(n.left))
            elif k in (_EK.NamedValue, _EK.HierarchicalValue):
                names.append((self.key(n.symbol), n.sourceRange.start.offset))
            return ast.VisitAction.Advance

        stmt.visit(v)
        return {name for name, off in names if off not in lv}

    def written_names(self, stmt) -> set[str]:
        out: set[str] = set()

        def v(n):
            if n.kind == _EK.Assignment:
                out.update(self.key(x.symbol) for x in self.lvalues(n.left))
            return ast.VisitAction.Advance

        stmt.visit(v)
        return out

    def forced_in(self, stmt) -> set[str]:
        out: set[str] = set()

        def v(n):
            if n.kind == _SK.ProceduralAssign and n.assignment.left.kind == _EK.NamedValue:
                out.add(self.key(n.assignment.left.symbol))
            elif n.kind == _SK.ProceduralDeassign and n.lvalue.kind == _EK.NamedValue:
                out.add(self.key(n.lvalue.symbol))
            return ast.VisitAction.Advance

        stmt.visit(v)
        return out

    # ---- pass 1: which regs are forced -------------------------------------------
    def prescan(self) -> None:
        def v(n):
            if n.kind == _SK.ProceduralAssign:
                if n.isForce:
                    raise self.err("force/release is not supported by the transform")
                if n.assignment.left.kind != _EK.NamedValue:
                    raise self.err(f"procedural assign to a select or concatenation at offset "
                                   f"{n.sourceRange.start.offset}")
                self.forced_names.add(self.key(n.assignment.left.symbol))
                self._reg(n.assignment.left.symbol)
            elif n.kind == _SK.ProceduralDeassign and n.isRelease:
                raise self.err("force/release is not supported by the transform")
            elif n.kind == _SY.Instance and n is not self.inst:
                return ast.VisitAction.Skip
            return ast.VisitAction.Advance

        self.inst.visit(v)

    def _reg(self, sym) -> None:
        name = self.key(sym)
        if name in self.regs:
            return
        if sym.kind != _SY.Variable or sym.type.isUnpackedArray:
            raise self.err(f"{name}: only plain packed reg variables can be transformed")
        decl = sym.syntax.parent if sym.syntax is not None else None
        if decl is None or decl.kind != pyslang.syntax.SyntaxKind.DataDeclaration:
            raise self.err(f"{name}: declared as an ANSI output reg; rewrite the port by hand")
        is_port = any(p.internalSymbol is not None and p.internalSymbol.name == sym.name
                      for p in self.body.portList)
        loc = sym.location.offset
        # Keep the packed range exactly as declared ([4:1], [0:3], signed), so every existing
        # X[i] / X[a:b] read indexes the new net the same way (review #5).
        t = self.span(decl.type)
        m = re.match(r"^\s*(?:reg|logic|bit)\b\s*(.*)$", self.text[t.start:t.end], re.S)
        if m is None:
            raise self.err(f"{name}: forced variable is not declared as reg/logic/bit")
        dims = m.group(1).strip()
        self.regs[name] = ForcedReg(name, dims + " " if dims else "",
                                    Span(loc, loc + len(sym.name)), self.span(decl).end, is_port)

    # ---- pass 2: drivers, writes, forcing sites ------------------------------------
    def walk(self) -> None:
        def v(n):
            k = n.kind
            if k == _SY.Instance and n is not self.inst:
                self.sub_instance(n)
                return ast.VisitAction.Skip
            if k == _SY.PrimitiveInstance:
                self.gate(n)
                return ast.VisitAction.Skip
            if k == _SY.UninstantiatedDef:
                for e in n.portConnections:
                    if e is not None:
                        self.opaque |= self.reads(e, set())
                return ast.VisitAction.Skip
            if k == _SY.ContinuousAssign:
                a = n.assignment
                reads = self.reads(a.right, set())
                for nv in self.lvalues(a.left):
                    self.drivers[self.key(nv.symbol)].append(_Driver(frozenset(reads), frozenset()))
                return ast.VisitAction.Skip
            if k in (_SY.Net, _SY.Variable) and n.initializer is not None:
                self.drivers[self.key(n)].append(_Driver(frozenset(self.reads(n.initializer, set())),
                                                         frozenset()))
            if k == _SY.ProceduralBlock:
                self.block(n)
                return ast.VisitAction.Skip
            return ast.VisitAction.Advance

        self.inst.visit(v)

    def gate(self, prim) -> None:
        """buf/not/and/or/nand/nor/xor/xnor/bufif*/notif* and UDPs: outputs <- inputs."""
        terms = [e for e in prim.portConnections if e is not None]
        name = prim.primitiveType.name
        n_out = len(terms) - 1 if name in _MULTI_OUT else 1
        reads = set()
        for e in terms[n_out:]:
            self.reads(e, reads)
        for e in terms[:n_out]:
            for nv in self.lvalues(e):
                self.drivers[self.key(nv.symbol)].append(_Driver(frozenset(reads), frozenset()))

    def sub_instance(self, inst) -> None:
        """A module from the same file: conservatively, every output depends on every input
        (over-approximation adds triggers, it never drops one)."""
        ins, outs = set(), []
        for conn in inst.portConnections:
            e = conn.expression
            if e is None:
                continue
            if conn.port.direction == ast.ArgumentDirection.In:
                self.reads(e, ins)
            else:
                outs.append(e)
        for e in outs:
            for nv in self.lvalues(e):
                self.drivers[self.key(nv.symbol)].append(_Driver(frozenset(ins), frozenset()))

    def block(self, pb) -> None:
        body, edges, levels = pb.body, set(), set()
        stmt, implicit = body, pb.procedureKind in (ast.ProceduralBlockKind.AlwaysComb,
                                                    ast.ProceduralBlockKind.AlwaysLatch)
        if body.kind == _SK.Timed:
            implicit |= self.events(body.timing, edges, levels)
            stmt = body.stmt
        if implicit:  # @* / always_comb / always_latch: sensitive to everything read
            levels |= self.reads(stmt, set())
        self.stmt(stmt, frozenset(), _Ctx(frozenset(edges), frozenset(levels)))

    def events(self, timing, edges: set, levels: set) -> bool:
        k = timing.kind
        if k == _TK.EventList:
            return any([self.events(e, edges, levels) for e in timing.events])
        if k == _TK.SignalEvent:
            self.reads(timing.expr, edges if timing.edge in _EDGES else levels)
            return False
        if k == _TK.ImplicitEvent:
            return True
        if k in _DELAYS:
            return False
        raise self.err(f"unsupported timing control {k}")

    def seq(self, stmts, conds: frozenset[str], ctx: _Ctx) -> None:
        pending: set[str] = set()
        for s in stmts:
            if s.kind == _SK.Timed and s.timing.kind in _DELAYS:
                pending.clear()
            hit = pending & self.rvalue_names(s)
            if hit:
                raise self.err(f"{sorted(hit)[0]} is read after its procedural assign/deassign "
                               "in the same block without an intervening delay")
            self.stmt(s, conds, ctx)
            pending |= self.forced_in(s)

    def stmt(self, s, conds: frozenset[str], ctx: _Ctx) -> None:
        k = s.kind
        if k == _SK.Block:
            self.stmt(s.body, conds, ctx)
        elif k == _SK.List:
            self.seq(list(s.list), conds, ctx)
        elif k == _SK.Conditional:
            c = set(conds)
            for cond in s.conditions:
                self.reads(cond.expr, c)
            self.stmt(s.ifTrue, frozenset(c), ctx)
            if s.ifFalse is not None:
                self.stmt(s.ifFalse, frozenset(c), ctx)
        elif k == _SK.Case:
            c = set(conds)
            self.reads(s.expr, c)
            for item in s.items:
                for e in item.expressions:
                    self.reads(e, c)
            for item in s.items:
                self.stmt(item.stmt, frozenset(c), ctx)
            if s.defaultCase is not None:
                self.stmt(s.defaultCase, frozenset(c), ctx)
        elif k == _SK.Timed:
            edges, levels = set(ctx.edges), set(ctx.levels)
            self.events(s.timing, edges, levels)
            self.stmt(s.stmt, conds, _Ctx(frozenset(edges), frozenset(levels)))
        elif k == _SK.ExpressionStatement:
            self.expr_stmt(s.expr, conds, ctx)
        elif k == _SK.ProceduralAssign:
            self.force(s, conds, ctx)
        elif k == _SK.ProceduralDeassign:
            self.regs[self.key(s.lvalue.symbol)].deassigns.append(self.span(s))
            self._site(self.key(s.lvalue.symbol), ctx)
        elif hasattr(s, "body") and k in (_SK.ForLoop, _SK.RepeatLoop, _SK.WhileLoop,
                                          _SK.DoWhileLoop, _SK.ForeverLoop):
            self.stmt(s.body, frozenset(self.reads(s, set(conds))), ctx)
        elif k in (_SK.Empty, _SK.Disable, _SK.Return, _SK.Break, _SK.Continue):
            pass
        else:
            if self.forced_in(s) or self.written_names(s) & self.forced_names:
                raise self.err(f"unhandled statement kind {k} touches a forced reg")
            self._generic_writes(s, frozenset(self.reads(s, set(conds))), ctx)

    def expr_stmt(self, e, conds: frozenset[str], ctx: _Ctx) -> None:
        if e.kind == _EK.Assignment:
            reads = set(conds) | set(ctx.levels)
            self.reads(e.right, reads)
            self.select_reads(e.left, reads)
            for nv in self.lvalues(e.left):
                name = self.key(nv.symbol)
                self.drivers[name].append(_Driver(frozenset(reads), frozenset(ctx.edges - reads)))
                if name in self.regs:
                    self.regs[name].writes.add(self.span(nv))
        elif e.kind == _EK.Call and not e.isSystemCall:
            sub = e.subroutine
            if sub in self._stack:
                raise self.err(f"recursive call of {sub.name}")
            args = set(conds)
            for a in e.arguments:
                if a.kind == _EK.Assignment and any(self.key(n.symbol) in self.regs
                                                    for n in self.lvalues(a.left)):
                    raise self.err(f"forced reg passed to an output argument of {sub.name}")
                self.reads(a, args)
            self._stack.append(sub)
            self.stmt(sub.body, frozenset(args), ctx)
            self._stack.pop()

    def force(self, s, conds: frozenset[str], ctx: _Ctx) -> None:
        a = s.assignment
        name = self.key(a.left.symbol)
        rhs = self.reads(a.right, set())
        if name in rhs:
            raise self.err(f"override expression of {name} reads {name}")
        for r in rhs:
            if "." in r and not r.startswith("glbl."):
                raise self.err(f"override expression of {name} reads local {r}")
        self.regs[name].overrides.append((self.span(s), self.span(a.right)))
        self.drivers[name].append(_Driver(frozenset(rhs | conds | ctx.levels),
                                          frozenset(ctx.edges - rhs - conds)))
        self._site(name, ctx)

    def _site(self, name: str, ctx: _Ctx) -> None:
        self.regs[name].sensitivity |= ctx.edges | ctx.levels

    def _generic_writes(self, s, reads: frozenset[str], ctx: _Ctx) -> None:
        def v(n):
            if n.kind == _EK.Assignment:
                for nv in self.lvalues(n.left):
                    self.drivers[self.key(nv.symbol)].append(_Driver(reads, frozenset(ctx.edges - reads)))
            return ast.VisitAction.Advance

        s.visit(v)

    # ---- cone tracing ----------------------------------------------------------------
    def trace(self, start: set[str]) -> tuple[set[str], set[str]]:
        trig: set[str] = set()
        en: set[str] = set()
        seen: set[tuple[str, bool]] = set()
        work = [(s, False) for s in start]
        while work:
            s, via_clock = work.pop()
            if (s, via_clock) in seen:
                continue
            seen.add((s, via_clock))
            if s.startswith("glbl.") or s in self.inputs:
                (en if via_clock else trig).add(s)
                continue
            if s in self.opaque:
                raise self.err(f"cannot trace {s}: it is driven by an instance output")
            if not self.drivers.get(s):
                raise self.err(f"cannot resolve the driver of {s} while tracing triggers "
                               "(spec §6.2: never drop a signal silently)")
            for d in self.drivers.get(s, ()):
                work += [(r, via_clock) for r in d.reads]
                work += [(c, True) for c in d.clocks]
        return trig, en - trig


def _compile(path: Path, module: str, glbl: Path, overrides: dict[str, str]):
    opts = ast.CompilationOptions()
    opts.paramOverrides = [f"{k}={v}" for k, v in overrides.items()]
    comp = ast.Compilation(pyslang.Bag([opts]))
    comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(path)))
    comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(glbl)))
    diags = [d for d in comp.getAllDiagnostics() if d.isError() and not _is_benign(d)]
    if diags:
        report = pyslang.DiagnosticEngine.reportAll(comp.sourceManager, diags)
        raise TransformError(module, f"pyslang errors with {overrides or 'defaults'}:\n{report}")
    inst = next((i for i in comp.getRoot().topInstances if i.name == module), None)
    if inst is None:
        raise TransformError(module, f"module not found in {path}")
    return comp, inst


def generate_configs(path: Path, module: str, choices: dict[str, list[str]] | None = None,
                     limit: int = 64) -> list[dict[str, str]]:
    """Parameter overrides that together elaborate every generate branch (review #3).

    Syntax-level: for each `if`/`case` generate construct, take the module parameters its
    condition names. Candidate values are `choices[name]` (the catalog's allowed values)
    when given; otherwise both values for a 1-bit parameter; otherwise every literal the
    condition compares the parameter with, plus the default. Take
    the product per construct (other parameters at default), union over constructs,
    deduplicate, and put `{}` first. A generate if/case nested inside another raises
    (known limitation, plan ambiguity 12). Loop generates need nothing: every iteration is
    elaborated. Raises if a condition has a parameter with no candidates, or the total
    exceeds `limit`."""
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    params = _module_parameters(tree, module)            # name -> default text
    out: list[dict[str, str]] = [{}]
    nested = _nested_generate_conditions(tree, module)
    if nested:
        raise TransformError(module, f"nested generate conditions are not supported: `{nested[0]}`")
    for cond in _generate_conditions(tree, module):      # syntax nodes of if/case conditions
        names = sorted(_identifiers(cond) & set(params))
        cands = {n: (choices or {}).get(n)
                 or (["1'b0", "1'b1"] if _is_one_bit(tree, module, n) else None)
                 or _literals_compared_with(cond, n, params[n]) for n in names}
        empty = [n for n, c in cands.items() if not c]
        if empty:
            raise TransformError(module, f"cannot enumerate generate configurations: no candidate "
                                 f"values for {empty} in `{cond}`")
        for combo in itertools.product(*(cands[n] for n in names)):
            cfg = {n: v for n, v in zip(names, combo, strict=True) if v != params[n]}
            if cfg not in out:
                out.append(cfg)
    if len(out) > limit:
        raise TransformError(module, f"cannot enumerate generate configurations: {len(out)} > {limit}")
    return out


def analyze(path: Path, module: str, glbl: Path,
            choices: dict[str, list[str]] | None = None) -> Analysis:
    text = Path(path).read_text()
    merged: dict[str, ForcedReg] = {}
    end = None
    for overrides in generate_configs(path, module, choices):
        _, inst = _compile(path, module, glbl, overrides)
        w = _Walker(module, inst, text)
        w.prescan()
        w.walk()
        for x in w.regs.values():
            if not x.overrides:
                raise TransformError(module, f"{x.name} is deassigned but never assigned")
            trig, en = w.trace(x.sensitivity)
            if not trig:
                raise TransformError(module, f"{x.name}: no trigger found (the forcing block has "
                                     "no sensitivity list or its cone has no primitive input)")
            m = merged.setdefault(x.name, ForcedReg(x.name, x.dims, x.decl_name, x.decl_end,
                                                    x.is_port))
            m.overrides = sorted(set(m.overrides) | set(x.overrides), key=lambda o: o[0].start)
            m.deassigns = sorted(set(m.deassigns) | set(x.deassigns), key=lambda d: d.start)
            m.writes |= x.writes
            m.sensitivity |= x.sensitivity
            m.triggers |= trig
            m.enablers |= en
        end = inst.body.definition.syntax.endmodule.location.offset
    return Analysis(module, Path(path), text, end, merged)
```

The helpers `_module_parameters`, `_generate_conditions`, `_identifiers`, `_is_one_bit` and `_literals_compared_with` (which returns `[]` when the condition compares with no literal, so the default alone never counts as a candidate list) are small syntax-tree walks over `pyslang.syntax` (`ModuleDeclaration` → `ParameterDeclaration`; `IfGenerate`/`CaseGenerate` → condition expression; `IdentifierName`; integer/vector/string literal tokens). Unit-test each on `vz_generate.v` and `vz_bad_genparam.v`.

**Implementer notes.**

- `_SK.Return`, `_SK.Break`, `_SK.Continue`, `_SK.Disable` and the loop kinds must exist in pyslang 11. Check `dir(ast.StatementKind)` and drop any that do not.
- A local variable declared in a named block has a hierarchical path like `VZ.blk.i`. After the module prefix is stripped it still contains a `.`, which is how `force()` recognises a local. glbl signals keep their `glbl.` prefix.
- The `rvalue_names` rule treats the lvalue of a `deassign X` as a *read*. That is intended: the rewrite turns it into `begin if (X__ovr_sel != 0) begin X__base = X; X__ovr_sel = 0; end end`.
- Still to verify with `dir()`: `CompilationOptions.paramOverrides` (slang's `-G`), `PrimitiveInstance.portConnections` and `.primitiveType.name`, `Instance.portConnections[i].port`/`.expression`, and the syntax kinds `IfGenerate`/`CaseGenerate`. If `paramOverrides` is not exposed, generate a wrapper module that instantiates the model with `#(.NAME(value))` and analyse that instance instead: same result.
- Spans from different generate configurations are identical source offsets, so `set` union deduplicates them.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tools/tests/test_vz_analyze.py -v > .cache/pytest.log 2>&1; tail -n 30 .cache/pytest.log`

Expected: all pass. Adjust the fixtures, never the expected sets, until they do. The expected sets are the spec's semantics.

- [ ] **Step 5: Commit**

```bash
git add tools/tests/fixtures/verilatorize && git commit -m "verilatorize: add toy fixtures for every spec §6.2 transform case and refusal" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tools && git commit -m "verilatorize: derive forced regs, triggers and enablers from the pyslang AST" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: `xut verilatorize` — the shadow-register rewrite

**Files:**
- Create: `tools/xut/verilatorize/rewrite.py`, `tools/xut/verilatorize/driver.py`, `tools/tests/test_vz_rewrite.py`, `tools/tests/fixtures/verilatorize/vz_ranges.v`, `tools/tests/fixtures/verilatorize/vz_ifelse.v`
- Modify: `tools/xut/cli.py`

**Interfaces:**
- Consumes: `Analysis`, `TransformError`, `analyze`, `has_procedural_assign` (Task 12); `ModelSource` (Task 1)
- Produces:
  - `xut.verilatorize.rewrite.rewrite(an) -> str`
  - `check_clean(text, model, glbl, configs) -> None`. It raises if any procedural `assign`/`deassign` syntax remains anywhere (every generate branch included), or if the rewritten text fails to elaborate without errors under **each** of `configs` (the `generate_configs` list). pyslang reports a procedural write to a net as an error, so a missed `X` → `X__base` rename in any generate branch is caught here.
  - `xut.verilatorize.driver.ModelEntry` (`status` = `transformed`|`unchanged`|`unsupported`, `reason, triggers, enablers, forced, generate_configs, source_sha256`, and `equiv: dict[str, str]` mapping a configuration key (`"default"` or sorted `NAME=value,...`) to `pass`|`fail`|`error`)
  - `Manifest` (`model_source`, `models: dict[str, ModelEntry]`, with `load`/`save`)
  - `vz_dir(ms) -> Path`
  - `verilatorize(ms, models=None, *, jobs=1) -> Manifest`, which is incremental by source sha256
  - CLI `xut verilatorize [--model-source auto] [--check] [--jobs N] [MODEL...]`

The rewrite follows spec §6.2 steps 1–3 (rev 3.1), with two refinements:

- Each override expression gets its own net `X__ovr_k`, declared with the **same packed range and signedness text** as `X` (`[4:1]`, `[0:3]`, `signed`), and the mux selects among nets of identical type. `assign X__ovr_k = e_k;` extends and truncates `e_k` exactly as the original `assign X = e_k;` did, and every existing `X[i]`/`X[a:b]` read indexes the new net exactly as it indexed the reg (review #5).
- `deassign X;` becomes `begin if (X__ovr_sel != 0) begin X__base = X; X__ovr_sel = 0; end end`. The outer `begin … end` matters: the replacement is a single statement, so when the original `deassign` is the then-arm of `if (c) deassign X; else …`, the original `else` still binds to `if (c)` and not to the new guard (dangling-else, PR #3 follow-up N1). A `deassign` of a reg that is not forced is a no-op in Verilog; the guard keeps it one, so a stale `X` (not yet propagated this time step) can never clobber an `X__base` written earlier in the same step (review #4, spec §6.2 step 2 rev 3.1).

Output for `VZTRIG` (reference for the golden test, whitespace as produced):

```verilog
  reg q__base; reg [1:0] q__ovr_sel = 2'd0; wire q; wire q__ovr_1; wire q__ovr_2; wire q__ovr_3;
  ...
  always @(gsr_in or CLR or PRE)
    if (gsr_in) q__ovr_sel = 2'd1;
    else if (CLR) q__ovr_sel = 2'd2;
    else if (PRE) q__ovr_sel = 2'd3;
    else begin if (q__ovr_sel != 2'd0) begin q__base = q; q__ovr_sel = 2'd0; end end
  always @(posedge C) q__base <= D;
  // xut verilatorize: shadow-register override muxes (spec §6.2)
  assign q__ovr_1 = 1'b0;
  assign q__ovr_2 = 1'b0;
  assign q__ovr_3 = 1'b1;
  assign q = (q__ovr_sel == 2'd0) ? q__base : (q__ovr_sel == 2'd1) ? q__ovr_1 : (q__ovr_sel == 2'd2) ? q__ovr_2 : q__ovr_3;
endmodule
```

- [ ] **Step 1: Write the failing tests** `tools/tests/test_vz_rewrite.py`

```python
# SPDX-License-Identifier: Apache-2.0
import shutil
from pathlib import Path

import pyslang
import pytest

from xut.container import SIM_IMAGE, DockerExecutor, image_digest
from xut.paths import repo_root
from xut.verilatorize.analyze import TransformError, analyze, generate_configs
from xut.verilatorize.rewrite import check_clean, rewrite

FIX = Path(__file__).parent / "fixtures" / "verilatorize"
GLBL = FIX / "glbl.v"
MODS = {"vz_single.v": "VZSINGLE", "vz_multi.v": "VZMULTI", "vz_retain.v": "VZRETAIN",
        "vz_nonconst.v": "VZNONCONST", "vz_trig.v": "VZTRIG", "vz_select.v": "VZSEL",
        "vz_task.v": "VZTASK", "vz_shift.v": "VZSHIFT", "vz_delay.v": "VZDELAY",
        "vz_async.v": "VZASYNC", "vz_cone.v": "MMCMVZ", "vz_gate.v": "BUFVZ",
        "vz_sub.v": "VZSUB", "vz_generate.v": "VZGEN", "vz_ranges.v": "VZRANGE",
        "vz_ifelse.v": "VZIFELSE"}


@pytest.mark.parametrize("fname", sorted(MODS))
def test_output_is_clean_and_elaborates_in_every_generate_config(fname):
    out = rewrite(analyze(FIX / fname, MODS[fname], GLBL))
    check_clean(out, MODS[fname], GLBL, generate_configs(FIX / fname, MODS[fname]))


def test_vztrig_golden_fragments():
    out = rewrite(analyze(FIX / "vz_trig.v", "VZTRIG", GLBL))
    assert "reg q__base; reg [1:0] q__ovr_sel = 2'd0; wire q;" in out
    assert "else begin if (q__ovr_sel != 2'd0) begin q__base = q; q__ovr_sel = 2'd0; end end" in out
    assert "always @(posedge C) q__base <= D;" in out
    assert ("assign q = (q__ovr_sel == 2'd0) ? q__base : (q__ovr_sel == 2'd1) ? q__ovr_1 : "
            "(q__ovr_sel == 2'd2) ? q__ovr_2 : q__ovr_3;") in out


def test_deassign_in_then_arm_keeps_its_else():
    out = rewrite(analyze(FIX / "vz_ifelse.v", "VZIFELSE", GLBL))
    assert ("if (C2) begin if (q__ovr_sel != 1'd0) begin q__base = q; q__ovr_sel = 1'd0; end end"
            " else q__ovr_sel = 1'd1;") in out
    assert "always @(posedge C) q__base <= D;" in out
    assert "assign q = (q__ovr_sel == 1'd0) ? q__base : q__ovr_1;" in out  # one override


def test_delay_and_blocking_form_preserved():
    out = rewrite(analyze(FIX / "vz_delay.v", "VZDELAY", GLBL))
    assert "q__base <= #100 D;" in out


def test_self_reference_reads_overridden_value():
    out = rewrite(analyze(FIX / "vz_shift.v", "VZSHIFT", GLBL))
    assert "data__base <= {data[2:0], D};" in out


def test_select_writes_renamed():
    out = rewrite(analyze(FIX / "vz_select.v", "VZSEL", GLBL))
    assert "v__base[0] <=" in out and "v__base[2:1] <=" in out


def test_both_generate_arms_rewritten():
    out = rewrite(analyze(FIX / "vz_generate.v", "VZGEN", GLBL))
    assert out.count("r__base <=") == 2          # posedge arm and negedge arm


def test_packed_range_preserved():
    out = rewrite(analyze(FIX / "vz_ranges.v", "VZRANGE", GLBL))
    assert "wire [4:1] a;" in out and "wire [0:3] b;" in out and "wire signed [7:0] c;" in out


def test_missed_rename_is_caught(monkeypatch):
    an = analyze(FIX / "vz_generate.v", "VZGEN", GLBL)
    an.forced["r"].writes = set(sorted(an.forced["r"].writes, key=lambda w: w.start)[:1])
    with pytest.raises(TransformError, match="IS_C_INVERTED"):   # the config that fails is named
        check_clean(rewrite(an), "VZGEN", GLBL, generate_configs(FIX / "vz_generate.v", "VZGEN"))


@pytest.mark.container
@pytest.mark.skipif(shutil.which("docker") is None or image_digest(SIM_IMAGE) is None,
                    reason="xut-sim image not built")
@pytest.mark.parametrize("fname", sorted(MODS))
def test_verilator_lints_transformed(fname):
    work = repo_root() / "build" / "vz-lint" / MODS[fname]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    (work / fname).write_text(rewrite(analyze(FIX / fname, MODS[fname], GLBL)))
    shutil.copy(GLBL, work / "glbl.v")
    log = work / "lint.log"
    rc = DockerExecutor().run(["verilator", "--lint-only", "--timing", "-Wno-fatal", "-Wno-lint",
                               "-Wno-style", "-Wno-MULTITOP", fname, "glbl.v"],
                              cwd=work, log=log, timeout_s=120)
    assert rc == 0, log.read_text()
```

`vz_ifelse.v` (`VZIFELSE`), in full:

```verilog
// SPDX-License-Identifier: Apache-2.0
// vz_ifelse.v — the deassign is the then-arm of an if/else (dangling-else guard).
`timescale 1ps/1ps
module VZIFELSE (output Q, input C, input D, input C2, input E);
  reg q;
  assign Q = q;
  always @(C2 or E)
    if (C2) deassign q;
    else assign q = E;
  always @(posedge C) q <= D;
endmodule
```
 The `deassign` is the then-arm of an if/else, which pins the dangling-else fix.

`vz_ranges.v` (`VZRANGE`): three forced regs `reg [4:1] a;`, `reg [0:3] b;` and `reg signed [7:0] c;`, each read through selects (`a[4]`, `b[0:1]`, `c[7]`) in continuous assigns.

- [ ] **Step 2: Implement `rewrite.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Shadow-register transform (spec §6.2 steps 1-3), applied as AST-anchored text edits."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pyslang

from xut.verilatorize.analyze import (_SYNTAX_FORCE, Analysis, TransformError, _compile,
                                      _syntax_kinds)

BANNER = ("// SPDX-License-Identifier: Apache-2.0\n"
          "// GENERATED by xut verilatorize from {src} (spec §6.2). Never commit.\n")


def _apply(model: str, text: str, edits: list[tuple[int, int, str]]) -> str:
    edits = sorted(edits, key=lambda e: (e[0], e[1]))
    for (s1, e1, _), (s2, _e2, _) in zip(edits, edits[1:], strict=False):
        if s2 < e1:
            raise TransformError(model, f"overlapping rewrite edits at offset {s2}")
    out, pos = [], 0
    for s, e, rep in edits:
        out += [text[pos:s], rep]
        pos = e
    out.append(text[pos:])
    return "".join(out)


def rewrite(an: Analysis) -> str:
    edits: list[tuple[int, int, str]] = []
    tail: list[str] = []
    for x in an.forced.values():
        n = len(x.overrides)
        w = max(1, n.bit_length())
        sel, base = f"{x.name}__ovr_sel", f"{x.name}__base"
        typ = x.dims  # the declaration's own packed range/signedness text
        edits.append((x.decl_name.start, x.decl_name.end, base))
        decl = [f"reg [{w - 1}:0] {sel} = {w}'d0;"]
        if not x.is_port:
            decl.append(f"wire {typ}{x.name};")
        decl += [f"wire {typ}{x.name}__ovr_{k};" for k in range(1, n + 1)]
        edits.append((x.decl_end, x.decl_end, " " + " ".join(decl)))
        edits += [(s.start, s.end, base) for s in sorted(x.writes, key=lambda s: s.start)]
        for k, (stmt, expr) in enumerate(x.overrides, start=1):
            edits.append((stmt.start, stmt.end, f"{sel} = {w}'d{k};"))
            tail.append(f"  assign {x.name}__ovr_{k} = {an.text[expr.start:expr.end]};")
        for d in x.deassigns:
            edits.append((d.start, d.end,
                          f"begin if ({sel} != {w}'d0) begin {base} = {x.name}; {sel} = {w}'d0; "
                          "end end"))  # outer begin/end: no dangling else (N1)
        mux = f"{x.name}__ovr_{n}"
        for k in range(n - 1, 0, -1):
            mux = f"({sel} == {w}'d{k}) ? {x.name}__ovr_{k} : {mux}"
        tail.append(f"  assign {x.name} = ({sel} == {w}'d0) ? {base} : {mux};")
    edits.append((an.endmodule, an.endmodule,
                  "  // xut verilatorize: shadow-register override muxes (spec §6.2)\n"
                  + "\n".join(tail) + "\n"))
    return BANNER.format(src=an.path.name) + _apply(an.model, an.text, edits)


def check_clean(text: str, model: str, glbl: Path, configs: list[dict[str, str]]) -> None:
    tree = pyslang.syntax.SyntaxTree.fromText(text)
    if _syntax_kinds(tree.root, set()) & _SYNTAX_FORCE:
        raise TransformError(model, "procedural assign/deassign remains after the rewrite")
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / f"{model}.v"
        f.write_text(text)
        for cfg in configs:
            try:
                _compile(f, model, glbl, cfg)  # raises on any non-benign error, naming cfg
            except TransformError as e:
                raise TransformError(model, f"rewritten model does not elaborate: {e}") from e
```

The mux expression reproduces spec §6.2 step 3, `(sel == 0) ? X__base : (sel == 1) ? e_1 : ...`. Its innermost arm is `e_n` rather than a redundant `(sel == n) ? e_n : X__base`: `sel` never holds a value above `n`, because only the rewrite writes it.

- [ ] **Step 3: Implement `driver.py`**
  - `verilatorize(ms, models, jobs)` iterates `ms.unisims/*.v` and `ms.retarget/*.v` (restricted to `models` when given).
  - Per file:
    - no procedural assign (`has_procedural_assign` false) → `unchanged`;
    - else `configs = generate_configs(f, f.stem, choices)` (with `choices` taken from the catalog's `allowed` values when the model is a catalogued primitive), `analyze(f, f.stem, ms.glbl, choices)` → `rewrite` → `check_clean(..., configs)` → write `vz_dir(ms)/<file>` → `transformed`, recording the triggers, enablers, forced names and `generate_configs`;
    - `TransformError` → `unsupported`, with `reason = str(e)`.
  - Re-transform only when the source sha256 or `xut.__version__` changed.
  - Use a `ProcessPoolExecutor(jobs)` for the analysis.
  - Save `vz_dir(ms)/manifest.json`, and print `progress: done=N total=M elapsed_s=E` lines.
  - The CLI prints a summary: counts per status, and each unsupported model with its reason.

- [ ] **Step 4: Run the tests** (all pass; the container tests need the image). **Then run it on the real model sources**, which takes minutes, so log to a file:

```bash
uv run xut verilatorize --model-source unisim-2025.2 --jobs 32 > .cache/vz-2025.2.log 2>&1; tail -n 30 .cache/vz-2025.2.log
uv run xut verilatorize --model-source unisim-gh-2020.1 --jobs 32 > .cache/vz-gh.log 2>&1; tail -n 30 .cache/vz-gh.log
```

Expected:
- about 45 models are `transformed` or `unsupported` for 2025.2 (45 files contain the word `deassign`), and 40 for the 2020.1 submodule (spec §6.2);
- `FDRE`, `FDSE`, `FDCE` and `FDPE` are `transformed`, each with a non-empty trigger list and more than one generate configuration recorded (their models select behaviour through generate blocks). UG953 says GSR initialises these registers, so `glbl.GSR` is expected among the triggers. If it is not, record the tool's actual list in the log entry: that is information, not an error;
- every `unsupported` line names a construct.

Record the counts in the log entry. Do **not** open the FD\* UNISIM sources to check the triggers (clean-room rule for the flops unit, Task 20). The trigger list comes from the tool.

- [ ] **Step 5: Commit** with `verilatorize: add shadow-register rewrite, per-configuration elaboration check, and model-source driver`.

---

### Task 14: Equivalence stimulus and the Icarus equivalence check

**Files:**
- Create: `tools/xut/verilatorize/equiv.py`, `tools/tests/test_vz_equiv.py`
- Modify: `tools/xut/verilatorize/driver.py` (`--check`), `tools/xut/cli.py`

**Interfaces:**
- Consumes: `VecBuilder` (Task 5); `spec_from_hdl`, `write_dut` (Task 4); `parse_module` (step 1); `write_stim`, `raw_to_trace`, `TB` (Task 7); `diff` (Task 3); `executor_for` (Task 1)
- Produces:
  - `xut.verilatorize.equiv.equiv_stimulus(an, m, seed=1) -> Vec`
  - `EquivResult` (`model, status, reason, mismatches, triggers, enablers`)
  - `check_model(an, ms, out_dir, attrs: dict[str, str] | None = None) -> EquivResult`, for one attribute configuration
  - `config_key(attrs) -> str` (`"default"`, or sorted `NAME=value` joined by `,`)
  - Driver: `verilatorize(..., check=True)` runs `check_model` for every transformed model under the default configuration **and** every entry of its `generate_configs`, storing each result in `manifest.models[M].equiv[config_key]`.
  - Runners: `ensure_model(ms, prim, attrs)` (Task 15) runs `check_model` on demand for any other configuration a test uses. So every attribute configuration any test uses, plus the default, is equivalence-checked before a Verilator result for it counts (controller ruling on review #3).

**Equivalence stimulus** (spec §6.2). It is generated from the analysis, is mandatory, and is deterministic for a given seed:

- All ports are at idle 0.
- The wrapper uses `spec_from_hdl(mod, key, attrs, raw_clock_out=True)` with the configuration's attributes, so clock outputs are sampled directly. This is acceptable for an original-vs-transformed comparison, which never meets the hardware harness.
- Enabler clocks always run: every clock-class input cycles in each `activity(n)` step.
- `activity(n)` means `n` cycles on every clock-class input with random data on the non-trigger data ports, sampling after every edge. With no clock ports it is `n` samples with random data.
- A trigger is pulsed through the glbl channel (`glbl.*`), through `async_` for async/gate ports, with `set` for data ports, and with `edge` for clock ports.

Phases:

1. **Independent pulses, mid-simulation.** For each trigger, three times: `activity(2)`, assert, sample, `activity(2)`, deassert, sample, `activity(1)`.
2. **Coincident with clock edges.** For each non-clock trigger and each clock: assert inside `simultaneous()` together with a rising edge, sample, fall, `activity(1)`, then deassert inside `simultaneous()` together with the next rising edge, and sample.
3. **Pairs, overlapping.** For each pair (a, b):
   - a↑ b↑ a↓ b↓ (overlap), with `activity(1)` between the steps;
   - a↑ b↑ b↓ a↓ (nested);
   - a↑b↑ together, then a↓b↓ together (coincident, inside `simultaneous()`).
4. **With async-control activity.** For each trigger t and each async/gate port q that is not a trigger: q↑, t↑, q↓, t↓, with a sample after each step.

The file is `hw_renderable no`. `validate` must report no errors, and a test pins that.

**Check.**
- Write `dut/`, `stim.xvec` and `stim.memh` once.
- Compile and run twice on Icarus: `orig/` with `-y ms.unisims [-y ms.retarget]`, and `vz/` with `-y vz_dir(ms)` first.
- Both runs must print `XUT_DONE`, else the result is `error`.
- `diff(orig, vz)` is exact (4-state) → `pass`/`fail`. `mismatches.txt` lists the differences, and `result.json` goes in `vz_dir(ms)/equiv/<MODEL>/<config_key>/`.
- A `glbl.*` trigger other than `GSR`, `GTS` or `GRESTORE` has no glbl channel: `equiv_stimulus` raises `TransformError` (never skips it), which makes the result `error`.

- [ ] **Step 1: Write the tests** `tools/tests/test_vz_equiv.py`:
  - `equiv_stimulus` for `VZTRIG` validates with zero errors, contains `simultaneous` events, pulses `glbl GSR`, `CLR` and `PRE` at least three times each, and has at least three overlapping-pair sections (three pairs).
  - For `MMCMVZ`, the stimulus pulses RST and PWRDWN, and every pulse has a `CLKIN1` edge both before and after it.
  - Container tests: for every fixture in `MODS` (Task 13), build a `ModelSource` in `tmp_path/src/` (`unisims/` holds the fixture, `glbl.v` the fixture glbl). Run the driver with `check=True`, and expect `equiv[key] == "pass"` for every recorded configuration of all sixteen (VZIFELSE included). `VZGEN` must have two keys (`default`, `IS_C_INVERTED=1'b1`).
  - A **guard test** for the rev-3.1 `deassign` rule: fixture `VZRETAIN` extended with an `initial r = 1'b1;` and a forcing block whose control goes x→0 at t=0 (so it runs `deassign` while unforced). Equivalence must pass; with the guard removed by monkeypatching `rewrite`, it must fail.
  - A **mutation test.** Deliberately corrupt the rewrite: monkeypatch `rewrite` so that `deassign` becomes `X__ovr_sel = 0;` without `X__base = X;`, which breaks retention. `VZRETAIN` must then give `equiv == "fail"` with at least one mismatch. This proves the check can fail.

- [ ] **Step 2: Implement `equiv.py`** following the phase list. Keep the phase functions small and named after the spec bullets: `_independent`, `_coincident`, `_pairs`, `_with_async`.

- [ ] **Step 3: Run the tests, then the real check** (in the background, logging to a file, with a progress Monitor at a 60 s cadence; expected duration 2–5 minutes at `--jobs 32`):

```bash
uv run xut verilatorize --model-source unisim-2025.2 --check --jobs 32 > .cache/vz-check-2025.2.log 2>&1
```

Expected: the `progress:` lines reach `done=M total=M`, and the summary shows `equiv: pass` for **every** recorded configuration of FDRE, FDSE, FDCE and FDPE. Every `fail` is a **finding**, not something to fix silently:
- first confirm it with the mutation-free rewrite;
- if it is real, record `findings/<PRIM>-transform-bug.md` in the pilot branch later (Task 24), and note it in this branch's log entry.

- [ ] **Step 4: Commit** with `verilatorize: add mandatory equivalence stimulus and Icarus original-vs-transformed check`.

---

### Task 15: Verilator runner (two X-seed runs) and the iverilog-vz companion

**Files:**
- Create: `tools/xut/runners/verilator.py`, `tools/tests/test_runner_verilator.py`
- Modify: `tools/xut/runners/__init__.py` (register `verilator` **and** `iverilog-vz` in `RUNNERS`: this is the first task where `iverilog-vz` works), `tools/xut/runners/iverilog.py` (`IverilogVzRunner.lib_first`), `tools/xut/run.py` (auto-add `iverilog-vz`)

**Interfaces:**
- Consumes: `Manifest`, `vz_dir`, `verilatorize`, `check_model` (Tasks 13–14); `prepare_vector`, `vector_check` (Tasks 9–10)
- Produces:
  - `VerilatorRunner` (`name="verilator"`, `x_observable=False`)
  - `x_seeds(seed) -> tuple[int, int]` = `((2*seed+1) % 2**31 or 1, (2*seed+2) % 2**31 or 2)`
  - `ensure_model(ms, prim, attrs) -> ModelEntry`, which transforms on demand and runs the equivalence check for this configuration if `equiv[config_key(attrs)]` is missing. It is cached, and guarded by a per-model lock because runner jobs are threads.

- [ ] **Step 1: Spike — is glbl as a second top usable on Verilator v5.048?** (The step-2 research only exercised 5.032; nothing about multi-top support is assumed from it.) Using the Task 7 toy DUT, whose testbench writes `glbl.GSR_int` and whose DUT reads `glbl.GSR`:

```bash
mkdir -p build/vl-spike && cp tools/tests/fixtures/tb/toy_dut.v tools/xut/hdl/xut_vector_tb.sv build/vl-spike/
# write stim.memh / stim.vh / xut_cfg.vh with a 10-line python snippet using write_stim (as in test_stimcompile)
docker run --rm --network=none -u $(id -u):$(id -g) -v $PWD:/work -w /work/build/vl-spike xut-sim:1 \
  bash -c 'verilator --binary --timing -Wno-fatal -Wno-lint -Wno-style -Wno-MULTITOP -Mdir obj -o simx -I. xut_vector_tb.sv toy_dut.v && ./obj/simx' \
  > .cache/vl-spike.log 2>&1; cat .cache/vl-spike.log
```

Decision:
- If the log shows `XUT_DONE` and the samples match Task 7's `{S0: 1, S1: 1, S2: 0}`, keep glbl as a second top (spec §6).
- Otherwise, set `+define+XUT_GLBL_INSTANCE` for Verilator only: the testbench then instantiates `glbl` and UNISIM resolves `glbl.GSR` upward. Record the choice in the runner docstring and in the log entry.

Either way, the choice is fixed in code and pinned by `test_runner_verilator.py::test_glbl_mode`. If the fallback is chosen, pass `+define+XUT_GLBL_INSTANCE` to **every** Verilator build (vector **and** sv): `xut_trace.svh`, which every sv testbench includes, then instantiates `glbl`, so `flop_gsr_tb.svh`'s `glbl.GSR_int` writes keep working (review #12). cocotb tops already instantiate `glbl`. A test runs the TOYFF sv fixture on Verilator with that define set.

- [ ] **Step 2: Write the tests** (marker `container`):
  - The TOYFF vector test passes on `verilator` (use a TOYFF model source containing only the toy model; the manifest marks it `unchanged`).
  - `result.json` has `seeds.x` with two distinct values and `x_dependence: false`.
  - A toy DUT whose output is an uninitialised reg (never written) gives `x_dependence: true` when the two seeds randomise it differently. Its expected trace masks that bit with `-`, so the status is still `pass`.
  - When the manifest says the primitive is `unsupported`, the result is `error` and the reason starts `verilatorize cannot transform`.
  - When the manifest says `equiv: fail`, the result is `error` and the reason starts `transform-bug:`.
  - `xut run --runner verilator` also produces `build/rtl/iverilog-vz/<model-source>/<id>/result.json`.
  - The TOYFF cocotb fixture (Task 11) passes on `verilator`, with two X-seed runs recorded in `seeds.x`; its `iverilog-vz` companion also passes. cocotb tops instantiate `glbl` themselves, so the Step 1 multi-top decision does not affect them.

- [ ] **Step 3: Implement `runners/verilator.py`**

Per config:

1. `ensure_model(ctx.model_source, case.prim, attrs)`, where `attrs` is the configuration's attributes (the `.xvec` `attr.*` header, or the sv/cocotb `configs` entry):
   - status `unsupported` → `error "verilatorize cannot transform <PRIM>: <reason>"`;
   - status `transformed` with `equiv[config_key(attrs)] != "pass"` → `error "transform-bug: Icarus equivalence <status> for <PRIM> <config> blocks Verilator results (spec §6.2)"`.
2. Prepare exactly as iverilog does (`prepare_vector`).
3. Build once:

```
verilator --binary --timing -j 2 --timescale 1ps/1ps -Wno-fatal -Wno-lint -Wno-style -Wno-MULTITOP
  --x-assign unique --x-initial unique -Mdir obj -o simx -I. -Idut
  -y <vz_dir> -y <ms>/unisims [-y <ms>/retarget] +libext+.v [+define+K=V ...]
  xut_vector_tb.sv dut/xut_dut.v <ms>/glbl.v
```

4. For each seed `s` in `x_seeds(stimulus_seed)`, in `xseed-<s>/`:
   - copy `stim.memh`;
   - run `../obj/simx +verilator+seed+<s> +verilator+rand+reset+2`;
   - read `raw.txt` into a trace.
5. The config's `trace.xtr` is the first seed's trace, compared against `expected.xtr` with `x_observable=False`.
6. `diff` of the two seeds' traces → `xdep.json` `{"x_dependence": bool, "mismatches": [...]}`.
7. `finish()` sets `res.x_dependence = any(...)` and `res.seeds["x"] = list(x_seeds(...))`.

For the cocotb style, run `cocotb_run.py --sim verilator` (Task 11) once per X seed with the same `ensure_model` gate, and compare the two traces for `x_dependence` exactly as for vectors.

For the sv style, the same applies with `-G<NAME>=<value>` for the configuration's attributes and the top taken from the file stem.

Build and run timeouts come from `case.timeout_s` (default 600 s). Verilator builds are slow, so recommend `--jobs 40` or more for full runs (spec machine: 88 CPUs).

In `iverilog.py`, `IverilogVzRunner` overrides `lib_first(case, cfg, ctx)`: it calls `ensure_model(ctx.model_source, case.prim, attrs)` and **returns** `(vz_dir(ctx.model_source),)`. The value is used as a local in `run_config` and never stored on `self`, because runner jobs are threads. If the primitive's entry is `unsupported`, `IverilogVzRunner.run_config` returns `skip` "model not transformed: <reason>" before compiling.

- [ ] **Step 4: Run the tests. Commit** with `runners: add verilator runner with paired X-seed runs and iverilog-vz companion`.

---

### Task 16: Portability smoke run, `status/PORTABILITY.md`, and lint rules

**Files:**
- Create: `tools/xut/portability.py`, `tools/tests/test_portability.py`
- Modify: `tools/xut/cli.py`, `tools/xut/lint.py`, `tools/tests/test_lint.py`, `tools/xut/status.py` (`generate` also includes PORTABILITY.md when `build/portability/*.json` exists)

**Interfaces:**
- Produces:
  - `xut.portability.Row` (`model, iverilog, verilator, verilatorize, equiv, triggers, enablers, reason`)
  - `smoke_top(mod: HdlModule) -> str`
  - `classify(log_text) -> str`, which returns a category: `udp`, `tri0-tri1`, `real`, `secureip`, `strength`, `deassign`, `timeout` or `other`
  - `run_smoke(ms, *, jobs, models=None) -> list[Row]`, which writes `build/portability/<ms>.json`
  - `render(rows_by_source: dict[str, list[Row]], meta) -> str`
  - `parse(md: str) -> dict[str, dict[str, Row]]`, the inverse of `render`, used by lint
  - CLI `xut portability [--model-source S]... [--jobs N] [--models GLOB] [--write] [--force]`
  - `xut.lint.check_portability(root) -> list[LintIssue]`

**Smoke top** (per model, inputs tied low; spec §6.2 "compile and elaborate"; a short run catches runtime `$finish`):

```verilog
// SPDX-License-Identifier: Apache-2.0
// GENERATED by xut portability
`timescale 1ps / 1ps
module xut_smoke;
  reg  [W-1:0] i_<P> = 0;          // one per input port
  wire [W-1:0] o_<P>;              // one per output port
  wire [W-1:0] io_<P>;             // one per inout port (undriven)
  <MODEL> dut (.<P>(i_<P>), ...);
  initial begin #200000; $display("XUT_SMOKE_OK"); $finish; end
endmodule
```

**Execution.**
- **Configurations** (review #3): each model is elaborated under its default parameters, under every `generate_configs` entry (Task 12), and with each `IS_*_INVERTED` parameter flipped one at a time. A model's row is `yes` only if every configuration compiles and runs; otherwise the reason names the first failing configuration. The smoke top passes the overrides as `#(.NAME(value))`.
- Generate `build/portability/<ms>/<MODEL>/<config_key>/{smoke.v, iverilog.sh, verilator.sh}` for every model and configuration: `unisims/*.v`, plus the `retarget/*.v` files named by catalog entries whose `model.library` is `retarget`.
- Generate one `driver.sh`: `ls */iverilog.sh */verilator.sh | xargs -P "$JOBS" -n 1 bash`. Each script writes `<tool>.log` and `<tool>.rc`, then appends its name to `done.txt`.
- Run `driver.sh` in **one** container. Meanwhile Python polls `done.txt` every 10 s and prints `progress: done=N total=M elapsed_s=E`.
- The Verilator script uses the transformed copy when the manifest says `transformed`. It builds with the Task 15 flags and runs `./obj/simx`.
- A model marked `unsupported` by verilatorize gets `verilator = "no: verilatorize: <reason>"` without building.

**Table** (one section per model source):

```
# UNISIM portability

Generated by `xut portability` on <UTC time> at <git HEAD>. Container xut-sim:1 <digest>.

## unisim-2025.2

| simulator | yes | no |
|---|---|---|
| iverilog | 471 | 39 |
| verilator | … | … |

| Model | iverilog | verilator | verilatorize | equiv | triggers | enablers | reason |
|---|---|---|---|---|---|---|---|
| FDRE | yes | yes | transformed | pass | glbl.GSR | — | |
| XADC | yes | no | unchanged | — | — | — | verilator: real: … |
```

(The counts above are illustrative; the real run supplies them.)

**Lint rules** (added to `xut lint`):
- `portability-agreement` (error):
  - a test declares `iverilog: yes` or `verilator: yes` for P while the row for P (in any section) says `no`;
  - the message quotes the table's reason and tells the author to declare `runners.<runner>: "unsupported"` with the reason in `unsupported_reasons.<runner>`.
- `verilatorize-equiv` (error):
  - a row with `verilatorize = transformed` and `equiv` of `—` (missing), whatever the tests say ("`xut lint` fails if a transformed model has no equivalence stimulus", spec §6.2);
  - a row with `equiv` of `fail` or `error` while any test of that primitive declares `verilator: yes`.
- A missing `status/PORTABILITY.md` gives one **warning**, `portability table not generated yet (run on main: uv run xut portability --write)`.

`--write` writes `status/PORTABILITY.md`. It refuses unless the branch is `main` or `--force` is given, using `status.current_branch()` (step 1). Without `--write`, it renders to `build/portability/PORTABILITY.md`.

- [ ] **Step 1: Write the tests.**
  - `smoke_top` for a toy HdlModule with an input bus, an output and an inout.
  - `classify` on canned log snippets (a UDP error, a `tri1`, `real`, `secureip` or encrypted file, and an unknown error).
  - `render`/`parse` round trip.
  - Lint:
    - a test declaring `verilator: yes` for a row with `verilator: no` gives an error;
    - a transformed row with `equiv —` gives an error;
    - a transformed row with `equiv pass` is OK;
    - no table gives a warning with exit 0.
  - A container test runs `run_smoke` on the Task 12 fixture model source, and the table has one row per fixture.

- [ ] **Step 2: Implement. Run the tests.**

- [ ] **Step 3: Full smoke run on both model sources.** This is a long run. The estimate is about 510 models × (about 2 s iverilog + about 40 s verilator) ÷ 80 parallel jobs ≈ 5 min for the typical models. A few large models (GTX/GTH, PCIe, MMCM) may take several minutes each, so budget 10–30 min per model source. That is under 4 h, so **report at least every 5 minutes**, with the remaining time and the finish clock-time. Start it in the background:

```bash
uv run xut portability --model-source unisim-2025.2 --model-source unisim-gh-2020.1 --jobs 80 > .cache/portability.log 2>&1
```

- Watch it with a Monitor that reads `.cache/portability.log` for the latest `progress: done=N total=M elapsed_s=E` line. Compute the rate as `N / E` and extrapolate the remaining time as `(M − N) / rate`, and report every 5 minutes.
- If the first ETA exceeds 30 min, keep the 5-minute cadence. If it drops below 10 min, tighten to 60 s.

Expected at the end:
- `build/portability/unisim-2025.2.json` and `build/portability/unisim-gh-2020.1.json` exist;
- `build/portability/PORTABILITY.md` exists;
- FDRE, FDSE, FDCE and FDPE are `yes` / `yes` / `transformed` / `pass` in both sections.

Inspect the `no` rows. They must carry reasons in the spec's categories (STARTUPE2 strength-resolved GSR, UDPs, `tri0/tri1`, `real`, secureip), or `other` with the first error line.

- [ ] **Step 4: Commit and PR C**

```bash
git add tools && git commit -m "infra: add portability smoke run, PORTABILITY.md renderer and lint agreement rules" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
uv run pytest -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
```

Write `log/<ts>-infra-verilatorize-portability.md`, recording the transform and equivalence counts, the smoke-run summary table and every `unsupported` or `fail` model. Commit it, push (`git push -u origin infra/verilatorize`), and open **PR C** with `gh pr create --base infra/sim-runners --title "infra: verilatorize, verilator runner, portability table"`, whose body ends with the Claude Code line. **Do not** commit `status/PORTABILITY.md`: the orchestrator generates it on `main` after the merge, with `uv run xut portability --write`, and commits it as `status: regenerate`.

---

### Task 17: `xut crosscheck` and finding classes

**Files:**
- Create: `tools/xut/crosscheck.py`, `tools/tests/test_crosscheck.py`
- Modify: `tools/xut/cli.py`

**Create the worktree** (stacked on `infra/sim-runners`, PR base `infra/sim-runners` until PR B merges; it needs no verilatorize code, because `iverilog-vz` results are just another runner directory):

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git worktree add ../xilinx-unittests-worktrees/infra-crosscheck -b infra/crosscheck infra/sim-runners
cd ../xilinx-unittests-worktrees/infra-crosscheck && mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1
```

**Interfaces:**
- Consumes: `Trace`, `compare`, `diff` (Task 3); `discover`/`select` (Task 8); `result.json` (Task 8)
- Produces:
  - `xut.crosscheck.FINDING_CLASSES`, the spec §8 table in order
  - `X_OBSERVABLE: dict[str, bool]` (`python xsim iverilog iverilog-vz` → True; `verilator hw` → False)
  - `View` (`flow, runner, status, model_source, trace: Trace | None, result: dict`)
  - `Finding` (frozen: `cls, test_id, flow, model_source, runners: tuple, points: tuple[str, ...], expected: bool`, with property `slug`)
  - `gather(root, test_id) -> dict[str, dict[tuple[str, str], View]]`: per model source (the `<model-source>` path component), the views keyed `(flow, runner)`; `classify` runs once per model source, so traces are only ever compared like-for-like. The golden (`python`) expectation is taken from the same model-source directory; it is model-independent, so either copy serves.
  - `classify(test_id, views, expected_divergence=()) -> list[Finding]`
  - `matrix(views) -> str` (markdown)
  - `write_finding(root, prim, f) -> Path | None`, which never overwrites
  - CLI `xut crosscheck SELECT... [--write-findings]`. It writes `build/crosscheck/<test-id>.json`, prints the matrix and findings, and exits 1 if any finding is not covered by `expected_divergence`.
  - **`expected_divergence` never masks** (controller ruling on review (b) #4, spec §8 rev 3.1). Expected bits stay defined, and every disagreement is still computed and reported. A finding matched by an `expected_divergence` entry is reported with class **`known-divergence`** plus `of: <original class>` and `finding: <finding id>` (the file stem). It is listed in the crosscheck output, recorded in the status file's `findings`, and so appears in PROGRESS.md/TODO.md. Only unlisted findings make the exit code 1.

**Classification rules.** Each is pinned by a test with synthetic `View`s. Traces are compared only within one model source.

| Class | Rule |
|---|---|
| `sim-divergence` | For each model source, `diff` every pair of `xsim`, `iverilog` and `verilator` traces (x-aware). Any point → one finding listing the pairs and points. |
| `doc-vs-model` | A point where the expected trace (`python`) disagrees with **every** available UNISIM simulator of that source, those simulators agree among themselves, and the expected bit's provenance is `doc:`. |
| `doc-gap` | The same, but the provenance is `inferred:`. |
| `x-dependence` | The verilator `result.json` has `x_dependence: true`. |
| `transform-bug` | `diff(iverilog, iverilog-vz)` for the same model source is non-empty. |
| `flow-mismatch` | For a flow ≠ `rtl` and a simulator runner, the trace differs from the same runner's `rtl` trace. |
| `silicon-mismatch` | The `hw` trace disagrees with the `rtl/python` expectation (compared with `x_observable=False`). |
| `nondeterminism` | The `hw` `result.json` has `hw.repeats_differ: true`. |
| `harness-error` | The `hw` `result.json` has `hw.selftest == "fail"`. |

The last four have no producer until steps 3–4. They are implemented now against synthetic results, so those steps only add runners. A point that is already part of a `sim-divergence` is not also reported as `doc-vs-model` or `doc-gap`.

`Finding.slug` = `f"{cls}-{test_id.split('.', 2)[2].replace('.', '-')}"`. For example, `7series.FDRE.L1.gsr_init` gives the slug `doc-gap-L1-gsr_init`, so the file is `findings/FDRE-doc-gap-L1-gsr_init.md`.

The finding stub `write_finding` writes (spec §8 "Recording"):

```markdown
# FDRE: doc-gap in 7series.FDRE.L1.gsr_init

- Class: doc-gap
- Test: 7series.FDRE.L1.gsr_init
- Flow / model source: rtl / unisim-2025.2
- Runners: iverilog, verilator, xsim
- First seen: 2026-09-26 at <git HEAD>
- Status: open

## Evidence

- cfg-init0/S3 Q[0]: expected 0, got 1 (inferred:GSR_is_described_as_an_active-state_override...)

## Analysis

Not yet analysed. Explain the divergence against the cited UG953 page, then either
correct the golden model (with its provenance) or add an `expected_divergence`
entry to test.yaml pointing here. Never weaken the test (spec §8).
```

- [ ] **Step 1: Write the tests.** Include one per class using synthetic views, and these cases:
  - agreement → no findings;
  - two model sources are never cross-compared;
  - an `expected_divergence` entry turns the finding into `known-divergence` (with `of` and `finding` set), it is still printed and written to `build/crosscheck/<test-id>.json`, and the CLI exits 0;
  - the expected trace is unchanged by `expected_divergence` (no bit becomes `-`);
  - `write_finding` twice → the second call returns `None` and the file is unchanged.

- [ ] **Step 2: Implement `tools/xut/crosscheck.py`** (core shown; `gather`, `matrix` and the CLI are straightforward reads and formatting):

```python
# SPDX-License-Identifier: Apache-2.0
"""Cross-check every trace of a test and classify disagreements (spec §8)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from xut.formats.xtr import Trace, compare, diff

FINDING_CLASSES = ("doc-vs-model", "doc-gap", "sim-divergence", "x-dependence", "transform-bug",
                   "flow-mismatch", "silicon-mismatch", "nondeterminism", "harness-error",
                   "known-divergence")
SIMS = ("xsim", "iverilog", "verilator")
X_OBSERVABLE = {"python": True, "xsim": True, "iverilog": True, "iverilog-vz": True,
                "verilator": False, "hw": False}


@dataclass
class View:
    flow: str
    runner: str
    status: str
    model_source: str | None
    trace: Trace | None
    result: dict


@dataclass(frozen=True)
class Finding:
    cls: str
    test_id: str
    flow: str
    model_source: str | None
    runners: tuple[str, ...]
    points: tuple[str, ...]
    expected: bool = False
    known_of: str | None = None  # original class when reported as known-divergence
    finding: str | None = None  # finding id (file stem) from expected_divergence

    @property
    def slug(self) -> str:
        return f"{self.cls}-{self.test_id.split('.', 2)[2].replace('.', '-')}"


def _f(cls, test_id, flow, ms, runners, points) -> Finding:
    return Finding(cls, test_id, flow, ms, tuple(sorted(runners)), tuple(points[:200]))


def classify(test_id: str, views: dict[tuple[str, str], View],
             expected_divergence: tuple[dict, ...] = ()) -> list[Finding]:
    out: list[Finding] = []
    exp = views.get(("rtl", "python"))
    sims: dict[str, dict[str, View]] = defaultdict(dict)
    for (flow, runner), v in views.items():
        if flow == "rtl" and runner in SIMS and v.trace is not None:
            sims[v.model_source][runner] = v
    for ms, group in sims.items():
        diverged, points = set(), []
        for a, b in combinations(sorted(group), 2):
            for m in diff(group[a].trace, group[b].trace, a_x=X_OBSERVABLE[a], b_x=X_OBSERVABLE[b]):
                diverged.add((m.label, m.port, m.bit))
                points.append(f"{a} vs {b}: {m}")
        if points:
            out.append(_f("sim-divergence", test_id, "rtl", ms, group, points))
        if exp is None or exp.trace is None:
            continue
        per_point: dict[tuple, dict[str, object]] = defaultdict(dict)
        for r, v in group.items():
            for m in compare(exp.trace, v.trace, x_observable=X_OBSERVABLE[r]):
                per_point[(m.label, m.port, m.bit)][r] = m
        doc, gap = [], []
        for pt, by_runner in sorted(per_point.items()):
            if pt in diverged or set(by_runner) != set(group):
                continue
            m = next(iter(by_runner.values()))
            (doc if (m.prov or "").startswith("doc:") else gap).append(str(m))
        if doc:
            out.append(_f("doc-vs-model", test_id, "rtl", ms, group, doc))
        if gap:
            out.append(_f("doc-gap", test_id, "rtl", ms, group, gap))
    vl = views.get(("rtl", "verilator"))
    if vl is not None and vl.result.get("x_dependence"):
        out.append(_f("x-dependence", test_id, "rtl", vl.model_source, ["verilator"],
                      [f"X seeds {vl.result.get('seeds', {}).get('x')} disagree"]))
    iv, vz = views.get(("rtl", "iverilog")), views.get(("rtl", "iverilog-vz"))
    if iv and vz and iv.trace and vz.trace and iv.model_source == vz.model_source:
        pts = [str(m) for m in diff(iv.trace, vz.trace)]
        if pts:
            out.append(_f("transform-bug", test_id, "rtl", iv.model_source,
                          ["iverilog", "iverilog-vz"], pts))
    for (flow, runner), v in views.items():
        if flow != "rtl" and runner in SIMS and v.trace is not None:
            ref = views.get(("rtl", runner))
            if ref and ref.trace and ref.model_source == v.model_source:
                pts = [str(m) for m in diff(ref.trace, v.trace, a_x=X_OBSERVABLE[runner],
                                            b_x=X_OBSERVABLE[runner])]
                if pts:
                    out.append(_f("flow-mismatch", test_id, flow, v.model_source, [runner], pts))
        if runner == "hw":
            hw = v.result.get("hw") or {}
            if hw.get("selftest") == "fail":
                out.append(_f("harness-error", test_id, flow, None, ["hw"], ["self-test failed"]))
                continue
            if hw.get("repeats_differ"):
                out.append(_f("nondeterminism", test_id, flow, None, ["hw"],
                              [f"{hw.get('repeats')} runs disagree"]))
            if exp and exp.trace and v.trace:
                pts = [str(m) for m in compare(exp.trace, v.trace, x_observable=False)]
                if pts:
                    out.append(_f("silicon-mismatch", test_id, flow, None, ["hw"], pts))
    return [_mark(f, expected_divergence) for f in out]


def _mark(f: Finding, expected: tuple[dict, ...]) -> Finding:
    """A listed divergence is still reported, as known-divergence (never masked)."""
    for e in expected:
        if e.get("cls") == f.cls and set(e.get("runners", f.runners)) >= set(f.runners):
            fid = Path(e["finding"]).stem
            return Finding("known-divergence", f.test_id, f.flow, f.model_source, f.runners,
                           f.points, True, f.cls, fid)
    return f
```

- [ ] **Step 3: Run the tests. Commit** with `infra: add xut crosscheck with spec §8 finding classes and finding stubs`.

---

### Task 18: `xut status record`, bins-accounted lint, shared unit test paths, pytest over `tests/`

**Files:**
- Modify: `tools/xut/status.py`, `tools/xut/schemas/status.schema.json`, `tools/xut/cli.py`, `tools/xut/workunits.py`, `tools/xut/testspec.py`, `tools/xut/lint.py`, `pyproject.toml`, `AGENTS.md`, `docs/templates/test.yaml`, `.github/workflows/ci.yml`
- Create: `tools/tests/test_status_record.py`
- Modify tests: `tools/tests/test_workunits.py`, `tools/tests/test_lint.py`

**Interfaces:**
- Consumes: `load_status`, `coverage_bins`, `RESULT_VALUES` (step 1); `discover` (Task 8); `result.json` (Task 8); `load_entry`
- Produces:
  - `xut.status.record(root, prim, family="7series", model_source="unisim-2025.2") -> dict`, which writes and returns the new status
  - CLI `xut status record PRIM... | --unit NAME [--model-source NAME]`, default `unisim-2025.2`
  - **Model source in status** (review (b) round 2, N2). The step-1 key pattern `<level>/<runner>/<flow>` is kept. The reference source (`unisim-2025.2`) fills `results` as before. Any other source fills `results_by_model_source.<source>` with the same key shape, and `measured.model_sources` lists every source recorded. Recording one source never touches another's results, so both coexist. Task 18 amends `tools/xut/schemas/status.schema.json` (new optional `results_by_model_source` object, whose values use the `results` schema, and `measured.model_sources`), and `render_progress` shows the reference source's marks with a `+gh` suffix when the submodule source disagrees in pass/fail for the same cell.
  - `owned_paths(unit)` also returns `tests/<family>/<group>/_shared/<unit>/**`
  - `TestCase.shared_dirs` = `[root/tests/<family>/<group>/_shared/<work_unit>]` when that directory exists
  - `xut.lint.check_bins_accounted(root) -> list[LintIssue]`
  - `xut.lint.check_gaps_present(root) -> list[LintIssue]`: rule `gaps-present` (error) for any test whose `gaps` is missing or empty. Every test must say what it misses (spec §1.6, controller ruling on review (b) #3).

`record` rules (spec §9, §11):

- **`results`.** The key is `<level>/<runner>/<flow>` for runners `python`, `xsim`, `iverilog`, `verilator` and `hw`. `iverilog-vz` is not recorded: it feeds `transform-bug` findings only.
  - The value is the worst status over that primitive's tests at that level, with the precedence `fail > error > pass > not-run > unsupported > n/a > skip`.
  - **Flows.** Keys are written for every flow a test declares, not only the flows that ran: a declared but unrun flow (`vivado`, `yosys`, `openxc7`, `vpr` in step 2) gets `not-run`, so TODO.md shows the step-4 cells. The `hw` runner never runs the `rtl` flow, so its keys use the declared non-`rtl` flows (`L1/hw/vivado`, …), never `…/hw/rtl`.
  - A runner declared `"unsupported"` gives `unsupported`, and one declared `"no"` gives `n/a` (both are step-1 `RESULT_VALUES`).
  - A skip because the runner is unavailable gives `not-run`.
  - A declared runner with no result gives `not-run`.
- **`measured.tree_hash`** covers everything the primitive's results depend on in the repository (review (b) #2):
  - `tests/<family>/<group>/<PRIM>` (its tests);
  - `tests/<family>/<group>/_shared/<unit>/**` (shared recipes, sv bodies, cocotb session, metadata generator);
  - `models/xut_models/<family>/<prim>.py` and `models/xut_models/<family>/_common/<unit>.py` (the golden model);
  - `catalog/<family>/<PRIM>.overrides.yaml` (the claims).

  It is `sha256` over the sorted lines `"<path> <git rev-parse HEAD:<path>>"` for those paths that exist, stored as `"sha256:<hex>"` (one string, as the status schema allows). `record` refuses (with a `ClickException` naming the files) when `git status --porcelain -- <all of those paths>` is not empty, because a hash of uncommitted inputs would be a lie.
- **`measured.tools`** is the union of the `tools` of the recorded results, plus `container` (digest) and `model_source`.
- **`coverage.covered`** is:
  - (the declared `exercises` of vector tests) ∩ (the python runner's `bins_reached`) — the golden model confirms reach, spec §9;
  - ∪ the declared `exercises` of sv and cocotb tests that passed on at least one simulator runner.
  - `uncovered` = `coverage_bins(entry)` − `covered`.
- **`findings`** lists the **file stems** (e.g. `FDRE-doc-gap-L1-gsr_init`, as the step-1 schema describes), not paths, of `findings/<PRIM>-*.md` whose `Status:` line is `open`. Known divergences stay listed while their finding is open.
- **Declared but not reached.** An exercised bin that the python runner did not reach produces a warning from `record`, naming the test and the bin. It is also left in `uncovered`.

`check_bins_accounted` (spec §12 "every bin is covered or listed as a gap"): for each `test.yaml`, every bin in `coverage_bins(entry)` must appear in some test's `exercises`, or at the start of some `gaps` string (`"claim:FDRE.C8 — ..."`). Otherwise it is an error with rule `bins-accounted`.

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tools/tests", "tests"]
norecursedirs = [".*", "build", "sv", "cocotb", "vectors"]
```

Model and generator unit tests that a work unit owns live beside its tests, named uniquely (`tests/7series/register/FDRE/test_fdre_model.py`) to avoid pytest module-name clashes. cocotb modules are named `cocotb_*.py`, so pytest never collects them.

In AGENTS.md, add a line under "Only touch owned paths": shared test code for a unit lives in `tests/<family>/<group>/_shared/<unit>/`.

- [ ] **Step 1: Write the tests.**
  - `record` on a tmp repo (`git init`, a committed fixture test dir, fabricated `build/rtl/*/<model-source>/…/result.json` files) produces the expected `results` keys and values, `tree_hash` equals `git rev-parse`, and `covered` follows the reach intersection.
  - A dirty test dir is refused, and so is a dirty `_shared/<unit>` file or `_common/<unit>.py`.
  - Committing a change to a `_shared/<unit>` file changes the primitive's `tree_hash`.
  - `record(..., model_source="unisim-gh-2020.1")` writes only `results_by_model_source["unisim-gh-2020.1"]` and leaves `results` untouched; recording `unisim-2025.2` afterwards leaves the gh results untouched; both files validate against the amended schema, and a bare `results_by_model_source` entry with a bad key fails validation.
  - `owned_paths(flops)` contains `tests/7series/register/_shared/flops/**`.
  - `check_bins_accounted` flags a missing bin and accepts one listed in `gaps`.
  - `check_gaps_present` flags a test with `gaps: []` and one with no `gaps` key.

- [ ] **Step 2: Implement. Run** `uv run pytest -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log`.

- [ ] **Step 3: Commit in pieces and open PR D**

```bash
git add tools/xut/workunits.py tools/xut/testspec.py tools/tests/test_workunits.py AGENTS.md && git commit -m "infra: let a work unit own shared test code under tests/<family>/<group>/_shared/<unit>" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tools/xut/status.py tools/xut/cli.py tools/tests/test_status_record.py && git commit -m "status: add xut status record (results, tree hash, reach-confirmed coverage)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tools/xut/lint.py tools/tests/test_lint.py pyproject.toml docs/templates/test.yaml && git commit -m "infra: lint bins-accounted and gaps-present; collect unit-owned pytest files under tests/" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

**CI on the open-source model source** (review (b) #5). Add to the `sim` job in `.github/workflows/ci.yml`:

```yaml
      - run: uv run xut run 'unit:flops' --level L0 --level L1 --style vector --runner python --runner iverilog --model-source unisim-gh-2020.1 --jobs 4
      - run: uv run xut crosscheck 'unit:flops' --model-source unisim-gh-2020.1
```

Until the flops unit merges, `xut run` selects nothing and exits 0 with `no tests selected`; the step becomes live with PR E. Commit it with `infra: CI runs flops L0/L1 vector tests on iverilog against the UNISIM submodule`. `xut crosscheck` gains `--model-source` to restrict the report to one source.

Update `docs/templates/test.yaml` with the Task 8 keys (`source`, `configs`, `expected_divergence`, `timeout_s`, `sv_deviations`). Write the log entry, push (`git push -u origin infra/crosscheck`), and open **PR D** with `gh pr create --base infra/sim-runners --title "infra: crosscheck, status record, shared unit test paths"`. Merge order: A, B, then C and D (either order; the second one resolves the Task 16/18 rebase conflict). After each merge the orchestrator regenerates status on `main` (`uv run xut status generate`, and after C also `uv run xut portability --write`) and commits `status: regenerate`.

---

## Pilot: the `flops` work unit (branch `unit/7series/flops`)

Start only after PRs A–D are merged (branch from `origin/main`). The whole unit (Tasks 19–27) is **one** PR, opened in Task 27; each task is still reviewed before the next starts. This branch touches **only** these paths, which `xut lint --branch` enforces:

- `catalog/7series/FD{R,S,C,P}E.overrides.yaml`;
- `models/xut_models/7series/_common/flops.py` and `models/xut_models/7series/fd{r,s,c,p}e.py`;
- `tests/7series/register/{FDRE,FDSE,FDCE,FDPE}/**` and `tests/7series/register/_shared/flops/**`;
- `status/7series/FD{R,S,C,P}E.yaml`;
- `findings/FD{R,S,C,P}E-*.md`;
- `log/*-unit-7series-flops-*.md`.

If an infra change is needed, record it as a TODO in the log entry, or stack on a new `infra/*` branch. Never edit `tools/` from here.

**Clean room.** Tasks 20, 25 and 26 are written from `.cache/docs/ug953-2026.1.txt` (FDCE pp. 369–370, FDPE pp. 372–373, FDRE pp. 375–376, FDSE pp. 378–379) and nothing else. Do not open `FD*.v` from either model source. When analysing a finding, use UG953 and the observed traces, never the UNISIM text.

### Task 19: Catalog overrides and behavioural claims for the four flops

**Files:**
- Create: `catalog/7series/FDRE.overrides.yaml`, `FDSE.overrides.yaml`, `FDCE.overrides.yaml`, `FDPE.overrides.yaml`

**Interfaces:**
- Consumes: `load_entry` (step 1), which applies and validates overrides; `coverage_bins` (step 1)
- Produces: claim ids `<PRIM>.C1` … `<PRIM>.C8`, with the same meaning for all four primitives:

| Claim | Meaning (paraphrase) | FDRE | FDSE | FDCE | FDPE |
|---|---|---|---|---|---|
| C1 | CE High, control inactive: Q takes D at the active clock edge | doc:375 | doc:378 | doc:369 | doc:372 |
| C2 | CE Low: clock edges are ignored | doc:375 | doc:378 | doc:369 | doc:372 |
| C3 | Active control overrides all other inputs (sync: at the next active edge; async: at once) | doc:375 | doc:378 | doc:369 | doc:372 |
| C4 | GSR active (power-up or asserted): Q takes INIT | doc:375 | doc:378 | doc:369 | doc:372 |
| C5 | IS_C_INVERTED=1: negative-edge register | doc:376 | doc:379 | doc:370 | doc:373 |
| C6 | IS_<ctrl>_INVERTED=1: control active-Low | doc:376 | doc:379 | doc:370 | doc:373 |
| C7 | IS_D_INVERTED=1: D is inverted | doc:376 | doc:379 | doc:370 | doc:373 |
| C8 | IS_D_INVERTED must be 0 unless the flop is an I/O register | doc:376 | doc:379 | doc:370 | doc:373 |

- [ ] **Step 1: Create the worktree**

```bash
cd /home/tim/github/f4pga/xilinx-unittests && git fetch origin
git worktree add ../xilinx-unittests-worktrees/unit-7series-flops -b unit/7series/flops origin/main
cd ../xilinx-unittests-worktrees/unit-7series-flops && mkdir -p .cache && uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1
git config core.hooksPath tools/hooks
uv run xut fetch-docs > .cache/fetch.log 2>&1; cat .cache/fetch.log
```

- [ ] **Step 2: Write `catalog/7series/FDRE.overrides.yaml`**

```yaml
# SPDX-License-Identifier: Apache-2.0
# flops work unit: corrections and claims layered over the generated FDRE.yaml.
attributes:
  # UG953 p376 gives the range "1'b0 to 1'b1"; these are 1-bit binaries.
  IS_C_INVERTED: {allowed: ["1'b0", "1'b1"]}
  IS_D_INVERTED: {allowed: ["1'b0", "1'b1"]}
  IS_R_INVERTED: {allowed: ["1'b0", "1'b1"]}
claims:
  - {id: FDRE.C1, page: 375, provenance: "doc:375", text: "With CE High and R inactive, Q takes D at the active clock edge."}
  - {id: FDRE.C2, page: 375, provenance: "doc:375", text: "With CE Low, clock edges are ignored and Q holds."}
  - {id: FDRE.C3, page: 375, provenance: "doc:375", text: "Active R overrides all other inputs, CE Low included; Q goes Low at the next active clock edge."}
  - {id: FDRE.C4, page: 375, provenance: "doc:375", text: "While GSR is active (power-up or asserted) Q takes the INIT value."}
  - {id: FDRE.C5, page: 376, provenance: "doc:376", text: "IS_C_INVERTED=1 makes the register negative-edge triggered."}
  - {id: FDRE.C6, page: 376, provenance: "doc:376", text: "IS_R_INVERTED=1 makes R active-Low."}
  - {id: FDRE.C7, page: 376, provenance: "doc:376", text: "IS_D_INVERTED=1 inverts the D input."}
  - {id: FDRE.C8, page: 376, provenance: "doc:376", text: "IS_D_INVERTED must stay 0 unless the flop is used as an I/O register."}
```

- [ ] **Step 3: Write the other three the same way**, with these exact differences:
  - **`FDSE.overrides.yaml`:**
    - attributes `IS_C_INVERTED`, `IS_D_INVERTED`, `IS_S_INVERTED`;
    - pages 378 (C1–C4) and 379 (C5–C8);
    - C1 says "S inactive";
    - C3: "Active S overrides all other inputs, CE Low included; Q goes High at the next active clock edge.";
    - C6: "IS_S_INVERTED=1 makes S active-Low.".
  - **`FDCE.overrides.yaml`:**
    - attributes `IS_C_INVERTED`, `IS_CLR_INVERTED`, `IS_D_INVERTED`;
    - pages 369 and 370;
    - C1 says "CLR not asserted";
    - C3: "Active CLR overrides all other inputs and drives Q Low at once, without a clock edge.";
    - C6: "IS_CLR_INVERTED=1 makes CLR active-Low.".
  - **`FDPE.overrides.yaml`:**
    - attributes `IS_C_INVERTED`, `IS_D_INVERTED`, `IS_PRE_INVERTED`;
    - pages 372 and 373;
    - C1 says "PRE not asserted";
    - C3: "Active PRE overrides all other inputs and drives Q High at once, without a clock edge.";
    - C6: "IS_PRE_INVERTED=1 makes PRE active-Low.".

- [ ] **Step 4: Validate**

```bash
uv run python -c "
from xut.catalog.model import load_entry
from xut.status import coverage_bins
from xut.paths import repo_root
for p in ('FDRE','FDSE','FDCE','FDPE'):
    e = load_entry('7series', p, repo_root())
    print(p, len(e.claims), len(coverage_bins(e)), [a['allowed'] for a in e.attributes])
" > .cache/overrides.log 2>&1; cat .cache/overrides.log
```

Expected, per primitive: 8 claims; 21 bins (5 ports + 8 attribute values + 8 claims); every `allowed` list is `["1'b0", "1'b1"]` or the INIT pair.

- [ ] **Step 5: Commit** with `flops: add catalog overrides with behavioural claims C1-C8 for FDRE/FDSE/FDCE/FDPE`.

---

### Task 20: Clean-room golden model (shared SDR flop + FDRE)

**Files:**
- Create: `models/xut_models/7series/_common/flops.py`, `models/xut_models/7series/fdre.py`, `tests/7series/register/_shared/flops/flop_recipes.py` (the `KINDS` table only, extended in Task 21), `tests/7series/register/_shared/flops/test_flop_models.py`

**Interfaces:**
- Consumes: `Model`, `Out`, `ModelUnsupported`, `bit_attr` (Task 6)
- Produces:
  - `xut_models.7series._common.flops.SdrFlop` (class attributes `CTRL, CTRL_VALUE, CTRL_ASYNC, INIT_DEFAULT, PAGE, ATTR_PAGE`)
  - `xut_models.7series.fdre.MODEL = FDRE`

- [ ] **Step 1: Write the failing model tests** `tests/7series/register/_shared/flops/test_flop_models.py`

```python
# SPDX-License-Identifier: Apache-2.0
"""Claim-by-claim tests of the flops golden models (clean-room, UG953 v2026.1)."""

import pytest

from flop_recipes import KINDS
from xut_models.registry import get

PRIMS = ["FDRE"]  # FDSE added in Task 25, FDCE/FDPE in Task 26


def forced(prim):
    return 0 if KINDS[prim].ctrl in ("R", "CLR") else 1


def fresh(prim, **attrs):
    m = get("7series", prim)(attrs)
    m.power_on()
    for p in m.inputs():
        m.set_input(p, 0)
    m.glbl("GSR", 0)
    return m


def q(m):
    return m.outputs()["Q"]


def load(m, v):
    m.set_input("CE", 1)
    m.set_input("D", v)
    m.clock_edge("C", True)
    m.clock_edge("C", False)


@pytest.mark.parametrize("prim", PRIMS)
def test_c4_default_init_from_documentation(prim):
    default = 1 if prim in ("FDSE", "FDPE") else 0
    m = fresh(prim)
    assert q(m).bits == str(default) and q(m).prov.startswith("doc:")
    assert f"{prim}.C4" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
@pytest.mark.parametrize("init", [0, 1])
def test_c4_explicit_init(prim, init):
    assert q(fresh(prim, INIT=f"1'b{init}")).bits == str(init)


@pytest.mark.parametrize("prim", PRIMS)
def test_c1_capture_on_rising_edge_only(prim):
    m = fresh(prim, INIT="1'b0")
    m.set_input("CE", 1)
    m.set_input("D", 1)
    m.clock_edge("C", False)
    assert q(m).bits == "0"
    m.clock_edge("C", True)
    assert q(m).bits == "1" and f"{prim}.C1" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c2_ce_low_holds(prim):
    m = fresh(prim, INIT="1'b0")
    m.set_input("D", 1)
    m.clock_edge("C", True)
    assert q(m).bits == "0" and f"{prim}.C2" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
@pytest.mark.parametrize("ce", [0, 1])
def test_c3_control_overrides(prim, ce):
    k, f = KINDS[prim], forced(prim)
    m = fresh(prim)
    load(m, 1 - f)
    m.set_input("CE", ce)
    m.set_input("D", 1 - f)
    m.set_input(k.ctrl, 1)
    assert q(m).bits == (str(f) if k.is_async else str(1 - f))  # async: at once
    m.clock_edge("C", True)
    assert q(m).bits == str(f) and q(m).prov.startswith("doc:")
    m.set_input(k.ctrl, 0)
    assert q(m).bits == str(f)                                   # released: holds


@pytest.mark.parametrize("prim", PRIMS)
def test_c5_negative_edge(prim):
    m = fresh(prim, INIT="1'b0", IS_C_INVERTED="1'b1")
    m.set_input("CE", 1)
    m.set_input("D", 1)
    m.clock_edge("C", True)
    assert q(m).bits == "0"
    m.clock_edge("C", False)
    assert q(m).bits == "1" and f"{prim}.C5" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c6_control_active_low(prim):
    k, f = KINDS[prim], forced(prim)
    m = fresh(prim, **{f"IS_{k.ctrl}_INVERTED": "1'b1"})  # pin 0 -> active
    m.clock_edge("C", True)
    assert q(m).bits == str(f) and f"{prim}.C6" in m.claims_hit
    m.set_input(k.ctrl, 1)                                  # inactive now
    load(m, 1 - f)
    assert q(m).bits == str(1 - f)


@pytest.mark.parametrize("prim", PRIMS)
def test_c7_d_inverted(prim):
    m = fresh(prim, IS_D_INVERTED="1'b1")
    load(m, 0)
    assert q(m).bits == "1" and f"{prim}.C7" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_gsr_midrun_and_inferred_edge(prim):
    m = fresh(prim, INIT="1'b1")
    load(m, 0)
    m.glbl("GSR", 1)
    assert q(m) == q(fresh(prim, INIT="1'b1"))           # INIT, doc
    m.set_input("CE", 1)
    m.set_input("D", 0)
    m.clock_edge("C", True)
    assert q(m).bits == "1" and q(m).prov.startswith("inferred:")
    m.glbl("GSR", 0)
    load(m, 0)
    assert q(m).bits == "0"


@pytest.mark.parametrize("prim", [p for p in PRIMS if KINDS[p].is_async])
def test_gsr_versus_async_control_is_undefined(prim):
    k, f = KINDS[prim], forced(prim)
    same = fresh(prim, INIT=f"1'b{f}")
    same.glbl("GSR", 1)
    same.set_input(k.ctrl, 1)
    assert q(same).bits == str(f) and q(same).prov.startswith("doc:")  # both rules agree
    m = fresh(prim, INIT=f"1'b{1 - f}")
    m.glbl("GSR", 1)
    m.set_input(k.ctrl, 1)
    assert q(m).bits == "-" and q(m).prov.startswith("inferred:")
    m.glbl("GSR", 0)                                        # control still active: it wins
    assert q(m).bits == str(forced(prim)) and q(m).prov.startswith("doc:")


@pytest.mark.parametrize("prim", PRIMS)
def test_gts_is_not_modelled(prim):
    from xut_models.base import ModelUnsupported

    with pytest.raises(ModelUnsupported):
        fresh(prim).glbl("GTS", 1)
```

`flop_recipes.py` starts with the `FlopKind` dataclass and the `KINDS` table from Task 21, Step 1, so these tests can import it now.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tests/7series/register/_shared/flops -v > .cache/pytest.log 2>&1; tail -n 15 .cache/pytest.log`

Expected: FAIL (`LookupError: no golden model for 7series/FDRE`).

- [ ] **Step 3: Implement `models/xut_models/7series/_common/flops.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Clean-room golden model of the 7-series SDR flip-flops FDRE, FDSE, FDCE, FDPE.

Written from UG953 v2026.1 only (FDCE pp. 369-370, FDPE pp. 372-373,
FDRE pp. 375-376, FDSE pp. 378-379); no UNISIM source was consulted.
Claim numbers match catalog/7series/<PRIM>.overrides.yaml:

  C1 capture   CE High, control inactive: Q <- D at the active clock edge
  C2 ce_hold   CE Low: clock edges are ignored
  C3 control   an active control overrides all other inputs
               (R/S at the next active edge; CLR/PRE at once)
  C4 gsr_init  GSR active: Q = INIT
  C5 inv_c     IS_C_INVERTED=1: the falling edge is the active edge
  C6 inv_ctrl  IS_<ctrl>_INVERTED=1: the control is active-Low
  C7 inv_d     IS_D_INVERTED=1: D is inverted
Behaviour UG953 does not state is tagged ``inferred:`` or reported as ``-``.
"""

from __future__ import annotations

from typing import ClassVar

from xut_models.base import Model, ModelUnsupported, Out, bit_attr

_CLAIM = {"capture": 1, "ce_hold": 2, "control": 3, "gsr_init": 4, "inv_c": 5,
          "inv_ctrl": 6, "inv_d": 7}
_GSR_EDGE = ("inferred:UG953 describes GSR as holding INIT while active, so clock "
             "edges during GSR are taken to be ignored")
_GSR_VS_CTRL = "inferred:UG953 does not say whether GSR or an active CLR/PRE wins"


class SdrFlop(Model):
    CTRL: ClassVar[str]  # R | S | CLR | PRE
    CTRL_VALUE: ClassVar[int]  # the value the control drives onto Q
    CTRL_ASYNC: ClassVar[bool]
    INIT_DEFAULT: ClassVar[int]  # from the UG953 attribute table
    PAGE: ClassVar[int]  # Introduction / Logic Table page
    ATTR_PAGE: ClassVar[int]  # Available Attributes page
    CLOCKS = ("C",)
    OUTPUTS = {"Q": 1}

    @classmethod
    def inputs(cls) -> dict[str, int]:
        return {"C": 1, "CE": 1, "D": 1, cls.CTRL: 1}

    def __init__(self, attrs):
        super().__init__(attrs)
        a = self.attrs
        self.init = bit_attr(a.get("INIT", self.INIT_DEFAULT))
        self.inv_c = bit_attr(a.get("IS_C_INVERTED", 0))
        self.inv_d = bit_attr(a.get("IS_D_INVERTED", 0))
        self.inv_ctrl = bit_attr(a.get(f"IS_{self.CTRL}_INVERTED", 0))
        self.pin = dict.fromkeys(self.inputs(), 0)
        self.gsr = 0
        self.q = Out("-", "inferred:state before power-on is not described")

    # -- helpers ------------------------------------------------------------------
    def _hit(self, role: str) -> None:
        self.hit(f"{self.PRIM}.C{_CLAIM[role]}")

    def _doc(self, bit: int, page: int | None = None) -> Out:
        return Out(str(bit), f"doc:{page or self.PAGE}")

    def _ctrl_active(self) -> bool:
        active = bool(self.pin[self.CTRL] ^ self.inv_ctrl)
        if active and self.inv_ctrl:
            self._hit("inv_ctrl")
        return active

    def _under_gsr(self) -> Out:
        if self.CTRL_ASYNC and self._ctrl_active() and self.init != self.CTRL_VALUE:
            return Out("-", _GSR_VS_CTRL)  # the two documented behaviours disagree
        self._hit("gsr_init")  # (when they agree, both documented rules give INIT)
        return self._doc(self.init)

    def _force(self) -> None:
        self.q = self._doc(self.CTRL_VALUE)
        self._hit("control")

    # -- Model API ------------------------------------------------------------------
    def power_on(self) -> None:
        self.gsr = 1
        self.q = self._under_gsr()

    def glbl(self, signal: str, value: int) -> None:
        if signal != "GSR":
            raise ModelUnsupported(f"{self.PRIM}: UG953 describes only GSR for this primitive")
        self.gsr = value
        if value:
            self.q = self._under_gsr()
        elif self.CTRL_ASYNC and self._ctrl_active():
            self._force()

    def set_input(self, port: str, value: int) -> None:
        self.pin[port] = value
        if port != self.CTRL or not self.CTRL_ASYNC:
            return
        if self.gsr:
            self.q = self._under_gsr()
        elif self._ctrl_active():
            self._force()

    def clock_edge(self, port: str, rising: bool) -> None:
        if rising == bool(self.inv_c):
            return  # not the active edge
        if self.inv_c:
            self._hit("inv_c")
        if self.gsr:
            if self.q.bits != "-":
                self.q = Out(self.q.bits, _GSR_EDGE)
            return
        if self._ctrl_active():
            self._force()  # sync: at this edge; async: already forced, stays
            return
        if not self.pin["CE"]:
            self._hit("ce_hold")
            return
        if self.inv_d:
            self._hit("inv_d")
        self.q = self._doc(self.pin["D"] ^ self.inv_d)
        self._hit("capture")

    def outputs(self) -> dict[str, Out]:
        return {"Q": self.q}
```

`models/xut_models/7series/fdre.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""FDRE golden model: UG953 v2026.1 pp. 375-376 (clean-room)."""

from ._common.flops import SdrFlop


class FDRE(SdrFlop):
    PRIM = "FDRE"
    CTRL = "R"  # synchronous reset: Q goes Low at the next clock transition (p375)
    CTRL_VALUE = 0
    CTRL_ASYNC = False
    INIT_DEFAULT = 0  # attribute table, p376
    PAGE = 375
    ATTR_PAGE = 376


MODEL = FDRE
```

- [ ] **Step 4: Run the tests.** Expected: all pass for `FDRE`. The two async-only tests are collected with an empty parameter list and reported as skipped by pytest; that is expected until Task 26.

- [ ] **Step 5: Commit** with `flops: add clean-room SDR flop golden model and FDRE (UG953 pp. 375-376)`.

---

### Task 21: Shared stimulus recipes, FDRE vector tests, test.yaml and README generator

**Files:**
- Create:
  - `tests/7series/register/_shared/flops/flop_recipes.py` (complete it)
  - `tests/7series/register/_shared/flops/flop_tests.py`
  - `tests/7series/register/_shared/flops/test_flop_tests.py`
  - `tests/7series/register/FDRE/vectors/gen.py`
  - `tests/7series/register/FDRE/test.yaml` (generated, committed)
  - `tests/7series/register/FDRE/README.md` (generated, committed)

**Interfaces:**
- Consumes: `GenContext`, `VecBuilder` (Task 5); `validate` (Task 5)
- Produces:
  - `flop_recipes.KINDS`, `FlopKind`, `Flop`, `all_configs`, `attr_names`, `inv`
  - the recipes `l0_smoke`, `l1_capture`, `l1_ce_hold`, `l1_ctrl_over_ce`, `l1_ctrl_async`, `l1_recovery`, `l1_gsr`, `l1_is_c_inverted`, `l1_is_ctrl_inverted`, `l1_is_d_inverted`, `l2_exhaustive` and `l2_random`
  - `generators(prim) -> dict[str, Callable[[GenContext], Iterable[Vec]]]`
  - `flop_tests.tests_for(kind) -> list[tuple[dict, str]]` (test entry, why)
  - `render_test_yaml(kind) -> str`, `render_readme(kind, root) -> str`
  - `main(prims)`, which writes both files for each primitive

- [ ] **Step 1: Complete `flop_recipes.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Stimulus recipes shared by the flops work unit (FDRE, FDSE, FDCE, FDPE).

Each recipe takes a GenContext and a FlopKind and yields .xvec files built with
VecBuilder, so every file satisfies the spec §5.1 class rules by construction.
Recipes only drive inputs and place samples: expected values come from the
golden model (python runner), never from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

BIN = ("1'b0", "1'b1")


@dataclass(frozen=True)
class FlopKind:
    prim: str
    ctrl: str  # R | S | CLR | PRE
    is_async: bool
    word: str  # reset | set | clear | preset (used in test ids)
    forced: int  # the value the control drives onto Q
    init_default: int


KINDS = {
    "FDRE": FlopKind("FDRE", "R", False, "reset", 0, 0),
    "FDSE": FlopKind("FDSE", "S", False, "set", 1, 1),
    "FDCE": FlopKind("FDCE", "CLR", True, "clear", 0, 0),
    "FDPE": FlopKind("FDPE", "PRE", True, "preset", 1, 1),
}


def inv(port: str) -> str:
    return f"IS_{port}_INVERTED"


def attr_names(k: FlopKind) -> tuple[str, ...]:
    return ("INIT", inv("C"), inv("D"), inv(k.ctrl))


def all_configs(k: FlopKind):
    """All 16 combinations of the four 1-bit attributes: (cfg name, attrs)."""
    for bits in product((0, 1), repeat=4):
        name = "i{}_c{}_d{}_{}{}".format(bits[0], bits[1], bits[2], k.ctrl.lower(), bits[3])
        yield name, {n: BIN[b] for n, b in zip(attr_names(k), bits, strict=True)}


class Flop:
    """One configuration, driven in logical terms (control active/inactive, logical D)."""

    def __init__(self, ctx, k: FlopKind, cfg: str, attrs: dict[str, str]):
        self.k, self.attrs = k, attrs
        self.b = ctx.dut(cfg, **attrs)
        self.inv_d = int(attrs.get(inv("D"), BIN[0])[-1])
        self.inv_ctrl = int(attrs.get(inv(k.ctrl), BIN[0])[-1])
        self.init = int(attrs.get("INIT", BIN[k.init_default])[-1])
        self.ctrl_on = False
        self.b.init(**{k.ctrl: self.inv_ctrl})  # inactive while glbl holds GSR

    def ctrl(self, active: bool) -> None:
        if active == self.ctrl_on:
            return
        self.ctrl_on = active
        level = int(active) ^ self.inv_ctrl
        if self.k.is_async:
            self.b.async_(self.k.ctrl, level)
        else:
            self.b.set(**{self.k.ctrl: level})

    def data(self, d: int | None = None, ce: int | None = None) -> None:
        ports = {}
        if d is not None:
            ports["D"] = d ^ self.inv_d
        if ce is not None:
            ports["CE"] = ce
        self.b.set(**ports)

    def clock(self, n: int = 1, sample: bool = True) -> None:
        """n full cycles (rise, then fall): one active edge each, whatever IS_C_INVERTED is."""
        self.b.cycle("C", n=n, sample=sample)

    def sample(self) -> str:
        return self.b.sample()

    def load(self, q: int) -> None:
        """Bring Q to q through the documented capture path (C1)."""
        self.ctrl(False)
        self.data(d=q, ce=1)
        self.clock(sample=False)

    def gsr_pulse(self) -> None:
        self.b.glbl("GSR", 1)
        self.b.sample()
        self.b.glbl("GSR", 0)
        self.b.sample()

    def build(self):
        return self.b.build()


def _init_only(ctx, k, init, **extra):
    return Flop(ctx, k, f"init{init}", {"INIT": BIN[init], **extra})


def l0_smoke(ctx, k):
    """16 configurations: power-up value, then one capture of ~INIT."""
    for cfg, attrs in all_configs(k):
        f = Flop(ctx, k, cfg, attrs)
        f.sample()
        f.data(d=1 - f.init, ce=1)
        f.clock()
        yield f.build()


def l1_capture(ctx, k):
    # "default" sets no attribute at all: the one vector config where the model's
    # documented defaults meet the UNISIM defaults (Review Focus 2).
    for f in [Flop(ctx, k, "default", {})] + [_init_only(ctx, k, init) for init in (0, 1)]:
        for d in (1, 0, 1, 1, 0, 0):
            f.data(d=d, ce=1)
            f.clock()
        yield f.build()


def l1_ce_hold(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.data(d=1 - init, ce=0)
        f.clock(n=3)
        f.data(ce=1)
        f.clock()
        f.data(d=init, ce=0)
        f.clock(n=3)
        yield f.build()


def l1_ctrl_over_ce(ctx, k):
    """The control overrides CE and D: sync at the active edge, async at once."""
    for init, ce in product((0, 1), repeat=2):
        f = Flop(ctx, k, f"init{init}_ce{ce}", {"INIT": BIN[init]})
        f.load(1 - k.forced)
        f.data(d=1 - k.forced, ce=ce)
        f.ctrl(True)
        f.sample()  # async: already forced; sync: unchanged until the edge
        f.clock()  # sync: forced at the active edge
        f.ctrl(False)
        f.sample()  # released: Q keeps the forced value
        f.data(ce=1)
        f.clock()  # captures D again
        yield f.build()


def l1_ctrl_async(ctx, k):
    """Async kinds only: the control acts with no clock edge at all."""
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.load(1 - k.forced)
        for _ in range(3):
            f.ctrl(True)
            f.sample()
            f.ctrl(False)
            f.sample()
            f.load(1 - k.forced)
            f.sample()
        yield f.build()


def l1_recovery(ctx, k):
    """Async kinds only: after release, the next active edge (>= async_sep_ps later) captures D."""
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.ctrl(True)
        f.data(d=1 - k.forced, ce=1)
        f.clock()
        f.ctrl(False)
        f.clock()
        yield f.build()


def l1_gsr(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.load(1 - init)
        f.sample()
        f.data(d=1 - init, ce=1)
        f.b.glbl("GSR", 1)
        f.sample()  # INIT (C4)
        f.clock()  # edges while GSR is active (inferred: ignored)
        f.b.glbl("GSR", 0)
        f.sample()
        f.clock()  # captures D again
        yield f.build()


def l1_is_c_inverted(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init, **{inv("C"): BIN[1]})
        for d in (1 - init, init, 1 - init):
            f.data(d=d, ce=1)
            f.clock()  # samples after the rise (no change) and after the fall (capture)
        yield f.build()


def l1_is_ctrl_inverted(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init, **{inv(k.ctrl): BIN[1]})
        f.load(1 - k.forced)
        f.ctrl(True)  # drives the pin Low
        f.sample()
        f.clock()
        f.ctrl(False)
        f.load(1 - k.forced)
        f.sample()
        yield f.build()


def l1_is_d_inverted(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init, **{inv("D"): BIN[1]})
        for d in (0, 1, 1, 0):
            f.data(d=d, ce=1)  # logical d; Flop.data applies the inversion
            f.clock()
        yield f.build()


def l2_exhaustive(ctx, k):
    """16 configurations x prior Q x (control, CE, D) at an active edge. No GSR, so the
    configurations without IS_D_INVERTED stay hardware-eligible (GSR on hw needs §7.2)."""
    for cfg, attrs in all_configs(k):
        f = Flop(ctx, k, cfg, attrs)
        for q0, (c, ce, d) in product((0, 1), product((0, 1), repeat=3)):
            f.load(q0)
            f.sample()
            f.data(d=d, ce=ce)
            f.ctrl(bool(c))
            if k.is_async:
                f.sample()
            f.clock()
            f.ctrl(False)
        yield f.build()


def l2_random(ctx, k, steps: int = 300):
    """Seeded constrained-random sessions over the 16 configurations (seed in the header)."""
    for cfg, attrs in all_configs(k):
        f = Flop(ctx, k, cfg, attrs)
        rng = ctx.rng
        for _ in range(steps):
            r = rng.random()
            if k.is_async and r < 0.13:
                f.ctrl(rng.random() < 0.5)
                f.sample()
            else:
                f.data(d=rng.randrange(2), ce=int(rng.random() < 0.8))
                if not k.is_async:
                    f.ctrl(rng.random() < 0.15)
                f.clock()
        yield f.build()


def l0_illegal_init(ctx, k):
    """INIT=1'bx is outside UG953's allowed values: the model must reject it (expect=reject)."""
    b = ctx.dut("init_x", allow_illegal=True, expect="reject", INIT="1'bx")
    b.sample()
    yield b.build()


def generators(prim: str) -> dict:
    """test.yaml function name -> generator, for vectors/gen.py of each primitive."""
    k = KINDS[prim]
    table = {"l0_smoke": l0_smoke, "l0_illegal_init": l0_illegal_init,
             "l1_capture": l1_capture, "l1_ce_hold": l1_ce_hold,
             f"l1_{k.word}_over_ce": l1_ctrl_over_ce, "l1_gsr_init": l1_gsr,
             "l1_is_c_inverted": l1_is_c_inverted,
             f"l1_is_{k.ctrl.lower()}_inverted": l1_is_ctrl_inverted,
             "l1_is_d_inverted": l1_is_d_inverted, "l2_exhaustive": l2_exhaustive,
             "l2_random": l2_random}
    if k.is_async:
        table |= {f"l1_{k.word}_async": l1_ctrl_async, f"l1_{k.word}_recovery": l1_recovery}
    return {name: (lambda fn: lambda ctx: fn(ctx, k))(fn) for name, fn in table.items()}
```

- [ ] **Step 2: Write `tests/7series/register/FDRE/vectors/gen.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""FDRE vector generators (test.yaml: source: vectors/gen.py:<name>).

The recipes live in tests/7series/register/_shared/flops/flop_recipes.py.
"""

import flop_recipes

globals().update(flop_recipes.generators("FDRE"))
```

- [ ] **Step 3: Write `flop_tests.py`**, the single source of the four `test.yaml` and `README.md` files.

```python
# SPDX-License-Identifier: Apache-2.0
"""Single source of the flops unit's test.yaml and README.md files.

    uv run python tests/7series/register/_shared/flops/flop_tests.py FDRE [FDSE ...]

test_flop_tests.py fails when a committed file differs from this rendering.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from flop_recipes import BIN, KINDS, FlopKind, attr_names

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
PAGES = {"FDRE": (375, 376), "FDSE": (378, 379), "FDCE": (369, 370), "FDPE": (372, 373)}
TITLE = {"FDRE": "D flip-flop with clock enable and synchronous reset",
         "FDSE": "D flip-flop with clock enable and synchronous set",
         "FDCE": "D flip-flop with clock enable and asynchronous clear",
         "FDPE": "D flip-flop with clock enable and asynchronous preset"}
ALL_FLOWS = ["rtl", "vivado", "yosys", "openxc7", "vpr"]
RUNNERS = ("python", "xsim", "iverilog", "verilator", "hw")
# (value, reason) pairs; values are the step-1 schema strings "no" | "unsupported".
HW_GSR = ("unsupported", "GSR pulses need the GSR-immune harness state of spec §7.2")
SV_PY = ("no", "self-checking sv testbench; there is no golden-model replay")
SV_HW = ("unsupported", "sv testbenches are simulation-only (spec §4.3)")
X_VL = ("unsupported", "2-state simulator: x stimulus is randomised per X seed (spec §5.6), so "
        "the undocumented x checkpoints cannot be compared")
CO_XS = ("unsupported", "cocotb has no xsim backend (spec §4.3)")
CO_HW = ("unsupported", "cocotb runs in simulation; failing seeds are frozen into vector tests")
CO_PY = ("no", "the cocotb test compares against the golden model itself")
VL_REJ = ("unsupported", "a 2-state simulator cannot represent the 1'bx attribute value")
HW_REJ = ("unsupported", "rejection of an illegal attribute is a simulation-model check")


def hw_inv_d(ap: int) -> tuple[str, str]:
    return ("unsupported", f"UG953 p{ap}: IS_D_INVERTED must be 0 unless the flop is an I/O "
                           "register; the fabric harness uses SLICE flops")


def _runners(**over: tuple[str, str]) -> tuple[dict, dict]:
    """(runners, unsupported_reasons) in the step-1 schema's string form."""
    runners = {r: over[r][0] if r in over else "yes" for r in RUNNERS}
    return runners, {r: reason for r, (_, reason) in over.items()}


def _claims(k: FlopKind, *ns: int) -> list[str]:
    return [f"claim:{k.prim}.C{n}" for n in ns]


def _ports(k: FlopKind, *names: str) -> list[str]:
    return [f"port:{n}" for n in names]


def _attrs(names) -> list[str]:
    return [f"attr:{n}={v}" for n in names for v in BIN]


def _related(k: FlopKind, level: str, suffix: str) -> list[str]:
    out = []
    for o in KINDS.values():
        if o is k or (("_async" in suffix or "_recovery" in suffix) and not o.is_async):
            continue
        s = suffix.replace(k.word, o.word).replace(f"is_{k.ctrl.lower()}_", f"is_{o.ctrl.lower()}_")
        out.append(f"7series.{o.prim}.{level}.{s}")
    return out


def tests_for(k: FlopKind) -> list[tuple[dict, str]]:
    p, ap = PAGES[k.prim]
    c, w, lc = k.ctrl, k.word, k.ctrl.lower()
    all_ports = _ports(k, "C", "CE", "D", "Q", c)
    out: list[tuple[dict, str]] = []

    def add(level, suffix, style, source, exercises, why, *, gaps, sampling=None,
            runners=None, flows=None, configs=None, exclusions=None, related=()):
        assert gaps, f"{suffix}: every test must say what it misses"
        declared, reasons = runners or _runners()
        e = {"id": f"7series.{k.prim}.{level}.{suffix}", "level": level, "style": style,
             "source": source, "exercises": exercises, "attr_sampling": sampling or {},
             "runners": declared, "flows": flows or ALL_FLOWS,
             "related": _related(k, level, suffix) + list(related), "gaps": list(gaps)}
        if reasons:
            e["unsupported_reasons"] = reasons
        if exclusions:
            e["config_exclusions"] = exclusions
        if configs:
            e["configs"] = configs
        out.append((e, why))

    init_s = {"INIT": [0, 1]}
    no_x = "no x/z on any input (sv_x_inputs covers x)"
    d1 = {"hw": {"*_d1_*": f"IS_D_INVERTED=1 (UG953 p{ap}) is only legal on I/O registers; "
                           "the fabric harness uses SLICE flops"}}
    add("L0", "smoke", "vector", "vectors/gen.py:l0_smoke",
        all_ports + _attrs(attr_names(k)) + _claims(k, 1, 4),
        "Every one of the 16 attribute combinations elaborates, powers up to INIT and "
        "captures once on every simulator: the minimum any toolchain must get right.",
        sampling={n: [0, 1] for n in attr_names(k)}, exclusions=d1,
        gaps=["only one capture per configuration; no control, CE-low or GSR activity",
              no_x, "illegal values are tried only by L0.illegal_init"],
        related=[f"7series.{k.prim}.L0.illegal_init"])
    add("L0", "illegal_init", "vector", "vectors/gen.py:l0_illegal_init", [],
        f"INIT=1'bx is outside UG953's 1'b0/1'b1 (p{ap}); the simulation must reject it "
        "(expect=reject), which exercises the runtime-rejection path of spec §4.1.",
        # python stays "yes": it prepares dut/, stim.xvec, an empty expected.xtr and
        # configs.json for every vector test, reject tests included (Task 8 "Reject tests").
        runners=_runners(verilator=VL_REJ, hw=HW_REJ),
        gaps=["only INIT=1'bx is tried; over-width literals are truncated at elaboration "
              "and IS_*_INVERTED illegal values are not tried",
              "whether UNISIM rejects it is observed, not documented (see Task 24)"],
        related=[f"7series.{k.prim}.L0.smoke"])
    add("L1", "capture", "vector", "vectors/gen.py:l1_capture",
        _ports(k, "C", "CE", "D", "Q") + _claims(k, 1),
        "Pins the basic D-to-Q transfer on the active edge, for both INIT values and for "
        "the all-defaults configuration (model defaults vs UNISIM defaults).",
        sampling=init_s,
        gaps=["CE held High and the control inactive throughout", "no GSR after power-up",
              "default polarities only", no_x],
        related=[f"7series.{k.prim}.L2.exhaustive"])
    add("L1", "ce_hold", "vector", "vectors/gen.py:l1_ce_hold",
        _ports(k, "C", "CE", "D", "Q") + _claims(k, 2),
        "Shows that CE Low makes clock edges no-ops even with D different from Q.",
        sampling=init_s,
        gaps=["CE never toggles within a cycle (between edges only)", "control inactive",
              "default polarities only", no_x])
    add("L1", f"{w}_over_ce", "vector", f"vectors/gen.py:l1_{w}_over_ce",
        _ports(k, c, "CE", "Q") + _claims(k, 3),
        (f"{c} must win over CE Low and over D, "
         + ("at once, with no clock edge." if k.is_async else "at the next active edge.")
         + " A priority inversion here is a classic synthesis-mapping bug."),
        sampling=init_s,
        gaps=[f"{c} is never asserted and released within one clock period" if not k.is_async
              else f"{c} release timing relative to the clock is covered only by {w}_recovery",
              "default polarities only", no_x])
    if k.is_async:
        add("L1", f"{w}_async", "vector", f"vectors/gen.py:l1_{w}_async",
            _ports(k, c, "Q") + _claims(k, 3),
            f"{c} acts without any clock edge, repeatedly, from both Q values.",
            sampling=init_s,
            gaps=["no clock activity while the control is asserted", "no GSR overlap",
                  "default polarities only"])
        add("L1", f"{w}_recovery", "vector", f"vectors/gen.py:l1_{w}_recovery",
            _ports(k, c, "C", "D", "Q") + _claims(k, 1, 3),
            f"After {c} is released, the next active edge captures D. The edge is at least "
            "async_sep_ps after the release, so recovery timing is not tested (spec §2).",
            sampling=init_s, gaps=["recovery/removal timing is out of scope (spec §2)",
                                   "one release per configuration"])
    add("L1", "gsr_init", "vector", "vectors/gen.py:l1_gsr_init",
        _ports(k, "Q") + _claims(k, 4),
        "A GSR pulse mid-run returns Q to INIT from the opposite value; checks glbl handling "
        "in every simulator and, later, every flow's INIT mapping.",
        sampling=init_s, runners=_runners(hw=HW_GSR),
        gaps=["GSR overlapping an active control is not driven here",
              "edges during GSR are an inferred behaviour (see sv_gsr_midsim)"],
        related=[f"7series.{k.prim}.L1.sv_gsr_midsim"])
    add("L1", "is_c_inverted", "vector", "vectors/gen.py:l1_is_c_inverted",
        _ports(k, "C", "Q") + ["attr:IS_C_INVERTED=1'b1"] + _claims(k, 5),
        "Samples after both edges show capture only on the falling edge.",
        sampling={"INIT": [0, 1], "IS_C_INVERTED": [1]},
        gaps=["CE High and control inactive throughout; the other inversions stay 0 "
              "(combinations are in L2.exhaustive)"])
    add("L1", f"is_{lc}_inverted", "vector", f"vectors/gen.py:l1_is_{lc}_inverted",
        _ports(k, c, "Q") + [f"attr:IS_{c}_INVERTED=1'b1"] + _claims(k, 6),
        f"{c} held Low acts as active; a flow that drops the inversion fails at once.",
        sampling={"INIT": [0, 1], f"IS_{c}_INVERTED": [1]},
        gaps=["one assertion per configuration; other inversions stay 0"])
    add("L1", "is_d_inverted", "vector", "vectors/gen.py:l1_is_d_inverted",
        _ports(k, "D", "Q") + ["attr:IS_D_INVERTED=1'b1"] + _claims(k, 7),
        "Q takes the complement of D.",
        sampling={"INIT": [0, 1], "IS_D_INVERTED": [1]}, runners=_runners(hw=hw_inv_d(ap)),
        gaps=[f"claim:{k.prim}.C8 — IS_D_INVERTED=1 is only legal on I/O registers; a "
              "placement rule for hardware flows (steps 3-4), not a simulation behaviour"])
    add("L2", "exhaustive", "vector", "vectors/gen.py:l2_exhaustive",
        all_ports + _attrs(attr_names(k)) + _claims(k, 1, 2, 3, 5, 6, 7),
        "Every attribute combination x prior Q x (control, CE, D): the complete "
        "single-edge truth table.",
        sampling={n: [0, 1] for n in attr_names(k)}, exclusions=d1,
        gaps=["single edge per combination: no multi-cycle ordering (see L2.random)",
              "no GSR (L1.gsr_init and sv_gsr_midsim cover it; hardware GSR needs §7.2)",
              no_x],
        related=[f"7series.{k.prim}.L1.capture"])
    add("L2", "random", "vector", "vectors/gen.py:l2_random",
        all_ports + _attrs(attr_names(k)) + _claims(k, 1, 2, 3),
        "Seeded constrained-random sequences find ordering effects that the "
        "single-edge table cannot.",
        sampling={n: [0, 1] for n in attr_names(k)}, exclusions=d1,
        gaps=["no GSR (hardware GSR needs §7.2; L1.gsr_init covers simulation)",
              "one seed per run; failing seeds must be frozen by hand (xut freeze-seed is "
              "deferred)",
              no_x] + (["the control only changes between edges (sync kinds)"]
                       if not k.is_async else []),
        related=[f"7series.{k.prim}.L2.cocotb_random"])
    add("L1", "sv_gsr_midsim", "sv", f"sv/tb_{k.prim.lower()}_gsr.sv",
        _ports(k, "Q") + _claims(k, 4),
        "Direct UNISIM instances for both INIT values; glbl GSR is forced mid-run while "
        "clocking. Edges during GSR are recorded, not judged, because UG953 is silent.",
        runners=_runners(python=SV_PY, hw=SV_HW), flows=["rtl"],
        gaps=["behaviour of clock edges while GSR is active: undocumented, checkpoint only",
              "default IS_* polarities only", "control inactive throughout"],
        configs=[{"cfg": "default", "attrs": {}}],
        related=[f"7series.{k.prim}.L1.gsr_init"])
    add("L1", "sv_x_inputs", "sv", f"sv/tb_{k.prim.lower()}_x.sv",
        _ports(k, "CE", "D", c, "Q") + _claims(k, 2, 3),
        "X on D, CE or the control: the documented cases (CE Low holds; the control "
        "overrides) are checked; the undocumented ones are recorded for cross-simulator "
        "comparison. Not run on Verilator: see unsupported_reasons (plan ambiguity 9).",
        runners=_runners(python=SV_PY, verilator=X_VL, hw=SV_HW), flows=["rtl"],
        gaps=["UG953 does not define X behaviour; X on D with CE High, X on CE and X on the "
              "control are checkpoints only", "no x on C", "default polarities only"],
        configs=[{"cfg": "default", "attrs": {}}])
    add("L2", "cocotb_random", "cocotb", f"cocotb/cocotb_{k.prim.lower()}_random.py",
        all_ports + _claims(k, 1, 2, 3, 4),
        "Long model-checked random sessions on Icarus and Verilator; any failing seed becomes "
        "a frozen vector test that also runs on xsim and hardware.",
        runners=_runners(python=CO_PY, xsim=CO_XS, hw=CO_HW), flows=["rtl"],
        gaps=["no GSR mid-session", "only 4 of the 16 attribute configurations", no_x],
        configs=[{"cfg": "default", "attrs": {}},
                 {"cfg": "init1", "attrs": {"INIT": "1'b1"}},
                 {"cfg": "inv_all", "attrs": {"IS_C_INVERTED": "1'b1", "IS_D_INVERTED": "1'b1",
                                              f"IS_{c}_INVERTED": "1'b1"}},
                 {"cfg": "init1_inv_c", "attrs": {"INIT": "1'b1", "IS_C_INVERTED": "1'b1"}}],
        related=[f"7series.{k.prim}.L2.random"])
    return out


HEADER = ("# SPDX-License-Identifier: Apache-2.0\n"
          "# GENERATED by tests/7series/register/_shared/flops/flop_tests.py; edit that file.\n")


def render_test_yaml(k: FlopKind) -> str:
    p, _ = PAGES[k.prim]
    doc = {"primitive": k.prim, "family": "7series", "work_unit": "flops",
           "doc_refs": [{"guide": "UG953", "version": "2026.1", "section": k.prim, "page": p}],
           "tests": [e for e, _ in tests_for(k)]}
    # safe_dump quotes the strings "yes"/"no" ('yes'), so they reload as strings, as the
    # step-1 schema requires; test_flop_tests.py validates the output against that schema.
    return HEADER + yaml.safe_dump(doc, sort_keys=False, width=100, allow_unicode=True)


def _cell(e: dict, runner: str) -> str:
    v = e["runners"][runner]
    return v if v == "yes" else f"{v}: {e['unsupported_reasons'][runner]}"


def render_readme(k: FlopKind, root: Path = ROOT) -> str:
    p, ap = PAGES[k.prim]
    tests = tests_for(k)
    findings = sorted((root / "findings").glob(f"{k.prim}-*.md"))
    lines = [f"# {k.prim} — {TITLE[k.prim]}", "",
             f"UG953 v2026.1, section {k.prim}, pages {p}–{ap} (REGISTER / SDR). "
             "Work unit: `flops`. GENERATED by `_shared/flops/flop_tests.py`.", "",
             "## Overview", "",
             f"{k.prim} is a single D flip-flop with clock enable and "
             + ("an asynchronous " if k.is_async else "a synchronous ")
             + f"{k.word} input `{k.ctrl}` that drives Q {'High' if k.forced else 'Low'}. "
             "GSR loads INIT. Programmable inversion exists on C, D and the control pin. "
             f"Behavioural claims {k.prim}.C1–C8 are in `catalog/7series/{k.prim}.overrides.yaml`.",
             "", "## Tests", "", "| ID | Level | Style | Exercises |", "|---|---|---|---|"]
    lines += [f"| `{e['id']}` | {e['level']} | {e['style']} | {', '.join(e['exercises'])} |"
              for e, _ in tests]
    lines += ["", "## Why each test is useful, and what it misses", ""]
    for e, why in tests:
        lines.append(f"- `{e['id']}`: {why}")
        lines += [f"  - Misses: {g}" for g in e["gaps"]]
        for runner, excl in e.get("config_exclusions", {}).items():
            lines += [f"  - Not on {runner} for configurations `{pat}`: {why_x}"
                      for pat, why_x in excl.items()]
    lines += ["", "## Oracle", "",
              f"- Vector tests: the clean-room golden model `models/xut_models/7series/"
              f"{k.prim.lower()}.py` (shared logic in `_common/flops.py`), written from UG953 "
              "alone. Every expected bit carries `doc:<page>` or `inferred:<reason>`, and bits "
              "UG953 leaves undefined are `-`.",
              "- sv tests: self-checks of documented behaviour only; undocumented X and GSR "
              "cases are checkpoints compared between simulators by `xut crosscheck`.",
              "- cocotb: the same golden model, cycle by cycle.",
              "- References: UNISIM on xsim, Icarus and Verilator (after `xut verilatorize`, "
              "guarded by its Icarus equivalence check).", "",
              "## Known gaps (all tests)", "",
              "- Timing (setup/hold, clock-to-Q, recovery/removal) is out of scope (spec §2)."]
    gaps = dict.fromkeys(g for e, _ in tests for g in e["gaps"])
    lines += [f"- {g}" for g in gaps]
    lines += ["", "## Runner support and expected divergences", "",
              "| Test | python | xsim | iverilog | verilator | hw |", "|---|---|---|---|---|---|"]
    for e, _ in tests:
        lines.append(f"| `{e['id']}` | " + " | ".join(_cell(e, x) for x in RUNNERS) + " |")
    lines += ["", "Findings:" if findings else "Findings: none recorded.", ""]
    lines += [f"- [{f.stem}](../../../../findings/{f.name})" for f in findings]
    lines += ["", "## Related tests", ""]
    lines += [f"- `{e['id']}`: " + ", ".join(f"`{r}`" for r in e["related"]) for e, _ in tests]
    lines += ["", "## How to run", "", "```bash",
              f"uv run xut run '7series.{k.prim}.*' --jobs 40 > .cache/run-{k.prim.lower()}.log 2>&1",
              f"uv run xut crosscheck '7series.{k.prim}.*' > .cache/xc-{k.prim.lower()}.log 2>&1",
              f"uv run xut status record {k.prim}", "```", ""]
    return "\n".join(lines)


def main(prims: list[str]) -> None:
    for prim in prims:
        d = ROOT / "tests/7series/register" / prim
        d.mkdir(parents=True, exist_ok=True)
        (d / "test.yaml").write_text(render_test_yaml(KINDS[prim]))
        (d / "README.md").write_text(render_readme(KINDS[prim]))
        print(f"wrote {d}/test.yaml and README.md")


if __name__ == "__main__":
    main(sys.argv[1:])
```

`test_flop_tests.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest

from flop_recipes import KINDS
from flop_tests import ROOT, render_readme, render_test_yaml

PRESENT = [p for p in KINDS if (ROOT / "tests/7series/register" / p / "test.yaml").is_file()]


@pytest.mark.parametrize("prim", PRESENT)
def test_committed_files_are_current(prim):
    d = ROOT / "tests/7series/register" / prim
    assert (d / "test.yaml").read_text() == render_test_yaml(KINDS[prim]), "re-run flop_tests.py"
    assert (d / "README.md").read_text() == render_readme(KINDS[prim]), "re-run flop_tests.py"


@pytest.mark.parametrize("prim", PRESENT)
def test_every_generator_exists(prim):
    from flop_recipes import generators

    import yaml

    names = generators(prim)
    for t in yaml.safe_load((ROOT / "tests/7series/register" / prim / "test.yaml").read_text())["tests"]:
        if t["style"] == "vector":
            assert t["source"].split(":", 1)[1] in names


def test_every_test_has_gaps():
    for k in KINDS.values():
        from flop_tests import tests_for

        assert all(e["gaps"] for e, _ in tests_for(k)), k.prim


@pytest.mark.parametrize("prim", PRESENT)
def test_validates_against_step1_schema(prim):
    import json

    import jsonschema
    import yaml

    schema = json.loads((ROOT / "tools/xut/schemas/test.schema.json").read_text())
    doc = yaml.safe_load((ROOT / "tests/7series/register" / prim / "test.yaml").read_text())
    jsonschema.validate(doc, schema)
    for t in doc["tests"]:
        assert set(t["runners"].values()) <= {"yes", "no", "unsupported"}
        need = {r for r, v in t["runners"].items() if v != "yes"}
        assert need == set(t.get("unsupported_reasons", {})), t["id"]
```

- [ ] **Step 4: Generate FDRE's files and inspect them**

```bash
uv run python tests/7series/register/_shared/flops/flop_tests.py FDRE > .cache/flop-tests.log 2>&1; cat .cache/flop-tests.log
uv run xut lint > .cache/lint.log 2>&1; cat .cache/lint.log
```

Expected:
- `tests/7series/register/FDRE/test.yaml` has 14 tests (FDRE has no async tests), every one with a non-empty `gaps` list.
- Lint reports only `related` warnings (FDSE, FDCE and FDPE do not exist yet) and no `bins-accounted` error: `claim:FDRE.C8` is covered by a `gaps` entry, and the other 20 bins by `exercises`.

The start of the rendered `test.yaml`:

```yaml
# SPDX-License-Identifier: Apache-2.0
# GENERATED by tests/7series/register/_shared/flops/flop_tests.py; edit that file.
primitive: FDRE
family: 7series
work_unit: flops
doc_refs:
- guide: UG953
  version: '2026.1'
  section: FDRE
  page: 375
tests:
- id: 7series.FDRE.L0.smoke
  level: L0
  style: vector
  source: vectors/gen.py:l0_smoke
  exercises:
  - port:C
  - port:CE
  - port:D
  - port:Q
  - port:R
  - attr:INIT=1'b0
  …
```

(The rest follows mechanically from `tests_for`. `test_flop_tests.py` keeps the committed file identical to the rendering.)

- [ ] **Step 5: Run the python runner on FDRE and check the stimulus**

```bash
uv run xut run '7series.FDRE.*' --runner python > .cache/run-fdre-python.log 2>&1; tail -n 20 .cache/run-fdre-python.log
```

Expected:
- every vector test `pass`, and the sv and cocotb tests `skip` with their declared reasons;
- `build/rtl/python/unisim-2025.2/7series.FDRE.L1.gsr_init/cfg-init0/stim.xvec` starts with `# xut-vec 2  prim=FDRE cfg=init0` and has `hw_renderable yes`, because GSR is renderable per spec §5.2 (the runner declaration covers the §7.2 limitation);
- the L0 `result.json` `bins_reached` includes every L0 `exercises` bin.

- [ ] **Step 6: Commit**

```bash
uv run pytest tests -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log
git add tests/7series/register/_shared/flops && git commit -m "flops: add shared stimulus recipes and the test.yaml/README generator" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tests/7series/register/FDRE && git commit -m "flops: add FDRE L0-L2 vector tests, test.yaml and README" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 22: FDRE sv tests (GSR mid-simulation, X inputs)

**Files:**
- Create: `tests/7series/register/_shared/flops/flop_gsr_tb.svh`, `tests/7series/register/_shared/flops/flop_x_tb.svh`, `tests/7series/register/FDRE/sv/tb_fdre_gsr.sv`, `tests/7series/register/FDRE/sv/tb_fdre_x.sv`

**Interfaces:**
- Consumes: `xut_trace.svh` (`XUT_CHECK`, `XUT_CHECKN`, `XUT_POINT1`, `XUT_POINT2`, `xut_finish`) (Task 9)
- Produces: the shared testbench bodies, parameterised by the defines `FLOP_TB`, `FLOP_PRIM`, `FLOP_CTRL`, `FLOP_FORCED` and `FLOP_ASYNC`

- [ ] **Step 1: Write `flop_gsr_tb.svh`**

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// GSR mid-simulation test shared by the flops unit (spec §4.3 sv style).
// The including file defines FLOP_TB, FLOP_PRIM and FLOP_CTRL.
// Checks only documented behaviour: GSR active -> INIT on Q (C4); capture after (C1).
// Clock edges while GSR is active are checkpoints only: UG953 does not describe them.
`timescale 1ps / 1ps
module `FLOP_TB;
`include "xut_trace.svh"
  reg C = 1'b0, CE = 1'b0, D = 1'b0, CTRL = 1'b0;
  wire Q0, Q1;
  `FLOP_PRIM #(.INIT(1'b0)) u0 (.Q(Q0), .C(C), .CE(CE), .D(D), .`FLOP_CTRL(CTRL));
  `FLOP_PRIM #(.INIT(1'b1)) u1 (.Q(Q1), .C(C), .CE(CE), .D(D), .`FLOP_CTRL(CTRL));

  task automatic cycle;
    begin
      #4000 C = 1'b1;
      #5000 C = 1'b0;
      #1000;
    end
  endtask

  task automatic phase(input integer n, input reg d);
    begin
      D = d;
      CE = 1'b1;
      cycle;                                   // both flops now hold d
      glbl.GSR_int = 1'b1;
      #1000;
      `XUT_CHECKN("gsr.Q0.P", n, Q0, 1'b0)
      `XUT_CHECKN("gsr.Q1.P", n, Q1, 1'b1)
      $fdisplay(xut_fd, "P%0d.gsr  Q0=%b Q1=%b", n, Q0, Q1);
      cycle;                                   // an edge while GSR is active
      $fdisplay(xut_fd, "P%0d.gsr_edge  Q0=%b Q1=%b", n, Q0, Q1);
      glbl.GSR_int = 1'b0;
      #1000;
      $fdisplay(xut_fd, "P%0d.released  Q0=%b Q1=%b", n, Q0, Q1);
      cycle;                                   // captures d again
      `XUT_CHECKN("after.Q0.P", n, Q0, d)
      `XUT_CHECKN("after.Q1.P", n, Q1, d)
      $fdisplay(xut_fd, "P%0d.after  Q0=%b Q1=%b", n, Q0, Q1);
    end
  endtask

  initial begin
    #120000;                                   // past glbl ROC_WIDTH (100 ns)
    `XUT_CHECK("P0.Q0", Q0, 1'b0)
    `XUT_CHECK("P0.Q1", Q1, 1'b1)
    `XUT_POINT2("P0", "Q0", Q0, "Q1", Q1)
    phase(1, 1'b1);
    phase(2, 1'b0);
    xut_finish;
  end
endmodule
```

- [ ] **Step 2: Write `flop_x_tb.svh`**

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// X-input test shared by the flops unit. The including file defines FLOP_TB,
// FLOP_PRIM, FLOP_CTRL, FLOP_FORCED (1'b0 or 1'b1) and FLOP_ASYNC (0 or 1).
// Checked (documented): CE Low holds Q with D = x (C2); an active control forces Q
// with D = x and CE = x (C3). Checkpoints only (undocumented): x on D with CE High,
// x on CE, x on the control.
`timescale 1ps / 1ps
module `FLOP_TB;
`include "xut_trace.svh"
  reg C = 1'b0, CE = 1'b0, D = 1'b0, CTRL = 1'b0;
  wire Q;
  `FLOP_PRIM u (.Q(Q), .C(C), .CE(CE), .D(D), .`FLOP_CTRL(CTRL));

  task automatic cycle;
    begin
      #4000 C = 1'b1;
      #5000 C = 1'b0;
      #1000;
    end
  endtask

  task automatic load(input reg v);
    begin
      CTRL = 1'b0;
      #1000;
      D = v;
      CE = 1'b1;
      cycle;
    end
  endtask

  initial begin
    #120000;
    load(~`FLOP_FORCED);                      // X1: CE Low, D = x -> hold (C2)
    CE = 1'b0;
    D = 1'bx;
    cycle;
    cycle;
    `XUT_CHECK("X1", Q, ~`FLOP_FORCED)
    `XUT_POINT1("X1", "Q", Q)
    load(~`FLOP_FORCED);                      // X2: control active, D = CE = x (C3)
    D = 1'bx;
    CE = 1'bx;
    #1000 CTRL = 1'b1;
    #1000;
    if (`FLOP_ASYNC) `XUT_CHECK("X2a", Q, `FLOP_FORCED)
    `XUT_POINT1("X2a", "Q", Q)
    cycle;
    `XUT_CHECK("X2", Q, `FLOP_FORCED)
    `XUT_POINT1("X2", "Q", Q)
    load(~`FLOP_FORCED);                      // X3: CE High, D = x (undocumented)
    D = 1'bx;
    cycle;
    `XUT_POINT1("X3", "Q", Q)
    load(1'b0);                               // X4: CE = x, D != Q (undocumented)
    D = 1'b1;
    CE = 1'bx;
    cycle;
    `XUT_POINT1("X4", "Q", Q)
    load(~`FLOP_FORCED);                      // X5: control = x (undocumented)
    #1000 CTRL = 1'bx;
    #1000;
    `XUT_POINT1("X5a", "Q", Q)
    cycle;
    `XUT_POINT1("X5", "Q", Q)
    CTRL = 1'b0;
    xut_finish;
  end
endmodule
```

- [ ] **Step 3: Write the FDRE wrappers**

`tests/7series/register/FDRE/sv/tb_fdre_gsr.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDRE.L1.sv_gsr_midsim (body: _shared/flops/flop_gsr_tb.svh)
`define FLOP_TB tb_fdre_gsr
`define FLOP_PRIM FDRE
`define FLOP_CTRL R
`include "flop_gsr_tb.svh"
```

`tests/7series/register/FDRE/sv/tb_fdre_x.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDRE.L1.sv_x_inputs (body: _shared/flops/flop_x_tb.svh)
`define FLOP_TB tb_fdre_x
`define FLOP_PRIM FDRE
`define FLOP_CTRL R
`define FLOP_FORCED 1'b0
`define FLOP_ASYNC 0
`include "flop_x_tb.svh"
```

- [ ] **Step 4: Run on all simulators**

```bash
uv run xut run 7series.FDRE.L1.sv_gsr_midsim 7series.FDRE.L1.sv_x_inputs --runner iverilog --runner xsim --runner verilator --jobs 8 > .cache/run-fdre-sv.log 2>&1; tail -n 20 .cache/run-fdre-sv.log
```

Expected:
- `sv_gsr_midsim`: `pass` on `iverilog`, `xsim`, `verilator` and `iverilog-vz`, with checkpoint labels `P0`, `P1.gsr` … `P2.after`.
- `sv_x_inputs`: `pass` on `iverilog` and `xsim`, with labels `X1` … `X5`; `skip` on `verilator` and `iverilog-vz` with the declared reason. On a 2-state simulator the `1'bx` stimulus is randomised per X seed, so the undocumented checkpoints would differ by construction (spec §5.6). That is a property of the test, not an `x-dependence` of the model.

A `fail` means one of two things:
- **A documented behaviour** (C1–C4) fails on a UNISIM simulator. That is a `doc-vs-model`-class finding: write it up in Task 24.
- **A testbench bug.** Fix the testbench, never by removing a check.

- [ ] **Step 5: Commit** with `flops: add shared GSR and X-input sv testbenches and the FDRE instances`.

---

### Task 23: FDRE cocotb test

**Files:**
- Create: `tests/7series/register/_shared/flops/flops_cocotb.py`, `tests/7series/register/FDRE/cocotb/cocotb_fdre_random.py`

**Interfaces:**
- Consumes: `XutDut` (Task 11); `registry.get` (Task 6); `KINDS` (Task 21)
- Produces: `flops_cocotb.random_session(dut, prim, cycles=2000)`

- [ ] **Step 1: Write `flops_cocotb.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Constrained-random cocotb session shared by the flops unit (spec §4.3 cocotb style).

Runs inside the xut-sim container. Each step drives random inputs, applies the same
events to the golden model, and compares Q after every clock edge and every async
control change. Every comparison point is written to trace.xtr. When a seed fails,
freeze it: copy the session into vectors/frozen/<seed>.xvec as a new vector test.
"""

import os
import random

from flop_recipes import KINDS
from xut.cocotb_dut import XutDut
from xut_models.registry import get


async def random_session(dut, prim: str, cycles: int = 2000) -> None:
    k = KINDS[prim]
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    model = get("7series", prim)(x.attrs)
    rng = random.Random(int(os.environ["XUT_SEED"]))
    inv_ctrl = int(x.attrs.get(f"IS_{k.ctrl}_INVERTED", "1'b0")[-1])
    model.power_on()
    await x.set(**{k.ctrl: inv_ctrl})  # control inactive during power-up
    for p in ("CE", "D", k.ctrl):
        model.set_input(p, x.value(p))
    await x.settle()  # 120 ns; glbl releases GSR at 100 ns
    model.glbl("GSR", 0)
    errors: list[str] = []
    n = 0

    def check() -> None:
        nonlocal n
        exp = model.outputs()["Q"]
        got = x.get("Q")
        x.sample(f"S{n}", {"Q": exp.prov})
        if exp.bits != "-" and got != exp.bits:
            errors.append(f"S{n}: Q={got}, model {exp.bits} ({exp.prov})")
        n += 1

    for _ in range(cycles):
        if k.is_async and rng.random() < 0.1:
            v = rng.randrange(2)
            await x.set(**{k.ctrl: v})  # alone, >= 1 ns from any edge (XutDut spacing)
            model.set_input(k.ctrl, v)
            check()
            continue
        ports = {"D": rng.randrange(2), "CE": int(rng.random() < 0.8)}
        if not k.is_async:
            ports[k.ctrl] = int(rng.random() < 0.15) ^ inv_ctrl
        await x.set(**ports)
        for p, v in ports.items():
            model.set_input(p, v)
        for rising in (True, False):
            await x.edge("C", rising)
            model.clock_edge("C", rising)
            check()
    x.close()
    assert not errors, f"{len(errors)} mismatch(es); first: {errors[:5]}"
```

- [ ] **Step 2: Write `cocotb_fdre_random.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""7series.FDRE.L2.cocotb_random: constrained-random FDRE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdre_random(dut):
    await random_session(dut, "FDRE", cycles=2000)
```

- [ ] **Step 3: Run it**

```bash
uv run xut run 7series.FDRE.L2.cocotb_random --runner iverilog --runner verilator --runner xsim > .cache/run-fdre-cocotb.log 2>&1; tail -n 12 .cache/run-fdre-cocotb.log
```

Expected:
- `iverilog`, `verilator` and `iverilog-vz`: pass for all four configurations, each `trace.xtr` part holding 4000 samples (Verilator records its two X seeds in `seeds.x`);
- `xsim`: `skip` with the declared reason (cocotb has no xsim backend).

- [ ] **Step 4: Commit** with `flops: add shared cocotb random session and the FDRE cocotb test`.

---

### Task 24: FDRE end-to-end run, crosscheck, findings, status

**Files:**
- Modify: `status/7series/FDRE.yaml`
- Create if needed: `findings/FDRE-*.md`, plus `tests/7series/register/FDRE/README.md` (regenerated) and `test.yaml` (regenerated, if an `expected_divergence` is added)
- Create: `log/<ts>-unit-7series-flops-fdre-pilot.md`

- [ ] **Step 1: Full run.**
  - **Estimate:** 14 tests; vector configurations total 16 + 1 + 3 + 2 + 4 + 2 + 2 + 2 + 2 + 16 + 16 = 66, plus 2 sv and 4 cocotb. Verilator builds dominate: about 70 × 40 s ≈ 47 CPU-minutes. At `--jobs 40` that is about 2–4 minutes, and xsim adds about 65 × 15 s ÷ 40 ≈ 0.5 min.
  - **Cadence:** expected under 10 minutes, so report every 60 s with the remaining time and the finish clock-time, from the `progress:` lines.

```bash
uv run xut run '7series.FDRE.*' --jobs 40 > .cache/run-fdre.log 2>&1
```

(Run it in the background with a Monitor on `.cache/run-fdre.log`.)

Expected: every declared runner is `pass` for every test, and every undeclared cell is `skip` with a reason. `build/rtl/{python,xsim,iverilog,iverilog-vz,verilator}/unisim-2025.2/7series.FDRE.*/result.json` all exist.

- [ ] **Step 2: Crosscheck**

```bash
uv run xut crosscheck '7series.FDRE.*' --write-findings > .cache/xc-fdre.log 2>&1; echo "exit=$?"; cat .cache/xc-fdre.log
```

Expected in the best case: `exit=0` and no findings. For each finding reported:
1. Read the evidence against the UG953 text (pages 375–376), without opening UNISIM.
2. If the golden model contradicts UG953, fix the model with a test in `test_flop_models.py` and re-run. That is a model bug, not a finding.
3. Otherwise complete the finding file's **Analysis** section and keep it open. **Do not change the expectation**: the model keeps its `doc:`/`inferred:` value, and the bit stays defined. (`-` is only for bits the model already declares undefined because UG953 is silent on a *conflict*, Review Focus 2; it is never introduced in response to a finding.) Never make the model copy UNISIM.
4. Add `{finding: findings/FDRE-<slug>.md, cls: <class>, runners: [...]}` to the test's `expected_divergence` in `flop_tests.py`, and link the finding from the test's `gaps`. Regenerate (`flop_tests.py FDRE`) and re-run crosscheck. The disagreement is still reported, now as `known-divergence` referencing the finding, and the exit code becomes 0.

**`L0.illegal_init`** (the reject path). If iverilog and xsim both reject `INIT=1'bx` (no `XUT_DONE`, or an elaboration error), keep the test. If either simulator accepts it (`fail` "illegal attribute was accepted"), that is not a UG953 violation: UG953 lists the legal values but does not promise a runtime check. Remove the test from `flop_tests.py`, and add to `L0.smoke`'s `gaps`: "UNISIM (<model source>) accepts INIT=1'bx without rejecting it; the reject path is not exercised for flops". Record the observation in the log entry. This is recording a gap, not weakening a documented check.

For a `transform-bug` or `x-dependence`: record it and declare `verilator` `"unsupported"`, with the finding link as its `unsupported_reasons` entry, in `flop_tests.py` for the affected tests. That is the spec's "blocks the Verilator results for that model". Never delete a check.

- [ ] **Step 3: Commit the tests, then record status** (`record` requires a clean test dir):

```bash
git add tests/7series/register findings && git commit -m "flops: FDRE crosscheck findings and expected divergences" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
uv run xut status record FDRE > .cache/status-fdre.log 2>&1; cat .cache/status-fdre.log
git diff --stat status/7series/FDRE.yaml
git add status/7series/FDRE.yaml && git commit -m "flops: record FDRE L0-L2 results and coverage" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Skip the first commit if Step 2 changed nothing. Expected in `status/7series/FDRE.yaml`:
- `results` has keys such as `L1/iverilog/rtl: pass`, `L1/verilator/rtl: pass`, `L1/xsim/vivado: not-run` and `L1/hw/vivado: not-run`;
- `coverage.uncovered` is exactly `[claim:FDRE.C8]`;
- `measured.tree_hash` is a `sha256:` over the FDRE test dir, `_shared/flops`, `fdre.py`, `_common/flops.py` and `FDRE.overrides.yaml` at `HEAD`.

- [ ] **Step 4: Lint, log, per-task review**

```bash
uv run pytest -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
```

Expected: lint has no errors. Its warnings are only the `related` targets for FDSE, FDCE and FDPE.

Write `log/<ts>-unit-7series-flops-fdre-pilot.md`: the result matrix (paste `xut crosscheck`'s matrix), findings, run durations, and next steps (FDSE, FDCE, FDPE). Commit it with `flops: log FDRE pilot`. Do **not** open a PR yet: the unit has one PR (opened in Task 27). Run the per-task review on the local commits through the subagent-driven-development workflow (reviewer (a), then reviewer (b), sequentially; each writes a report file). Reviewer (b) checks the clean-room rule and every claim against UG953 pages 375–376. Address must-fix items in new commits before Task 25.

---

### Task 25: FDSE

**Files:**
- Create: `models/xut_models/7series/fdse.py`, `tests/7series/register/FDSE/{test.yaml, README.md, vectors/gen.py, sv/tb_fdse_gsr.sv, sv/tb_fdse_x.sv, cocotb/cocotb_fdse_random.py}`
- Modify: `tests/7series/register/_shared/flops/test_flop_models.py` (`PRIMS`), `status/7series/FDSE.yaml`

- [ ] **Step 1: Add FDSE to the model tests** (`PRIMS = ["FDRE", "FDSE"]`) and confirm they fail with `LookupError`.

- [ ] **Step 2: Write `models/xut_models/7series/fdse.py`** (clean-room, UG953 pp. 378–379):

```python
# SPDX-License-Identifier: Apache-2.0
"""FDSE golden model: UG953 v2026.1 pp. 378-379 (clean-room)."""

from ._common.flops import SdrFlop


class FDSE(SdrFlop):
    PRIM = "FDSE"
    CTRL = "S"  # synchronous set: Q goes High at the next clock transition (p378)
    CTRL_VALUE = 1
    CTRL_ASYNC = False
    INIT_DEFAULT = 1  # attribute table, p379
    PAGE = 378
    ATTR_PAGE = 379


MODEL = FDSE
```

Run the model tests: all pass. Commit the model now, before any test file:

```bash
git add models tests/7series/register/_shared/flops/test_flop_models.py && git commit -m "flops: add FDSE golden model (UG953 pp. 378-379)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Write the FDSE test files**

```python
# tests/7series/register/FDSE/vectors/gen.py
# SPDX-License-Identifier: Apache-2.0
"""FDSE vector generators (test.yaml: source: vectors/gen.py:<name>)."""

import flop_recipes

globals().update(flop_recipes.generators("FDSE"))
```

`sv/tb_fdse_gsr.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDSE.L1.sv_gsr_midsim (body: _shared/flops/flop_gsr_tb.svh)
`define FLOP_TB tb_fdse_gsr
`define FLOP_PRIM FDSE
`define FLOP_CTRL S
`include "flop_gsr_tb.svh"
```

`sv/tb_fdse_x.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDSE.L1.sv_x_inputs (body: _shared/flops/flop_x_tb.svh)
`define FLOP_TB tb_fdse_x
`define FLOP_PRIM FDSE
`define FLOP_CTRL S
`define FLOP_FORCED 1'b1
`define FLOP_ASYNC 0
`include "flop_x_tb.svh"
```

`cocotb/cocotb_fdse_random.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""7series.FDSE.L2.cocotb_random: constrained-random FDSE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdse_random(dut):
    await random_session(dut, "FDSE", cycles=2000)
```

Then generate `test.yaml` and `README.md`: `uv run python tests/7series/register/_shared/flops/flop_tests.py FDSE > .cache/flop-tests.log 2>&1; cat .cache/flop-tests.log`. Also re-run it for `FDRE`, because FDRE's `related` targets now partly exist; this changes nothing in its content.

- [ ] **Step 4: Run, crosscheck and record.** The estimate is the same as FDRE's: 65 vector configurations, under 10 minutes at `--jobs 40`, so report every 60 s from the `progress:` lines.

```bash
uv run xut run '7series.FDSE.*' --jobs 40 > .cache/run-fdse.log 2>&1
uv run xut crosscheck '7series.FDSE.*' --write-findings > .cache/xc-fdse.log 2>&1; echo "exit=$?"; cat .cache/xc-fdse.log
```

Handle each finding with the Task 24, Step 2 procedure, against UG953 pp. 378–379. Then commit the tests and findings and record the status:

```bash
git add tests/7series/register/FDSE findings && git commit -m "flops: add FDSE vector, sv and cocotb tests" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
uv run xut status record FDSE > .cache/status-fdse.log 2>&1; cat .cache/status-fdse.log
git add status/7series/FDSE.yaml && git commit -m "flops: record FDSE results and coverage" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: `coverage.uncovered` is exactly `[claim:FDSE.C8]`.

The history now reads model (Step 2) → tests (Step 4) → status (Step 4), with no rebase needed.

---

### Task 26: FDCE and FDPE (asynchronous control)

**Files:**
- Create: `models/xut_models/7series/fdce.py`, `models/xut_models/7series/fdpe.py`, and for each of FDCE and FDPE the test tree `tests/7series/register/<PRIM>/{test.yaml, README.md, vectors/gen.py, sv/tb_<prim>_gsr.sv, sv/tb_<prim>_x.sv, cocotb/cocotb_<prim>_random.py}`
- Modify: `test_flop_models.py` (`PRIMS = ["FDRE", "FDSE", "FDCE", "FDPE"]`), `status/7series/FDCE.yaml`, `status/7series/FDPE.yaml`

What is new here is the `async` port class:
- `CLR`/`PRE` changes are alone in their event and at least `async_sep_ps` from clock edges (spec §5.1, enforced by `VecBuilder.async_`);
- the golden model reports `-` while GSR and the control are both active;
- the generator adds the `_async` and `_recovery` tests.

- [ ] **Step 1: Extend `PRIMS` and confirm the new cases fail.** This includes `test_gsr_versus_async_control_is_undefined`, which now has parameters.

- [ ] **Step 2: Write the models** (clean-room, UG953 pp. 369–370 and 372–373):

```python
# SPDX-License-Identifier: Apache-2.0
"""FDCE golden model: UG953 v2026.1 pp. 369-370 (clean-room)."""

from ._common.flops import SdrFlop


class FDCE(SdrFlop):
    PRIM = "FDCE"
    CTRL = "CLR"  # asynchronous clear: overrides all inputs, Q Low (p369)
    CTRL_VALUE = 0
    CTRL_ASYNC = True
    INIT_DEFAULT = 0  # attribute table, p370
    PAGE = 369
    ATTR_PAGE = 370


MODEL = FDCE
```

```python
# SPDX-License-Identifier: Apache-2.0
"""FDPE golden model: UG953 v2026.1 pp. 372-373 (clean-room)."""

from ._common.flops import SdrFlop


class FDPE(SdrFlop):
    PRIM = "FDPE"
    CTRL = "PRE"  # asynchronous preset: overrides all inputs, Q High (p372)
    CTRL_VALUE = 1
    CTRL_ASYNC = True
    INIT_DEFAULT = 1  # attribute table, p373
    PAGE = 372
    ATTR_PAGE = 373


MODEL = FDPE
```

Run the model tests: all pass, including the async-only tests.

- [ ] **Step 3: Write the test files**

`tests/7series/register/FDCE/vectors/gen.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""FDCE vector generators (test.yaml: source: vectors/gen.py:<name>)."""

import flop_recipes

globals().update(flop_recipes.generators("FDCE"))
```

`tests/7series/register/FDPE/vectors/gen.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""FDPE vector generators (test.yaml: source: vectors/gen.py:<name>)."""

import flop_recipes

globals().update(flop_recipes.generators("FDPE"))
```

`tests/7series/register/FDCE/sv/tb_fdce_gsr.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDCE.L1.sv_gsr_midsim (body: _shared/flops/flop_gsr_tb.svh)
`define FLOP_TB tb_fdce_gsr
`define FLOP_PRIM FDCE
`define FLOP_CTRL CLR
`include "flop_gsr_tb.svh"
```

`tests/7series/register/FDCE/sv/tb_fdce_x.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDCE.L1.sv_x_inputs (body: _shared/flops/flop_x_tb.svh)
`define FLOP_TB tb_fdce_x
`define FLOP_PRIM FDCE
`define FLOP_CTRL CLR
`define FLOP_FORCED 1'b0
`define FLOP_ASYNC 1
`include "flop_x_tb.svh"
```

`tests/7series/register/FDPE/sv/tb_fdpe_gsr.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDPE.L1.sv_gsr_midsim (body: _shared/flops/flop_gsr_tb.svh)
`define FLOP_TB tb_fdpe_gsr
`define FLOP_PRIM FDPE
`define FLOP_CTRL PRE
`include "flop_gsr_tb.svh"
```

`tests/7series/register/FDPE/sv/tb_fdpe_x.sv`:

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// 7series.FDPE.L1.sv_x_inputs (body: _shared/flops/flop_x_tb.svh)
`define FLOP_TB tb_fdpe_x
`define FLOP_PRIM FDPE
`define FLOP_CTRL PRE
`define FLOP_FORCED 1'b1
`define FLOP_ASYNC 1
`include "flop_x_tb.svh"
```

`tests/7series/register/FDCE/cocotb/cocotb_fdce_random.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""7series.FDCE.L2.cocotb_random: constrained-random FDCE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdce_random(dut):
    await random_session(dut, "FDCE", cycles=2000)
```

`tests/7series/register/FDPE/cocotb/cocotb_fdpe_random.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""7series.FDPE.L2.cocotb_random: constrained-random FDPE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdpe_random(dut):
    await random_session(dut, "FDPE", cycles=2000)
```

Generate the metadata with `flop_tests.py FDCE FDPE`, then re-run it for `FDRE FDSE` so every `related` list is current.

- [ ] **Step 4: Validate the async stimulus before simulating**

```bash
uv run xut run '7series.FDCE.*' '7series.FDPE.*' --runner python > .cache/run-async-python.log 2>&1; tail -n 20 .cache/run-async-python.log
```

Expected: every vector test passes, meaning every generated `.xvec` validated.

Spot-check that `build/rtl/python/unisim-2025.2/7series.FDCE.L1.clear_async/cfg-init0/stim.xvec` has every `set in[<CLR bit>]` alone at its time, and at least 1000 ps from the nearest `edge` line:

```bash
uv run xut vec check build/rtl/python/unisim-2025.2/7series.FDCE.L1.clear_async/cfg-init0/stim.xvec --map build/rtl/python/unisim-2025.2/7series.FDCE.L1.clear_async/cfg-init0/dut/xut_dut.map.json > .cache/vec-check.log 2>&1; cat .cache/vec-check.log
```

Expected: no `error:` lines and `hw_renderable: yes`.

- [ ] **Step 5: Run, crosscheck and record both primitives**

- **Estimate:** 2 × (65 vector configurations + 4 for `_async`/`_recovery`) ≈ 144 Verilator builds ≈ 96 CPU-minutes. At `--jobs 40` that is about 3–6 minutes.
- **Cadence:** report every 60 s.

```bash
uv run xut run '7series.FDCE.*' '7series.FDPE.*' --jobs 40 > .cache/run-async.log 2>&1
uv run xut crosscheck '7series.FDCE.*' '7series.FDPE.*' --write-findings > .cache/xc-async.log 2>&1; echo "exit=$?"; cat .cache/xc-async.log
```

Handle findings as in Task 24, Step 2, against UG953 pp. 369–370 and 372–373. The GSR-versus-control conflict is `-` in the model, so it cannot produce a `doc-vs-model` finding. If the simulators disagree with *each other* there, that is a `sim-divergence` to record.

- [ ] **Step 6: Commit** in three pieces: model, then tests and findings, then status (`record` needs the tests committed first).

```bash
git add models tests/7series/register/_shared/flops/test_flop_models.py && git commit -m "flops: add FDCE and FDPE golden models (UG953 pp. 369-373)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git add tests/7series/register findings && git commit -m "flops: add FDCE and FDPE vector, sv and cocotb tests" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
uv run xut status record FDCE FDPE > .cache/status-async.log 2>&1; cat .cache/status-async.log
git add status/7series && git commit -m "flops: record FDCE and FDPE results and coverage" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: `coverage.uncovered` is exactly `[claim:FDCE.C8]` and `[claim:FDPE.C8]` respectively.

---

### Task 27: Whole-unit verification — PR E (the unit's single PR)

- [ ] **Step 1: Re-run the whole unit from a clean build directory**

```bash
rm -rf build/rtl
uv run xut run 'unit:flops' --jobs 40 > .cache/run-flops.log 2>&1
uv run xut run 'unit:flops' --model-source unisim-gh-2020.1 --runner python --runner iverilog --runner verilator --jobs 40 > .cache/run-flops-gh.log 2>&1
uv run xut crosscheck 'unit:flops' > .cache/xc-flops.log 2>&1; echo "exit=$?"; tail -n 40 .cache/xc-flops.log
```

The second run is the open-source model source (the submodule). Its results land under `build/rtl/<runner>/unisim-gh-2020.1/`, and crosscheck compares them only with each other, never with `unisim-2025.2` traces. A cross-version report is a separate, explicit step (spec §6.2) and is not part of step 2.

- **Estimate:** about 280 Verilator builds ÷ 40 jobs × 40 s ≈ 5–8 minutes. That is under 10 minutes, so report every 60 s. If the first ETA exceeds 10 minutes, switch to a 5-minute cadence.
- **Expected:** `exit=0`. Every disagreement is either absent or reported as `known-divergence` linked to an open finding.

- [ ] **Step 2: Status, lint and tests**

```bash
uv run xut status record --unit flops > .cache/status-flops.log 2>&1; cat .cache/status-flops.log
uv run xut status record --unit flops --model-source unisim-gh-2020.1 >> .cache/status-flops.log 2>&1; cat .cache/status-flops.log
uv run pytest -v > .cache/pytest.log 2>&1; tail -n 5 .cache/pytest.log
uv run xut lint --branch > .cache/lint.log 2>&1; cat .cache/lint.log
git status --porcelain > .cache/git-status.log 2>&1; cat .cache/git-status.log
```

Expected:
- no lint errors or warnings (every `related` target now exists);
- `git status` shows only the four status files as modified; each has `results` (unisim-2025.2) and `results_by_model_source.unisim-gh-2020.1`, and `measured.model_sources` lists both;
- `status/PROGRESS.md` is **not** modified (it is generated on `main` only).

- [ ] **Step 3: Commit, log, PR E**

```bash
git add status/7series && git commit -m "flops: record whole-unit results" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Write `log/<ts>-unit-7series-flops-complete.md` with the final matrix, the findings and the timings, and commit it. Then push and open the unit's **one** PR:

```bash
git push -u origin unit/7series/flops
gh pr create --base main --title "flops: FDRE/FDSE/FDCE/FDPE pilot" --body-file .cache/pr-e.md
```

The body lists every task's per-task review outcome, the Review Focus items 2–4 as they apply, and ends with the Claude Code line. Run the review gate (sequential reviewers). After the merge, the orchestrator runs on `main`:

```bash
uv run xut status generate > .cache/status-gen.log 2>&1; cat .cache/status-gen.log
git add status/PROGRESS.md status/TODO.md status/LOG.md status/PORTABILITY.md
git commit -m "status: regenerate" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review against the spec (performed while writing this plan)

- **§4.1 levels.** L0 (`smoke`, 16 configurations, short simulation), L1 (one test per claim, port behaviour and attribute), L2 (`exhaustive`, `random`, `cocotb_random`) are all delivered for the four flops. L3 is step 5.
- **§4.2 attribute sampling.** Every enumerated value is covered: the four 1-bit attributes, exhaustively in L0/L2. The `attr_sampling` of each test is recorded in `test.yaml`. There are no integer or bit-vector attributes on the flops, and no declared crosses beyond the full 16-way product.
- **§4.3 styles.**
  - Vector: generators → `.xvec` → the one generic testbench on every simulator (Tasks 7–10, 21).
  - sv: GSR and X tests emit `.xtr` through `xut_trace.svh` (Tasks 9, 22), in the common subset. `sv_deviations` exists in the schema (Task 8) and the flops need none.
  - cocotb: Icarus and Verilator (v5.048 from source, spec rev 3.1), emitting `.xtr` (Tasks 11, 15, 23).
  - Frozen failing seeds: `.xvec` sources are supported (Task 8), and the process is documented in `flops_cocotb.py`.
- **§5.1 port classes.**
  - Validated by `validate` (Task 5), with `inout` split, and `pad`/`drp` recorded in the map (Task 4).
  - `clock_out` refuses with a pointer to §5.4, which slots in later as wrapper observers.
  - `drp` is ready for the §5.5 transaction layer: its bits are tagged `drp`.
- **§5.2 wrapper.** `xut_dut` with `clk`/`in_vec`/`out_vec`, `map.json`, `DONT_TOUCH`/`KEEP_HIERARCHY`/`keep`, and the glbl channel through the testbench's writes to `glbl.*_int` (Tasks 4, 7).
- **§5.3 formats.**
  - `.xvec`: timed events in ps, `settle_ps`, free and stepped clocks, `simultaneous`, `hw_renderable` with reasons, and `sample`.
  - `.xtr`: per-bit values grouped by port, and don't-care `-` only in golden expectations (Tasks 2, 3, 5).
  - Additions resolved in this plan: `t=0` initialisation, `attr.*` header keys, `expect=reject`, `async_sep_ps`, and trace provenance.
- **§5.6 runner capabilities.** `x_observable` is used by `compare` and `diff`. Verilator runs twice with recorded X seeds (Task 15).
- **§6 flows and runners.**
  - The `rtl` flow only. `flow` is a field everywhere (`build/<flow>/…`, `RunContext.flow`, crosscheck's `flow-mismatch`), so step 4 adds flows without interface changes.
  - `python`, `xsim` (subshell), `iverilog` and `verilator` (container) runners are delivered.
  - `hw` has a declared place in `test.yaml`, `result.json` (`hw` field) and crosscheck.
- **§6.2 verilatorize.** The following are all covered (Tasks 12–16):
  - pyslang AST, full-cone triggers with enablers;
  - the shadow-register transform, with per-expression width-matched override nets;
  - loud failure with the model named;
  - `build/verilatorized/` only;
  - fixtures for all ten listed cases, plus the RST|PWRDWN cone, gate-primitive and sub-instance cones, both generate arms, packed ranges, and ten refusal cases;
  - analysis over every generate branch, elaboration-checked per generate configuration, and equivalence per used configuration;
  - the guarded `deassign` of spec rev 3.1;
  - a generated, mandatory equivalence stimulus: independent, coincident, pairwise and async-interaction pulses;
  - Icarus original-vs-transformed runs, with a mutation test proving the check can fail;
  - `iverilog-vz` on every verilator test;
  - `transform-bug` blocking;
  - lint when the equivalence check is missing;
  - model identity;
  - the portability table with triggers;
  - pinned XIL_* defines (recorded, default undefined).
- **§8 crosscheck.** All nine classes are classified, like-for-like by model source (the build path includes the model source; CI runs flops L0/L1 against the submodule). Findings are recorded as `findings/<PRIM>-<slug>.md` and linked from the README. `expected_divergence` never masks: listed disagreements are still reported as `known-divergence` (spec §8 rev 3.1). Weakening tests is explicitly forbidden in Task 24.
- **§9 coverage.** Bins are confirmed by golden-model reach (`Reach`, Task 6; `status record`, Task 18). Model code coverage is step 5.
- **§11 metadata and status.** `test.yaml` follows the spec plus `source`/`configs`. `status record` writes results, the tree hash, tools and coverage. Generated files are never committed on branches (Global Constraints; Tasks 16, 27).
- **§12 documentation.** Generated READMEs have every template section, with gaps listed per test. Lint checks `bins-accounted` and `gaps-present` (Task 18) on top of the step-1 rules.
- **§13 process.**
  - Branch types and worktrees, and a path-owned pilot, extended in Task 18 with `_shared/<unit>`.
  - Small prefixed commits with the trailer; one PR per branch (A–E), stacked bases, orchestrator-only `--force-with-lease` rebases; the review gate with sequential reviewers; infra merged first.
- **§14 no silent skips.** Every (test, runner) pair writes a `result.json`, and `error` is distinct from `fail` (Task 8).
- **§16 step 2 scope** is fully covered. Deliberately **not** in step 2:
  - clock observers (§5.4);
  - DRP transactions (§5.5);
  - the hardware harness and the `hw` runner (§7);
  - non-`rtl` flows and fasm2bels (§6, §6.1);
  - model code coverage (§9);
  - publishing images;
  - **`xut freeze-seed`** (spec §4.3), which would turn a failing cocotb seed into a committed `vectors/frozen/<seed>.xvec`. TODO(step 5, infra): `XutDut` must record every driven event as it happens (a `VecBuilder`-compatible log), and `xut freeze-seed <test-id> --cfg <cfg> --seed <n>` must write the `.xvec` plus a test.yaml entry. Until then, a failing seed is frozen by hand, and each cocotb and random test lists this in its `gaps`;
  - a cross-model-source comparison report (spec §6.2), beyond running both sources like-for-like.

  The interfaces above leave a place for each of them.

**Spec ambiguities resolved in this plan:**

1. **cocotb on Verilator — resolved by the owner-delegated controller ruling.** cocotb 2.0.1 refuses Verilator < 5.036, and spec rev 3 pinned apt 5.032. Ruling: cocotb-on-Verilator is required, so Verilator is pinned to **v5.048 built from the upstream git tag** (commit `d0aa828c217410fffc73d92077b6f4f54830357c`) in a multi-stage `xut-sim` build on the same base digest. iverilog stays apt `12.0-2+b1` and cocotb stays pip `2.0.1`. The spec is amended to rev 3.1. Task 1 pins cocotb running on Verilator with a positive smoke test, and also pins that v5.048 still rejects procedural `deassign`, the reason `xut verilatorize` exists. The glbl-as-second-top spike (Task 15, Step 1) runs against v5.048 and assumes nothing from the 5.032 research.
2. **Multi-configuration tests.** The run directory `build/<flow>/<runner>/<model-source>/<test-id>/` (model source per ambiguity 17) holds `trace.xtr`, `result.json` and `run.log` (spec §16 step 2). Here they are aggregates over per-configuration `cfg-<cfg>/` subdirectories, and trace labels are `<cfg>/<label>`.
3. **Initialisation before `settle_ps`.** Only `t=0 set` lines are allowed, so inverted control pins are inactive during power-up.
4. **Trace readability and provenance.** Traces are written as `<label>  <port>=<bits>` (`_` every 4 bits), with golden provenance after `|`.
5. **Shared unit test code.** It lives in `tests/<family>/<group>/_shared/<unit>/**`, a new owned path (Task 18), so the four flops share recipes, testbenches and the metadata generator.
6. **Where glbl lives.** glbl stays a second top level (spec §6). The testbench writes `glbl.*_int` for the glbl channel. A Verilator spike (Task 15, Step 1) decides the fallback: an in-testbench glbl instance, which UNISIM resolves by upward name lookup.
7. **Portability scope.** The table covers every `unisims/*.v` plus the `retarget/` models that are in the catalog, each under its default, generate-selecting and `IS_*_INVERTED` configurations. xsim is not in the smoke run, because it uses Vivado's precompiled library.
8. **Runner declarations** (controller ruling on PR #3 review item 1). `runners` values stay step 1's strings `"yes"|"no"|"unsupported"`, and reasons go in a separate `unsupported_reasons` map. The schema amendment is part of Task 8 (`infra/sim-runners`).
9. **`sv_x_inputs` on Verilator** (review item 11). Declared `"unsupported"` with a reason. A 2-state simulator randomises the `1'bx` stimulus per X seed (spec §5.6), so the undocumented checkpoints would differ by construction. That is a property of the stimulus, not a model `x-dependence` finding (§8). Its `iverilog-vz` companion is skipped with it, because it follows the Verilator declaration.
10. **Trigger tracing and generate branches** (controller rulings on review items 2 and 3). Tracing crosses gate primitives, continuous assigns and same-file sub-instances (over-approximated: outputs depend on all inputs). Any unresolvable driver makes the model `unsupported`. Analysis and rewrite cover every generate branch, and equivalence runs for the default plus every attribute configuration a test uses.
11. **Guarded `deassign`** (review item 4 and follow-up N1). `begin if (X__ovr_sel != 0) begin X__base = X; X__ovr_sel = 0; end end`. The outer `begin … end` prevents a dangling `else` when the `deassign` is an if-arm. Spec §6.2 step 2 is amended in rev 3.1.
12. **Nested generate constructs** (known limitation). `generate_configs` enumerates each generate `if`/`case` on its own. A generate construct nested inside another raises `TransformError("nested generate conditions ...")`, so the model is `unsupported` in the manifest and in `PORTABILITY.md`. It is never partially transformed. `xut lint` (`portability-agreement`, `verilatorize-equiv`) then rejects any test that declares `verilator: "yes"` for such a primitive. Lifting this means enumerating nested conditions under their parents' configurations, which is a later infra change.
13. **One PR per branch** (controller ruling on review (b) #1). `infra/sim-formats` (A), stacked `infra/sim-runners` (B), then `infra/verilatorize` (C) and `infra/crosscheck` (D) stacked on B, and one unit PR (E). The orchestrator rebases children onto `main` with `--force-with-lease`, and AGENTS.md is amended in Task 1.
14. **Status tree hash** (review (b) #2). It covers the test dir, `_shared/<unit>`, the unit's models and the overrides, and the dirty check covers the same set.
15. **Per-test gaps** (review (b) #3). Every test lists what it misses, READMEs show gaps per test, and lint `gaps-present` enforces it.
16. **Known divergences** (review (b) #4). `expected_divergence` never masks a bit; crosscheck reports `known-divergence` referencing the finding, and fails only on unlisted ones. Spec §8 is amended in rev 3.1.
17. **Model source in the build path** (review (b) #5). `build/<flow>/<runner>/<model-source>/<test-id>/`; Task 27 also runs the unit on `unisim-gh-2020.1`, and CI runs flops L0/L1 vector tests on iverilog against the submodule.
18. **Hardware eligibility per configuration.** `config_exclusions` keeps the non-`IS_D_INVERTED` configurations of L0/L2 on `hw`; L2 no longer pulses GSR.
