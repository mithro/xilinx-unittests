# SPDX-License-Identifier: Apache-2.0
"""7series.FDPE.L2.cocotb_random: constrained-random FDPE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdpe_random(dut):
    await random_session(dut, "FDPE", cycles=2000)
