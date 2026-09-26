# SPDX-License-Identifier: Apache-2.0
"""Vivado 2025.2 simulator runner (native, host), vector and sv styles (spec §4.3, §6).

Vivado is never sourced into the calling environment: each configuration directory
(``build/rtl/xsim/unisim-2025.2/<id>/cfg-<cfg>/``) gets an ``xsim.sh`` that sources
``settings64.sh`` only inside ``bash -c '...'`` and is run as ``bash xsim.sh > run.log
2>&1`` with that directory as its working directory, so ``xsim.dir/``, ``*.jou``,
``*.log`` and ``*.pb`` land there and never in the repository root::

    xvlog -sv -i . -i dut [-i <inc>...] [-d <def>...] <files> <vivado>/glbl.v
    xelab -L unisims_ver -L unimacro_ver --timescale 1ps/1ps --debug off
          [-generic_top NAME=VAL...] -s xut_snap work.<top> work.glbl
    echo XUT_XSIM_RUN; xsim xut_snap -R

**Model source.** xsim always elaborates against Vivado's *precompiled* ``unisims_ver``
library (the task brief's choice: that is what a Vivado user simulates), which is
built from the ``unisim-2025.2`` sources. So the runner is available only for model
source ``unisim-2025.2``; any other source is a ``skip`` with the reason (a result
named ``unisim-gh-2020.1`` must never come from 2025.2 models). ``extra_files`` (tests
only) are compiled into ``work`` ahead of the library, e.g. the toy ``TOYFF.v``.

**Compile vs run.** ``xsim.sh`` echoes ``XUT_XSIM_RUN`` just before ``xsim -R``; the
log before it is the compile/elaboration output, the rest the run output
(``SimOutcome`` keeps them apart for the reject rule). The compile failed when the
marker is missing (``set -e`` and the ``&&`` chain stop at the first failing tool) or
when the compile output has an ``ERROR:`` or ``CRITICAL WARNING:`` line, whatever the
exit codes say.

**Parameters** (sv configurations: ``-generic_top NAME=VAL``). Probed on 2025.2
(``test_xelab_generic_top_*``): xelab takes sized literals *including* x/z digits
(``1'bx`` arrives as x, unlike Icarus -P), reals and quoted strings; but a bare word
(``x``, ``abc``) is silently taken as a string and bit-truncated, so ``1'b0``-style
parameters would get a wrong value without any diagnostic. ``generic_value`` refuses
bare words; a string must be written quoted (``"ABC"``).

**Defines.** ``-d`` defines reach only the ``work`` library; the precompiled
``unisims_ver`` cannot see them. So any ``XIL_*`` define (a UNISIM build switch such as
``XIL_TIMING``) makes the runner unavailable (``skip``, with the reason), rather than
recording defines the model was not built with.

**Host quirk.** Vivado's bundled gcc looks for ``crt1.o``/``crti.o`` only where RHEL
keeps them (``/usr/lib64``); on a multiarch (Debian/Ubuntu) host xelab's link fails
with "cannot find crt1.o". When ``/usr/lib64/crt1.o`` is missing and
``/usr/lib/x86_64-linux-gnu/crt1.o`` exists, the subshell (only) exports
``LIBRARY_PATH=/usr/lib/x86_64-linux-gnu``; xelab then prints the harmless
``WARNING: [XSIM 43-3431]``.
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from xut.container import RunTimeout
from xut.errors import XutError
from xut.paths import VIVADO_SETTINGS, VIVADO_SRC
from xut.runners.base import (
    ConfigResult,
    RunContext,
    Runner,
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
    sv_check,
    sv_seed_define,
    tool_versions,
    vector_check,
)
from xut.testspec import TestCase

#: The only model source xsim can honestly report (precompiled unisims_ver).
MODEL_SOURCE = "unisim-2025.2"
#: Printed by xsim.sh just before ``xsim -R``: splits compile output from run output.
RUN_MARKER = "XUT_XSIM_RUN"
SNAPSHOT = "xut_snap"
#: A compile/elaboration diagnostic that is a failure, whatever the exit code.
_COMPILE_ERROR = re.compile(r"^\s*(ERROR|CRITICAL WARNING):")
_MULTIARCH_LIB = "/usr/lib/x86_64-linux-gnu"
#: Shell snippet (for inside the Vivado subshell only): Vivado's gcc searches only the
#: RHEL crt1.o location, so point it at the multiarch one when that is all there is.
LIBRARY_PATH_GUARD = (
    f"if [ ! -e /usr/lib64/crt1.o ] && [ -e {_MULTIARCH_LIB}/crt1.o ]; then "
    f"export LIBRARY_PATH={_MULTIARCH_LIB}${{LIBRARY_PATH:+:$LIBRARY_PATH}}; fi"
)
_KILL_GRACE_S = 10
#: A -generic_top value xelab 2025.2 takes as written: a (signed) decimal, a real, a
#: based literal (x/z digits allowed: xelab keeps them) or a quoted string.
_GENERIC_OK = re.compile(
    r"^(-?[0-9]+"
    r"|-?[0-9]+\.[0-9]+([eE][+-]?[0-9]+)?|-?[0-9]+[eE][+-]?[0-9]+"
    r"|[0-9]*'s?([bB][01xXzZ?_]+|[oO][0-7xXzZ?_]+|[dD][0-9_]+|[hH][0-9a-fA-FxXzZ?_]+)"
    r'|"[^"]*")$'
)


def generic_value(name: str, value: object) -> str:
    """``value`` as an xelab ``-generic_top`` literal. A bare word is refused: xelab
    silently reads it as a string and truncates it to the parameter's width."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ParamError(f"attribute {name}={value!r}: not a number or Verilog literal")
    text = str(value)
    if not _GENERIC_OK.match(text):
        raise ParamError(
            f"attribute {name}={text}: not a Verilog integer/real/based literal or a quoted "
            "string; xelab -generic_top would silently read it as a string"
        )
    return text


def settings_available() -> bool:
    return VIVADO_SETTINGS.is_file()


def render_script(
    cd: Path,
    files: Sequence[str],
    top: str,
    incs: Sequence[str],
    params: dict[str, str],
    defines: dict[str, str],
    glbl_instance: bool = False,
    *,
    glbl: str | None = None,
    libs: Sequence[str] = ("unisims_ver", "unimacro_ver"),
    sourcelibdirs: Sequence[str] = (),
    verilog_files: Sequence[str] = (),
) -> str:
    """``xsim.sh`` for one configuration directory ``cd`` (see the module docstring).
    Every argument is shell-quoted; the whole Vivado command chain is one ``bash -c``
    argument, so ``settings64.sh`` is sourced only in that subshell.

    The runner uses the defaults. The verilatorize equivalence oracle (spec §6.2, ruling
    S31) compiles a model source's own model file instead: ``libs=()`` (no precompiled
    ``unisims_ver``), ``glbl`` that source's ``glbl.v``, and ``sourcelibdirs`` its
    ``unisims``/``retarget`` directories (xvlog ``--sourcelibdir``, like Icarus ``-y``)
    for any model the file instantiates. ``verilog_files`` (the UNISIM originals, written
    in Verilog-2001) are compiled by a second ``xvlog`` without ``-sv``, together with
    ``glbl`` and the ``sourcelibdirs`` search: an SV keyword used as an identifier in a
    Verilog model must not break it. ``files`` stay SystemVerilog (the testbench)."""
    q = shlex.quote
    defs = [a for k, v in defines.items() for a in ("-d", k if v == "" else f"{k}={v}")]
    if glbl_instance:
        defs += ["-d", "XUT_GLBL_INSTANCE"]
    inc_args = [a for i in (".", "dut", *incs) for a in ("-i", i)]
    gens = [a for k, v in params.items() for a in ("-generic_top", f"{k}={v}")]
    tops = [f"work.{top}"] + ([] if glbl_instance else ["work.glbl"])
    srclib = [a for d in sourcelibdirs for a in ("--sourcelibdir", d)]
    if srclib:
        srclib += ["--sourcelibext", ".v"]
    glbl_file = str(VIVADO_SRC / "glbl.v") if glbl is None else glbl
    if verilog_files:
        xvlog = ["xvlog", "-sv", *inc_args, *defs, *files]
        xvlog_v = ["xvlog", *inc_args, *defs, *srclib, *verilog_files, glbl_file]
    else:
        xvlog = ["xvlog", "-sv", *inc_args, *defs, *srclib, *files, glbl_file]
        xvlog_v = []
    xelab = [
        "xelab",
        *(a for lib in libs for a in ("-L", lib)),
        *("--timescale", "1ps/1ps", "--debug", "off"),
        *gens,
        *("-s", SNAPSHOT, *tops),
    ]
    steps = [LIBRARY_PATH_GUARD, xvlog, *([xvlog_v] if xvlog_v else []), xelab]
    inner = f"source {q(str(VIVADO_SETTINGS))} && \\\n" + "".join(
        f"  {st if isinstance(st, str) else ' '.join(q(a) for a in st)} && \\\n" for st in steps
    )
    inner += f"  echo {RUN_MARKER} && \\\n  xsim {SNAPSHOT} -R"
    return (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# GENERATED by xut (xsim runner). Vivado is sourced only in this subshell.\n"
        # repr: a newline in the path must not end the comment and become a command
        f"# Configuration directory: {str(cd)!r}\n"
        "set -e\n"
        'cd "$(dirname "$0")"\n'
        f"bash -c {q(inner)}\n"
    )


def split_log(text: str, rc: int) -> SimOutcome:
    """The ``SimOutcome`` of an ``xsim.sh`` log and exit code ``rc``: the compile
    failed when ``xsim -R`` never started (no ``RUN_MARKER`` line; ``run_rc`` is then
    None, and the whole log is the compile text) or when the compile output has an
    ``ERROR:``/``CRITICAL WARNING:`` line."""
    lines = text.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if ln.strip() == RUN_MARKER), None)
    if at is None:
        return SimOutcome(False, _diagnostics(text), None, "")
    ctext, rtext = "".join(lines[:at]), "".join(lines[at + 1 :])
    ok = not any(_COMPILE_ERROR.match(ln) for ln in ctext.splitlines())
    return SimOutcome(ok, _diagnostics(ctext), rc, rtext)


def _diagnostics(ctext: str) -> str:
    """The compile output without ``INFO:`` lines and the LIBRARY_PATH warning (XSIM
    43-3431, "If errors occur, ..."): neither is ever a diagnostic, and INFO lines
    carry file paths that could spuriously match the reject rule's words."""
    keep = [
        ln
        for ln in ctext.splitlines(keepends=True)
        if not ln.lstrip().startswith("INFO:") and "[XSIM 43-3431]" not in ln
    ]
    return "".join(keep)


def run_script(cd: Path, timeout_s: int) -> int:
    """``bash xsim.sh > run.log 2>&1`` in ``cd``; its exit code. The script runs in its
    own process group, so a timeout kills xvlog/xelab/xsim too, not only bash."""
    with (cd / "run.log").open("w") as log:
        p = subprocess.Popen(
            ["bash", "xsim.sh"],
            cwd=cd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=_KILL_GRACE_S)
            raise RunTimeout(f"timeout after {timeout_s}s: xsim.sh") from e


class XsimError(XutError, RuntimeError):
    """Vivado's xsim could not report its version."""


_VERSION: dict[str, str] = {}
_VERSION_LOCK = threading.Lock()


def xsim_version(scratch: Path) -> str:
    """First line of ``xsim -version`` (sourced in a subshell), once per process."""
    with _VERSION_LOCK:
        if "xsim" in _VERSION:
            return _VERSION["xsim"]
        scratch.mkdir(parents=True, exist_ok=True)
        log = scratch / f".xsim-version-{uuid.uuid4().hex}.log"
        cmd = f"source {shlex.quote(str(VIVADO_SETTINGS))} && xsim -version"
        with log.open("w") as f:
            rc = subprocess.run(
                ["bash", "-c", cmd], cwd=scratch, stdout=f, stderr=subprocess.STDOUT, timeout=120
            ).returncode
        text = log.read_text()
        log.unlink()
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if rc != 0 or not first.startswith("Vivado Simulator"):
            raise XsimError(f"xsim -version failed (rc {rc}): {text.strip()[:300]}")
        _VERSION["xsim"] = first
        return first


class XsimRunner(Runner):
    name = "xsim"
    x_observable = True
    #: cocotb has no xsim backend (spec §4.3): cocotb tests are a skip with the reason.
    styles = frozenset({"vector", "sv"})
    #: True: glbl is instantiated inside the testbench (XUT_GLBL_INSTANCE), not a top.
    glbl_instance: ClassVar[bool] = False

    def __init__(self, extra_files: Sequence[Path] = ()) -> None:
        """``extra_files`` (tests only): Verilog compiled into ``work`` with the DUT,
        for toy primitives that ``unisims_ver`` does not have."""
        self.extra_files = tuple(Path(f).resolve() for f in extra_files)

    def available(self, ctx: RunContext) -> tuple[bool, str]:
        xil = sorted(k for k in ctx.defines if k.startswith("XIL_"))
        if xil:
            return False, (
                f"xsim cannot honour {', '.join(xil)}: its -d defines reach only the work "
                "library, and Vivado's precompiled unisims_ver was built without them, so "
                "the result would misstate the model build"
            )
        if not settings_available():
            return False, f"Vivado 2025.2 not installed ({VIVADO_SETTINGS} missing)"
        if ctx.model_source.name != MODEL_SOURCE:
            return False, (
                f"xsim uses Vivado's precompiled unisims_ver ({MODEL_SOURCE}); "
                f"requested {ctx.model_source.name}"
            )
        return True, ""

    def tools(self, ctx: RunContext) -> dict:
        return tool_versions(ctx, lambda d: {"xsim": xsim_version(d)})

    def run_config(self, case: TestCase, cfg: str, cd: Path, ctx: RunContext) -> ConfigResult:
        timeout = timeout_for(case, ctx)
        if case.style == "vector":
            return self._run_vector(case, cfg, cd, ctx, timeout)
        return self._run_sv(case, cfg, cd, ctx, timeout)

    def _build_and_run(
        self,
        cd: Path,
        files: Sequence[str],
        top: str,
        incs: Sequence[str],
        params: dict[str, str],
        ctx: RunContext,
        timeout: int,
        defines: dict[str, str] | None = None,
    ) -> SimOutcome:
        defs = ctx.defines if defines is None else defines
        text = render_script(cd, files, top, incs, params, defs, self.glbl_instance)
        (cd / "xsim.sh").write_text(text)
        rc = run_script(cd, timeout)
        return split_log((cd / "run.log").read_text(errors="replace"), rc)

    def _run_vector(
        self, case: TestCase, cfg: str, cd: Path, ctx: RunContext, timeout: int
    ) -> ConfigResult:
        vec, m, comp, exp, header = prepare_vector(cd, case, cfg, ctx, self.name)
        files = ["xut_vector_tb.sv", "dut/xut_dut.v", *map(str, self.extra_files)]
        out = self._build_and_run(cd, files, "xut_vector_tb", [], {}, ctx, timeout)
        if vec.expect == "reject":
            return reject_check(cd, out, vec.illegal, header)
        if (r := classify_run(cfg, out)) is not None:
            return r
        return vector_check(cd, m, comp.labels, exp, header, self.x_observable, out.run_text)

    def _run_sv(
        self, case: TestCase, cfg: str, cd: Path, ctx: RunContext, timeout: int
    ) -> ConfigResult:
        source = case.test_dir / str(case.source)
        attrs = cfg_attrs(case, cfg)
        params = {k: generic_value(k, v) for k, v in attrs.items()}
        incs = [str(p) for p in (HDL, *case.shared_dirs, source.parent)]
        files = [str(source), *map(str, self.extra_files)]
        seed = seed_for(case, ctx)
        defines = {**ctx.defines, "XUT_SEED": sv_seed_define(seed)}
        out = self._build_and_run(cd, files, source.stem, incs, params, ctx, timeout, defines)
        if (r := classify_run(cfg, out, need_done=False)) is not None:
            return r
        return sv_check(
            cd, out.run_text, {**trace_header(self.name, case, cfg, ctx), "seed": str(seed)}
        )
