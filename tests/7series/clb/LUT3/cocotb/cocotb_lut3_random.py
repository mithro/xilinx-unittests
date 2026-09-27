# SPDX-License-Identifier: Apache-2.0
"""7series.LUT3.L2.cocotb_random: random LUT3 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def lut3_random(dut: object) -> None:
    await random_session(dut, "LUT3", steps=2000)
