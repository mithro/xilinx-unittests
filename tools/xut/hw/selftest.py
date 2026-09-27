# SPDX-License-Identifier: Apache-2.0
"""The self-test channels every bitstream carries (spec §7.1 "Self-test"). Standard
library only.

Slot 0 is a 16-bit passthrough: out_vec = in_vec, no primitive in between. Slot 1 is an
8-bit counter clocked through its own harness flip-flop and BUFG (in[0] = count
enable, in[1] = synchronous clear). Their programs run first after every programming;
any mismatch is a harness error, never a DUT result.
"""

from __future__ import annotations

from xut.hw import proto
from xut.hw.image import HwProgram, ImageBuilder
from xut.hw.interp import DutSim, run_program

PASS_SLOT, COUNT_SLOT = 0, 1
PASS_WIDTH = 16
COUNT_NIN, COUNT_NCLK, COUNT_NOUT = 2, 1, 8
COUNT_EDGES = 260  # wraps past 255


class PassthroughSim:
    def reset(self, t0: str) -> None:
        self._v = t0

    def drive(self, in_bits: str, clk_bits: str) -> None:
        self._v = in_bits

    def out_bits(self) -> str:
        return self._v


class CounterSim:
    def reset(self, t0: str) -> None:
        self._in, self._clk, self._n = t0, "0", 0

    def drive(self, in_bits: str, clk_bits: str) -> None:
        if self._clk == "0" and clk_bits == "1":  # rising edge: the inputs before it count
            if self._in[-2] == "1":
                self._n = 0
            elif self._in[-1] == "1":
                self._n = (self._n + 1) % 256
        self._in, self._clk = in_bits, clk_bits

    def out_bits(self) -> str:
        return format(self._n, "08b")


def passthrough_program() -> HwProgram:
    b = ImageBuilder(PASS_WIDTH, 0, PASS_WIDTH, "0" * PASS_WIDTH)
    pats = [1 << i for i in range(16)] + [0xFFFF ^ (1 << i) for i in range(16)]
    pats += [0xA5A5, 0x5A5A, 0x0000, 0xFFFF]
    for i, p in enumerate(pats):
        b.set_bits(format(p, "016b"))
        b.sample(f"p{i}")
    return b.end()


def counter_program() -> HwProgram:
    b = ImageBuilder(COUNT_NIN, COUNT_NCLK, COUNT_NOUT, "00")
    b.sample("c0")
    b.set_bits("01")  # CE
    for k in range(1, COUNT_EDGES + 1):
        b.edge(0, 1)
        b.edge(0, 0)
        if k in (1, 2, 255, 256, 257) or k % 20 == 0:
            b.sample(f"c{k}")
    b.set_bits("00")  # hold
    b.edge(0, 1)
    b.edge(0, 0)
    b.sample("hold")
    b.set_bits("10")  # clear
    b.edge(0, 1)
    b.edge(0, 0)
    b.sample("clear")
    return b.end()


def selftest_programs() -> dict[int, HwProgram]:
    return {PASS_SLOT: passthrough_program(), COUNT_SLOT: counter_program()}


def selftest_sims() -> dict[int, DutSim]:
    return {PASS_SLOT: PassthroughSim(), COUNT_SLOT: CounterSim()}


def expected_samples(slot: int) -> list[str]:
    prog, sim = selftest_programs()[slot], selftest_sims()[slot]
    sim.reset(prog.t0)
    return run_program(prog.words, prog.nin, prog.nclk, sim, prog.t0).samples


def check(slot: int, reply: proto.RunReply) -> str | None:
    """None when self-test ``slot`` answered as expected; otherwise what differed."""
    if reply.status != proto.STATUS_CODE["ok"]:
        return f"slot {slot}: status {proto.STATUS.get(reply.status, reply.status)}"
    labels = selftest_programs()[slot].labels
    exp = expected_samples(slot)
    if len(reply.samples) != len(exp):
        return f"slot {slot}: {len(reply.samples)} samples, expected {len(exp)}"
    for label, got, want in zip(labels, reply.samples, exp, strict=True):
        if got != want:
            return f"slot {slot} sample {label}: got {got}, expected {want}"
    return None
