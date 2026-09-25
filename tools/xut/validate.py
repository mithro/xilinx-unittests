# SPDX-License-Identifier: Apache-2.0
"""Port-class rules for stimulus files (spec §5.1, §5.3) and hw renderability.

``xut.formats.xvec`` checks syntax and co-timing (Ruling S6: co-timed ``set``s on
disjoint bits are one atomic input change; any other co-timed group must be all
``simultaneous``, and marking is all-or-nothing). This module adds the §5.1 class
rules on top, using the DUT map for each ``in_vec`` bit's class, and decides whether
the file can be rendered for hardware. ``simultaneous`` makes a file legal for
simulation but never hardware-renderable.

``clock_start``/``clock_stop`` are not changes in their own right: the changes they
cause are the free-clock edges from ``free_clock_edges``, which are merged into the
timeline (so a ``clock_start`` does not collide with its own first rising edge).

What ``hw_renderable`` means (Ruling S8-prime): *order-renderable on the stepped
harness*. The stepped hardware harness renders the ORDER of events, not their
picosecond times: it re-times every event with a gap of N system cycles. That
preserves behaviour only under two conditions, both enforced here:

- **No free-running clock.** A ``mode=free`` clock keeps running while the harness
  inserts its system cycles, so re-timing would change how many free-clock edges
  fall between two events. Any file declaring a ``mode=free`` clock is ``hw no``
  ("free-running clocks need real-time rendering (step 3)") until step 3 defines
  real-time rendering. The free-clock separation rules stay as simulation errors.
- **Every model-internal delay is shorter than the event gap.** Stepped rendering is
  order-preserving only when all of the primitive's model-internal delays (UNISIM
  ``#`` delays, tap chains, ...) are shorter than the smallest gap between distinct
  event times. So every such gap (``t=0`` initialisation excluded) must be at least
  ``min_event_gap(async_sep_ps, map)`` = ``max(async_sep_ps, the primitive's
  catalog min_event_gap_ps)``, where the catalog value defaults to ``MIN_SEP_PS``
  (1 ns clears FDRE's 100 ps clock-to-Q); a smaller gap is ``hw no``. Units whose
  primitives have longer internal delays MUST set ``min_event_gap_ps`` in
  ``<PRIM>.overrides.yaml`` (e.g. IDELAYE2: 31 taps x 78 ps plus DELAY_D is about
  2.4 ns). ``xut.stimgen.VecBuilder`` uses the same value as its gap.

Further ``hw no`` reasons: x/z stimulus; ``glbl GTS``/``GRESTORE`` (sim-only, spec
§5.2); any ``glbl GSR`` event (GSR on hardware needs the GSR-immune harness of spec
§7.2, step 3; GSR is still an async input for every simulation separation rule); and
any ``pad``-class bit or ``inout`` port in the map, input or output (they are only
realisable through the pad harness, spec §7.3). The hardware harness must also wait
for the STARTUPE2 GSR release before the first event (a step 3 requirement).

``Report.x_inputs`` is true when any ``set`` (initialisation included) drives an
``x`` or ``z`` bit. 2-state runners (Verilator, hardware) cannot represent such a
stimulus and must skip it with a reason rather than run it (the runners of PR B
implement that).

Explicitly deferred, not supported yet:

- the ``JTAG_*`` signals of glbl's channel (spec §5.2; used by BSCANE2): the grammar
  has only ``GSR``/``GTS``/``GRESTORE``; they arrive with the configuration group;
- DRP transactions (spec §5.5): ``drp``-class bits are validated as ``data`` for
  now, so a cycle-exact DRDY expectation is NOT refused here yet; the DRP
  transaction layer that §5.5 requires builds on the map's class record.

An ``expect=reject`` stimulus must name the attribute(s) it makes illegal (header
``illegal=``, each one an ``attr.<NAME>`` it sets; ruling S13b): the reject rule accepts
only an error naming one of them as evidence.

Zero evidence is never a pass (ruling S15): a stimulus that is not ``expect=reject``
must have at least one ``sample``, else it is an error (its expected trace would be
empty, and every runner would "pass" it while checking nothing).

glbl's start-up GSR release at ``ROC_WIDTH`` is an implicit async change: every event,
free-clock edges included, must be at least ``async_sep_ps`` away from it, or it races
the release (an error).

The settle window covers glbl's start-up pulses: ``settle_ps >= MIN_SETTLE_PS =
max(ROC_WIDTH, GRES_START + GRES_WIDTH) + SETTLE_MARGIN_PS``, from constants that a
test checks against every model source's ``glbl.v``.

A file with any error is never hardware-renderable: ``Report.hw_renderable`` is
false whenever ``errors`` is non-empty, and ``mark`` refuses such a report. A ``Vec``
built in memory is held to every rule the parser applies (``xvec.check_structure``),
so an in-memory Vec that would not parse back is an error, never a silent yes;
validation then continues on its well-formed part (``xvec.checkable``).
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
#: glbl.v parameters (1 ps timescale), checked against every model source's glbl.v by
#: tools/tests/test_validate.py.
ROC_WIDTH_PS = 100_000  # GSR released after ROC_WIDTH
GRES_START_PS = 10_000  # GTS/GRESTORE (PRLD) pulse starts
GRES_WIDTH_PS = 10_000  # ... and lasts GRES_WIDTH
GRES_END_PS = GRES_START_PS + GRES_WIDTH_PS
SETTLE_MARGIN_PS = MIN_SEP_PS
#: The shortest legal settle_ps: every glbl start-up pulse is over, plus a margin.
MIN_SETTLE_PS = max(ROC_WIDTH_PS, GRES_END_PS) + SETTLE_MARGIN_PS

FREE_CLOCK_REASON = "free-running clocks need real-time rendering (step 3)"

#: Ops that are not input changes (clock_start/stop act through their computed edges).
_NOT_CHANGES = ("sample", "end", "clock_start", "clock_stop")


class ValidationError(XutError, ValueError):
    """An invalid stimulus was used where a valid one is required (``mark``)."""


def min_event_gap(async_sep_ps: int, m: DutMap) -> int:
    """THE minimum gap between distinct event times for stepped hw rendering (Ruling
    S8-prime), shared with ``xut.stimgen.VecBuilder``: ``max(async_sep_ps, the
    primitive's min_event_gap_ps)``, the latter defaulting to ``MIN_SEP_PS``."""
    return max(async_sep_ps, m.min_event_gap_ps or MIN_SEP_PS)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    hw_reasons: list[str] = field(default_factory=list)
    #: Some ``set`` drives x or z: 2-state runners (Verilator, hw) must skip the file.
    x_inputs: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def hw_renderable(self) -> bool:
        """Order-renderable on the stepped hw harness (Ruling S8-prime); never with errors."""
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
    if vec.settle_ps < MIN_SETTLE_PS:
        r.errors.append(
            f"settle_ps={vec.settle_ps} < {MIN_SETTLE_PS} = max(glbl ROC_WIDTH {ROC_WIDTH_PS}, "
            f"GRES_START+GRES_WIDTH {GRES_END_PS}) + {SETTLE_MARGIN_PS} margin"
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
        r.x_inputs = True
    return classes


def _check_map_hw(vec: Vec, m: DutMap, r: Report) -> None:
    """File-level hw reasons that do not depend on the events."""
    pads = [b.port for b in m.bits if b.cls in ("pad", "inout") or b.role]
    if pads:
        r.hw_reasons.append(
            f"pad-class or inout port(s) {', '.join(dict.fromkeys(pads))} need the pad "
            "harness (spec §7.3)"
        )
    free = [c.name for c in vec.clocks if c.mode == "free"]
    if free:
        r.hw_reasons.append(f"{FREE_CLOCK_REASON}: {', '.join(free)}")


def _check_event_gaps(vec: Vec, gap: int, r: Report) -> None:
    """Every gap between distinct event times (initialisation excluded) >= ``gap``."""
    ts = sorted({e.t for e in vec.events if not (e.t == 0 and e.op == "set")})
    for prev, t in zip(ts, ts[1:], strict=False):
        if t - prev < gap:
            r.hw_reasons.append(
                f"t={t}: {t - prev} ps after the previous event at t={prev} (< min event "
                f"gap {gap} ps; stepped rendering preserves order only, Ruling S8-prime)"
            )


def _nearest(ts: list[int], t: int) -> tuple[int, int] | None:
    """(distance, time) of the entry of sorted ``ts`` nearest to ``t``, or None."""
    i = bisect.bisect_left(ts, t)
    near = [(abs(x - t), x) for x in ts[max(0, i - 1) : i + 1]]
    return min(near) if near else None


def _check_reject(vec: Vec, r: Report) -> None:
    """Ruling S13b: an ``expect=reject`` configuration names the attribute(s) it makes
    illegal (header ``illegal=``), each one it sets; nothing else carries ``illegal``."""
    if vec.expect == "reject":
        if not vec.illegal:
            r.errors.append(
                "reject config must name its illegal attribute: header illegal=<NAME>[,...] "
                "(GenContext.dut(..., expect='reject', illegal=[...]))"
            )
        for n in vec.illegal:
            if n not in vec.attrs:
                r.errors.append(f"illegal={n} is not an attribute this configuration sets")
    elif "illegal" in vec.header:
        r.errors.append("header illegal= is only meaningful with expect=reject")


def _check_gsr_release(timed: list[Event], sep: int, r: Report) -> None:
    """glbl releases its start-up GSR at ROC_WIDTH with no event in the file: an
    implicit async change. Any event (free-clock edges and samples included) within
    ``async_sep_ps`` of it races the release, which the language does not order."""
    for t in sorted({e.t for e in timed}):
        if abs(t - ROC_WIDTH_PS) < sep:
            what = ", ".join(dict.fromkeys(_desc(e) for e in timed if e.t == t))
            r.errors.append(
                f"t={t}: {what} is {abs(t - ROC_WIDTH_PS)} ps from glbl's GSR release at "
                f"ROC_WIDTH={ROC_WIDTH_PS} (< async_sep_ps={sep}): it races the release"
            )


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
    _check_map_hw(vec, m, r)
    _check_event_gaps(vec, min_event_gap(sep, m), r)
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
    _check_gsr_release(timed, sep, r)
    _check_reject(vec, r)
    if vec.expect != "reject" and not any(e.op == "sample" for e in vec.events):
        r.errors.append(
            "no samples: a stimulus must sample the outputs at least once (ruling S15: "
            "an empty expected trace would pass on every runner while checking nothing)"
        )
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
            if gsr:
                r.hw_reasons.append(
                    f"t={t}: glbl GSR on hardware needs the GSR-immune harness (spec §7.2; step 3)"
                )
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
