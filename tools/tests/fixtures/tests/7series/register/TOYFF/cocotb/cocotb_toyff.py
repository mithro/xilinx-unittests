# SPDX-License-Identifier: Apache-2.0
"""7series.TOYFF.L2.cocotb_capture (xut tool tests only): 20 random D values, each
captured on a rising C, checked against ToyDff (from the fixture's ``_shared/toy``) and
sampled into trace.xtr after every cycle."""

import os
import random

import cocotb
from toy_golden import ToyDff

from xut.cocotb_dut import XutDut

CYCLES = 20


@cocotb.test()
async def toyff_capture(dut: object) -> None:
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    model = ToyDff(x.attrs)
    rng = random.Random(int(os.environ["XUT_SEED"]))
    model.power_on()
    for p in (*x.clocks, *x.in_ports):
        model.set_input(p, x.value(p))
    await x.settle()  # glbl releases GSR at 100 ns
    model.glbl("GSR", 0)
    errors: list[str] = []
    for n in range(CYCLES):
        d = rng.randrange(2)
        await x.set(D=d)
        model.set_input("D", d)
        await x.cycle("C")
        model.clock_edge("C", True)
        model.clock_edge("C", False)
        exp = model.outputs()["Q"]
        got = x.sample(f"S{n}", {"Q": exp.prov})["Q"]
        if got != exp.bits:
            errors.append(f"S{n}: Q={got}, model {exp.bits}")
    x.close()
    assert not errors, f"{len(errors)} mismatch(es); first: {errors[:5]}"
