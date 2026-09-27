# SPDX-License-Identifier: Apache-2.0
"""7series.CFGLUT5.L2.cocotb_random: random CFGLUT5 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def cfglut5_random(dut: object) -> None:
    await random_session(dut, "CFGLUT5", steps=2000)
