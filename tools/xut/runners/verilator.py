# SPDX-License-Identifier: Apache-2.0
"""Verilator runner (container, ``--timing``), with two X-seed runs per configuration, and
its ``iverilog-vz`` companion (spec §5.6, §6, §6.2).

**Model gate** (spec §6.2). Verilator only ever sees a UNISIM model after
``xut verilatorize``: every configuration first calls ``ensure_model(model source,
primitive, attrs)`` (``xut.verilatorize.driver``), which transforms the primitive on demand
and runs the Icarus equivalence check for this configuration when the manifest has no
result for it. Then (ruling S35.1):

- ``unsupported``: ``error "verilatorize cannot transform <PRIM>: <reason>"``;
- ``transformed`` with an equivalence ``fail``: ``error "transform-bug: ..."``;
- ``transformed`` with an equivalence ``error`` (or anything but ``pass``): ``error
  "equivalence check error for <PRIM> <config>: <reason> blocks Verilator results (spec
  §6.2)"``. A non-pass is never a pass or a skip;
- ``unchanged`` (no procedural ``assign``/``deassign``): the original model is used.

``attrs`` is the configuration's attributes (the ``.xvec`` ``attr.*`` header, or the
sv/cocotb ``configs`` entry), keyed by ``driver.model_attrs``. An ``expect=reject``
configuration is gated on the **default** configuration's equivalence instead: its own
attributes are illegal, so the model stops itself and no equivalence verdict can exist.

**x stimulus** (ruling S35.2). A 2-state simulator cannot drive ``x``/``z``: a vector
configuration whose stimulus sets any input bit to x or z is an ``error``
(``X_STIMULUS``), never a skip, unless the test declares verilator unsupported.

**Build** (vector style), once per configuration in its ``cfg-<cfg>/`` directory under the
run root (``build/<flow>/verilator/<model-source>/<id>/``)::

    verilator --binary --timing -j 2 --timescale 1ps/1ps -Wno-fatal -Wno-MULTITOP
      --x-assign unique --x-initial unique -Mdir obj -o simx -I. -Idut
      -y <vz_dir> -y <ms>/unisims [-y <ms>/retarget] +libext+.v [+define+K=V ...]
      xut_vector_tb.sv dut/xut_dut.v <ms>/glbl.v

Warnings are not waived beyond that (ruling S35.5): they are written to ``build.log`` and
never fail the build (``-Wno-fatal``); lint and style warnings are kept in the log too. A
failed build is ``error "compile failed: <first %Error line>"``; ``TRISTATE`` below
explains one inherent case.

**glbl** is a second top (spec §6): the Task 15 spike showed Verilator 5.048 elaborates
``glbl`` beside ``xut_vector_tb`` (``-Wno-MULTITOP``), the model's upward ``glbl.GSR`` and
the testbench's ``glbl.GSR_int`` writes both reaching it (``glbl_instance = False``,
pinned by ``test_glbl_mode``). cocotb tops instantiate ``glbl`` themselves.

**Two X seeds** (spec §5.6). For each ``s`` in ``x_seeds(stimulus seed)``, in
``xseed-<s>/``: ``../obj/simx +verilator+seed+<s> +verilator+rand+reset+2`` (with
``--x-initial unique``, every uninitialised variable gets a seed-dependent value). The
configuration's ``trace.xtr`` is the first seed's trace. **Both** seeds' traces are
compared with ``expected.xtr`` (``x_observable=False``): a defined expected bit that either
seed gets wrong fails the configuration. The two traces are then compared with each other
(``xtr.diff``) into ``xdep.json`` ``{"x_dependence": bool, "mismatches": [...]}``; a
difference is ``x-dependence`` (only possible where ``expected.xtr`` masks the bit with
``-``, or where the configuration fails anyway). ``finish`` records ``seeds.x`` and
``x_dependence`` (``null`` when no configuration compared two runs). An ``expect=reject``
configuration runs once (``reject_check``) and has no X-seed comparison.

**sv style**: the same build with ``-G<NAME>=<value>`` per attribute, the testbench
``sv/<stem>.sv`` (top ``<stem>``, ``glbl`` a second top), ``-I`` hdl/, the shared dirs and
the testbench's directory, and ``+define+XUT_SEED=64'd<seed>``; each X seed runs the one
binary in its own directory and is judged by ``sv_check``. **cocotb style**:
``cocotb_run.py --sim verilator --x-seed <s>`` once per X seed, each in ``xseed-<s>/``
with the verilatorized directory first on the library path; each seed is judged by
``cocotb_check``. For both, the configuration's status is the worse of the two seeds'.

Build and run timeouts are the test's (``timeout_for``: test.yaml ``timeout_s``,
``--timeout``, 600 s). Verilator builds are slow: use ``xut run --jobs 40`` or more for
full runs (88 CPUs).

``TRISTATE`` (ruling S35.3; Task 13 report, S29.3). Verilator 5.048's V3Tristate lowers a
case comparison with z, such as ``CE === 1'bz`` (the FD* models test for an unconnected
CE and R this way), into a comparison of the port's enable, which turns the input port
into a tristate. For a non-top module the instance pin then needs an ``__out`` variable an
input does not have, and Verilator stops with "Unsupported: tristate in top-level IO:
'CE'" (V3Tristate.cpp, pin handling). It happens for any model instantiated below the top
that compares an input with z, whatever the wrapper connects (a bit select, a whole port
or an intermediate wire all fail identically), so it is neither the testbench's nor the
transform's doing. The runner reports it as an ``error`` whose reason says so.

``IverilogVzRunner`` (``iverilog-vz``) is Icarus on the verilatorized models: every test
that runs on ``verilator`` also runs here (spec §6.2; ``xut run`` adds it). Its
``lib_first`` puts ``vz_dir`` before the model source. A primitive the transform
refused is ``skip "model not transformed: <reason>"``. It lives in this module, not in
``iverilog.py``: the transform's tool hash covers every module the verilatorize package
imports (``iverilog.py`` among them), and it must not change with the runner.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from xut.catalog import model as catalog_model
from xut.container import Executor, executor_for
from xut.formats import xtr, xvec
from xut.runners.base import (
    ConfigResult,
    RunContext,
    Runner,
    RunResult,
    prepare_vector,
    python_dir,
    timeout_for,
    trace_header,
    worst,
)
from xut.runners.iverilog import IverilogRunner, param_value
from xut.runners.reject import SimOutcome, reject_check
from xut.runners.sim import (
    HDL,
    ContainerSim,
    cfg_attrs,
    classify_run,
    cocotb_check,
    cocotb_command,
    sv_check,
    sv_seed_define,
    vector_check,
)
from xut.testspec import TestCase
from xut.validate import validate
from xut.verilatorize.driver import ModelEntry, ensure_model, model_attrs, vz_dir
from xut.verilatorize.equiv import config_key
from xut.wrap import DutMap, spec_from_catalog, write_dut

__all__ = [
    "TRISTATE",
    "X_STIMULUS",
    "IverilogVzRunner",
    "VerilatorRunner",
    "blocked",
    "build_failure",
    "config_attrs",
    "ensure_model",
    "verilator_argv",
    "x_seeds",
]

X_STIMULUS = "2-state simulator cannot apply x stimulus"
TRISTATE = "tristate in top-level IO"
_TRISTATE_WHY = (
    " (inherent: Verilator 5.048 turns an input port that the model compares with z, "
    "e.g. `CE === 1'bz`, into a tristate, which it supports only on the top module; "
    "not caused by the testbench or the transform; see xut.runners.verilator)"
)
_MAX = 300


def x_seeds(seed: int) -> tuple[int, int]:
    """The two Verilator X-initialisation seeds of a run with stimulus seed ``seed``:
    distinct, and never 0 (``+verilator+seed+0`` means "pick one at random")."""
    return ((2 * seed + 1) % 2**31 or 1, (2 * seed + 2) % 2**31 or 2)


def config_attrs(case: TestCase, cfg: str, ctx: RunContext) -> tuple[dict, bool]:
    """``(attrs, reject)``: the configuration's attributes (a vector configuration's
    ``.xvec`` header, from the python run; else test.yaml ``configs``) and whether it is an
    ``expect=reject`` configuration."""
    if case.style == "vector":
        vec = xvec.load(python_dir(ctx, case) / f"cfg-{cfg}" / "stim.xvec")
        return dict(vec.attrs), vec.expect == "reject"
    return cfg_attrs(case, cfg), False


def blocked(e: ModelEntry, prim: str, key: str) -> str | None:
    """Why ``e`` blocks a Verilator result for configuration ``key`` (ruling S35.1), or
    None. Only an equivalence ``pass`` lets a transformed model through."""
    if e.status == "unsupported":
        return f"verilatorize cannot transform {prim}: {e.reason}"
    if e.status != "transformed":
        return None
    status, why = e.equiv.get(key), e.equiv_reason.get(key, "")
    if status == "pass":
        return None
    if status == "fail":
        return (
            f"transform-bug: Icarus equivalence fail for {prim} {key} blocks Verilator "
            f"results (spec §6.2): {why or 'see the equivalence result.json'}"
        )
    return (
        f"equivalence check error for {prim} {key}: {why or status or 'no result'} blocks "
        "Verilator results (spec §6.2)"
    )


def build_failure(text: str) -> str:
    """The reason for a failed Verilator build: its first ``%Error`` line, and, for the
    inherent tristate case (module docstring), the explanation."""
    errors = [ln.strip() for ln in text.splitlines() if ln.lstrip().startswith("%Error")]
    why = f"compile failed: {errors[0][:_MAX] if errors else 'no %Error line (see build.log)'}"
    if any(TRISTATE in e for e in errors):
        why += _TRISTATE_WHY
    return why


def verilator_argv(
    ex: Executor, ctx: RunContext, vz: Path, sources: list[str], extra: list[str]
) -> list[str]:
    """The Verilator build command (module docstring): the verilatorized directory first on
    the library path, then the model source; ``extra`` goes before the libraries."""
    libs = [a for d in (vz, *ctx.model_source.search) for a in ("-y", ex.guest(d))]
    defs = [f"+define+{k}" if v == "" else f"+define+{k}={v}" for k, v in ctx.defines.items()]
    return [
        "verilator", "--binary", "--timing", "-j", "2", "--timescale", "1ps/1ps",
        "-Wno-fatal", "-Wno-MULTITOP", "--x-assign", "unique", "--x-initial", "unique",
        "-Mdir", "obj", "-o", "simx", *extra, *libs, "+libext+.v", *defs, *sources,
    ]  # fmt: skip


def _x_inputs(src: Path) -> bool:
    """The python run's stimulus in ``src`` drives x or z on some input (a missing one is
    left to ``prepare_vector``, which says why)."""
    if not (src / "stim.xvec").is_file():
        return False
    m = DutMap.load(src / "dut" / "xut_dut.map.json")
    return validate(xvec.load(src / "stim.xvec"), m).x_inputs


def _log(path: Path) -> Callable[[str], None]:
    def write(line: str) -> None:
        with path.open("a") as f:
            f.write(line + "\n")

    return write


def _pair(first: ConfigResult, second: ConfigResult, s2: int) -> ConfigResult:
    """The configuration's result from both X-seed runs: the first seed's, made worse by
    the second's (whose reason is then named with its seed)."""
    if worst([first.status, second.status]) == first.status:
        return first
    reason = f"X seed {s2}: {second.reason or second.status}"
    if first.reason:
        reason = f"{first.reason}; {reason}"
    first.status, first.reason = second.status, reason
    return first


def _xdep(cd: Path, a: xtr.Trace, b: xtr.Trace, seeds: tuple[int, int]) -> None:
    mm = [str(x) for x in xtr.diff(a, b)]
    doc = {"x_dependence": bool(mm), "seeds": list(seeds), "mismatches": mm}
    (cd / "xdep.json").write_text(json.dumps(doc, indent=1) + "\n")


class VerilatorRunner(ContainerSim, Runner):
    name = "verilator"
    x_observable = False
    #: glbl is a second top (spec §6), never an instance: the Task 15 spike (module docstring)
    glbl_instance: ClassVar[bool] = False

    def run_config(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext) -> ConfigResult:
        ex = executor_for(ctx.model_source, ctx.root)
        timeout = timeout_for(case, ctx)
        seeds = x_seeds(self.stimulus_seed(case, ctx))
        if case.style == "vector":
            return self._vector(case, cfg, cd, ctx, ex, timeout, seeds)
        attrs = cfg_attrs(case, cfg)
        why = self._gate(case, cfg, cd, ctx, attrs)
        if why is not None:
            return ConfigResult(cfg, "error", why)
        if case.style == "cocotb":
            return self._cocotb(case, cfg, cd, ctx, ex, timeout, seeds, attrs)
        return self._sv(case, cfg, cd, ctx, ex, timeout, seeds, attrs)

    def _gate(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext, attrs: dict) -> str | None:
        """``blocked`` for this configuration, after ``ensure_model`` (logged to run.log)."""
        ms = ctx.model_source
        e = ensure_model(ms, case.prim, attrs, root=ctx.root, log=_log(cd / "run.log"))
        if e.status != "transformed":
            return blocked(e, case.prim, "")
        return blocked(e, case.prim, config_key(model_attrs(ms, case.prim, attrs)))

    def _build(
        self, ex: Executor, cd: Path, argv: list[str], timeout: int
    ) -> tuple[bool, str, str | None]:
        """Build into ``cd/obj``, the output in ``cd/build.log``: ``(ok, output, reason)``."""
        rc, text = IverilogRunner.step(ex, argv, cd, cd / "build.log", timeout)
        ok = rc == 0 and (cd / "obj" / "simx").is_file()
        with (cd / "run.log").open("a") as f:
            f.write(f"verilator build: exit {rc} (full output in build.log)\n")
            f.writelines(f"{ln}\n" for ln in text.splitlines() if ln.startswith("%Error"))
        return ok, text, None if ok else build_failure(text)

    def _run_seed(
        self, ex: Executor, cd: Path, s: int, timeout: int, files: tuple[str, ...] = ()
    ) -> tuple[Path, int, str]:
        """Run the built binary with X seed ``s`` in ``cd/xseed-<s>/`` (``files`` copied
        there first): ``(dir, exit code, output)``."""
        sd = cd / f"xseed-{s}"
        sd.mkdir()
        for f in files:
            shutil.copy(cd / f, sd / f)
        argv = ["../obj/simx", f"+verilator+seed+{s}", "+verilator+rand+reset+2"]
        rc, text = IverilogRunner.step(ex, argv, sd, sd / "run.log", timeout)
        with (cd / "run.log").open("a") as f:
            f.write(f"===== X seed {s}: exit {rc}\n{text}")
        return sd, rc, text

    def _vector(
        self,
        case: TestCase,
        cfg: str,
        cd: Path,
        ctx: RunContext,
        ex: Executor,
        timeout: int,
        seeds: tuple[int, int],
    ) -> ConfigResult:
        if _x_inputs(python_dir(ctx, case) / f"cfg-{cfg}"):  # before any expectation
            return ConfigResult(cfg, "error", X_STIMULUS)
        vec, m, comp, exp, header = prepare_vector(cd, case, cfg, ctx, self.name)
        reject = vec.expect == "reject"
        why = self._gate(case, cfg, cd, ctx, {} if reject else dict(vec.attrs))
        if why is not None:
            return ConfigResult(cfg, "error", why)
        vz = vz_dir(ctx.model_source, ctx.root)
        sources = ["xut_vector_tb.sv", "dut/xut_dut.v", ex.guest(ctx.model_source.glbl)]
        argv = verilator_argv(ex, ctx, vz, sources, ["-I.", "-Idut"])
        ok, ctext, bad = self._build(ex, cd, argv, timeout)
        if reject:
            rc, rtext = None, ""
            if ok:
                _, rc, rtext = self._run_seed(ex, cd, seeds[0], timeout, ("stim.memh", "stim.xvec"))
            return reject_check(cd, SimOutcome(ok, ctext, rc, rtext), vec.illegal, header)
        if not ok:
            return ConfigResult(cfg, "error", bad)
        runs = [self._run_seed(ex, cd, s, timeout, ("stim.memh", "stim.xvec")) for s in seeds]
        for (_, rc, rtext), s in zip(runs, seeds, strict=True):
            r = classify_run(cfg, SimOutcome(True, ctext, rc, rtext))
            if r is not None:
                r.reason = f"X seed {s}: {r.reason}"
                return r
        (sd1, _, t1), (sd2, _, t2) = runs
        shutil.copy(sd1 / "raw.txt", cd / "raw.txt")
        first = vector_check(cd, m, comp.labels, exp, header, self.x_observable, t1)
        second = vector_check(sd2, m, comp.labels, exp, header, self.x_observable, t2)
        _xdep(cd, xtr.load(cd / "trace.xtr"), xtr.load(sd2 / "trace.xtr"), seeds)
        return _pair(first, second, seeds[1])

    def _sv(
        self,
        case: TestCase,
        cfg: str,
        cd: Path,
        ctx: RunContext,
        ex: Executor,
        timeout: int,
        seeds: tuple[int, int],
        attrs: dict,
    ) -> ConfigResult:
        source = case.test_dir / str(case.source)
        seed = self.stimulus_seed(case, ctx)
        header = {**trace_header(self.name, case, cfg, ctx), "seed": str(seed)}
        extra = [
            *(f"-G{k}={param_value(k, v)}" for k, v in attrs.items()),
            *(f"-I{ex.guest(p)}" for p in (HDL, *case.shared_dirs, source.parent)),
            f"+define+XUT_SEED={sv_seed_define(seed)}",
        ]
        sources = [ex.guest(source), ex.guest(ctx.model_source.glbl)]
        argv = verilator_argv(ex, ctx, vz_dir(ctx.model_source, ctx.root), sources, extra)
        ok, ctext, bad = self._build(ex, cd, argv, timeout)
        if not ok:
            return ConfigResult(cfg, "error", bad)
        results, traces = [], []
        for s in seeds:
            sd, rc, rtext = self._run_seed(ex, cd, s, timeout)
            r = classify_run(cfg, SimOutcome(True, ctext, rc, rtext), need_done=False)
            results.append(r if r is not None else sv_check(sd, rtext, header))
            traces.append(sd / "trace.xtr")
        return self._seeds_done(cd, cfg, seeds, results, traces)

    def _cocotb(
        self,
        case: TestCase,
        cfg: str,
        cd: Path,
        ctx: RunContext,
        ex: Executor,
        timeout: int,
        seeds: tuple[int, int],
        attrs: dict,
    ) -> ConfigResult:
        seed = self.stimulus_seed(case, ctx)
        header = {**trace_header(self.name, case, cfg, ctx), "seed": str(seed)}
        entry = catalog_model.load_entry(case.family, case.prim, ctx.root)
        vz = vz_dir(ctx.model_source, ctx.root)
        results, traces = [], []
        for s in seeds:
            sd = cd / f"xseed-{s}"
            write_dut(spec_from_catalog(entry, cfg, attrs), sd / "dut", cocotb_top=True)
            argv, env = cocotb_command(
                ex, "verilator", case, sd, ctx, self.name, seed, (vz,), x_seed=s
            )
            rc = ex.run(argv, cwd=sd, log=sd / "run.log", timeout_s=timeout, env=env)
            with (cd / "run.log").open("a") as f:
                f.write(f"===== X seed {s}: cocotb_run exit {rc} (see xseed-{s}/run.log)\n")
            results.append(cocotb_check(sd, rc, seed, header))
            traces.append(sd / "trace.xtr")
        return self._seeds_done(cd, cfg, seeds, results, traces)

    def _seeds_done(
        self,
        cd: Path,
        cfg: str,
        seeds: tuple[int, int],
        results: list[ConfigResult],
        traces: list[Path],
    ) -> ConfigResult:
        """sv/cocotb: the first seed's trace is the configuration's; both are compared for
        x-dependence when both exist; the result is the worse of the two."""
        if traces[0].is_file():
            shutil.copy(traces[0], cd / "trace.xtr")
        if all(t.is_file() for t in traces):
            try:
                _xdep(cd, xtr.load(traces[0]), xtr.load(traces[1]), seeds)
            except xtr.XtrError as e:
                return ConfigResult(cfg, "error", f"malformed trace.xtr: {e}")
        return _pair(results[0], results[1], seeds[1])

    def finish(self, case: TestCase, ctx: RunContext, d: Path, res: RunResult) -> None:
        stim = res.seeds.get("stimulus")
        res.seeds["x"] = list(x_seeds(stim if isinstance(stim, int) else 0))
        flags = [
            json.loads(p.read_text())["x_dependence"] for p in sorted(d.glob("cfg-*/xdep.json"))
        ]
        res.x_dependence = any(flags) if flags else None


class IverilogVzRunner(IverilogRunner):
    """Icarus on verilatorized UNISIM: guards every verilator result (spec §6.2)."""

    name = "iverilog-vz"

    def _entry(
        self, case: TestCase, cfg: str, ctx: RunContext, log: Callable[[str], None]
    ) -> ModelEntry:
        attrs, reject = config_attrs(case, cfg, ctx)
        return ensure_model(
            ctx.model_source, case.prim, {} if reject else attrs, root=ctx.root, log=log
        )

    def run_config(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext) -> ConfigResult:
        e = self._entry(case, cfg, ctx, _log(cd / "run.log"))
        if e.status == "unsupported":
            return ConfigResult(cfg, "skip", f"model not transformed: {e.reason}")
        return super().run_config(case, cfg, cd, ctx)

    def lib_first(self, case: TestCase, cfg: str, ctx: RunContext) -> tuple[Path, ...]:
        """``vz_dir`` first. ``ensure_model`` (cached: ``run_config`` already did the work)
        makes sure the primitive's copy is current; the value is a local of the caller,
        never stored on ``self``: runner jobs are threads."""
        self._entry(case, cfg, ctx, print)
        return (vz_dir(ctx.model_source, ctx.root),)
