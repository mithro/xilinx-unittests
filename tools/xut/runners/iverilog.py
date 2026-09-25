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
  xsim and verilator; a rejection passes only on positive evidence, rulings S13-S13b);
- otherwise ``raw.txt`` -> ``trace.xtr`` -> ``compare`` with the python run's
  ``expected.xtr`` (``vector_check``, shared by every simulator runner: ``xut.runners.sim``);
  an error/fatal line from the model in the run output fails the configuration
  ("model reported errors: ...") even when the traces match.

cocotb configuration (spec §4.3; cocotb is a style, not a runner): ``write_dut`` writes
``dut/`` with ``xut_cocotb_top.v`` from the catalog entry and the configuration's
attributes, then ``tools/xut/hdl/cocotb_run.py --sim icarus`` runs in the container
(``cocotb_command``: PYTHONPATH = tools, models, the test's ``cocotb/`` and shared dirs;
``XUT_MAP``, ``XUT_TRACE``, ``XUT_SEED``, ``XUT_RUNNER``, ``XUT_MODEL``, ``XUT_FLOW``).
cocotb's ``RANDOM_SEED`` is the test's stimulus seed (``seed_for``: ``--seed``, default
crc32 of the test id), recorded in result.json ``seeds.stimulus`` and named in every
fail/error reason (``[seed N]``). ``cocotb_check`` classifies the run from
``results.xml`` and ``run.log`` (model errors).

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
import traceback
from pathlib import Path
from typing import ClassVar

from xut.container import SIM_IMAGE, Executor, executor_for, image_digest, sim_tool_versions
from xut.errors import XutError
from xut.runners.base import (
    ConfigResult,
    RunContext,
    Runner,
    error_reason,
    prepare_vector,
    seed_for,
    timeout_for,
    trace_header,
)
from xut.runners.reject import SimOutcome, reject_check
from xut.runners.sim import (
    HDL,
    ParamError,
    cfg_attrs,
    classify_run,
    cocotb_check,
    cocotb_command,
    sv_check,
    sv_seed_define,
    tool_versions,
    vector_check,
    with_seed,
)
from xut.testspec import TestCase
from xut.wrap import spec_from_catalog, write_dut

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


def _native() -> bool:
    return os.environ.get("XUT_NATIVE") == "1"


class IverilogRunner(Runner):
    name = "iverilog"
    x_observable = True
    #: True: glbl is instantiated inside the testbench (XUT_GLBL_INSTANCE), not a top.
    glbl_instance: ClassVar[bool] = False

    def lib_first(self, case: TestCase, cfg: str, ctx: RunContext) -> tuple[Path, ...]:
        """Library dirs searched before the model source. iverilog-vz returns the
        verilatorized dir (see ``Runner`` for the per-instance contract)."""
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
        ex = executor_for(ctx.model_source, ctx.root)
        return tool_versions(ctx, lambda d: sim_tool_versions(ex, d))

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
        out = SimOutcome(compiled_ok, ctext, rc, rtext)
        if vec.expect == "reject":
            return reject_check(cd, out, vec.illegal, header)
        if (r := classify_run(cfg, out)) is not None:
            return r
        return vector_check(cd, m, comp.labels, exp, header, self.x_observable, out.run_text)

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
        seed = seed_for(case, ctx)
        header["seed"] = str(seed)
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
            f"-DXUT_SEED={sv_seed_define(seed)}",
            ex.guest(source),
            ex.guest(ctx.model_source.glbl),
        ]
        compiled_ok, ctext = self._compile(ex, argv, cd, log, timeout)
        if not compiled_ok:
            return ConfigResult(cfg, "error", "compile failed")
        rc, rtext = self._step(ex, ["vvp", "-n", "sim.vvp"], cd, log, timeout)
        if (
            r := classify_run(cfg, SimOutcome(True, ctext, rc, rtext), need_done=False)
        ) is not None:
            return r
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
        """One cocotb configuration; every fail/error reason names the seed
        (``with_seed``), including an exception before the simulator ran."""
        seed = seed_for(case, ctx)
        try:
            return self._cocotb(case, cfg, cd, ctx, ex, timeout, seed)
        except Exception as e:
            with (cd / "run.log").open("a") as f:
                f.write(traceback.format_exc())
            return with_seed(ConfigResult(cfg, "error", error_reason(e)), seed)

    def _cocotb(
        self,
        case: TestCase,
        cfg: str,
        cd: Path,
        ctx: RunContext,
        ex: Executor,
        timeout: int,
        seed: int,
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
