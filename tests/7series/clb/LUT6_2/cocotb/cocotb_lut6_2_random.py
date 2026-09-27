# SPDX-License-Identifier: Apache-2.0
"""7series.LUT6_2.L2.cocotb_random: random LUT6_2 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def lut6_2_random(dut: object) -> None:
    await random_session(dut, "LUT6_2", steps=2000)
