# SPDX-License-Identifier: Apache-2.0
"""Icarus Verilog runner (container), vector and sv styles (spec §4.3, §6).

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
    sha256_file,
    timeout_for,
    trace_header,
)
from xut.runners.reject import SimOutcome, reject_check
from xut.stimcompile import raw_to_trace
from xut.testspec import TestCase
from xut.wrap import DutMap

HDL = Path(__file__).resolve().parent.parent / "hdl"

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
            return sim_tool_versions(executor_for(ctx.model_source), d)
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
        ex = executor_for(ctx.model_source)
        timeout = timeout_for(case, ctx)
        if case.style == "vector":
            return self._run_vector(case, cfg, cd, ctx, ex, timeout)
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
        attrs = next((c.get("attrs", {}) for c in case.configs if c["cfg"] == cfg), {})
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


class IverilogVzRunner(IverilogRunner):
    """Icarus on verilatorized UNISIM: guards every verilator result (spec §6.2). Not in
    ``RUNNERS`` until Task 15 wires it, so no run can select this stub."""

    name = "iverilog-vz"

    def lib_first(self, case: TestCase, cfg: str, ctx: RunContext) -> tuple[Path, ...]:
        raise NotImplementedError("iverilog-vz is completed in Task 15")
