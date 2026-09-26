# SPDX-License-Identifier: Apache-2.0
"""Constrained-random cocotb session shared by the flops unit (spec §4.3 cocotb style).

Runs inside the xut-sim container. One check right after GSR release compares the
power-on INIT value (claim:*.C4/gsr_init), then each step drives random inputs, applies
the same events to the golden model, and compares Q after every clock edge and every
async control change. Every comparison point is written to trace.xtr: 2 * cycles + 1
samples for a synchronous-control kind (FDRE/FDSE). When a seed fails, freeze it: copy
the session into vectors/frozen/<seed>.xvec as a new vector test.
"""

import os
import random

from flop_recipes import KINDS

from xut.cocotb_dut import XutDut
from xut_models.registry import get


async def random_session(dut, prim: str, cycles: int = 2000) -> None:
    k = KINDS[prim]
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    model = get("7series", prim)(x.attrs)
    rng = random.Random(int(os.environ["XUT_SEED"]))
    inv_ctrl = int(x.attrs.get(f"IS_{k.ctrl}_INVERTED", "1'b0")[-1])
    model.power_on()
    # Ruling S37(2): the model refuses any input other than 0/1 (models/xut_models/
    # 7series/_common/flops.py set_input), so every port fed to set_input must first be
    # driven to a defined value through x.set() -- never seeded from x.value() of a port
    # this session never drove. CE and D are driven to 0 here (their idle value; the
    # session overwrites them every step), and the control to its inactive level.
    await x.set(CE=0, D=0, **{k.ctrl: inv_ctrl})  # control inactive during power-up
    for p in ("CE", "D", k.ctrl):
        model.set_input(p, x.value(p))
    await x.settle()  # 120 ns; glbl releases GSR at 100 ns
    model.glbl("GSR", 0)
    errors: list[str] = []
    n = 0

    def check() -> None:
        nonlocal n
        exp = model.outputs()["Q"]
        got = x.get("Q")
        x.sample(f"S{n}", {"Q": exp.prov})
        # The flops model never emits a don't-care ("-") bit, but this session is shared
        # by later primitives whose models may (spec §5.3); keep the guard so a future
        # don't-care is never reported as a mismatch here.
        if exp.bits != "-" and got != exp.bits:
            errors.append(f"S{n}: Q={got}, model {exp.bits} ({exp.prov})")
        n += 1

    # claim:*.C4 (gsr_init): compare the power-on/GSR-release INIT value before the main
    # loop's first draw can overwrite it (review Task 23 round 1) -- without this, the
    # claim was exercised only when the first draw happened to leave Q untouched.
    check()

    for _ in range(cycles):
        if k.is_async and rng.random() < 0.1:
            v = rng.randrange(2)
            await x.set(**{k.ctrl: v})  # alone, >= 1 ns from any edge (XutDut spacing)
            model.set_input(k.ctrl, v)
            check()
            continue
        ports = {"D": rng.randrange(2), "CE": int(rng.random() < 0.8)}
        if not k.is_async:
            ports[k.ctrl] = int(rng.random() < 0.15) ^ inv_ctrl
        await x.set(**ports)
        for p, v in ports.items():
            model.set_input(p, v)
        for rising in (True, False):
            await x.edge("C", rising)
            model.clock_edge("C", rising)
            check()
    x.close()
    assert not errors, f"{len(errors)} mismatch(es); first: {errors[:5]}"
