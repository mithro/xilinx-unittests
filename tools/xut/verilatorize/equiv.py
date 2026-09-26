# SPDX-License-Identifier: Apache-2.0
"""Mandatory equivalence stimulus and the original-vs-transformed check (spec §6.2).

Every transformed model is proved equivalent to its original before any Verilator result
for it counts. ``check_model`` does that for one attribute configuration:

1. ``dut/`` (``spec_from_hdl(..., raw_clock_out=True)``: clock outputs are sampled directly,
   which is fine for a comparison that never meets the hardware harness), ``stim.xvec``
   (``equiv_stimulus``) and ``stim.memh`` are written once.
2. The transformed model runs on Icarus (``vz/``: ``-y <vz dir>`` first, then the model
   source's ``unisims``/``retarget``).
3. The original runs on the *oracle* (ruling S28b/S31):

   * Icarus (``orig/``: ``-y unisims [-y retarget]``) only when no override expression is
     non-constant (``nonconstant_overrides``) **and** Icarus compiles and runs the original
     cleanly: exit code 0, ``XUT_DONE``, and no ``error:``/``sorry:`` line. Icarus 12
     evaluates a procedural continuous assign with a non-constant right-hand side once
     ("sorry: ... RHS evaluated once"), so it cannot be the oracle for such a model;
   * otherwise Vivado's xsim (``orig-xsim/``), through the xsim runner's script plumbing:
     Vivado is sourced only inside a ``bash -c`` subshell, ``LIBRARY_PATH`` is pointed at
     the multiarch crt files when needed, and the model source's own model file is
     compiled (never the precompiled ``unisims_ver``, so an ``unisim-gh-2020.1`` result
     really comes from the 2020.1 model). xsim unavailable is an ``error``, never a pass or
     a skip.

   ``result.json`` records which one was used (``"oracle": "iverilog" | "xsim"``).
4. Both runs must print ``XUT_DONE``, else the result is ``error``. The two traces are
   compared exactly, 4-state (``xtr.diff``): no difference is ``pass``, any difference
   ``fail``, listed in ``mismatches.txt``. When *both* models stop early (a UNISIM model's
   own DRC or attribute check calls ``$finish``: an illegal attribute combination, or a
   protocol the generic stimulus breaks, such as the FIFO reset sequence), the result is
   still ``error``, never a pass: the reason quotes each model's message, and the samples
   both printed are compared and listed.

The wrapper instantiates the model with the configuration's attributes, but the stimulus
header does not record them (``result.json`` does): an ``.xvec`` header cannot hold a quoted
string literal such as ``"VIRTEX6"``.

**Scope: sampled outputs only.** The check compares the primitive's outputs at the
stimulus's sample points. A zero-width glitch inside one time step (an output, or an
internal reg, that pulses and returns within the step) is out of scope: it is not a value
any sample can see, and Verilator does not promise zero-width glitch fidelity in general.
Ruling S29 (and the Task 13 re-review's M4) accepted this for NBA-triggered assign-only regs
(fixture ``VZCEA``, the IDELAYE2/ODELAYE2 family): the values agree, only an internal
``@(X)`` consumer could count a different number of events.

**Equivalence stimulus** (``equiv_stimulus``), generated from the analysis, deterministic
for a seed, never hardware-renderable (``hw_renderable no``). Every port idles at 0.
``activity(n)`` is ``n`` cycles of every clock-class input that is not held high by a
trigger, one clock after another, with random data on the non-trigger data ports before
each cycle and a sample after every edge (no clock: ``n`` samples, each after new random
data). A trigger is pulsed through the glbl channel (``glbl.GSR``, ``GTS``, ``GRESTORE``;
any other ``glbl.*`` raises ``TransformError``), with ``async_`` for an async/gate port, with
``set`` for a data port and with ``edge`` for a clock port. After a short baseline
``activity(2)``:

1. ``_independent``: each trigger, three times: ``activity(2)``, assert, sample,
   ``activity(2)``, deassert, sample, ``activity(1)``;
2. ``_coincident``: each non-clock trigger with each clock: assert together with a rising
   edge (``simultaneous``), sample, fall, sample, ``activity(1)``, deassert together with
   the next rising edge, sample, fall, sample. Rising edges only, as the brief specifies: a
   pulse coincident with a *falling* edge (the active edge of an ``IS_C_INVERTED=1``
   configuration) is not generated; such configurations see triggers near falling edges
   only through the activity of phases 1 and 3, at the builder's separation;
3. ``_pairs``: each pair (a, b), with a sample and ``activity(1)`` after each step:
   a↑ b↑ a↓ b↓ (overlap), a↑ b↑ b↓ a↓ (nested), and a↑b↑ then a↓b↓ together
   (coincident, ``simultaneous``);
4. ``_with_async``: each trigger t with each async/gate port q that is not a trigger:
   q↑ t↑ q↓ t↓, a sample after each step, then ``activity(1)``.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
import shutil
import traceback
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Protocol

from xut.catalog.unisim import parse_module
from xut.container import Executor, executor_for, sim_tool_versions
from xut.formats import xtr, xvec
from xut.formats.xvec import Vec
from xut.modelsrc import ModelSource
from xut.runners import xsim
from xut.runners.iverilog import IverilogRunner
from xut.stimcompile import TB, raw_to_trace, write_stim
from xut.stimgen import VecBuilder
from xut.validate import validate
from xut.verilatorize.analyze import TransformError
from xut.wrap import DutMap, spec_from_hdl, write_dut

GLBL_CHANNEL = ("GSR", "GTS", "GRESTORE")
HW_REASON = "verilatorize equivalence stimulus: simulation only (spec §6.2)"
ORACLES = ("iverilog", "xsim")
DONE = "XUT_DONE"
#: A compiler line that makes an Icarus build unclean, whatever the exit code.
_UNCLEAN = re.compile(r"\b(error|sorry):", re.IGNORECASE)
#: A simulator line that makes an Icarus run unclean (a model's own error messages are
#: not: both sides print them, and the traces are compared).
_SORRY = re.compile(r"\bsorry:", re.IGNORECASE)
_TIMEOUT_S = 900


class Subject(Protocol):
    """What the check needs from a model's analysis (an ``Analysis`` is one)."""

    @property
    def model(self) -> str: ...
    @property
    def path(self) -> Path: ...
    @property
    def triggers(self) -> list[str]: ...
    @property
    def enablers(self) -> list[str]: ...
    @property
    def nonconstant_overrides(self) -> bool: ...


@dataclass(frozen=True)
class Checked:
    """A transformed model as the driver's manifest records it (a ``Subject``)."""

    model: str
    path: Path
    triggers: list[str]
    enablers: list[str]
    nonconstant_overrides: bool


@dataclass
class EquivResult:
    model: str
    status: str  # pass | fail | error
    reason: str = ""
    mismatches: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    enablers: list[str] = field(default_factory=list)
    config: str = "default"
    oracle: str = ""  # iverilog | xsim; "" when the original never ran


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=")


def config_key(attrs: dict[str, str] | None) -> str:
    """``"default"``, or the sorted ``NAME=value`` pairs joined by ``,``. A ``\\``, ``,`` or
    ``=`` inside a name or value is escaped with ``\\``, so two configurations never share a
    key (``{"A": "1,B=2"}`` is ``A=1\\,B\\=2``, ``{"A": "1", "B": "2"}`` is ``A=1,B=2``)."""
    if not attrs:
        return "default"
    return ",".join(f"{_esc(k)}={_esc(attrs[k])}" for k in sorted(attrs))


def config_dir(key: str) -> str:
    """A directory (and wrapper configuration) name for ``key``: ``default``, or ``key``
    with every character outside ``[A-Za-z0-9_.-]`` replaced, plus a short hash of the key
    (two keys never share a directory)."""
    if key == "default":
        return key
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")[:80]
    return f"{slug}-{hashlib.sha256(key.encode()).hexdigest()[:8]}"


# ---- the equivalence stimulus -------------------------------------------------------------
@dataclass(frozen=True)
class _Trig:
    name: str  # as the analysis names it: a port, or glbl.<SIG>
    kind: str  # glbl | clock | async | data
    target: str  # the port, or the glbl signal
    ones: int = 1


class _Stim:
    def __init__(self, an: Subject, m: DutMap, seed: int) -> None:
        self.m, self.model = m, an.model
        self.b = VecBuilder(m, seed=seed)
        self.rng = random.Random(seed)
        self.clocks = list(dict.fromkeys(b.port for b in m.of("clk")))
        ins = m.in_ports()
        self.trigs = [self._trig(t, ins) for t in an.triggers]
        ports = {t.target for t in self.trigs if t.kind != "glbl"}
        self.data = [p for p in ins if m.cls_of(p) not in ("async", "gate") and p not in ports]
        self.asyncs = [p for p in ins if m.cls_of(p) in ("async", "gate") and p not in ports]
        self.held: set[str] = set()  # clock triggers asserted (high): not cycled
        self.on: set[str] = set()
        self.tag, self.n = "base", 0

    def _err(self, msg: str) -> TransformError:
        return TransformError(self.model, f"equivalence stimulus: {msg}")

    def _width(self, port: str) -> int:
        return len(self.m.port_bits("in", port))

    def _trig(self, name: str, ins: list[str]) -> _Trig:
        if name.startswith("glbl."):
            sig = name.removeprefix("glbl.")
            if sig not in GLBL_CHANNEL:
                raise self._err(f"trigger {name} has no glbl channel (only {GLBL_CHANNEL})")
            return _Trig(name, "glbl", sig)
        if name in self.clocks:
            return _Trig(name, "clock", name)
        if name not in ins:
            raise self._err(f"trigger {name} is not an input port of the wrapper")
        w = self._width(name)
        if self.m.cls_of(name) in ("async", "gate"):
            if w != 1:
                raise self._err(f"{w}-bit async/gate trigger {name} cannot be pulsed alone")
            return _Trig(name, "async", name)
        return _Trig(name, "data", name, (1 << w) - 1)

    def sample(self, what: str) -> None:
        self.b.sample(f"{self.tag}.{what}.{self.n}")
        self.n += 1

    def drive(self, t: _Trig, on: bool) -> None:
        if (t.name in self.on) == on:
            raise self._err(f"{t.name} driven to its current level")  # a generator bug
        (self.on.add if on else self.on.discard)(t.name)
        if t.kind == "glbl":
            self.b.glbl(t.target, int(on))
        elif t.kind == "clock":
            self.b.edge(t.target, on)
            (self.held.add if on else self.held.discard)(t.target)
        elif t.kind == "async":
            self.b.async_(t.target, int(on))
        else:
            self.b.set(**{t.target: t.ones if on else 0})

    def pulse_async(self, port: str, on: bool) -> None:
        if self._width(port) != 1:
            raise self._err(f"{self._width(port)}-bit async/gate port {port} cannot change alone")
        self.b.async_(port, int(on))

    def randomize(self) -> None:
        vals = {p: self.rng.getrandbits(self._width(p)) for p in self.data}
        if vals:
            self.b.set(**vals)

    def cycle(self, clock: str) -> None:
        """One cycle of ``clock`` (period spacing), a sample after each edge."""
        start = self.b.t
        self.b.edge(clock, True)
        self.sample(f"{clock}r")
        self.b.wait(max(0, start + self.b.period // 2 - self.b.t))
        self.b.edge(clock, False)
        self.sample(f"{clock}f")
        self.b.wait(max(0, start + self.b.period - self.b.t))

    def activity(self, n: int) -> None:
        free = [c for c in self.clocks if c not in self.held]
        for _ in range(n):
            if not free:
                self.randomize()
                self.sample("a")
            for c in free:
                self.randomize()
                self.cycle(c)

    @contextmanager
    def together(self) -> Iterator[None]:
        with self.b.simultaneous():
            yield


def _independent(s: _Stim) -> None:
    for t in s.trigs:
        for k in range(3):
            s.tag = f"ind.{t.name}.{k}"
            s.activity(2)
            s.drive(t, True)
            s.sample("on")
            s.activity(2)
            s.drive(t, False)
            s.sample("off")
            s.activity(1)


def _coincident(s: _Stim) -> None:
    for t in (t for t in s.trigs if t.kind != "clock"):
        for c in s.clocks:
            s.tag = f"coin.{t.name}.{c}"
            with s.together():
                s.b.edge(c, True)
                s.drive(t, True)
            s.sample("on")
            s.b.edge(c, False)
            s.sample("fall")
            s.activity(1)
            with s.together():
                s.b.edge(c, True)
                s.drive(t, False)
            s.sample("off")
            s.b.edge(c, False)
            s.sample("idle")


def _steps(s: _Stim, steps: Sequence[tuple[_Trig, bool]]) -> None:
    for t, on in steps:
        s.drive(t, on)
        s.sample(f"{t.name}{'u' if on else 'd'}")
        s.activity(1)


def _pairs(s: _Stim) -> None:
    for a, b in itertools.combinations(s.trigs, 2):
        s.tag = f"pair.{a.name}.{b.name}.overlap"
        _steps(s, [(a, True), (b, True), (a, False), (b, False)])
        s.tag = f"pair.{a.name}.{b.name}.nested"
        _steps(s, [(a, True), (b, True), (b, False), (a, False)])
        s.tag = f"pair.{a.name}.{b.name}.coincident"
        for on in (True, False):
            with s.together():
                s.drive(a, on)
                s.drive(b, on)
            s.sample("u" if on else "d")
            s.activity(1)


def _with_async(s: _Stim) -> None:
    for t in s.trigs:
        for q in s.asyncs:
            s.tag = f"async.{t.name}.{q}"
            s.pulse_async(q, True)
            s.sample(f"{q}u")
            s.drive(t, True)
            s.sample("u")
            s.pulse_async(q, False)
            s.sample(f"{q}d")
            s.drive(t, False)
            s.sample("d")
            s.activity(1)


def equiv_stimulus(an: Subject, m: DutMap, seed: int = 1) -> Vec:
    """The equivalence stimulus of ``an`` for wrapper map ``m`` (module docstring)."""
    s = _Stim(an, m, seed)
    s.activity(2)
    for phase in (_independent, _coincident, _pairs, _with_async):
        phase(s)
    vec = s.b.build()
    vec.hw_renderable, vec.hw_reason = False, HW_REASON
    report = validate(vec, m)
    if report.errors:  # a generator bug, never a stimulus to run
        raise s._err("invalid: " + "; ".join(report.errors[:5]))
    return vec


# ---- the check ------------------------------------------------------------------------------
#: A model's own message about why it stopped (UNISIM DRC/attribute checks, then $finish).
_MODEL_ERROR = re.compile(r"\berror\b", re.IGNORECASE)


@dataclass
class _Run:
    ok: bool
    why: str = ""
    raw: str = ""
    #: it compiled and ran, but stopped before XUT_DONE (``raw`` holds what it printed)
    early: bool = False


def _ended_early(what: str, rc: int | None, run_text: str, d: Path) -> _Run:
    """A run that stopped before XUT_DONE, with the model's own first error line (a UNISIM
    DRC or attribute check calls $finish) and the samples it printed before stopping."""
    msg = next(
        (ln.strip() for ln in run_text.splitlines() if _MODEL_ERROR.search(ln)), "no message"
    )
    raw = (d / "raw.txt").read_text() if (d / "raw.txt").is_file() else ""
    return _Run(False, f"{what} ended early (exit {rc}, no {DONE}): {msg}", raw, early=True)


def _icarus(
    ex: Executor,
    d: Path,
    out: Path,
    model_file: Path,
    libs: Sequence[Path],
    ms: ModelSource,
    timeout: int,
) -> _Run:
    """Compile and run the vector testbench on Icarus in ``d``. ``model_file`` (the
    original or the transformed copy) is compiled explicitly, so the model under test can
    never be resolved from another directory; ``libs`` (``-y``) serve only the models it
    instantiates."""
    d.mkdir()
    shutil.copy(out / "stim.memh", d / "stim.memh")
    log = d / "run.log"
    argv = [
        "iverilog", "-g2012", "-o", "sim.vvp", "-s", "xut_vector_tb", "-s", "glbl",
        "-I", ex.guest(out), "-I", ex.guest(out / "dut"),
        *(a for lib in libs for a in ("-y", ex.guest(lib))), "-Y", ".v",
        ex.guest(TB), ex.guest(out / "dut" / "xut_dut.v"), ex.guest(model_file),
        ex.guest(ms.glbl),
    ]  # fmt: skip
    rc, ctext = IverilogRunner.step(ex, argv, d, log, timeout)
    bad = [ln for ln in ctext.splitlines() if _UNCLEAN.search(ln)]
    if rc != 0 or bad:
        return _Run(False, f"compile failed (exit {rc}): {(bad or ['no diagnostic'])[0].strip()}")
    rc, rtext = IverilogRunner.step(ex, ["vvp", "-n", "sim.vvp"], d, log, timeout)
    bad = [ln for ln in rtext.splitlines() if _SORRY.search(ln)]
    if bad:
        return _Run(False, f"run reported: {bad[0].strip()}")
    if rc != 0 or DONE not in rtext:
        return _ended_early("simulation", rc, rtext, d)
    return _Run(True, raw=(d / "raw.txt").read_text())


def _xsim(d: Path, out: Path, an: Subject, ms: ModelSource, timeout: int) -> _Run:
    """The original model on xsim in ``d`` (Vivado sourced only in the script's subshell)."""
    d.mkdir()
    shutil.copy(out / "stim.memh", d / "stim.memh")
    text = xsim.render_script(
        d,
        [str(TB)],
        "xut_vector_tb",
        [str(out), str(out / "dut")],
        {},
        {},
        glbl=str(ms.glbl),
        libs=(),
        sourcelibdirs=[str(p) for p in ms.search],
        verilog_files=[str(out / "dut" / "xut_dut.v"), str(an.path)],
    )
    (d / "xsim.sh").write_text(text)
    rc = xsim.run_script(d, timeout)
    o = xsim.split_log((d / "run.log").read_text(errors="replace"), rc)
    if not o.compiled_ok:
        first = next((ln for ln in o.compile_text.splitlines() if "ERROR" in ln), "")
        return _Run(False, f"xsim compile failed (exit {rc}): {first.strip() or 'see run.log'}")
    if o.run_rc != 0 or DONE not in o.run_text:
        return _ended_early("xsim simulation", o.run_rc, o.run_text, d)
    return _Run(True, raw=(d / "raw.txt").read_text())


def _xsim_reason(an: Subject, force_xsim: bool) -> str:
    if force_xsim:
        return "xsim oracle forced"
    if an.nonconstant_overrides:
        return (
            "a non-constant override expression: Icarus 12 evaluates such a procedural "
            "continuous assign once (ruling S28b)"
        )
    return ""


def check_model(
    an: Subject,
    ms: ModelSource,
    out_dir: Path,
    attrs: dict[str, str] | None = None,
    *,
    lib: Path | None = None,
    seed: int = 1,
    force_xsim: bool = False,
) -> EquivResult:
    """Equivalence-check ``an``'s transformed model (in ``lib``, default ``vz_dir(ms)``)
    against its original for one attribute configuration, in ``out_dir`` (emptied first).
    Never raises: anything that goes wrong is an ``error`` result, with the traceback in
    ``error.log`` (when it can be written). ``result.json`` and ``mismatches.txt`` go in
    ``out_dir``; a result that cannot be recorded there is an ``error``. The transformed
    copy ``lib/<MODEL>.v`` must exist and differ from the original, else ``error``: the
    check never falls back to comparing the original with itself."""
    attrs = dict(attrs or {})
    res = EquivResult(an.model, "error", triggers=list(an.triggers))
    res.enablers = list(an.enablers)
    out = Path(out_dir)
    info: dict[str, object] = {}
    try:
        from xut.verilatorize import driver  # driver imports this module lazily

        res.config = config_key(attrs)
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        _check(an, ms, out, attrs, lib or driver.vz_dir(ms), seed, force_xsim, res, info)
    except Exception as e:  # an error result, never a pass
        res.status, res.reason = "error", f"{type(e).__name__}: {e}"
        _write(out / "error.log", traceback.format_exc())
    try:
        (out / "mismatches.txt").write_text("".join(f"{m}\n" for m in res.mismatches))
        doc = {
            **asdict(res),
            "mismatches": len(res.mismatches),
            "model_source": ms.name,
            "attrs": attrs,
            "seed": seed,
            **info,
        }
        (out / "result.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    except Exception as e:  # a verdict that cannot be recorded is not a verdict
        res.status = "error"
        res.reason = f"cannot record the result in {out}: {type(e).__name__}: {e}"
    return res


def _write(path: Path, text: str) -> None:
    """Best effort (the error result is returned either way)."""
    try:
        path.write_text(text)
    except OSError:
        return


def _check(
    an: Subject,
    ms: ModelSource,
    out: Path,
    attrs: dict[str, str],
    lib: Path,
    seed: int,
    force_xsim: bool,
    res: EquivResult,
    info: dict[str, object],
) -> None:
    cfg = config_dir(res.config)
    spec = spec_from_hdl(parse_module(an.path, an.model), cfg, attrs, raw_clock_out=True)
    # The wrapper instantiates the model with the attributes; the stimulus header does not
    # record them (result.json does): an .xvec header cannot hold a quoted string literal.
    m = replace(write_dut(spec, out / "dut"), attrs={})
    vec = equiv_stimulus(an, m, seed)
    xvec.dump(vec, out / "stim.xvec")
    comp = write_stim(vec, m, out)
    info["stimulus_sha256"] = xvec.digest(vec)
    info["samples"] = len(comp.labels)
    need_xsim = _xsim_reason(an, force_xsim)
    if need_xsim and not xsim.settings_available():
        res.reason = f"xsim oracle needed ({need_xsim}) but Vivado 2025.2 is unavailable"
        return
    copy = Path(lib) / f"{an.model}.v"
    if not copy.is_file():
        res.reason = f"no transformed copy of {an.model} at {copy}"
        return
    if copy.read_bytes() == Path(an.path).read_bytes():
        res.reason = f"the transformed copy {copy} is identical to the original {an.path}"
        return
    ex = executor_for(ms, lib)
    tools = {"iverilog": sim_tool_versions(ex, out)["iverilog"]}
    vz = _icarus(ex, out / "vz", out, copy, [lib, *ms.search], ms, _TIMEOUT_S)
    if not need_xsim:
        orig = _icarus(ex, out / "orig", out, Path(an.path), ms.search, ms, _TIMEOUT_S)
        res.oracle = "iverilog"
        if not orig.ok:
            need_xsim = f"Icarus does not run the original cleanly: {orig.why}"
    if need_xsim:
        info["oracle_reason"] = need_xsim
        if not xsim.settings_available():
            res.reason = f"xsim oracle needed ({need_xsim}) but Vivado 2025.2 is unavailable"
            return
        res.oracle = "xsim"
        tools["xsim"] = xsim.xsim_version(out)
        orig = _xsim(out / "orig-xsim", out, an, ms, _TIMEOUT_S)
    info["tools"] = tools
    header = {"model": ms.name, "prim": an.model, "cfg": cfg, "flow": "rtl"}
    if vz.early and orig.early:
        # Both stopped (a model's own DRC $finish): no verdict, but say how far they agreed.
        n = min(len(vz.raw.splitlines()), len(orig.raw.splitlines()))
        lab = comp.labels[:n]
        t_o = raw_to_trace(_first(orig.raw, n), lab, m, {**header, "runner": res.oracle})
        t_v = raw_to_trace(_first(vz.raw, n), lab, m, {**header, "runner": "iverilog-vz"})
        res.mismatches = [str(x) for x in xtr.diff(t_o, t_v)]
        info["samples_before_stop"] = n
        res.reason = (
            f"both models stopped before the end of the stimulus: the original on "
            f"{res.oracle}: {orig.why}; the transformed model on Icarus: {vz.why}; "
            f"{n} of {len(comp.labels)} samples ran, {len(res.mismatches)} differ"
        )
        return
    if not vz.ok:
        res.reason = f"transformed model on Icarus: {vz.why}"
        return
    if not orig.ok:
        res.reason = f"original model on {res.oracle}: {orig.why}"
        return
    t_orig = raw_to_trace(orig.raw, comp.labels, m, {**header, "runner": res.oracle})
    t_vz = raw_to_trace(vz.raw, comp.labels, m, {**header, "runner": "iverilog-vz"})
    xtr.dump(t_orig, out / "orig.xtr")
    xtr.dump(t_vz, out / "vz.xtr")
    res.mismatches = [str(x) for x in xtr.diff(t_orig, t_vz)]
    res.status = "fail" if res.mismatches else "pass"
    if res.mismatches:
        res.reason = f"{len(res.mismatches)} mismatch(es) against the original on {res.oracle}"


def _first(raw: str, n: int) -> str:
    """The first ``n`` sample lines of a raw.txt (samples print in order)."""
    return "".join(f"{ln}\n" for ln in raw.splitlines()[:n])
