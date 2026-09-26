# SPDX-License-Identifier: Apache-2.0
"""Replay an .xvec through a golden model -> expected trace (spec §4.3 vector tests).

The replay mirrors the vector testbench: the model is built from the explicitly-set
attributes only (it supplies its documented defaults for the rest), glbl holds GSR
from time 0 until ROC_WIDTH, every in_vec port starts at 0, and free-running clocks
are expanded with the one shared definition (``xvec.free_clock_edges``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import groupby

from xut.errors import XutError
from xut.formats.common import int_literal
from xut.formats.xtr import Trace, prov_token
from xut.formats.xvec import Event, Vec, free_clock_edges
from xut.validate import ROC_WIDTH_PS, validate
from xut.wrap import DutMap
from xut_models.base import Model, ModelContractError, ModelUnsupported, Out


class InvalidStimulus(XutError, ValueError):
    """The .xvec breaks the class rules (xut.validate): no golden trace may exist for it."""


@dataclass
class Reach:
    """Bins the stimulus actually reached in the model (spec §9)."""

    ports: set[str] = field(default_factory=set)
    attrs: dict[str, str] = field(default_factory=dict)
    claims: set[str] = field(default_factory=set)
    #: Port × class events the applied stimulus produced (ruling S19), as
    #: ``<P>:<event>`` or ``<P>[i]:<event>``: data ``0``/``1`` (a value a ``set`` wrote),
    #: clock ``edge``, async/gate ``rise``/``fall`` (pin level; ``polarity_bins`` turns
    #: them into ``assert``/``release``), inout ``drive0``/``drive1``/``release``.
    events: set[str] = field(default_factory=set)

    def bins(self) -> set[str]:
        return (
            {f"port:{p}" for p in self.ports}
            | {f"port:{e}" for e in self.events}
            | {f"attr:{k}={v}" for k, v in self.attrs.items()}
            | {f"claim:{c}" for c in self.claims}
        )


def _is_one(literal: object) -> bool:
    """True if a Verilog literal (``1'b1``, ``1``, ``'h1``) or int is the value 1."""
    return int_literal(literal) == 1


def polarity_bins(bins: set[str], active: dict[str, str], attrs: dict[str, object]) -> set[str]:
    """Rename ``port:<P>:rise``/``fall`` to ``assert``/``release`` for every port whose
    active level is declared (``active``: port -> ``high``/``low``), as the primitive
    sees it: an ``IS_<P>_INVERTED`` attribute of 1 in ``attrs`` flips the level."""
    out = set()
    for b in bins:
        m = re.fullmatch(r"port:((\w+)(?:\[\d+\])?):(rise|fall)", b)
        level = active.get(m.group(2)) if m else None
        if m is None or level not in ("high", "low"):
            out.add(b)
            continue
        high = (level == "high") != _is_one(attrs.get(f"IS_{m.group(2)}_INVERTED", 0))
        event = "assert" if (m.group(3) == "rise") == high else "release"
        out.add(f"port:{m.group(1)}:{event}")
    return out


def _bit_name(m: DutMap, port: str, index: int) -> str:
    return port if len(m.port_bits("in", port)) == 1 else f"{port}[{index}]"


def _data_events(m: DutMap, e: Event) -> set[str]:
    """``<P>:<v>`` / ``<P>[i]:<v>`` for every data-class bit a ``set`` writes 0 or 1 to."""
    by_pos = {b.bit: b for b in m.of("in")}
    out = set()
    for i, ch in enumerate(reversed(e.value)):
        b = by_pos.get(e.lsb + i)
        if b is not None and b.role == "" and b.cls == "data" and ch in "01":
            out.add(f"{_bit_name(m, b.port, b.index)}:{ch}")
    return out


def _stimulus_events(m: DutMap, old: list[str], new: list[str]) -> set[str]:
    """The async/gate and inout events of one time step's ``set``s, from the in_vec bits
    before (``old``) and after (``new``) the step (data values are taken per ``set``)."""
    out: set[str] = set()
    ins = m.of("in")
    for b in ins:
        o, n = old[b.bit], new[b.bit]
        if b.role == "" and b.cls in ("async", "gate") and o + n in ("01", "10"):
            out.add(f"{_bit_name(m, b.port, b.index)}:{'rise' if n == '1' else 'fall'}")
    for p in dict.fromkeys(b.port for b in ins if b.role == "drive_en"):
        en = m.port_bits("in", p, "drive_en")
        val = m.port_bits("in", p, "drive_val")
        for e, v in zip(en, val, strict=True):
            if (
                new[e.bit] == "1"
                and new[v.bit] in "01"
                and (old[e.bit] != "1" or old[v.bit] != new[v.bit])
            ):
                out.add(f"{p}:drive{new[v.bit]}")
            if old[e.bit] == "1" and new[e.bit] == "0":
                out.add(f"{p}:release")
    return out


def expand_free_clocks(vec: Vec) -> list[Event]:
    """Explicit events plus the shared free-clock edges (xvec.free_clock_edges)."""
    out = [e for e in vec.events if e.op not in ("clock_start", "clock_stop")]
    return sorted(out + free_clock_edges(vec), key=lambda e: e.t)


def _port_bits(m: DutMap, bits: list[str], port: str) -> str:
    """MSB-first value of in_vec ``port``."""
    return "".join(bits[b.bit] for b in reversed(m.port_bits("in", port)))


def _port_value(m: DutMap, bits: list[str], port: str) -> int:
    s = _port_bits(m, bits, port)
    if set(s) - {"0", "1"}:
        raise ModelUnsupported(f"{port}={s}: x/z stimulus is covered by sv tests, not the model")
    return int(s, 2)


def bit_prov(token: str, bit: int) -> str:
    """Provenance of ``bit`` (LSB = 0) from an .xtr token written by ``replay``."""
    tags = token.split(",")
    if len(tags) == 1:
        return tags[0]
    if not 0 <= bit < len(tags):
        raise IndexError(f"bit {bit} out of range for per-bit provenance {token!r}")
    return tags[bit]


def _check_outputs(model_cls: type[Model], outs: dict[str, Out], label: str) -> None:
    """A model must report exactly its OUTPUTS, each at its declared width."""
    if set(outs) != set(model_cls.OUTPUTS):
        raise ModelContractError(
            f"{model_cls.PRIM} model at sample {label}: outputs {sorted(outs)} "
            f"!= declared OUTPUTS {sorted(model_cls.OUTPUTS)}"
        )
    for p, o in outs.items():
        if len(o.bits) != model_cls.OUTPUTS[p]:
            raise ModelContractError(
                f"{model_cls.PRIM} model at sample {label}: {p} has {len(o.bits)} bits, "
                f"declared width {model_cls.OUTPUTS[p]}"
            )


def _check_inputs(model_cls: type[Model], vec: Vec, m: DutMap) -> None:
    if not (model_cls.PRIM == vec.prim == m.prim):
        raise ModelContractError(
            f"primitive mismatch: model {model_cls.PRIM}, vec {vec.prim}, map {m.prim}"
        )
    if (vec.nin, vec.nclk) != (m.nin, m.nclk):
        raise ModelContractError(
            f"{vec.prim}: vec nin={vec.nin} nclk={vec.nclk} does not match the map "
            f"(nin={m.nin} nclk={m.nclk})"
        )
    widths = {p: len(m.port_bits("in", p)) for p in m.in_ports()}
    widths |= {b.port: 1 for b in m.of("clk")}
    if widths != model_cls.inputs():
        raise ModelContractError(
            f"{vec.prim}: model inputs {model_cls.inputs()} do not match the map's "
            f"input ports {widths}"
        )


def replay(model_cls: type[Model], vec: Vec, m: DutMap) -> tuple[Trace, Reach]:
    """Run ``vec`` through a fresh ``model_cls``: the expected trace plus the reached bins."""
    # The testbench applies every operation of one time step before the DUT wakes, so a
    # simultaneous `edge r` + `set D` captures the NEW D. File-order replay would predict
    # the old one: refuse rather than emit a silently wrong expectation (review #7).
    sim = sorted({e.t for e in vec.events if e.simultaneous})
    if sim:
        raise ModelUnsupported(
            f"simultaneous events at t={sim[:3]}: ordering within one time "
            "step is not modelled (use them only for sim-vs-sim checks)"
        )
    # Golden output from an invalid stimulus must be impossible (controller ruling).
    # hw_renderable=no is fine: replay is simulation-side.
    report = validate(vec, m)
    if report.errors:
        raise InvalidStimulus(
            f"{vec.prim}/{vec.cfg}: stimulus is invalid, refusing to replay:\n  "
            + "\n  ".join(report.errors)
        )
    _check_inputs(model_cls, vec, m)
    model = model_cls(vec.attrs)
    reach = Reach(attrs=dict(vec.attrs))
    trace = Trace(
        {
            "runner": "python",
            "flow": "rtl",
            "model": "golden",
            "seed": str(vec.seed),
            "kind": "expected",
            "prim": vec.prim,
            "cfg": vec.cfg,
        }
    )
    bits = ["0"] * m.nin
    seen: dict[str, set[int]] = {}
    model.power_on()
    for p in m.in_ports():
        model.set_input(p, 0)
    released = False
    # Co-timed events (Ruling S6, pinned by tests): the only unmarked events that may share
    # a time are `set`s on disjoint bits -- one atomic input change -- because validate's
    # lonely rule makes every edge, glbl and async/gate set alone at its time, and a sample
    # never shares its time with a change. So each time step applies ALL its set bits
    # first and only then calls set_input, once per changed port (map order): the model
    # never sees an intermediate state, and the file order of the sets cannot matter.
    for t, group in groupby(expand_free_clocks(vec), key=lambda e: e.t):
        events = list(group)
        if not released and t >= ROC_WIDTH_PS:
            model.glbl("GSR", 0)
            released = True
        sets = [e for e in events if e.op == "set"]
        if sets:
            before = {p: _port_bits(m, bits, p) for p in m.in_ports()}
            old = list(bits)
            for e in sets:
                for i, ch in enumerate(reversed(e.value)):
                    bits[e.lsb + i] = ch
                reach.events |= _data_events(m, e)
            reach.events |= _stimulus_events(m, old, bits)
            for p in m.in_ports():
                if _port_bits(m, bits, p) != before[p]:
                    v = _port_value(m, bits, p)
                    model.set_input(p, v)
                    seen.setdefault(p, set()).add(v)
        for e in events:
            if e.op == "edge":
                port = m.clock_port(e.target)
                model.clock_edge(port, e.value == "r")
                reach.ports.add(port)
                reach.events.add(f"{port}:edge")
            elif e.op == "glbl":
                model.glbl(e.target, int(e.value))
            elif e.op == "sample":
                outs = model.outputs()
                _check_outputs(model_cls, outs, e.target)
                trace.add(
                    e.target,
                    {p: o.bits for p, o in outs.items()},
                    {p: prov_token(o.prov) for p, o in outs.items()},
                )
                reach.ports |= set(outs)
    reach.ports |= {p for p, vals in seen.items() if len(vals) > 1 or vals != {0}}
    reach.claims = set(model.claims_hit)
    return trace, reach
