# SPDX-License-Identifier: Apache-2.0
"""Runner-neutral simulator code, shared by every simulator runner (iverilog, xsim, and
later verilator and iverilog-vz): the post-run ladder, the vector/sv/cocotb checks and
the cocotb launcher command (PR B gate review (a) M2).

A simulator runner builds and runs one configuration, describes what happened as a
``SimOutcome`` (compile output, run exit code, run output), then:

- ``expect=reject`` vector configurations: ``xut.runners.reject.reject_check``;
- otherwise ``classify_run`` (compile failed, then a non-zero exit, then ``Fatal:``,
  then -- for vector runs -- no ``XUT_DONE``: each an ``error``), and, if the run got
  that far, ``vector_check`` or ``sv_check``;
- cocotb configurations: ``cocotb_check`` on the launcher's ``results.xml``.

Every check names its configuration from ``header["cfg"]`` (``cfg_of``), never from
the directory name.
"""

from __future__ import annotations

import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from xut.container import Executor
from xut.errors import XutError
from xut.formats import xtr
from xut.runners.base import ConfigResult, RunContext, sha256_file
from xut.runners.reject import SimOutcome
from xut.stimcompile import raw_to_trace
from xut.testspec import TestCase
from xut.wrap import DutMap

HDL = Path(__file__).resolve().parent.parent / "hdl"
TOOLS = HDL.parent.parent
MODELS = TOOLS.parent / "models"
#: The in-container cocotb launcher (shared with the verilator runner).
COCOTB_RUN = HDL / "cocotb_run.py"
#: ``cocotb_run.py``'s exit code for a failed HDL build: keep equal to
#: ``tools/xut/hdl/cocotb_run.py`` ``BUILD_FAILED`` (pinned by test_runner_cocotb).
COCOTB_BUILD_FAILED = 3
#: Trace header keys a cocotb test's trace.xtr must carry with the runner's values.
_COCOTB_HEADER_KEYS = ("runner", "flow", "model", "seed", "prim", "cfg")
#: ``xut_finish``'s count of executed XUT_CHECK/XUT_CHECKN (hdl/xut_trace.svh).
_CHECKS = re.compile(r"^\s*XUT_CHECKS (\d+)\s*$", re.MULTILINE)

__all__ = [
    "COCOTB_BUILD_FAILED",
    "COCOTB_RUN",
    "HDL",
    "MODELS",
    "TOOLS",
    "ParamError",
    "SimOutcome",
    "cfg_attrs",
    "cfg_of",
    "classify_run",
    "cocotb_check",
    "cocotb_command",
    "fatal_line",
    "sv_check",
    "tool_versions",
    "vector_check",
]


class ParamError(XutError, ValueError):
    """An attribute value the simulator's command line cannot express."""


def cfg_of(header: dict[str, str]) -> str:
    """The configuration a check reports: the trace header's ``cfg``."""
    return header["cfg"]


def cfg_attrs(case: TestCase, cfg: str) -> dict:
    """The attributes of an sv/cocotb configuration (test.yaml ``configs``)."""
    return next((c.get("attrs", {}) for c in case.configs if c["cfg"] == cfg), {})


def tool_versions(ctx: RunContext, probe: Callable[[Path], dict]) -> dict:
    """``probe(scratch)`` in a private scratch directory under ``build/`` (a container
    needs a cwd under the run root), removed afterwards so no stray directory is left."""
    d = ctx.root / "build" / f".xut-versions-{uuid.uuid4().hex}"
    try:
        return probe(d)
    finally:
        if d.exists():
            shutil.rmtree(d)


def fatal_line(run_text: str) -> str | None:
    """A ``$fatal`` report (xsim: ``Fatal: ...``; xsim still exits 0 after it)."""
    return next((ln.strip() for ln in run_text.splitlines() if ln.startswith("Fatal:")), None)


def classify_run(cfg: str, out: SimOutcome, *, need_done: bool = True) -> ConfigResult | None:
    """The shared post-run ladder: an ``error`` for a failed compile, a non-zero exit
    code, a ``Fatal:`` report or (``need_done``) a run that never printed ``XUT_DONE``;
    ``None`` when the run completed and its output should be checked."""
    if not out.compiled_ok:
        return ConfigResult(cfg, "error", "compile failed")
    if out.run_rc != 0:
        return ConfigResult(cfg, "error", f"simulator exited with rc {out.run_rc}")
    if fatal := fatal_line(out.run_text):
        return ConfigResult(cfg, "error", f"simulator reported {fatal}")
    if need_done and "XUT_DONE" not in out.run_text:
        return ConfigResult(cfg, "error", "simulation ended early (no XUT_DONE)")
    return None


def vector_check(
    cd: Path,
    m: DutMap,
    labels: list[str],
    expected: xtr.Trace,
    header: dict[str, str],
    x_observable: bool,
) -> ConfigResult:
    """``raw.txt`` -> ``trace.xtr``, compared with ``expected``: pass or fail, each
    mismatch in ``mismatches.txt`` and the first three in the reason. An ``expected``
    without samples is an ``error``: zero evidence is never a pass (ruling S15)."""
    cfg = cfg_of(header)
    if not expected.samples:  # validate refuses such a stimulus; never pass on nothing
        return ConfigResult(cfg, "error", "expected trace has no samples (ruling S15)")
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
    """``trace.xtr`` = ``header`` + the testbench's ``trace.body``. A malformed
    ``trace.body`` is an error. Then, in order:

    - any ``XUT_FAIL`` or ``$error`` line (``ERROR:`` from vvp, ``Error:`` from xsim):
      ``fail`` with the first one;
    - no ``XUT_PASS``: ``error``;
    - no ``XUT_CHECKS <n>`` line (``xut_finish`` prints it: the number of
      ``XUT_CHECK``/``XUT_CHECKN`` executed): ``error``;
    - zero checks executed or zero checkpoints in ``trace.body``: ``error`` ("sv test
      recorded no checks/samples", ruling S15: zero evidence is never a pass);
    - otherwise ``pass``."""
    cfg = cfg_of(header)
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
    counts = _CHECKS.findall(log_text)
    if not counts:
        return ConfigResult(
            cfg,
            "error",
            "testbench did not report XUT_CHECKS (include xut_trace.svh and end with xut_finish)",
        )
    checks, samples = int(counts[-1]), len(t.samples)
    if checks == 0 or samples == 0:
        return ConfigResult(
            cfg,
            "error",
            f"sv test recorded no checks/samples ({checks} XUT_CHECK(s) executed, "
            f"{samples} checkpoint(s) in trace.body; ruling S15)",
            None,
            sha,
        )
    return ConfigResult(cfg, "pass", None, None, sha)


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
    - any failing test whose exception is not an ``AssertionError`` -- including
      cocotb's ``SimFailure`` (the simulator stopped early) -- is a crash: ``error``,
      even when an earlier test failed an assertion (a failed check never hides a
      crash); otherwise the first ``AssertionError``: ``fail`` with its message. Both
      keep the trace's sha256: the trace is the evidence of what ran;
    - no failure, but no ``trace.xtr`` or one with no sample: ``error`` ("cocotb test
      recorded no samples"): a pass must leave evidence of what was checked. This
      cannot prove the test ASSERTED anything -- a test that samples but never compares
      passes; zero assertions are not detectable in general (the trace makes the run
      cross-checkable against other simulators, which is the backstop);
    - no failure but a non-zero launcher exit: ``error``; otherwise ``pass``.
    """
    cfg = cfg_of(header)
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
    n_samples = 0
    if trace.is_file():
        try:
            t = xtr.load(trace)
        except xtr.XtrError as e:
            return ConfigResult(cfg, "error", f"malformed trace.xtr: {e}")
        got, n_samples = t.header, len(t.samples)
        bad = {k: got.get(k) for k in _COCOTB_HEADER_KEYS if got.get(k) != header.get(k)}
        if bad:
            return ConfigResult(
                cfg,
                "error",
                f"trace.xtr header {bad} does not match this run "
                f"{ {k: header.get(k) for k in bad} } (use XutDut's default header)",
            )
        sha = sha256_file(trace)
    failures = []
    for c in cases:
        f = c.find("failure")
        if f is None:
            f = c.find("error")
        if f is not None:
            name = f"{c.get('classname')}.{c.get('name')}"
            etype = f.get("error_type") or f.get("type") or "unknown"
            failures.append((name, etype, f.get("error_msg") or f.get("message") or ""))
    crash = next((x for x in failures if x[1] != "AssertionError"), None)
    if crash is not None:
        name, etype, msg = crash
        return ConfigResult(cfg, "error", f"{name}: {etype}: {msg}".strip(), None, sha)
    if failures:
        name, _, msg = failures[0]
        return ConfigResult(cfg, "fail", f"{name}: {msg}".strip(), None, sha)
    if n_samples == 0:
        return ConfigResult(cfg, "error", "cocotb test recorded no samples", None, sha)
    if rc != 0:
        return ConfigResult(cfg, "error", f"cocotb launcher exited with rc {rc}")
    return ConfigResult(cfg, "pass", None, None, sha)
