# SPDX-License-Identifier: Apache-2.0
"""7series.LUT1.L2.cocotb_random: random LUT1 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def lut1_random(dut: object) -> None:
    await random_session(dut, "LUT1", steps=2000)
