# SPDX-License-Identifier: Apache-2.0
"""7series.FDRE.L2.cocotb_random: constrained-random FDRE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdre_random(dut):
    await random_session(dut, "FDRE", cycles=2000)
