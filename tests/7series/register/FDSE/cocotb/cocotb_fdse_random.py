# SPDX-License-Identifier: Apache-2.0
"""7series.FDSE.L2.cocotb_random: constrained-random FDSE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdse_random(dut):
    await random_session(dut, "FDSE", cycles=2000)
