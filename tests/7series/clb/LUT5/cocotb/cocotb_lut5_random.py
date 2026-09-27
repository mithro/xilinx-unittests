# SPDX-License-Identifier: Apache-2.0
"""7series.LUT5.L2.cocotb_random: random LUT5 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def lut5_random(dut: object) -> None:
    await random_session(dut, "LUT5", steps=2000)
