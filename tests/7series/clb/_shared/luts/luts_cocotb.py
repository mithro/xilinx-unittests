# SPDX-License-Identifier: Apache-2.0
"""Constrained-random cocotb session shared by the luts unit (spec §4.3 cocotb style).

Runs inside the xut-sim container. Every input is driven to 0 first (ruling S37(2)), then
the power-on value is compared right after GSR releases (step-2 review: never leave the
first comparison to luck). Each step then changes a random subset of the LUT inputs at
once, or (CFGLUT5) runs one CLK cycle with random CE and CDI, applies the same events to
the golden model and compares every output. Every comparison point is written to
trace.xtr. When a seed fails, freeze it: copy the session into vectors/frozen/<seed>.xvec
as a new vector test (xut freeze-seed is deferred).
"""

import os
import random

from luts_recipes import KINDS

from xut.cocotb_dut import XutDut
from xut_models.registry import get

#: the chance a step is a CFGLUT5 reload (one CLK cycle), and that the reload has CE High
RELOAD_P = 0.3
CE_HIGH_P = 0.7
#: the chance each LUT input changes in an input step
MOVE_P = 0.5


async def random_session(dut: object, prim: str, steps: int = 2000) -> None:
    k = KINDS[prim]
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    model = get("7series", prim)(x.attrs)
    rng = random.Random(int(os.environ["XUT_SEED"]))
    model.power_on()
    idle = {p: 0 for p in model.inputs() if p not in model.CLOCKS}
    await x.set(**idle)
    for p, v in idle.items():
        model.set_input(p, v)
    await x.settle()  # 120 ns: glbl releases GSR at 100 ns
    model.glbl("GSR", 0)
    errors: list[str] = []
    n = 0

    def check() -> None:
        nonlocal n
        exp = model.outputs()
        x.sample(f"S{n}", {p: o.prov for p, o in exp.items()})
        for p, o in exp.items():
            got = x.get(p)
            # The luts models never emit a don't-care; keep the guard for spec §5.3.
            if o.bits != "-" and got != o.bits:
                errors.append(f"S{n}: {p}={got}, model {o.bits} ({o.prov})")
        n += 1

    check()  # the power-on value (C2/C3/C6), before the first draw can change it
    for _ in range(steps):
        if k.reconfig and rng.random() < RELOAD_P:
            ports = {"CE": int(rng.random() < CE_HIGH_P), "CDI": rng.randrange(2)}
            await x.set(**ports)
            for p, v in ports.items():
                model.set_input(p, v)
            for rising in (True, False):
                await x.edge("CLK", rising)
                model.clock_edge("CLK", rising)
                check()
            continue
        moved = [i for i in range(k.n) if rng.random() < MOVE_P] or [rng.randrange(k.n)]
        ports = {f"I{i}": rng.randrange(2) for i in moved}
        await x.set(**ports)
        for p, v in ports.items():
            model.set_input(p, v)
        check()
    x.close()
    assert not errors, f"{len(errors)} mismatch(es); first: {errors[:5]}"
