# SPDX-License-Identifier: Apache-2.0
"""TOYFF fixture generators (tools/tests only)."""

from collections.abc import Iterator

from xut.formats.xvec import Vec
from xut.stimgen import GenContext


def l1_capture(ctx: GenContext) -> Iterator[Vec]:
    """One configuration per INIT value: D=1 and D=0 are each captured on a rising C."""
    for init in (0, 1):
        b = ctx.dut(f"init{init}", INIT=init)
        b.sample("S0")
        for d in (1, 0):
            b.set(D=d)
            b.cycle("C")
        yield b.build()


def l0_reject(ctx: GenContext) -> Iterator[Vec]:
    """INIT=1'bx is outside TOYFF's legal values: the simulation must reject it."""
    b = ctx.dut("init_x", allow_illegal=True, expect="reject", INIT="1'bx")
    b.cycle("C")
    yield b.build()
