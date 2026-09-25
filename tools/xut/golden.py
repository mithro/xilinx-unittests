# SPDX-License-Identifier: Apache-2.0
"""Replay an .xvec through a golden model -> expected trace (spec §4.3 vector tests).

The replay mirrors the vector testbench: the model is built from the explicitly-set
attributes only (it supplies its documented defaults for the rest), glbl holds GSR
from time 0 until ROC_WIDTH, every in_vec port starts at 0, and free-running clocks
are expanded with the one shared definition (``xvec.free_clock_edges``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xut.errors import XutError
from xut.formats.xtr import Trace
from xut.formats.xvec import Event, Vec, free_clock_edges
from xut.validate import ROC_WIDTH_PS, validate
from xut.wrap import DutMap
from xut_models.base import Model, ModelUnsupported, Out


class InvalidStimulus(XutError, ValueError):
    """The .xvec breaks the class rules (xut.validate): no golden trace may exist for it."""


@dataclass
class Reach:
    """Bins the stimulus actually reached in the model (spec §9)."""

    ports: set[str] = field(default_factory=set)
    attrs: dict[str, str] = field(default_factory=dict)
    claims: set[str] = field(default_factory=set)

    def bins(self) -> set[str]:
        return (
            {f"port:{p}" for p in self.ports}
            | {f"attr:{k}={v}" for k, v in self.attrs.items()}
            | {f"claim:{c}" for c in self.claims}
        )


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


def _check_outputs(model_cls: type[Model], outs: dict[str, Out], label: str) -> None:
    """A model must report exactly its OUTPUTS, each at its declared width."""
    if set(outs) != set(model_cls.OUTPUTS):
        raise ValueError(
            f"{model_cls.PRIM} model at sample {label}: outputs {sorted(outs)} "
            f"!= declared OUTPUTS {sorted(model_cls.OUTPUTS)}"
        )
    for p, o in outs.items():
        if len(o.bits) != model_cls.OUTPUTS[p]:
            raise ValueError(
                f"{model_cls.PRIM} model at sample {label}: {p} has {len(o.bits)} bits, "
                f"declared width {model_cls.OUTPUTS[p]}"
            )


def _check_inputs(model_cls: type[Model], vec: Vec, m: DutMap) -> None:
    if not (model_cls.PRIM == vec.prim == m.prim):
        raise ValueError(
            f"primitive mismatch: model {model_cls.PRIM}, vec {vec.prim}, map {m.prim}"
        )
    if (vec.nin, vec.nclk) != (m.nin, m.nclk):
        raise ValueError(
            f"{vec.prim}: vec nin={vec.nin} nclk={vec.nclk} does not match the map "
            f"(nin={m.nin} nclk={m.nclk})"
        )
    widths = {p: len(m.port_bits("in", p)) for p in m.in_ports()}
    widths |= {b.port: 1 for b in m.of("clk")}
    if widths != model_cls.inputs():
        raise ValueError(
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
    for e in expand_free_clocks(vec):
        if not released and e.t >= ROC_WIDTH_PS:
            model.glbl("GSR", 0)
            released = True
        if e.op == "set":
            before = {p: _port_bits(m, bits, p) for p in m.in_ports()}
            for i, ch in enumerate(reversed(e.value)):
                bits[e.lsb + i] = ch
            for p in m.in_ports():
                if _port_bits(m, bits, p) != before[p]:
                    v = _port_value(m, bits, p)
                    model.set_input(p, v)
                    seen.setdefault(p, set()).add(v)
        elif e.op == "edge":
            port = m.clock_port(e.target)
            model.clock_edge(port, e.value == "r")
            reach.ports.add(port)
        elif e.op == "glbl":
            model.glbl(e.target, int(e.value))
        elif e.op == "sample":
            outs = model.outputs()
            _check_outputs(model_cls, outs, e.target)
            trace.add(
                e.target, {p: o.bits for p, o in outs.items()}, {p: o.prov for p, o in outs.items()}
            )
            reach.ports |= set(outs)
    reach.ports |= {p for p, vals in seen.items() if len(vals) > 1 or vals != {0}}
    reach.claims = set(model.claims_hit)
    return trace, reach
