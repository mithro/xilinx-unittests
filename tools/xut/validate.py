# SPDX-License-Identifier: Apache-2.0
"""Port-class rules for stimulus files (spec §5.1, §5.3) and hw renderability.

``xut.formats.xvec`` checks syntax and co-timing (Ruling S6: co-timed ``set``s on
disjoint bits are one atomic input change; any other co-timed group must be all
``simultaneous``). This module adds the §5.1 class rules on top, using the DUT map
for each ``in_vec`` bit's class, and decides whether the file can be rendered for
hardware. ``simultaneous`` makes a file legal for simulation but never
hardware-renderable.

``clock_start``/``clock_stop`` are not changes in their own right: the changes they
cause are the free-clock edges from ``free_clock_edges``, which are merged into the
timeline (so a ``clock_start`` does not collide with its own first rising edge).

What ``hw_renderable`` means (Ruling S8): *order-renderable*. The stepped hardware
harness renders the ORDER of events, not their picosecond times: it re-times every
event with a guaranteed gap of N system cycles, and the functional UNISIM models are
order-dependent only. So events at distinct times on ``stepped`` clocks stay
renderable however closely they are spaced in the file. The exception is a
``free``-running clock, whose edges the harness cannot re-time: any data, async/gate
or ``glbl GSR`` change closer than the recorded ``async_sep_ps`` to a free-clock edge
makes the file ``hw_renderable no`` (it stays legal for simulation). ``glbl GSR`` is
treated as an async input for every separation rule. The hardware harness must also
wait for the STARTUPE2 GSR release before the first event (a Step 3 requirement).

A file with any error is never hardware-renderable: ``Report.hw_renderable`` is
false whenever ``errors`` is non-empty, and ``mark`` refuses such a report. A ``Vec``
built in memory is also checked against the parser's structural rules
(``xvec.check_structure``), so parser-illegal co-timing is an error, not a silent yes.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from itertools import groupby

from xut.errors import XutError
from xut.formats.xvec import (
    Event,
    Vec,
    XvecError,
    check_structure,
    checkable,
    free_clock_edges,
    free_runs,
)
from xut.wrap import DutMap

#: THE minimum spacing, shared by the validator and xut.stimgen.VecBuilder: a sample
#: after a change and an async/gate change from a clock edge. 1 ns clears the UNISIM
#: 100 ps clock-to-Q. A file may record a larger ``async_sep_ps``, never a smaller one.
MIN_SEP_PS = 1_000
DEFAULT_GAP_PS = MIN_SEP_PS
DEFAULT_ASYNC_SEP_PS = MIN_SEP_PS
ROC_WIDTH_PS = 100_000  # glbl.v: GSR released after ROC_WIDTH
GRES_END_PS = 20_000  # glbl.v: GRES_START + GRES_WIDTH

#: Ops that are not input changes (clock_start/stop act through their computed edges).
_NOT_CHANGES = ("sample", "end", "clock_start", "clock_stop")


class ValidationError(XutError, ValueError):
    """An invalid stimulus was used where a valid one is required (``mark``)."""


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    hw_reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def hw_renderable(self) -> bool:
        """Order-renderable on the stepped hw harness (Ruling S8); never with errors."""
        return not self.errors and not self.hw_reasons


def _desc(e: Event) -> str:
    if e.op == "set":
        return f"set in[{e.msb}]" if e.msb == e.lsb else f"set in[{e.msb}:{e.lsb}]"
    return f"{e.op} {e.target}".strip()


def _check_header(vec: Vec, m: DutMap, r: Report) -> None:
    for key, want in (("nin", m.nin), ("nout", m.nout), ("nclk", m.nclk)):
        if getattr(vec, key) != want:
            r.errors.append(f"header {key}={vec.header[key]} but the wrapper has {want}")
    if vec.prim != m.prim:
        r.errors.append(f"header prim={vec.prim} but the wrapper is {m.prim}")
    if vec.cfg != m.cfg:
        r.errors.append(f"header cfg={vec.cfg} but the wrapper is configuration {m.cfg}")
    for k in sorted(vec.attrs.keys() | m.attrs.keys()):
        have, want = vec.attrs.get(k), m.attrs.get(k)
        if have != want:
            r.errors.append(
                f"header attr.{k}={have if have is not None else '(absent)'} but the "
                f"wrapper has {want if want is not None else '(not set)'}"
            )
    if vec.settle_ps < ROC_WIDTH_PS + MIN_SEP_PS:
        r.errors.append(
            f"settle_ps={vec.settle_ps} < glbl ROC_WIDTH {ROC_WIDTH_PS} + {MIN_SEP_PS} margin"
        )


def _check_free_stops(vec: Vec, r: Report) -> None:
    """A clock_stop must fall strictly inside a low phase (the testbench's generator then
    stops without another edge), and a restart must wait for that low phase to end."""
    for c, start, stop in free_runs(vec):
        if stop is None:
            continue
        high, pos = c.period * c.duty // 100, (stop - start) % c.period
        if not high < pos:
            r.errors.append(f"t={stop}: clock_stop {c.name} must fall strictly inside a low phase")
        restart = next(
            (
                e.t
                for e in vec.events
                if e.op == "clock_start" and e.target == c.name and e.t > stop
            ),
            None,
        )
        if restart is not None and restart < stop + (c.period - pos):
            r.errors.append(
                f"t={restart}: clock_start {c.name} before its previous low phase ended"
            )


def _check_set_classes(t: int, e: Event, cls: dict[int, str], r: Report) -> set[str]:
    """Class and hw checks every ``set`` gets, initialisation lines included."""
    classes = {cls[b] for b in range(e.lsb, e.msb + 1)}
    if "clock" in classes:
        r.errors.append(f"t={t}: set touches a clock-class bit")
    if set(e.value) - {"0", "1"}:
        r.hw_reasons.append(f"t={t}: x/z stimulus")
    if "pad" in classes:
        r.hw_reasons.append(f"t={t}: pad-class port needs the pad harness (spec §7.3)")
    return classes


def _nearest(ts: list[int], t: int) -> tuple[int, int] | None:
    """(distance, time) of the entry of sorted ``ts`` nearest to ``t``, or None."""
    i = bisect.bisect_left(ts, t)
    near = [(abs(x - t), x) for x in ts[max(0, i - 1) : i + 1]]
    return min(near) if near else None


def validate(vec: Vec, m: DutMap, *, min_sample_gap_ps: int = DEFAULT_GAP_PS) -> Report:
    r = Report()
    try:
        check_structure(vec)
    except XvecError as e:
        r.errors.append(f"structure: {e}")
        try:
            vec = checkable(vec)  # keep reporting class errors on the well-formed part
        except XvecError:
            return r  # the header itself is unusable
    _check_header(vec, m, r)
    if r.errors and (vec.nin != m.nin or vec.nclk != m.nclk):
        return r  # bit classes cannot be looked up against the wrong wrapper
    sep = int(vec.header.get("async_sep_ps", DEFAULT_ASYNC_SEP_PS))
    if sep < MIN_SEP_PS:
        r.errors.append(f"header async_sep_ps={sep} is below the minimum {MIN_SEP_PS}")
    cls = {b.bit: b.cls for b in m.of("in")}
    _check_free_stops(vec, r)
    for e in vec.events:
        if e.t == 0 and e.op == "set":
            _check_set_classes(0, e, cls, r)
    # Free-clock edges are changes like any other (review #6c): merged into the timeline,
    # they take part in the alone, sample-coincidence, sample-gap and async-separation rules.
    computed = free_clock_edges(vec)
    auto = {(e.t, e.target, e.value) for e in computed}
    timed = sorted(
        [e for e in vec.events if not (e.t == 0 and e.op == "set")] + computed,
        key=lambda e: e.t,
    )  # stable: file order within a time
    edges = [e.t for e in timed if e.op == "edge"]
    free_ts = [e.t for e in computed]  # sorted
    level: dict[str, str] = {c.name: "f" for c in vec.clocks}
    last_change: int | None = None
    for t, group in groupby(timed, key=lambda e: e.t):
        grp = list(group)
        changes = [e for e in grp if e.op not in _NOT_CHANGES]
        samples = [e for e in grp if e.op == "sample"]
        if samples and changes:
            r.errors.append(f"t={t}: a sample shares its time with a change")
        for s in samples:
            if last_change is not None and t - last_change < min_sample_gap_ps:
                r.errors.append(
                    f"t={t}: sample {s.target} is {t - last_change} ps after the last "
                    f"change (< {min_sample_gap_ps})"
                )
        lonely, mixed_line = [], []
        for e in changes:
            if e.op in ("edge", "glbl"):
                if len(changes) > 1:
                    lonely.append(e)
            elif e.op == "set":
                classes = [cls[b] for b in range(e.lsb, e.msb + 1)]
                n_async = sum(c in ("async", "gate") for c in classes)
                if n_async and len(changes) > 1:
                    lonely.append(e)
                if n_async > 1 or 0 < n_async < len(classes):
                    mixed_line.append((e, n_async, len(classes) - n_async))
        if not all(e.simultaneous for e in changes):
            for e, n_async, n_other in mixed_line:
                r.errors.append(
                    f"t={t}: {_desc(e)} changes {n_async} async/gate bit(s) and {n_other} "
                    "other bit(s) in one line: split the async/gate and data changes, and "
                    "each async/gate bit, into separate event times (spec §5.1)"
                )
            if lonely:
                r.errors.append(
                    f"t={t}: {', '.join(_desc(e) for e in lonely)} must be alone in its "
                    "event (spec §5.1) or every event at this time marked 'simultaneous'"
                )
        if any(e.simultaneous for e in grp):
            r.hw_reasons.append(f"t={t}: simultaneous events")
        for e in changes:
            if e.op == "edge":
                if vec.clock(e.target).mode == "free":
                    if (e.t, e.target, e.value) not in auto:
                        r.errors.append(f"t={t}: explicit edge on free-running {e.target}")
                elif level[e.target] == e.value:
                    r.errors.append(f"t={t}: edges on {e.target} must alternate r/f from idle 0")
                level[e.target] = e.value
                continue
            gsr = e.op == "glbl" and e.target == "GSR"
            if e.op == "glbl" and not gsr:
                r.hw_reasons.append(f"t={t}: glbl {e.target} is sim-only (spec §5.2)")
                continue
            is_async = gsr
            if e.op == "set":
                is_async = bool(_check_set_classes(t, e, cls, r) & {"async", "gate"})
            if is_async and not e.simultaneous:
                d = _nearest(edges, t)
                if d is not None and d[0] < sep:
                    r.errors.append(
                        f"t={t}: {'GSR' if gsr else 'async/gate'} change {d[0]} ps from a "
                        f"clock edge (< async_sep_ps={sep})"
                    )
            d = _nearest(free_ts, t)
            if d is not None and d[0] < sep:
                edge = next(x for x in computed if x.t == d[1])
                r.hw_reasons.append(
                    f"t={t}: {_desc(e)} is {d[0]} ps from free-running {edge.target} edge "
                    f"{edge.value} at t={edge.t} (< async_sep_ps={sep}; spec §5.1, Ruling S8)"
                )
        if changes:
            last_change = t
    return r


def mark(vec: Vec, report: Report) -> None:
    """Record ``report``'s hw renderability in ``vec`` (its ``hw_renderable`` line).
    Refuses a report with errors: an invalid file has no renderability to record."""
    if report.errors:
        raise ValidationError(f"cannot mark an invalid stimulus: {report.errors[0]}")
    vec.hw_renderable = report.hw_renderable
    vec.hw_reason = "; ".join(report.hw_reasons)
