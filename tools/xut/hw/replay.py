# SPDX-License-Identifier: Apache-2.0
"""Golden models as harness DUTs, and harness samples as traces.

``ModelDut`` drives a golden model (xut_models) with the harness's pin levels, with the
semantics of ``xut.golden.replay``: power-on, every input 0 and then the ``t0`` values
as one change, then GSR released before the first stepped operation. ``hw_replay``
compiles a stimulus, interprets it against that model and returns the trace; Task 3's
tests pin that it equals ``replay``'s for every renderable configuration.
"""

from __future__ import annotations

from collections.abc import Mapping

from xut.errors import XutError
from xut.formats.xtr import Trace
from xut.formats.xvec import Vec
from xut.hw import proto
from xut.hw.compile import compile_program
from xut.hw.image import width
from xut.hw.interp import run_program
from xut.stimcompile import out_port_bits, port_values
from xut.wrap import DutMap
from xut_models.base import Model


class SampleError(XutError, ValueError):
    """Harness samples that do not fit the wrapper's out_vec or the labels."""


class ModelDut:
    """``two_state``: report a golden don't-care (``-``) bit as ``0``, as 2-state silicon
    would. The harness emulator (``xut.hw.fake``) needs it, because the protocol carries
    only 0/1; ``hw_replay`` keeps ``-``, which ``compare`` masks."""

    def __init__(
        self, model_cls: type[Model], attrs: Mapping[str, str], m: DutMap, two_state: bool = False
    ) -> None:
        self.cls, self.attrs, self.m, self.two_state = model_cls, dict(attrs), m, two_state

    def _set(self, in_bits: str) -> None:
        new, old = in_bits[::-1], self._in[::-1]  # index = in_vec bit
        for p in self.m.in_ports():
            pb = self.m.port_bits("in", p)
            if any(new[b.bit] != old[b.bit] for b in pb):
                self.model.set_input(p, int("".join(new[b.bit] for b in reversed(pb)), 2))
        self._in = in_bits

    def reset(self, t0: str) -> None:
        self.model = self.cls(self.attrs)
        self.model.power_on()
        for p in self.m.in_ports():
            self.model.set_input(p, 0)
        self._in, self._clk = "0" * width(self.m.nin), "0" * width(self.m.nclk)
        self._set(t0)
        self.model.glbl("GSR", 0)

    def drive(self, in_bits: str, clk_bits: str) -> None:
        if in_bits != self._in:
            self._set(in_bits)
        new, old = clk_bits[::-1], self._clk[::-1]
        for b in self.m.of("clk"):
            if new[b.bit] != old[b.bit]:
                self.model.clock_edge(b.port, new[b.bit] == "1")
        self._clk = clk_bits

    def out_bits(self) -> str:
        outs = self.model.outputs()
        by_bit = ["0"] * width(self.m.nout)
        for b in self.m.of("out"):
            bits = outs[b.port].bits  # MSB first
            by_bit[b.bit] = bits[len(bits) - 1 - b.index]
        out = "".join(reversed(by_bit))
        return out.replace("-", "0") if self.two_state else out


def samples_to_trace(
    samples: list[str] | tuple[str, ...],
    labels: list[str] | tuple[str, ...],
    m: DutMap,
    header: dict[str, str],
    kind: str = "actual",
) -> Trace:
    """out_vec samples (MSB first) as a trace grouped by port, with the port grouping
    ``raw_to_trace`` uses (``stimcompile.out_port_bits``/``port_values``)."""
    if len(samples) != len(labels):
        raise SampleError(f"{len(samples)} samples for {len(labels)} labels")
    t = Trace({**header, **({"kind": kind} if kind != "actual" else {})})
    ports = out_port_bits(m)
    for label, bits in zip(labels, samples, strict=True):
        if len(bits) != width(m.nout):
            raise SampleError(f"sample {label}: {len(bits)} bits, out_vec is {width(m.nout)}")
        t.add(label, port_values(ports, bits))
    return t


def hw_replay(model_cls: type[Model], vec: Vec, m: DutMap) -> Trace:
    """``vec`` compiled for the harness and interpreted against ``model_cls``."""
    prog = compile_program(vec, m)
    dut = ModelDut(model_cls, vec.attrs, m)
    dut.reset(prog.t0)
    out = run_program(prog.words, prog.nin, prog.nclk, dut, prog.t0)
    if out.status != proto.STATUS_CODE["ok"]:
        st = proto.STATUS.get(out.status, out.status)
        raise SampleError(f"{vec.prim}/{vec.cfg}: program ended with status {st}")
    header = {"runner": "hw-replay", "flow": "rtl", "model": "golden", "seed": str(vec.seed)}
    return samples_to_trace(out.samples, prog.labels, m, header, kind="expected")
