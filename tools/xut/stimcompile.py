# SPDX-License-Identifier: Apache-2.0
"""Compile an .xvec into the generic testbench's operation image, and read raw samples back.

The testbench (``hdl/xut_vector_tb.sv``, ``TB``) is the same for every primitive. It
replays ``stim.memh``, one 128-bit operation word per line::

    127:120 op    1 SET, 2 EDGE, 3 GLBL, 4 SAMPLE, 5 CLK_HI, 6 CLK_START, 7 CLK_STOP, 15 END
    119:96  idx   in_vec bit | clock index | glbl signal (0 GSR, 1 GTS, 2 GRESTORE) | sample no.
     95:64  val   SET 0/1/2(x)/3(z); EDGE 1 rise / 0 fall; GLBL 0/1;
                  CLK_HI high time (ps); CLK_START low time (ps)
     63:0   t     absolute time (ps)

A multi-bit ``set`` becomes one SET per bit, LSB first, at the same time; the testbench
commits all SETs of one time step in one assignment (one atomic input change, ruling
S6). A free-running clock becomes CLK_HI + CLK_START where ``xvec.free_runs`` (with
``free_clock_edges`` THE free-clock definition) starts it, and CLK_STOP where it stops,
so the edges the testbench generates are exactly the ones golden replay and validate
use. Words are sorted by time, stably, so file order is kept within a time step.

The testbench prints ``S <n> <out_vec %b>`` per sample to ``raw.txt`` and ``XUT_DONE``
on END; ``raw_to_trace`` turns ``raw.txt`` back into an ``.xtr`` trace.

``compile_vec`` checks structure (``xvec.check_structure``), that the stimulus fits the
wrapper, and runs ``xut.validate.validate``: a stimulus with any validation error is
refused (ruling S11, as golden replay does under S9). ``hw_renderable=no`` is fine, and
a ``simultaneous`` group, which golden replay refuses, is still compiled here
(simulation-only checks).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from xut.errors import XutError
from xut.formats.xtr import Trace
from xut.formats.xvec import Vec, XvecError, check_structure, free_runs
from xut.validate import validate
from xut.wrap import DutMap

TB = Path(__file__).resolve().parent / "hdl" / "xut_vector_tb.sv"
OPS = {
    "set": 1,
    "edge": 2,
    "glbl": 3,
    "sample": 4,
    "clk_hi": 5,
    "clk_start": 6,
    "clk_stop": 7,
    "end": 15,
}
_BIT = {"0": 0, "1": 1, "x": 2, "z": 3}
_GLBL = {"GSR": 0, "GTS": 1, "GRESTORE": 2}
_IDX_MAX, _VAL_MAX, _T_MAX = (1 << 24) - 1, (1 << 32) - 1, (1 << 64) - 1
#: Time from the last event to the END appended when the stimulus has no ``end``.
END_MARGIN_PS = 1_000
_RAW = re.compile(r"^S (\d+) ([01xzXZ]+)$")


class StimCompileError(XutError, ValueError):
    """A stimulus the testbench cannot replay, or a raw.txt it did not write."""


@dataclass
class Compiled:
    words: list[int]
    labels: list[str]


def _w(op: str, idx: int, val: int, t: int) -> int:
    if not (0 <= idx <= _IDX_MAX and 0 <= val <= _VAL_MAX and 0 <= t <= _T_MAX):
        raise StimCompileError(f"{op} idx={idx} val={val} t={t} does not fit the operation word")
    return (OPS[op] << 120) | (idx << 96) | (val << 64) | t


def _check_fits(vec: Vec, m: DutMap) -> None:
    try:
        check_structure(vec)
    except XvecError as e:
        raise StimCompileError(f"{vec.prim}/{vec.cfg}: malformed stimulus: {e}") from e
    for key in ("nin", "nout", "nclk"):
        if getattr(vec, key) != getattr(m, key):
            raise StimCompileError(
                f"{vec.prim}/{vec.cfg}: stimulus {key}={getattr(vec, key)} does not match "
                f"the wrapper's {key}={getattr(m, key)}"
            )
    if (vec.prim, vec.cfg) != (m.prim, m.cfg):
        raise StimCompileError(
            f"stimulus {vec.prim}/{vec.cfg} is not for the wrapper {m.prim}/{m.cfg}"
        )
    for c in vec.clocks:
        if c.mode == "free":
            _clock_words(vec, c.name, 0)  # refuses a free clock with an empty phase
    # Ruling S11 (like golden replay, S9): no path may compile an invalid stimulus.
    # hw_reasons (hw_renderable=no, simultaneous groups, x/z) are fine: this is simulation.
    report = validate(vec, m)
    if report.errors:
        raise StimCompileError(
            f"{vec.prim}/{vec.cfg}: stimulus is invalid, refusing to compile:\n  "
            + "\n  ".join(report.errors)
        )


def _clock_words(vec: Vec, name: str, t: int) -> list[int]:
    c = vec.clock(name)
    high = c.period * c.duty // 100
    low = c.period - high
    if high <= 0 or low <= 0:
        raise StimCompileError(
            f"clock {name}: period={c.period} duty={c.duty} gives high={high} ps, "
            f"low={low} ps; both must be > 0 for the testbench's clock generator"
        )
    return [_w("clk_hi", c.index, high, t), _w("clk_start", c.index, low, t)]


def compile_vec(vec: Vec, m: DutMap) -> Compiled:
    """The operation words and sample labels (in sample-number order) of ``vec``."""
    _check_fits(vec, m)
    words: list[int] = []
    labels: list[str] = []
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
            words += _clock_words(vec, e.target, e.t)
        elif e.op == "clock_stop":
            words.append(_w("clk_stop", vec.clock(e.target).index, 0, e.t))
        elif e.op == "end":
            words.append(_w("end", 0, 0, e.t))
        else:  # check_structure refuses unknown ops; keep the compiler loud regardless
            raise StimCompileError(f"unknown op {e.op!r}")
    # A free clock with no clock_start starts at max(0, phase) (free_runs); after the
    # events of that time step, so the time-0 values are applied before its first rise.
    explicit = {e.target for e in vec.events if e.op == "clock_start"}
    for c, start, _stop in free_runs(vec):
        if c.name not in explicit:
            words += _clock_words(vec, c.name, start)
    if not vec.events or vec.events[-1].op != "end":
        last = vec.events[-1].t if vec.events else vec.settle_ps
        words.append(_w("end", 0, 0, last + END_MARGIN_PS))
    words.sort(key=lambda w: w & _T_MAX)  # stable: keeps file order within a time
    return Compiled(words, labels)


def write_stim(vec: Vec, m: DutMap, out_dir: Path) -> Compiled:
    """Write ``stim.memh``, ``stim.vh`` and ``labels.json`` into ``out_dir``."""
    c = compile_vec(vec, m)
    out_dir = Path(out_dir)
    (out_dir / "stim.memh").write_text("".join(f"{w:032x}\n" for w in c.words))
    (out_dir / "stim.vh").write_text(
        f"// SPDX-License-Identifier: Apache-2.0\n`define XUT_MAXOPS {len(c.words)}\n"
    )
    (out_dir / "labels.json").write_text(json.dumps(c.labels) + "\n")
    return c


def raw_to_trace(raw: str, labels: list[str], m: DutMap, header: dict[str, str]) -> Trace:
    """The testbench's ``raw.txt`` as a trace. Every line must be ``S <n> <bits>`` with
    ``n`` a known sample, seen once, and exactly ``max(1, nout)`` bits, and every label
    must be printed exactly once; anything else is an error (never skipped or padded)."""
    t = Trace(dict(header))
    width = max(1, m.nout)
    ports = {  # MSB first
        p: sorted((b for b in m.of("out") if b.port == p), key=lambda b: -b.index)
        for p in m.out_ports()
    }
    seen: set[int] = set()
    for n, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        r = _RAW.match(line.strip())
        if not r:
            raise StimCompileError(f"raw.txt line {n}: expected 'S <n> <bits>', got {line!r}")
        k, bits = int(r.group(1)), r.group(2).lower()
        if k >= len(labels):
            raise StimCompileError(f"raw.txt line {n}: sample {k} but only {len(labels)} labels")
        if k in seen:
            raise StimCompileError(f"raw.txt line {n}: sample {k} ({labels[k]}) printed twice")
        if len(bits) != width:
            raise StimCompileError(
                f"raw.txt line {n}: {len(bits)} bits, but out_vec width is {width}"
            )
        seen.add(k)
        by_index = bits[::-1]  # by_index[i] is out_vec[i]
        t.add(labels[k], {p: "".join(by_index[b.bit] for b in pb) for p, pb in ports.items()})
    missing = [f"{k} ({labels[k]})" for k in range(len(labels)) if k not in seen]
    if missing:
        more = f", ... ({len(missing) - 5} more)" if len(missing) > 5 else ""
        raise StimCompileError(f"raw.txt: sample(s) {', '.join(missing[:5])}{more} never printed")
    return t
