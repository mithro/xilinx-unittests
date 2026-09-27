# SPDX-License-Identifier: Apache-2.0
"""7series.LUT4.L2.cocotb_random: random LUT4 session vs the golden model."""

import cocotb
from luts_cocotb import random_session


@cocotb.test()
async def lut4_random(dut: object) -> None:
    await random_session(dut, "LUT4", steps=2000)
