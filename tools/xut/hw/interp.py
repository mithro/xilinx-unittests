# SPDX-License-Identifier: Apache-2.0
"""Reference interpreter of harness programs and emulator of the harness (spec §7.1).
Standard library only.

``run_program`` executes a program exactly as xut_hw_ctrl's sequencer does, against a
``DutSim``, and returns the samples plus a cycle-stamped log of every in_vec change,
clock change and capture. ``Harness`` wraps it in the protocol of ``xut.hw.proto``: fed
the host's bytes, it returns byte for byte what the RTL harness transmits
(tools/tests/test_hw_rtl.py pins that on Icarus and xsim). So the compiler, the
protocol and the host code are all testable without hardware.

Cycle model (xut_hw_ctrl): FETCH and DECODE take one cycle each per word; COMMIT and
EDGE then hold MARGIN + 1 cycles (S_WAITM counts MARGIN down to 0); WAIT n holds n + 1;
SAMPLE captures in DECODE. Printing time is not modelled: the DUT is static meanwhile.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Protocol

from xut.hw import proto
from xut.hw.image import (
    MARGIN,
    MAXWORDS,
    OP_COMMIT,
    OP_EDGE,
    OP_END,
    OP_SAMPLE,
    OP_SET,
    OP_WAIT,
    chunks,
    decode,
    width,
)


class DutSim(Protocol):
    def reset(self, t0: str) -> None:
        """Power-on: in_vec = ``t0`` (MSB first), every clock low."""

    def drive(self, in_bits: str, clk_bits: str) -> None:
        """New pin levels (MSB first). The harness changes in_vec or one clock, never both."""

    def out_bits(self) -> str:
        """out_vec now: max(1, nout) chars of 0/1, MSB first."""


@dataclass(frozen=True)
class CycleEvent:
    cycle: int
    kind: str  # commit | edge | sample
    detail: str


@dataclass
class RunOutcome:
    samples: list[str]
    status: int
    events: list[CycleEvent]
    cycles: int


def _clk(clk: list[str]) -> str:
    return "".join(reversed(clk)) if clk else "0"


def _from_chunks(ch: list[int], w: int) -> str:
    lsb = "".join(format(c, "016b")[::-1] for c in ch)
    return lsb[:w][::-1]


def run_program(
    words: list[int] | tuple[int, ...],
    nin: int,
    nclk: int,
    dut: DutSim,
    t0: str,
    *,
    margin: int = MARGIN,
    max_cycles: int = 1 << 40,
) -> RunOutcome:
    """Execute ``words`` on a slot whose DUT is ``dut`` (already reset to ``t0``)."""
    w = width(nin)
    nxt = chunks(t0)  # in_nxt starts as the slot's current in_vec (xut_hw_ctrl S_RUN_GO)
    cur = t0
    clk = ["0"] * nclk
    samples: list[str] = []
    events: list[CycleEvent] = []
    cyc = pc = 0
    ok, badop = proto.STATUS_CODE["ok"], proto.STATUS_CODE["badop"]
    while True:
        if pc >= len(words):
            return RunOutcome(samples, badop, events, cyc)
        cyc += 2  # FETCH, DECODE
        op, a, b = decode(words[pc])
        if op == OP_SET:
            if a < len(nxt):  # the RTL has no such chunk, or truncates it on COMMIT
                nxt[a] = b
        elif op == OP_COMMIT:
            cur = _from_chunks(nxt, w)
            events.append(CycleEvent(cyc, "commit", cur))
            dut.drive(cur, _clk(clk))
            cyc += margin + 1
        elif op == OP_EDGE:
            if a < nclk:  # no flip-flop for a missing clock: nothing changes
                clk[a] = str(b)
                dut.drive(cur, _clk(clk))
            events.append(CycleEvent(cyc, "edge", f"{a}={b}"))
            cyc += margin + 1
        elif op == OP_WAIT:
            cyc += a + 1
        elif op == OP_SAMPLE:
            bits = dut.out_bits()
            events.append(CycleEvent(cyc, "sample", bits))
            samples.append(bits)
        elif op == OP_END:
            return RunOutcome(samples, ok, events, cyc)
        else:
            return RunOutcome(samples, badop, events, cyc)
        pc += 1
        if cyc > max_cycles:
            raise RuntimeError(f"program still running after {max_cycles} cycles")


def margin_violations(events: list[CycleEvent], margin: int = MARGIN) -> list[str]:
    """Every operation closer than ``margin`` cycles to the last in_vec or clock change."""
    out: list[str] = []
    last: CycleEvent | None = None
    for e in events:
        if last is not None and e.cycle - last.cycle < margin:
            out.append(
                f"{e.kind} at cycle {e.cycle} is {e.cycle - last.cycle} cycle(s) after the "
                f"{last.kind} at cycle {last.cycle}"
            )
        if e.kind in ("commit", "edge"):
            last = e
    return out


@dataclass
class EmuSlot:
    nin: int
    nout: int
    nclk: int
    t0: str
    dut: DutSim


class Harness:
    """The harness as seen from its UART: ``feed`` the host's bytes, get its replies.
    Construction is "configuring the FPGA": every slot's DUT is reset to its ``t0``."""

    def __init__(
        self,
        build_id: int,
        slots: list[EmuSlot],
        *,
        margin: int = MARGIN,
        maxwords: int = MAXWORDS,
    ) -> None:
        self.build_id, self.slots, self.margin, self.maxwords = build_id, slots, margin, maxwords
        for s in slots:
            s.dut.reset(s.t0)
        self._buf = bytearray()
        self._mem = [0] * maxwords
        self._loaded, self._lslot, self._lwords = False, 0, 0
        self._used = [False] * len(slots)

    def feed(self, data: bytes) -> bytes:
        self._buf += data
        out = bytearray()
        while self._buf:
            n = self._step(out)
            if n == 0:
                break
            del self._buf[:n]
        return bytes(out)

    def _step(self, out: bytearray) -> int:
        """Handle the command at the head of the buffer; the bytes it used (0: need more)."""
        buf, c = self._buf, self._buf[0]
        if c == ord(proto.CMD_ID):
            out += proto.render(
                "id",
                build=self.build_id,
                slots=len(self.slots),
                maxwords=self.maxwords,
                margin=self.margin,
            )
            return 1
        if c == ord(proto.CMD_LOAD):
            if len(buf) < 4:
                return 0
            slot, n = buf[1], buf[2] | buf[3] << 8
            total = 4 + 4 * n + 4
            if len(buf) < total:
                return 0
            body = bytes(buf[1 : 4 + 4 * n])
            calc = zlib.crc32(body)
            for i in range(min(n, self.maxwords)):  # the RTL writes whatever it can
                self._mem[i] = int.from_bytes(buf[4 + 4 * i : 8 + 4 * i], "little")
            if slot >= len(self.slots):
                status = proto.STATUS_CODE["badslot"]
            elif n == 0 or n > self.maxwords:
                status = proto.STATUS_CODE["toolong"]
            elif int.from_bytes(buf[4 + 4 * n : total], "little") != calc:
                status = proto.STATUS_CODE["badcrc"]
            else:
                status = proto.STATUS_CODE["ok"]
            self._loaded = status == proto.STATUS_CODE["ok"]
            if self._loaded:
                self._lslot, self._lwords = slot, n
            out += proto.render("load", slot=slot, words=n, crc=calc, status=status)
            return total
        if c == ord(proto.CMD_RUN):
            body = proto.render("run", build=self.build_id, slot=self._lslot, words=self._lwords)
            samples: list[str] = []
            if not self._loaded:
                status = proto.STATUS_CODE["noload"]
            elif self._used[self._lslot]:
                status = proto.STATUS_CODE["used"]
            else:
                s = self.slots[self._lslot]
                self._used[self._lslot] = True
                r = run_program(
                    self._mem[: self._lwords], s.nin, s.nclk, s.dut, s.t0, margin=self.margin
                )
                samples, status = r.samples, r.status
            body += b"".join(proto.render("sample", sidx=i, bits=b) for i, b in enumerate(samples))
            out += body + proto.render(
                "end", slot=self._lslot, samples=len(samples), status=status, crc=zlib.crc32(body)
            )
            return 1
        out += proto.render("err", cmd=c, status=proto.STATUS_CODE["badcmd"])
        return 1
