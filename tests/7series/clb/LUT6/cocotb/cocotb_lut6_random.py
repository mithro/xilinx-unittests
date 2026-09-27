# SPDX-License-Identifier: Apache-2.0
"""7series.LUT6.L2.cocotb_random: random LUT6 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def lut6_random(dut: object) -> None:
    await random_session(dut, "LUT6", steps=2000)
