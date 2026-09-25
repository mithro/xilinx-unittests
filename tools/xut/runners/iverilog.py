# SPDX-License-Identifier: Apache-2.0
"""Icarus Verilog runner (container): vector, sv and cocotb styles (spec §4.3, §6).

Vector configuration (``cfgdir`` = ``build/rtl/iverilog/<model-source>/<id>/cfg-<cfg>/``):
copy ``dut/`` and ``stim.xvec`` from the python run's ``cfg-<cfg>/``, compile the
stimulus (``write_stim``), then compile and run the generic testbench against UNISIM::

    iverilog -g2012 -o sim.vvp -s xut_vector_tb -s glbl -I . -I dut
             -y <ms>/unisims [-y <ms>/retarget] -Y .v [-D<def>...]
             xut_vector_tb.sv dut/xut_dut.v <ms>/glbl.v
    vvp -n sim.vvp

- compile failure: ``error: compile failed``; ``vvp`` exit code non-zero: ``error``;
  no ``XUT_DONE``: ``error: simulation ended early``;
- ``expect=reject``: ``xut.runners.reject.reject_check`` decides instead (shared with
  xsim and verilator; a rejection passes only on positive evidence, ruling S13);
- otherwise ``raw.txt`` -> ``trace.xtr`` -> ``compare`` with the python run's
  ``expected.xtr`` (``vector_check``, shared by every simulator runner).

cocotb configuration (spec §4.3; cocotb is a style, not a runner): ``write_dut`` writes
``dut/`` with ``xut_cocotb_top.v`` from the catalog entry and the configuration's
attributes, then ``tools/xut/hdl/cocotb_run.py --sim icarus`` runs in the container
(``cocotb_command``: PYTHONPATH = tools, models, the test's ``cocotb/`` and shared dirs;
``XUT_MAP``, ``XUT_TRACE``, ``XUT_SEED``, ``XUT_RUNNER``, ``XUT_MODEL``, ``XUT_FLOW``).
cocotb's ``RANDOM_SEED`` is the test's stimulus seed (``seed_for``), recorded in
result.json ``seeds.stimulus``. ``cocotb_check`` classifies the run from ``results.xml``.

sv configuration: the testbench ``sv/<stem>.sv`` (top module ``<stem>``) includes
``hdl/xut_trace.svh``, which writes ``trace.body`` and prints ``XUT_PASS``/``XUT_FAIL``
(``sv_check``; a ``$error`` line, ``ERROR:`` from vvp, is a fail too, and a non-zero
vvp exit code an error). Each attribute of the configuration becomes
``-P<stem>.<NAME>=<value>``.

A compile counts as failed on a non-zero exit **or** on any ``error:``/``sorry:`` line in the
compiler's output: Icarus 12 reports an invalid ``-P`` value as an error but exits 0 and
elaborates with the parameter's default (pinned by a container test), which would
otherwise be a silent pass on the wrong configuration. ``param_value`` refuses such
values (x/z digits) before they reach the compiler. Real literals (``1.5``, ``2e3``) are
accepted: Icarus 12 takes them (probed in the container).

glbl is a second top module (spec §6). ``glbl_instance = True`` selects the
``XUT_GLBL_INSTANCE`` strategy instead (glbl instantiated inside the testbench, by
``xut_vector_tb.sv`` or ``xut_trace.svh``); Verilator may need it (Task 15).
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import ClassVar

from xut.container import SIM_IMAGE, Executor, executor_for, image_digest, sim_tool_versions
from xut.errors import XutError
from xut.formats import xtr
from xut.runners.base import (
    ConfigResult,
    RunContext,
    Runner,
    prepare_vector,
    seed_for,
    sha256_file,
    timeout_for,
    trace_header,
)
from xut.runners.reject import SimOutcome, reject_check
from xut.stimcompile import raw_to_trace
from xut.testspec import TestCase
from xut.wrap import DutMap, spec_from_catalog, write_dut

HDL = Path(__file__).resolve().parent.parent / "hdl"
TOOLS = HDL.parent.parent
MODELS = TOOLS.parent / "models"
#: The in-container cocotb launcher (shared with the verilator runner).
COCOTB_RUN = HDL / "cocotb_run.py"
#: ``cocotb_run.py``'s exit code for a failed HDL build (its ``BUILD_FAILED``).
COCOTB_BUILD_FAILED = 3
#: Trace header keys a cocotb test's trace.xtr must carry with the runner's values.
_COCOTB_HEADER_KEYS = ("runner", "flow", "model", "seed", "prim", "cfg")

#: A compiler diagnostic that is an error, whatever the exit code.
_COMPILE_ERROR = re.compile(r"\b(error|sorry):", re.IGNORECASE)
#: A -P value Icarus 12 accepts: a (signed) decimal, a real, a based literal of 0/1/hex
#: digits without x/z, or a plain string.
_PARAM_OK = re.compile(
    r"^(-?[0-9]+"  # decimal
    r"|-?[0-9]+\.[0-9]+([eE][+-]?[0-9]+)?|-?[0-9]+[eE][+-]?[0-9]+"  # real
    r"|[0-9]*'s?([bB][01_]+|[oO][0-7_]+|[dD][0-9_]+|[hH][0-9a-fA-F_]+)"  # based, no x/z
    r'|"[^"]*")$'  # string
)


class ParamError(XutError, ValueError):
    """An attribute value the simulator's command line cannot express."""


def param_value(name: str, value: object) -> str:
    """``value`` as an Icarus ``-P`` literal. x/z digits are refused: Icarus 12 reports
    them as an error, exits 0 and keeps the default, so passing one would silently run
    the wrong configuration."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ParamError(f"attribute {name}={value!r}: not a number or Verilog literal")
    text = str(value)
    if not _PARAM_OK.match(text):
        raise ParamError(
            f"attribute {name}={text}: Icarus -P cannot express this value (x/z digits or "
            "not a Verilog integer/real/string literal); an sv test needs a testbench-side "
            "default for it"
        )
    return text


def vector_check(
    cd: Path,
    m: DutMap,
    labels: list[str],
    expected: xtr.Trace,
    header: dict[str, str],
    x_observable: bool,
) -> ConfigResult:
    """``raw.txt`` -> ``trace.xtr``, compared with ``expected``: pass or fail, each
    mismatch in ``mismatches.txt`` and the first three in the reason."""
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
    return ConfigResult(
        cfg,
        status,
        reason,
        sha256_file(cd / "stim.xvec"),
        sha256_file(cd / "trace.xtr"),
        len(mm),
    )


def sv_check(cd: Path, log_text: str, header: dict[str, str]) -> ConfigResult:
    """``trace.xtr`` = ``header`` + the testbench's ``trace.body``; pass iff the run's
    output has ``XUT_PASS``, no ``XUT_FAIL`` and no ``$error`` line (``ERROR:`` from
    vvp, ``Error:`` from xsim). A malformed ``trace.body`` is an error."""
    cfg = cd.name[4:]
    body = cd / "trace.body"
    try:
        t = xtr.loads(
            xtr.dumps(xtr.Trace(dict(header))) + (body.read_text() if body.is_file() else "")
        )
    except xtr.XtrError as e:
        return ConfigResult(cfg, "error", f"malformed trace.body: {e}")
    xtr.dump(t, cd / "trace.xtr")
    sha = sha256_file(cd / "trace.xtr")
    bad = [
        ln.strip()
        for ln in log_text.splitlines()
        if "XUT_FAIL" in ln or ln.lstrip().startswith(("ERROR:", "Error:"))
    ]
    if bad:
        return ConfigResult(cfg, "fail", bad[0], None, sha)
    if "XUT_PASS" not in log_text:
        return ConfigResult(cfg, "error", "testbench did not report XUT_PASS/XUT_FAIL")
    return ConfigResult(cfg, "pass", None, None, sha)


def cfg_attrs(case: TestCase, cfg: str) -> dict:
    """The attributes of an sv/cocotb configuration (test.yaml ``configs``)."""
    return next((c.get("attrs", {}) for c in case.configs if c["cfg"] == cfg), {})


def cocotb_command(
    ex: Executor,
    sim: str,
    case: TestCase,
    cd: Path,
    ctx: RunContext,
    runner: str,
    seed: int,
    lib_first: tuple[Path, ...] = (),
    x_seed: int | None = None,
) -> tuple[list[str], dict[str, str]]:
    """``(argv, env)`` that run ``cocotb_run.py --sim <sim>`` for configuration dir ``cd``
    (which already holds ``dut/`` with ``xut_cocotb_top.v``)."""
    source = case.test_dir / str(case.source)
    ms = ctx.model_source
    argv = [
        "python3",
        ex.guest(COCOTB_RUN),
        "--sim",
        sim,
        "--work",
        ex.guest(cd),
        "--module",
        source.stem,
        "--test-dir",
        ex.guest(source.parent),
        "--unisims",
        ex.guest(ms.unisims),
        *(["--retarget", ex.guest(ms.retarget)] if ms.retarget else []),
        *(a for d in lib_first for a in ("--lib-first", ex.guest(d))),
        "--glbl",
        ex.guest(ms.glbl),
        "--seed",
        str(seed),
        *(["--x-seed", str(x_seed)] if x_seed is not None else []),
        *(a for k, v in ctx.defines.items() for a in ("--define", k if v == "" else f"{k}={v}")),
        *(a for d in case.shared_dirs for a in ("--shared", ex.guest(d))),
    ]
    path = [TOOLS, MODELS, source.parent, *case.shared_dirs]
    env = {
        "PYTHONPATH": ":".join(ex.guest(p) for p in path),
        "PYTHONDONTWRITEBYTECODE": "1",  # never leave container-built .pyc in the tree
        "XUT_MAP": "dut/xut_dut.map.json",
        "XUT_TRACE": "trace.xtr",
        "XUT_SEED": str(seed),
        "XUT_RUNNER": runner,
        "XUT_MODEL": ms.name,
        "XUT_FLOW": ctx.flow,
    }
    return argv, env


def cocotb_check(cd: Path, rc: int, seed: int, header: dict[str, str]) -> ConfigResult:
    """Classify a cocotb run of configuration dir ``cd`` from its ``results.xml``:

    - no ``results.xml``: ``error``, ``compile failed`` when the launcher says so (exit
      ``COCOTB_BUILD_FAILED``), else the test module did not import (see run.log); an
      unreadable one, no test case in it, or every one skipped: ``error``;
    - its ``random_seed`` is not ``seed``: ``error``;
    - a ``trace.xtr`` whose header does not name this run: ``error``;
    - the first failing test: ``fail`` with its message when it is an
      ``AssertionError`` (a check the test made); any other exception, including
      cocotb's ``SimFailure`` (the simulator stopped early), is a crash: ``error``.
      Either keeps the trace's sha256: the trace is the evidence of what ran;
    - no failure but a non-zero launcher exit: ``error``; otherwise ``pass``.
    """
    cfg = cd.name[4:]
    xml = cd / "results.xml"
    if not xml.is_file() and rc == COCOTB_BUILD_FAILED:
        return ConfigResult(cfg, "error", "compile failed")
    if not xml.is_file():
        return ConfigResult(
            cfg,
            "error",
            "cocotb wrote no results.xml (build failed or the test module did not "
            "import; see run.log)",
        )
    try:
        root = ET.parse(xml).getroot()
    except ET.ParseError as e:
        return ConfigResult(cfg, "error", f"unreadable results.xml: {e}")
    seeds = [p.get("value") for p in root.iter("property") if p.get("name") == "random_seed"]
    if not seeds or any(s != str(seed) for s in seeds):
        return ConfigResult(cfg, "error", f"results.xml random_seed {seeds} is not {seed}")
    cases = list(root.iter("testcase"))
    if all(c.find("skipped") is not None for c in cases):
        return ConfigResult(cfg, "error", "no cocotb test ran (none found, or all skipped)")
    trace = cd / "trace.xtr"
    sha = None
    if trace.is_file():
        try:
            got = xtr.load(trace).header
        except xtr.XtrError as e:
            return ConfigResult(cfg, "error", f"malformed trace.xtr: {e}")
        bad = {k: got.get(k) for k in _COCOTB_HEADER_KEYS if got.get(k) != header.get(k)}
        if bad:
            return ConfigResult(
                cfg,
                "error",
                f"trace.xtr header {bad} does not match this run "
                f"{ {k: header.get(k) for k in bad} } (use XutDut's default header)",
            )
        sha = sha256_file(trace)
    for c in cases:
        f = c.find("failure")
        if f is None:
            f = c.find("error")
        if f is None:
            continue
        name = f"{c.get('classname')}.{c.get('name')}"
        etype = f.get("error_type") or f.get("type") or "unknown"
        msg = f.get("error_msg") or f.get("message") or ""
        if etype == "AssertionError":
            return ConfigResult(cfg, "fail", f"{name}: {msg}".strip(), None, sha)
        return ConfigResult(cfg, "error", f"{name}: {etype}: {msg}".strip(), None, sha)
    if rc != 0:
        return ConfigResult(cfg, "error", f"cocotb launcher exited with rc {rc}")
    return ConfigResult(cfg, "pass", None, None, sha)


def _native() -> bool:
    return os.environ.get("XUT_NATIVE") == "1"


class IverilogRunner(Runner):
    name = "iverilog"
    x_observable = True
    #: True: glbl is instantiated inside the testbench (XUT_GLBL_INSTANCE), not a top.
    glbl_instance: ClassVar[bool] = False

    def lib_first(self, case: TestCase, cfg: str, ctx: RunContext) -> tuple[Path, ...]:
        """Library dirs searched before the model source. iverilog-vz returns the
        verilatorized dir. Returned, never stored on self: jobs run in threads."""
        return ()

    def available(self, ctx: RunContext) -> tuple[bool, str]:
        if _native():
            return True, ""
        if shutil.which("docker") is None:
            return False, "docker not found"
        if image_digest(SIM_IMAGE) is None:
            return False, f"{SIM_IMAGE} not built: uv run xut container build"
        return True, ""

    def tools(self, ctx: RunContext) -> dict:
        # A private scratch directory (the container needs a cwd under the repository),
        # removed afterwards so no stray directory is left in build/.
        d = ctx.root / "build" / f".xut-versions-{uuid.uuid4().hex}"
        try:
            return sim_tool_versions(executor_for(ctx.model_source, ctx.root), d)
        finally:
            if d.exists():
                shutil.rmtree(d)

    def container(self, ctx: RunContext) -> dict | None:
        if _native():
            return None
        return {"image": SIM_IMAGE, "digest": image_digest(SIM_IMAGE)}

    def _libs(self, ex: Executor, ctx: RunContext, first: tuple[Path, ...]) -> list[str]:
        out: list[str] = []
        for d in (*first, *ctx.model_source.search):
            out += ["-y", ex.guest(d)]
        return [*out, "-Y", ".v"]

    def _defs(self, ctx: RunContext) -> list[str]:
        return [f"-D{k}" if v == "" else f"-D{k}={v}" for k, v in ctx.defines.items()]

    def _tops(self, top: str) -> list[str]:
        """``-s`` tops and glbl define: glbl is a second top (spec §6) unless
        ``glbl_instance``."""
        if self.glbl_instance:
            return ["-s", top, "-DXUT_GLBL_INSTANCE"]
        return ["-s", top, "-s", "glbl"]

    @staticmethod
    def _step(ex: Executor, argv: list[str], cd: Path, log: Path, timeout: int) -> tuple[int, str]:
        """Run one command, appending to ``log``; its exit code and its own output
        (without the executor's ``$ argv`` header line)."""
        start = log.stat().st_size if log.is_file() else 0
        rc = ex.run(argv, cwd=cd, log=log, timeout_s=timeout)
        with log.open() as f:
            f.seek(start)
            lines = f.read().splitlines()
        return rc, "\n".join(lines[1:]) + "\n"

    def _compile(
        self, ex: Executor, argv: list[str], cd: Path, log: Path, timeout: int
    ) -> tuple[bool, str]:
        """Run the compiler: (ok, output). Not ok on a non-zero exit or on any
        ``error:``/``sorry:`` line it printed (Icarus exits 0 on a bad -P value)."""
        rc, out = self._step(ex, argv, cd, log, timeout)
        return rc == 0 and not any(_COMPILE_ERROR.search(ln) for ln in out.splitlines()), out

    def run_config(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext) -> ConfigResult:
        ex = executor_for(ctx.model_source, ctx.root)
        timeout = timeout_for(case, ctx)
        if case.style == "vector":
            return self._run_vector(case, cfg, cd, ctx, ex, timeout)
        if case.style == "cocotb":
            return self._run_cocotb(case, cfg, cd, ctx, ex, timeout)
        return self._run_sv(
            case, cfg, cd, ctx, ex, timeout, trace_header(self.name, case, cfg, ctx)
        )

    def _run_vector(
        self,
        case: TestCase,
        cfg: str,
        cd: Path,
        ctx: RunContext,
        ex: Executor,
        timeout: int,
    ) -> ConfigResult:
        # raises "no expected trace (python: ...)" before copying anything
        vec, m, comp, exp, header = prepare_vector(cd, case, cfg, ctx, self.name)
        log = cd / "run.log"
        argv = [
            "iverilog",
            "-g2012",
            "-o",
            "sim.vvp",
            *self._tops("xut_vector_tb"),
            "-I",
            ".",
            "-I",
            "dut",
            *self._libs(ex, ctx, self.lib_first(case, cfg, ctx)),
            *self._defs(ctx),
            "xut_vector_tb.sv",
            "dut/xut_dut.v",
            ex.guest(ctx.model_source.glbl),
        ]
        compiled_ok, ctext = self._compile(ex, argv, cd, log, timeout)
        rc: int | None = None
        rtext = ""
        if compiled_ok:
            rc, rtext = self._step(ex, ["vvp", "-n", "sim.vvp"], cd, log, timeout)
        if vec.expect == "reject":
            out = SimOutcome(compiled_ok, ctext, rc, rtext)
            return reject_check(cd, out, vec.attrs, case.prim, header)
        if not compiled_ok:
            return ConfigResult(cfg, "error", "compile failed")
        if rc != 0:
            return ConfigResult(cfg, "error", f"simulator exited with rc {rc}")
        if "XUT_DONE" not in rtext:
            return ConfigResult(cfg, "error", "simulation ended early (no XUT_DONE)")
        return vector_check(cd, m, comp.labels, exp, header, self.x_observable)

    def _run_sv(
        self,
        case: TestCase,
        cfg: str,
        cd: Path,
        ctx: RunContext,
        ex: Executor,
        timeout: int,
        header: dict[str, str],
    ) -> ConfigResult:
        source = case.test_dir / str(case.source)
        stem = source.stem
        attrs = cfg_attrs(case, cfg)
        params = [f"-P{stem}.{k}={param_value(k, v)}" for k, v in attrs.items()]
        incs: list[str] = []
        for p in (HDL, *case.shared_dirs, source.parent):
            incs += ["-I", ex.guest(p)]
        log = cd / "run.log"
        argv = [
            "iverilog",
            "-g2012",
            "-o",
            "sim.vvp",
            *self._tops(stem),
            *incs,
            *params,
            *self._libs(ex, ctx, self.lib_first(case, cfg, ctx)),
            *self._defs(ctx),
            ex.guest(source),
            ex.guest(ctx.model_source.glbl),
        ]
        if not self._compile(ex, argv, cd, log, timeout)[0]:
            return ConfigResult(cfg, "error", "compile failed")
        rc, rtext = self._step(ex, ["vvp", "-n", "sim.vvp"], cd, log, timeout)
        if rc != 0:
            return ConfigResult(cfg, "error", f"simulator exited with rc {rc}")
        header["seed"] = "0"
        return sv_check(cd, rtext, header)

    def _run_cocotb(
        self,
        case: TestCase,
        cfg: str,
        cd: Path,
        ctx: RunContext,
        ex: Executor,
        timeout: int,
    ) -> ConfigResult:
        from xut.catalog import model as catalog_model

        source = case.test_dir / str(case.source)
        if source.suffix != ".py" or not source.is_file():
            raise XutError(
                f"{case.id}: cocotb source {case.source!r} must name an existing "
                f"cocotb/<file>.py (looked for {source})"
            )
        entry = catalog_model.load_entry(case.family, case.prim, ctx.root)
        write_dut(spec_from_catalog(entry, cfg, cfg_attrs(case, cfg)), cd / "dut", cocotb_top=True)
        seed = seed_for(case, ctx)
        header = {**trace_header(self.name, case, cfg, ctx), "seed": str(seed)}
        argv, env = cocotb_command(
            ex, "icarus", case, cd, ctx, self.name, seed, self.lib_first(case, cfg, ctx)
        )
        rc = ex.run(argv, cwd=cd, log=cd / "run.log", timeout_s=timeout, env=env)
        return cocotb_check(cd, rc, seed, header)


class IverilogVzRunner(IverilogRunner):
    """Icarus on verilatorized UNISIM: guards every verilator result (spec §6.2). Not in
    ``RUNNERS`` until Task 15 wires it, so no run can select this stub."""

    name = "iverilog-vz"

    def lib_first(self, case: TestCase, cfg: str, ctx: RunContext) -> tuple[Path, ...]:
        raise NotImplementedError("iverilog-vz is completed in Task 15")
