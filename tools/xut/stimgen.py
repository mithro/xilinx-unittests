# SPDX-License-Identifier: Apache-2.0
"""Stimulus builder: emits only .xvec files that satisfy xut.validate.

Time only moves forward. Every event except a data ``set`` advances the cursor
past itself, so ``set``s are the only events that can share a time, and then only
on distinct ports (disjoint bit ranges: one atomic input change, Ruling S6); a
``set`` of a port already set at the current time moves ``gap_ps`` later. A
stepped ``cycle`` (period ``P``, gap ``g``, start ``s``) is: ``s`` rising edge,
``s+g`` sample, ``s+P/2`` falling edge, ``s+P/2+g`` sample, next data at ``s+P``.
``simultaneous()`` groups two or more changes at one instant, all marked
``simultaneous`` (simulation only; never hardware-renderable).

The output is valid by construction: ``gap_ps`` and ``async_sep_ps`` may not be
below ``xut.validate.MIN_SEP_PS`` (the validator's own minimum), and the separation
used is recorded in the header as ``async_sep_ps``, which ``validate`` then applies.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from xut.errors import XutError
from xut.formats.xvec import Clock, Event, Vec
from xut.validate import DEFAULT_ASYNC_SEP_PS, DEFAULT_GAP_PS, MIN_SEP_PS, ROC_WIDTH_PS
from xut.wrap import DutMap, DutSpec, build_map, spec_from_catalog

DEFAULT_SETTLE_PS = 120_000
DEFAULT_PERIOD_PS = 10_000


class BuilderError(XutError, ValueError):
    """A generator asked for a stimulus the builder cannot emit validly."""


class VecBuilder:
    def __init__(
        self,
        m: DutMap,
        *,
        seed: int,
        settle_ps: int = DEFAULT_SETTLE_PS,
        period_ps: int = DEFAULT_PERIOD_PS,
        gap_ps: int = DEFAULT_GAP_PS,
        async_sep_ps: int = DEFAULT_ASYNC_SEP_PS,
        expect: str | None = None,
    ) -> None:
        for name, v in (("gap_ps", gap_ps), ("async_sep_ps", async_sep_ps)):
            if v < MIN_SEP_PS:
                raise BuilderError(
                    f"{name}={v} is below the validator's minimum MIN_SEP_PS={MIN_SEP_PS}"
                )
        if settle_ps < ROC_WIDTH_PS + MIN_SEP_PS:
            raise BuilderError(
                f"settle_ps={settle_ps} < glbl ROC_WIDTH {ROC_WIDTH_PS} + {MIN_SEP_PS} margin"
            )
        if 3 * gap_ps > period_ps // 2:
            raise BuilderError(
                f"period_ps={period_ps} too short for edge + sample + change spacing "
                f"(needs >= {6 * gap_ps} with gap_ps={gap_ps})"
            )
        self.m, self.seed, self.settle, self.period = m, seed, settle_ps, period_ps
        self.gap, self.sep, self.expect = gap_ps, async_sep_ps, expect
        self.t = settle_ps
        self._events: list[Event] = []
        self._vals: dict[str, int | str] = {p: 0 for p in m.in_ports()}
        self._level = {f"clk{b.bit}": False for b in m.of("clk")}  # idle 0
        self._set_at: tuple[int, set[str]] = (-1, set())  # ports set at one time
        self._last_change = 0
        self._last_edge: int | None = None
        self._n = 0
        self._sim: list[Event] | None = None  # events of the open simultaneous() block

    # -- helpers -------------------------------------------------------------
    def _emit(self, op: str, target: str = "", lsb: int = 0, msb: int = 0, value: str = "") -> None:
        e = Event(self.t, op, target, lsb, msb, value, self._sim is not None)
        self._events.append(e)
        if self._sim is not None:
            self._sim.append(e)

    def _after(self, t: int) -> None:
        self.t = max(self.t, t)

    def _put(self, port: str, value: int | str) -> None:
        bits = self.m.port_bits("in", port)
        if not bits:
            raise BuilderError(f"{self.m.prim} has no in_vec port {port!r}")
        at, ports = self._set_at
        if at != self.t:
            self._set_at = (self.t, ports := set())
        if port in ports:
            raise BuilderError(f"t={self.t}: {port} set twice at one time")
        ports.add(port)
        width = len(bits)
        if isinstance(value, str):
            s = value
            if len(s) != width or set(s) - set("01xz"):
                raise BuilderError(f"{port}: {value!r} is not {width} character(s) of 01xz")
        else:
            if not 0 <= value < 1 << width:
                raise BuilderError(f"{port}: {value} does not fit in {width} bit(s)")
            s = format(value, f"0{width}b")
        self._emit("set", "in", bits[0].bit, bits[-1].bit, s)
        self._vals[port] = value
        self._last_change = self.t

    def _alone_start(self) -> None:
        if self._sim is None:
            self._after(self._last_change + self.gap)

    def _alone_end(self) -> None:
        if self._sim is None:
            self.t += self.gap

    def _not_in_sim(self, what: str) -> None:
        if self._sim is not None:
            raise BuilderError(f"{what} inside simultaneous(): only changes share its instant")

    def value(self, port: str) -> int | str:
        """The current value of input ``port`` (0 until set)."""
        if port not in self._vals:
            raise BuilderError(f"{self.m.prim} has no in_vec port {port!r}")
        return self._vals[port]

    # -- API -----------------------------------------------------------------
    def init(self, **ports: int | str) -> None:
        """Initial input values at t=0 (spec §5.3 initialisation lines)."""
        if any(e.t > 0 for e in self._events):
            raise BuilderError("init() must come before any timed event")
        self._not_in_sim("init()")
        t, self.t = self.t, 0
        for p, v in ports.items():
            self._put(p, v)
        self.t, self._last_change = t, 0

    def set(self, **ports: int | str) -> None:
        """Change data-class inputs together, strictly between clock edges."""
        for p in ports:
            if self.m.cls_of(p) in ("async", "gate", "clock") and self._sim is None:
                raise BuilderError(f"{p} is {self.m.cls_of(p)}-class: use async_() or edge()")
        if self._last_edge is not None and self._sim is None:
            self._after(self._last_edge + self.gap)
        at, already = self._set_at
        if self._sim is None and at == self.t and already & ports.keys():
            self.t += self.gap  # a second change of a port: a new input change, not a glitch
        for p, v in ports.items():
            if self._vals.get(p) != v:
                self._put(p, v)

    def async_(self, port: str, value: int | str) -> None:
        """Change one async/gate input alone, >= async_sep_ps away from clock edges."""
        if self._sim is None and len(self.m.port_bits("in", port)) > 1:
            raise BuilderError(
                f"{port} is {len(self.m.port_bits('in', port))} bits wide: several async/gate "
                "bits cannot change in one event outside simultaneous() (spec §5.1)"
            )
        if self._sim is None:
            self._alone_start()
            if self._last_edge is not None:
                self._after(self._last_edge + self.sep)
        self._put(port, value)
        self._alone_end()
        if self._sim is None:
            self._after(self._last_change + self.sep)

    def glbl(self, sig: str, value: int) -> None:
        """Drive glbl ``sig`` (GSR is hw-renderable; GTS/GRESTORE are sim-only)."""
        if sig not in ("GSR", "GTS", "GRESTORE") or value not in (0, 1):
            raise BuilderError(f"bad glbl event {sig}={value}")
        self._alone_start()
        self._emit("glbl", sig, value=str(value))
        self._last_change = self.t
        self._alone_end()

    def edge(self, port: str, rising: bool) -> None:
        """One edge on stepped clock ``port``; edges alternate from the idle 0."""
        name = self.m.clock_name(port)
        if self._level[name] == rising:
            raise BuilderError(f"edges on {port} must alternate r/f from idle 0")
        self._alone_start()
        self._emit("edge", name, value="r" if rising else "f")
        self._level[name] = rising
        self._last_edge = self._last_change = self.t
        self._alone_end()

    def sample(self, label: str | None = None) -> str:
        """Sample the outputs >= gap_ps after the last change; returns the label."""
        self._not_in_sim("sample()")
        self._after(self._last_change + self.gap)
        label = label or f"S{self._n}"
        self._n += 1
        self._emit("sample", label)
        self.t += self.gap
        return label

    def cycle(self, port: str | None = None, *, n: int = 1, sample: bool = True) -> None:
        """``n`` full clock cycles on ``port`` (the only clock when omitted)."""
        self._not_in_sim("cycle()")
        if port is None:
            clocks = list(dict.fromkeys(b.port for b in self.m.of("clk")))
            if len(clocks) != 1:
                raise BuilderError(f"cycle() needs a port: clocks are {clocks}")
            port = clocks[0]
        for _ in range(n):
            self._after(self._last_change + self.gap)
            start = self.t
            self.edge(port, True)
            if sample:
                self.sample()
            self._after(start + self.period // 2)
            self.edge(port, False)
            if sample:
                self.sample()
            self._after(start + self.period)

    def wait(self, ps: int) -> None:
        """Advance time by ``ps``."""
        self._not_in_sim("wait()")
        if ps < 0:
            raise BuilderError(f"wait({ps}): time never goes backwards")
        self.t += ps

    @contextmanager
    def simultaneous(self) -> Iterator[None]:
        """Events inside happen at one instant, all marked 'simultaneous' (sim only)."""
        self._not_in_sim("simultaneous()")
        self._after(self._last_change + self.gap)
        if self._last_edge is not None:
            self._after(self._last_edge + self.gap)
        self._sim = group = []
        try:
            yield
        finally:
            self._sim = None
        if len(group) < 2:
            raise BuilderError(
                f"t={self.t}: simultaneous() needs at least two events, got {len(group)}"
            )
        self.t += self.gap

    def build(self) -> Vec:
        """The finished stimulus, ending ``gap_ps`` after the last change at the earliest."""
        self._not_in_sim("build()")
        m = self.m
        header = {
            "prim": m.prim,
            "cfg": m.cfg,
            "nin": str(m.nin),
            "nout": str(m.nout),
            "nclk": str(m.nclk),
            "settle_ps": str(self.settle),
            "seed": str(self.seed),
            "async_sep_ps": str(self.sep),
        }
        if self.expect:
            header["expect"] = self.expect
        header.update({f"attr.{k}": v for k, v in m.attrs.items()})
        clocks = [Clock(f"clk{b.bit}", b.bit, self.period, 0, 50, "stepped") for b in m.of("clk")]
        end = Event(max(self.t, self._last_change + self.gap), "end")
        return Vec(header, clocks, [*self._events, end])


class GenContext:
    """What a vector generator function receives (``def gen(ctx) -> Iterable[Vec]``)."""

    def __init__(self, family: str, prim: str, seed: int, root: Path | None = None) -> None:
        from xut.paths import repo_root

        self.family, self.prim, self.seed = family, prim, seed
        self.rng = random.Random(seed)
        self.root = root or repo_root()
        self.specs: dict[str, DutSpec] = {}

    def dut(
        self,
        cfg: str,
        *,
        allow_illegal: bool = False,
        expect: str | None = None,
        **attrs: object,
    ) -> VecBuilder:
        """A builder for configuration ``cfg`` of this primitive with ``attrs`` set."""
        from xut.catalog.model import load_entry

        if cfg in self.specs:
            raise BuilderError(f"configuration {cfg!r} defined twice")
        spec = spec_from_catalog(
            load_entry(self.family, self.prim, self.root), cfg, attrs, allow_illegal=allow_illegal
        )
        self.specs[cfg] = spec
        return VecBuilder(build_map(spec), seed=self.seed, expect=expect)
