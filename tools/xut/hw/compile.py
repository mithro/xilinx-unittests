# SPDX-License-Identifier: Apache-2.0
"""Compile an .xvec into a harness program (spec §7.1).

Only a hardware-renderable stimulus compiles (spec §5.1, ruling S8'): no free-running
clock, no glbl event, no pad/inout port, no x/z, no ``simultaneous`` group, and at least
max(async_sep_ps, min_event_gap_ps) between distinct event times. ``validate`` decides;
its ``hw_reasons`` become the ``HwUnrenderable`` message, which the hw runner records as
the configuration's skip reason.

The stepped harness renders the ORDER of events, so times are dropped:

- the ``t=0 set`` lines are the slot's power-on in_vec (``t0``). The bitstream bakes it
  into the harness flip-flops' INIT, so the DUT already sees it during the configuration
  start-up (GSR), as it does while glbl holds GSR in simulation;
- each later time step becomes, in file order, its ``set``s as one COMMIT (co-timed
  disjoint sets are one atomic change, ruling S6), then its edges, then its samples. The
  validator makes an edge or a sample lonely at its time, so a step never mixes kinds;
- ``end`` (or the end of the file) becomes END.
"""

from __future__ import annotations

from itertools import groupby

from xut.errors import XutError
from xut.formats.xvec import Vec
from xut.hw.image import MAXWORDS, HwImageError, HwProgram, ImageBuilder, width
from xut.stimcompile import StimCompileError, check_fits
from xut.wrap import DutMap

REJECT_REASON = (
    "an expect=reject configuration checks the simulation model's attribute check; "
    "a bitstream has no such check"
)


class HwCompileError(XutError, ValueError):
    """An invalid stimulus (structure, sizes or class rules): never compiled."""


class HwUnrenderable(XutError, ValueError):
    """A valid stimulus the stepped harness cannot render; the message is the reason."""


def t0_bits(vec: Vec, m: DutMap) -> str:
    """The in_vec before ``settle_ps`` (0 plus the ``t=0 set`` lines), MSB first."""
    bits = ["0"] * width(m.nin)
    for e in vec.events:
        if e.t >= vec.settle_ps:
            break
        for i, ch in enumerate(reversed(e.value)):  # check_structure: only t=0 sets here
            bits[e.lsb + i] = ch
    return "".join(reversed(bits))


def compile_program(vec: Vec, m: DutMap, maxwords: int = MAXWORDS) -> HwProgram:
    if vec.expect == "reject":  # first: whatever else is wrong, it never reaches hardware
        raise HwUnrenderable(REJECT_REASON)
    try:
        report = check_fits(vec, m)  # structure, sizes and `validate`, run once
    except StimCompileError as e:
        raise HwCompileError(str(e)) from e
    if report.hw_reasons:
        raise HwUnrenderable("; ".join(report.hw_reasons))
    t0 = t0_bits(vec, m)
    b = ImageBuilder(m.nin, m.nclk, width(m.nout), t0)
    bits = list(reversed(t0))  # bits[i] = in_vec[i]
    body = [e for e in vec.events if e.t >= vec.settle_ps]
    for _t, group in groupby(body, key=lambda e: e.t):
        events = list(group)
        sets = [e for e in events if e.op == "set"]
        for e in sets:
            for i, ch in enumerate(reversed(e.value)):
                bits[e.lsb + i] = ch
        if sets:
            b.set_bits("".join(reversed(bits)))
        for e in events:
            if e.op == "set":
                continue
            if e.op == "edge":
                b.edge(vec.clock(e.target).index, 1 if e.value == "r" else 0)
            elif e.op == "sample":
                b.sample(e.target)
            elif e.op != "end":  # validate already refuses these; stay loud regardless
                raise HwUnrenderable(f"t={e.t}: {e.op} has no stepped-harness rendering")
    try:
        return b.end(maxwords)
    except HwImageError as e:
        raise HwUnrenderable(f"harness capacity: {e}") from e
