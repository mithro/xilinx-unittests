# SPDX-License-Identifier: Apache-2.0
"""``XutDut``: a map-aware handle on the ``xut_cocotb_top`` DUT for cocotb tests (spec §4.3).

Used only inside the simulator container, where the xut dependencies are not installed:
it imports ``cocotb`` and ``xut.formats.xtr`` (standard library only) and nothing else,
and reads ``xut_dut.map.json`` with ``json`` rather than ``xut.wrap``.

The top has three vectors (``xut wrap --cocotb-top``): ``clk``, ``in_vec`` and
``out_vec``. ``XutDut`` keeps a Python-int shadow of ``clk`` and ``in_vec`` and writes
the whole vector on every change, so a port is always driven exactly as the shadow
says; ``value(port)`` reads the shadow back. Ports are addressed by name through the
map; an inout's drive bits are ``<port>__drive_en`` / ``<port>__drive_val`` (spec §5.1).

Spacing mirrors ``VecBuilder``: every operation (``set``, ``edge``, ``gsr``) applies at
the current time and then waits the gap (``GAP_PS``, or the map's larger
``min_event_gap_ps``), so no two changes share a time step, a sample taken right after
an operation is one gap later (past the UNISIM clock-to-Q delay), and an async change
is never within a gap of a clock edge. ``settle()`` waits until ``SETTLE_PS``, past
glbl's start-up GSR pulse. Both constants equal ``xut.stimgen.DEFAULT_SETTLE_PS`` and
``xut.validate.DEFAULT_GAP_PS`` (pinned by a test; those modules are not importable
here).

Every ``sample(label)`` records every output port in the trace; ``close()`` writes it
through ``xut.formats.xtr`` (never hand-formatted), so labels, ports and provenance
follow the shared name grammar or raise.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cocotb.simtime import get_sim_time
from cocotb.triggers import Timer

from xut.formats import xtr

#: glbl releases GSR at ROC_WIDTH (100 ns); the vector testbench settles until 120 ns.
SETTLE_PS = 120_000
#: The minimum spacing between two operations (validate.MIN_SEP_PS).
GAP_PS = 1_000
#: The map format ``XutDut`` reads (xut.wrap.MAP_FORMAT).
MAP_FORMAT = "xut-map 1"


def _prov_token(prov: str | tuple[str, ...]) -> str:
    """A model ``Out.prov`` as one .xtr token: the tag, or per-bit tags comma-joined LSB
    first when they differ (as ``xut.golden`` writes them)."""
    if isinstance(prov, str):
        return prov
    return prov[0] if len(set(prov)) == 1 else ",".join(prov)


class XutDut:
    """The DUT of one configuration, addressed by port name (module docstring)."""

    def __init__(
        self,
        dut: object,
        map_path: str | os.PathLike[str],
        trace_path: str | os.PathLike[str],
        header: dict[str, str] | None = None,
    ) -> None:
        m = json.loads(Path(map_path).read_text())
        if m.get("format") != MAP_FORMAT:
            raise ValueError(f"{map_path}: not an {MAP_FORMAT} file")
        self.dut = dut
        self.trace_path = Path(trace_path)
        self.attrs: dict[str, str] = dict(m["attrs"])
        self.prim: str = m["prim"]
        self.cfg: str = m["cfg"]
        self.gap_ps = max(GAP_PS, m.get("min_event_gap_ps") or 0)
        # port name -> (vector, [vector bit of port bit 0, 1, ...])
        self._ports: dict[str, tuple[str, list[int]]] = {}
        for vec in ("clk", "in", "out"):
            for b in sorted((b for b in m["bits"] if b["vec"] == vec), key=lambda b: b["index"]):
                name = b["port"] if vec == "out" or not b["role"] else f"{b['port']}__{b['role']}"
                self._ports.setdefault(name, (vec, []))[1].append(b["bit"])
        self.in_ports: list[str] = [p for p, (v, _) in self._ports.items() if v == "in"]
        self.clocks: list[str] = [p for p, (v, _) in self._ports.items() if v == "clk"]
        self.out_ports: list[str] = [p for p, (v, _) in self._ports.items() if v == "out"]
        self._shadow = {"clk": 0, "in": 0}
        self.trace = xtr.Trace(
            header
            if header is not None
            else {
                "runner": os.environ.get("XUT_RUNNER", "cocotb"),
                "flow": os.environ.get("XUT_FLOW", "rtl"),
                "model": os.environ.get("XUT_MODEL", "unknown"),
                "seed": os.environ.get("XUT_SEED", "0"),
                "prim": self.prim,
                "cfg": self.cfg,
            }
        )
        # Every input starts at 0, as in the vector testbench and the golden replay.
        self._write("clk")
        self._write("in")

    # --- driving -----------------------------------------------------------------------

    def _port(self, port: str, vecs: tuple[str, ...]) -> tuple[str, list[int]]:
        if port not in self._ports or self._ports[port][0] not in vecs:
            known = [p for p, (v, _) in self._ports.items() if v in vecs]
            raise KeyError(f"{self.prim}: no port {port!r} here (known: {known})")
        return self._ports[port]

    def _write(self, vec: str) -> None:
        handle = self.dut.clk if vec == "clk" else self.dut.in_vec
        handle.value = self._shadow[vec]

    def _merged(self, shadow: int, port: str, value: int) -> int:
        """``shadow`` with ``port``'s bits set to ``value`` (checked, nothing mutated)."""
        _, bits = self._ports[port]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{port}={value!r}: drive an int (x/z inputs are sv-test territory)")
        if not 0 <= value < (1 << len(bits)):
            raise ValueError(f"{port}={value}: does not fit {len(bits)} bit(s)")
        for i, b in enumerate(bits):
            shadow = (shadow | (1 << b)) if (value >> i) & 1 else (shadow & ~(1 << b))
        return shadow

    async def _gap(self) -> None:
        await Timer(self.gap_ps, "ps")

    async def settle(self) -> None:
        """Wait until ``SETTLE_PS`` (at least one gap): glbl's GSR pulse is over."""
        now = int(get_sim_time("ps"))
        await Timer(max(SETTLE_PS - now, self.gap_ps), "ps")

    async def set(self, **ports: int) -> None:
        """Drive ``in_vec`` ports together (one write), then wait one gap."""
        s = self._shadow["in"]
        for p, v in ports.items():
            self._port(p, ("in",))  # a clock is driven with edge()
            s = self._merged(s, p, v)
        self._shadow["in"] = s  # only once every port checked out
        self._write("in")
        await self._gap()

    async def edge(self, port: str, rising: bool) -> None:
        """Drive a one-bit port (normally a clock) to 1 (``rising``) or 0, then wait one gap."""
        vec, bits = self._port(port, ("clk", "in"))
        if len(bits) != 1:
            raise ValueError(f"{port} is {len(bits)} bits wide: edge() needs a one-bit port")
        self._shadow[vec] = self._merged(self._shadow[vec], port, int(rising))
        self._write(vec)
        await self._gap()

    async def cycle(self, port: str, n: int = 1) -> None:
        """``n`` rising-then-falling edges of ``port``."""
        for _ in range(n):
            await self.edge(port, True)
            await self.edge(port, False)

    async def gsr(self, value: int) -> None:
        """Drive glbl's GSR (``glbl.GSR_int``, instantiated in ``xut_cocotb_top``)."""
        self.dut.glbl.GSR_int.value = int(value)
        await self._gap()

    def value(self, port: str) -> int:
        """The value this handle drives on input or clock ``port`` (the shadow)."""
        vec, bits = self._port(port, ("clk", "in"))
        s = self._shadow[vec]
        return sum(((s >> b) & 1) << i for i, b in enumerate(bits))

    # --- observing ---------------------------------------------------------------------

    def get(self, port: str) -> str:
        """Output ``port``, MSB first, in ``01xz``."""
        _, bits = self._port(port, ("out",))
        s = str(self.dut.out_vec.value).lower()
        return "".join(s[len(s) - 1 - b] for b in reversed(bits))

    def sample(self, label: str, prov: dict[str, str | tuple[str, ...]] | None = None) -> dict:
        """Record every output port as sample ``label`` (with optional per-port
        provenance, a model ``Out.prov``); returns the recorded values."""
        values = {p: self.get(p) for p in self.out_ports}
        tokens = {p: _prov_token(v) for p, v in (prov or {}).items()}
        self.trace.add(label, values, tokens or None)
        return values

    def close(self) -> None:
        """Write the trace (``xut.formats.xtr.dump``). Safe to call more than once."""
        xtr.dump(self.trace, self.trace_path)
