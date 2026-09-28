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
      --x-assign unique --x-initial unique -fno-dedup -Mdir obj -o simx -I. -Idut
      -y <vz_dir> -y <ms>/unisims [-y <ms>/retarget] +libext+.v [+define+K=V ...]
      xut_vector_tb.sv dut/xut_dut.v <ms>/glbl.v

Warnings are not waived beyond that (ruling S35.5): they are written to ``build.log`` and
never fail the build (``-Wno-fatal``); lint and style warnings are kept in the log too. A
failed build is ``error "compile failed: <first %Error line>"``; ``TRISTATE`` below
explains one inherent case.

``-fno-dedup`` (``OPT_FLAGS``; the cocotb launcher's builds carry it too). Verilator
5.048's V3Gate dedupe, which merges identical logic, stops with "Internal Error: ...
V3Gate.cpp:974: Consumer doesn't match lhs of assign" on a UNISIM LUT4, LUT5, LUT6 or
LUT6_2 whose output is constant (INIT all zeros or all ones; for LUT6_2 a uniform lower
half), on both model sources. Those models compute O with nested calls of a mux function
over INIT slices, which a constant INIT makes identical; LUT1-LUT3 use a UDP instead and
are unaffected. ``-fno-dedup`` turns off only that sub-pass (``-fno-gate`` would turn off
all of V3Gate; no other ``-fno-*`` option avoids the error). An optimisation pass changes
no semantics: every other Verilator result is byte-identical with and without it
(trace.xtr, raw.txt, xdep.json, per-configuration status; the infra/verilator-gate log).
Pinned by ``test_constant_output_lut4_builds_and_simulates``, whose control build without
the flag still fails: when a Verilator upgrade makes it pass, the flag can be reconsidered.

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
``--timeout``, 600 s). Verilator builds are slow: use the most ``xut run --jobs`` the
memory budget allows for full runs (``xut.container.max_jobs``: 25 at the defaults).

``TRISTATE`` (ruling S35.3; Task 13 report, S29.3). Verilator 5.048's V3Tristate lowers a
case comparison with z, such as ``CE === 1'bz`` (the FD* models test for an unconnected
CE and R this way), into a comparison of the port's enable, which turns the input port
into a tristate. For a non-top module the instance pin then needs an ``__out`` variable an
input does not have, and Verilator stops with "Unsupported: tristate in top-level IO:
'CE'" (V3Tristate.cpp, pin handling). It happens for any model instantiated below the top
that compares an input with z, whatever the wrapper connects (a bit select, a whole port
or an intermediate wire all fail identically), so it is neither the testbench's nor the
transform's doing. Ruling S38 answers it in the transform: ``xut verilatorize`` rewrites
every such comparison of an input port of the model to its constant for a driven input
(``xut.verilatorize.zcmp``), so the error remains only for a comparison the syntax tree
cannot see (code that a define such as ``XIL_TIMING`` enables); the runner reports it as an
``error`` whose reason says so.

**Every input driven** (ruling S38). The z-compare rewrite is exact only when every input
of the model is driven. For a model the manifest records with ``zcmp`` among its
``rewrites``, ``drive_guard`` makes the configuration an ``error`` (both runners) when the
wrapper leaves an input unconnected or the stimulus drives z (an sv testbench: when an
instance of the primitive leaves an input open, ties it to z, or connects it to a net that
can float z, such as a wire nothing drives: ``xut.runners.sv_nets``).

``IverilogVzRunner`` (``iverilog-vz``) is Icarus on the verilatorized models: every test
that runs on ``verilator`` also runs here (spec §6.2; ``xut run`` adds it). Its
``lib_first`` puts ``vz_dir`` before the model source. A primitive the transform
refused (or a model of its hierarchy) is ``skip "model not transformed: <reason>"``.

The transform's tool hash (``driver.tool_sources``) covers every module the verilatorize
package imports. The equivalence check imports ``xut.runners``, whose ``__init__`` imports
this module, so the hash covers this runner too (review M2): editing it re-transforms and
re-checks every model once. That errs on the safe side (a redo, never a stale copy).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import pyslang

from xut.catalog import model as catalog_model
from xut.container import Executor, executor_for
from xut.errors import XutError
from xut.formats import xtr, xvec
from xut.modelsrc import ModelSource
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
from xut.runners.sv_nets import Nets
from xut.testspec import TestCase
from xut.validate import validate
from xut.verilatorize import zcmp
from xut.verilatorize.driver import (
    ModelEntry,
    descendants_blocked,
    ensure_model,
    instance_attrs,
    model_attrs,
    model_files,
    model_instances,
    undriven_inputs,
    vz_dir,
)
from xut.wrap import DutMap, build_map, spec_from_catalog, write_dut

__all__ = [
    "TRISTATE",
    "X_STIMULUS",
    "IverilogVzRunner",
    "VerilatorRunner",
    "blocked",
    "build_failure",
    "config_attrs",
    "gate_config",
    "sv_instances",
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
#: Optimisations disabled in every Verilator build, vector, sv and cocotb alike (module
#: docstring, ``-fno-dedup``). ``xut/hdl/cocotb_run.py`` repeats them (pinned by
#: test_runner_cocotb).
OPT_FLAGS = ("-fno-dedup",)
_SX = pyslang.syntax.SyntaxKind


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


def refused(e: ModelEntry, prim: str) -> str | None:
    """Why no Verilator result can exist for ``prim``: verilatorize refused it, or a model
    of its hierarchy (which Verilator would then read unmodified; ruling S45)."""
    if e.status == "unsupported":
        return f"verilatorize cannot transform {prim}: {e.reason}"
    if e.depends_on_unsupported:
        return (
            f"verilatorize cannot transform {', '.join(e.depends_on_unsupported)} in the "
            f"hierarchy of {prim} (see the manifest; ruling S45)"
        )
    return None


def blocked(
    e: ModelEntry,
    prim: str,
    key: str,
    lookup: Callable[[str], ModelEntry | None] | None = None,
) -> str | None:
    """Why ``e`` blocks a Verilator result for configuration ``key`` (rulings S35.1, S45,
    S50), or None. Only an equivalence ``pass`` lets a gated model (transformed, or over a
    transformed dependency) through, and only when every transformed descendant also has a
    ``pass`` for the parameterisation this configuration instantiates it with
    (``driver.descendants_blocked``; ``lookup`` gives a descendant's entry, and without it a
    model with transformed descendants is blocked: fail closed)."""
    why = refused(e, prim)
    if why is not None or not e.gated:
        return why
    status, why = e.equiv.get(key), e.equiv_reason.get(key, "")
    if status == "fail":
        return (
            f"transform-bug: Icarus equivalence fail for {prim} {key} blocks Verilator "
            f"results (spec §6.2): {why or 'see the equivalence result.json'}"
        )
    if status != "pass":
        return (
            f"equivalence check error for {prim} {key}: {why or status or 'no result'} blocks "
            "Verilator results (spec §6.2)"
        )
    kid = descendants_blocked(e, key, lookup or (lambda _m: None))
    if kid is None:
        return None
    kstatus, kwhy = kid
    return (
        f"{'transform-bug: ' if kstatus == 'fail' else ''}equivalence of {prim} {key} is "
        f"blocked by its hierarchy: {kwhy}; blocks Verilator results (spec §6.2)"
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
        *OPT_FLAGS, "-Mdir", "obj", "-o", "simx", *extra, *libs, "+libext+.v", *defs, *sources,
    ]  # fmt: skip


def _x_inputs(src: Path) -> bool:
    """The python run's stimulus in ``src`` drives x or z on some input (a missing one is
    left to ``prepare_vector``, which says why)."""
    if not (src / "stim.xvec").is_file():
        return False
    m = DutMap.load(src / "dut" / "xut_dut.map.json")
    return validate(xvec.load(src / "stim.xvec"), m).x_inputs


@dataclass(frozen=True)
class SvInstance:
    """One instance of a UNISIM model in an elaborated sv testbench (rulings S38, S45, S50)."""

    path: str
    attrs: dict[str, object]  # every non-local parameter, as a Verilog literal
    undriven: list[str]  # input ports with no connection
    zdriven: list[str]  # input ports connected to a constant holding a z bit
    #: input ports connected to something that can carry z: "<port> (net <path> has no
    #: driver)", or another z source (``xut.runners.sv_nets``; Task 15 re-review N1)
    floating: list[str] = field(default_factory=list)
    model: str = ""  # the model it instantiates
    #: below another model's instance (its connections are the model's, not the testbench's)
    nested: bool = False


def _sv_bag(case: TestCase, ctx: RunContext, seed: int, attrs: dict | None) -> pyslang.Bag:
    """The runner's preprocessor options for the sv testbench (include dirs, defines,
    ``XUT_SEED``) and ``attrs`` as the top's parameter overrides (Verilator's ``-G``)."""
    source = case.test_dir / str(case.source)
    pp = pyslang.parsing.PreprocessorOptions()
    pp.additionalIncludePaths = [str(d) for d in (HDL, *case.shared_dirs, source.parent)]
    pp.predefines = [
        *(k if v == "" else f"{k}={v}" for k, v in ctx.defines.items()),
        f"XUT_SEED={sv_seed_define(seed)}",
    ]
    opts = pyslang.ast.CompilationOptions()
    opts.paramOverrides = [f"{k}={param_value(k, v)}" for k, v in (attrs or {}).items()]
    return pyslang.Bag([pp, opts])


def sv_models(case: TestCase, ctx: RunContext, prim: str, seed: int) -> list[str]:
    """``prim`` and every model of the model source the sv testbench instantiates
    (preprocessed: includes and macros), with their hierarchies (syntax only)."""
    from xut.verilatorize.driver import hierarchy

    source = case.test_dir / str(case.source)
    bag = _sv_bag(case, ctx, seed, None)
    tree = pyslang.syntax.SyntaxTree.fromFile(str(source), pyslang.SourceManager(), bag)
    names: set[str] = {prim}
    todo = [tree.root]
    while todo:
        n = todo.pop()
        if n.kind == _SX.HierarchyInstantiation:
            names.add(n.type.valueText)
        todo += [c for c in n if isinstance(c, pyslang.syntax.SyntaxNode)]
    return hierarchy(ctx.model_source, sorted(names & set(model_files(ctx.model_source))))


def sv_instances(
    case: TestCase,
    ctx: RunContext,
    prim: str,
    seed: int,
    attrs: dict | None = None,
    *,
    need_prim: bool = True,
) -> list[SvInstance]:
    """Every instance of a UNISIM model of the model source in the elaborated sv testbench
    of ``case`` (rulings S45, S50): its source is preprocessed with the runner's include dirs
    (``hdl/``, ``case.shared_dirs``, the testbench's directory) and defines, so an instance
    in an included ``.svh`` or named through a macro (``FLOP_PRIM``) is found (review I1),
    and elaborated with glbl and the hierarchies of the models it instantiates (originals),
    with ``attrs`` (the configuration's attributes) as the top's parameter overrides, the
    values Verilator's ``-G`` receives, to read each instance's parameters and connections.
    An input connected to a testbench net or variable that can carry z
    (``xut.runners.sv_nets``) is listed in ``floating``. Raises ``XutError`` (fail closed)
    when it does not elaborate cleanly, an attribute is not a parameter of the testbench's
    top, or (``need_prim``) no instance of ``prim`` is found."""
    from xut.catalog.unisim import is_benign

    ms, source = ctx.model_source, case.test_dir / str(case.source)
    # the tops are found by elaboration (the testbench and glbl): pyslang keeps topModules
    # as string views, which Python temporaries do not outlive
    bag = _sv_bag(case, ctx, seed, attrs)
    sm = pyslang.SourceManager()  # a fresh one: never a cached text of the file
    files = model_files(ms)
    comp = pyslang.ast.Compilation(bag)
    paths = [source, ms.glbl, *(files[m] for m in sv_models(case, ctx, prim, seed))]
    for f in paths:
        comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(f), sm, bag))
    models = {str(Path(f).resolve()) for f in paths[1:]}

    def benign(d: pyslang.Diagnostic) -> bool:
        # a model's benign diagnostics (e.g. an unknown secureip module inside UNISIM);
        # never the testbench's: an unknown module there fails closed
        where = str(Path(sm.getFullPath(d.location.buffer)).resolve())
        return is_benign(d) and (d.code != pyslang.Diags.UnknownModule or where in models)

    errors = [d for d in comp.getAllDiagnostics() if d.isError() and not benign(d)]
    if errors:
        report = pyslang.DiagnosticEngine.reportAll(sm, errors).strip().splitlines()
        raise XutError(
            f"{source.name}: the testbench does not elaborate, so its UNISIM instances cannot "
            f"be checked (ruling S45, fail closed): {' | '.join(report[:2])}"
        )
    root = comp.getRoot()
    top = next((t for t in root.topInstances if t.name == source.stem), None)
    if top is None:
        raise XutError(f"{source.name}: no top module {source.stem} (ruling S45, fail closed)")
    unknown = sorted(set(attrs or {}) - {p.name for p in top.body.parameters})
    if unknown:
        raise XutError(
            f"{source.name}: configuration attribute(s) {', '.join(unknown)} are not "
            f"parameters of {source.stem}, so what Verilator's -G elaborates cannot be "
            "checked (ruling S50, fail closed)"
        )
    found = model_instances(root, ms, source.stem)
    if need_prim and not any(o.definition.name == prim for o in found):
        raise XutError(
            f"{source.name}: no instance of {prim} found in the elaborated testbench (ruling "
            "S45, fail closed): its parameterisations and connections cannot be checked"
        )
    nets = Nets(root)
    paths_of = {o.hierarchicalPath for o in found}
    out = []
    for inst in found:
        path, name = inst.hierarchicalPath, inst.definition.name
        nested = any(path.startswith(f"{q}.") for q in paths_of)
        undriven, zdriven, floating = [], [], []
        for c in () if nested else inst.portConnections:
            if c.port.direction != pyslang.ast.ArgumentDirection.In:
                continue
            e = c.expression
            if e is None:
                undriven.append(c.port.name)
                continue
            v = e.eval(pyslang.ast.EvalContext(inst))  # a constant (literal, parameter)
            if v is not None and v.hasUnknown() and "z" in str(v).lower():
                zdriven.append(c.port.name)
                continue
            for why in nets.floats(e):
                floating.append(
                    f"{c.port.name} (net {why} has no driver)" if why in nets.nets
                    else f"{c.port.name} ({why})"
                )  # fmt: skip
        out.append(
            SvInstance(
                path,
                instance_attrs(ms, name, inst),
                sorted(undriven),
                sorted(zdriven),
                sorted(floating),
                name,
                nested,
            )
        )
    return out


def _defines_guard(ctx: RunContext, what: str) -> None:
    """Refuse (``XutError``) a run with defines over a gated model: the transform and the
    equivalence check never see ``ctx.defines`` (PR #10 nit; fail closed until they do)."""
    if ctx.defines:
        raise XutError(
            f"defines {', '.join(sorted(ctx.defines))} are set, but {what} is gated and its "
            "transform and equivalence check ran without them: the Verilator result would "
            "use code that was never analysed or proved (fail closed)"
        )


def _verdict(
    ms: ModelSource, model: str, attrs: dict, ctx: RunContext, log: Callable[[str], None]
) -> str | None:
    """Ensure (check) ``model`` under ``attrs`` and each transformed descendant for the
    parameterisation it is instantiated with (ruling S50): ``blocked``'s reason, or None."""
    from xut.verilatorize.equiv import config_key  # equiv imports xut.runners: late

    e = ensure_model(ms, model, attrs, root=ctx.root, log=log)
    key = config_key(model_attrs(ms, model, attrs))
    kids = {
        d["model"]: ensure_model(ms, d["model"], d["attrs"], root=ctx.root, log=log)
        for d in e.dep_configs.get(key, [])
    }
    return blocked(e, model, key, kids.get)


def gate_config(
    case: TestCase,
    cfg: str,
    ctx: RunContext,
    seed: int,
    log: Callable[[str], None],
    *,
    verdicts: bool,
    reject: bool = False,
) -> tuple[str, str] | None:
    """The model gate of one configuration, shared by both runners: ``("skip" | "error",
    reason)``, or None to run it.

    1. ``ensure_model(prim, check=False)`` transforms the primitive's hierarchy. Refused
       (``refused``): ``("skip", ...)`` for iverilog-vz (``verdicts=False``), ``("error",
       ...)`` for Verilator.
    2. vector/cocotb: a gated primitive is ensured (equivalence-checked) under the
       configuration's parameterisation (the vector stimulus's attributes, the ``default``
       configuration for ``expect=reject``, or the cocotb ``configs`` entry), and each
       transformed descendant under the parameterisation that configuration instantiates it
       with (ruling S50); with ``verdicts``, a non-pass is an error (``blocked``). sv: every
       UNISIM model instance of the testbench, elaborated with the configuration's ``-G``
       values (``sv_instances``; ruling S50), whatever model it is: each is refused like the
       primitive, and each gated one is ensured and gated for its own parameterisation.
       What cannot be determined is an error (fail closed), and so is a gated model under
       ``ctx.defines`` (the transform never saw them).
    3. The z-compare validity condition, every input driven (ruling S38), for a model whose
       ``effective_rewrites`` hold ``zcmp``: a wrapper input left unconnected (per bit,
       review M3), a stimulus driving z, or an sv instance input unconnected, tied to z or
       connected to a net or variable that can carry z is an error."""
    ms, prim = ctx.model_source, case.prim
    try:
        e = ensure_model(ms, prim, {}, root=ctx.root, log=log, check=False)
        why = refused(e, prim)
        if why is not None:
            return _refusal(e, why, verdicts)
        if case.style == "sv":
            return _gate_sv(case, cfg, ctx, seed, log, verdicts, e.gated)
        if not e.gated:
            return None
        _defines_guard(ctx, prim)
        if case.style == "vector":
            attrs = {} if reject else config_attrs(case, cfg, ctx)[0]
        else:
            attrs = cfg_attrs(case, cfg)
        why = _verdict(ms, prim, attrs, ctx, log)
        if why is not None and verdicts:
            return ("error", why)
        if zcmp.REWRITE not in (e.effective_rewrites or e.rewrites):
            return None
        why = _undriven(case, cfg, ctx)
        return None if why is None else ("error", why)
    except XutError as err:
        return ("error", str(err))


def _refusal(e: ModelEntry, why: str, verdicts: bool) -> tuple[str, str]:
    if verdicts:
        return ("error", why)
    # iverilog-vz: the brief's "model not transformed: <reason>"
    return ("skip", e.reason if e.status == "unsupported" else why)


def _gate_sv(
    case: TestCase,
    cfg: str,
    ctx: RunContext,
    seed: int,
    log: Callable[[str], None],
    verdicts: bool,
    prim_gated: bool,
) -> tuple[str, str] | None:
    """``gate_config`` steps 2-3 for an sv testbench: every model instance it elaborates."""
    ms = ctx.model_source
    entries: dict[str, ModelEntry] = {}
    for m in sv_models(case, ctx, case.prim, seed):  # refused first: before elaborating
        entries[m] = ensure_model(ms, m, {}, root=ctx.root, log=log, check=False)
        why = refused(entries[m], m)
        if why is not None:
            return _refusal(entries[m], why, verdicts)
    insts = sv_instances(case, ctx, case.prim, seed, cfg_attrs(case, cfg), need_prim=prim_gated)
    for m in sorted({i.model for i in insts} - set(entries)):  # never: sv_models covers them
        entries[m] = ensure_model(ms, m, {}, root=ctx.root, log=log, check=False)
        why = refused(entries[m], m)  # fail closed even on this should-not-happen path
        if why is not None:
            return _refusal(entries[m], why, verdicts)
    gated = [i for i in insts if entries[i.model].gated]
    if gated:
        _defines_guard(ctx, ", ".join(sorted({i.model for i in gated})))
    for i in gated:
        why = _verdict(ms, i.model, i.attrs, ctx, log)
        if why is not None and verdicts:
            return ("error", f"{i.path}: {why}")
    for i in insts:
        me = entries[i.model]
        if i.nested or zcmp.REWRITE not in (me.effective_rewrites or me.rewrites):
            continue
        if i.undriven or i.zdriven or i.floating:
            what = ", ".join([*i.undriven, *(f"{p} (tied to z)" for p in i.zdriven), *i.floating])
            return (
                "error",
                f"{i.path}: input port(s) {what} of {i.model} not driven by the testbench: "
                "the z-compare rewrite (ruling S38) is valid only with every input driven",
            )
    return None


def _undriven(case: TestCase, cfg: str, ctx: RunContext) -> str | None:
    """The every-input-driven check of ``gate_config`` step 3 (vector and cocotb)."""
    ms, prim = ctx.model_source, case.prim
    if case.style == "vector":
        src = python_dir(ctx, case) / f"cfg-{cfg}"
        if not (src / "stim.xvec").is_file():
            return None  # prepare_vector reports why
        m = DutMap.load(src / "dut" / "xut_dut.map.json")
        missing = undriven_inputs(ms, prim, zcmp.connected(m))
        if missing:
            return zcmp.undriven_reason(prim, missing)
        return zcmp.Z_STIMULUS if zcmp.drives_z(xvec.load(src / "stim.xvec")) else None
    entry = catalog_model.load_entry(case.family, prim, ctx.root)
    m = build_map(spec_from_catalog(entry, cfg, cfg_attrs(case, cfg)))
    missing = undriven_inputs(ms, prim, zcmp.connected(m))
    return zcmp.undriven_reason(prim, missing) if missing else None


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
        why = self._gate(case, cfg, cd, ctx)
        if why is not None:
            return ConfigResult(cfg, "error", why)
        if case.style == "cocotb":
            return self._cocotb(case, cfg, cd, ctx, ex, timeout, seeds, attrs)
        return self._sv(case, cfg, cd, ctx, ex, timeout, seeds, attrs)

    def _gate(
        self, case: TestCase, cfg: str, cd: Path, ctx: RunContext, reject: bool = False
    ) -> str | None:
        """``gate_config`` with verdicts required (every refusal is an error)."""
        seed = self.stimulus_seed(case, ctx)
        got = gate_config(case, cfg, ctx, seed, _log(cd / "run.log"), verdicts=True, reject=reject)
        return None if got is None else got[1]

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
        why = self._gate(case, cfg, cd, ctx, reject)
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
        try:
            _xdep(cd, xtr.load(cd / "trace.xtr"), xtr.load(sd2 / "trace.xtr"), seeds)
        except (xtr.XtrError, OSError) as e:  # as _seeds_done: the same error reason
            return ConfigResult(cfg, "error", f"malformed trace.xtr: {e}")
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
            except (xtr.XtrError, OSError) as e:
                return ConfigResult(cfg, "error", f"malformed trace.xtr: {e}")
        return _pair(results[0], results[1], seeds[1])

    def finish(self, case: TestCase, ctx: RunContext, d: Path, res: RunResult) -> None:
        stim = res.seeds.get("stimulus")
        # no stimulus seed: no X seeds were derived or used, so none is recorded (review M4)
        res.seeds["x"] = list(x_seeds(stim)) if isinstance(stim, int) else []
        flags = [
            json.loads(p.read_text())["x_dependence"] for p in sorted(d.glob("cfg-*/xdep.json"))
        ]
        res.x_dependence = any(flags) if flags else None


class IverilogVzRunner(IverilogRunner):
    """Icarus on verilatorized UNISIM: guards every verilator result (spec §6.2)."""

    name = "iverilog-vz"

    def run_config(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext) -> ConfigResult:
        """``gate_config`` without requiring verdicts (this run is the guard itself; every
        parameterisation is still ensured, so a verdict exists): a refused hierarchy is
        ``skip "model not transformed: ..."``, a validity-condition failure an error."""
        if (
            case.style == "vector"
            and not (python_dir(ctx, case) / f"cfg-{cfg}" / "stim.xvec").is_file()
        ):
            return super().run_config(case, cfg, cd, ctx)  # prepare_vector says why
        reject = case.style == "vector" and config_attrs(case, cfg, ctx)[1]
        got = gate_config(
            case,
            cfg,
            ctx,
            self.stimulus_seed(case, ctx),
            _log(cd / "run.log"),
            verdicts=False,
            reject=reject,
        )
        if got is not None:
            status, why = got
            return ConfigResult(
                cfg, status, f"model not transformed: {why}" if status == "skip" else why
            )
        return super().run_config(case, cfg, cd, ctx)

    def lib_first(self, case: TestCase, cfg: str, ctx: RunContext) -> tuple[Path, ...]:
        """``vz_dir`` first (``run_config`` already made its hierarchy current); the value is a
        local of the caller, never stored on ``self``: runner jobs are threads."""
        return (vz_dir(ctx.model_source, ctx.root),)
