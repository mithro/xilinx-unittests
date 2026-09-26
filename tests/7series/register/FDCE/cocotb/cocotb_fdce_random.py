# SPDX-License-Identifier: Apache-2.0
"""7series.FDCE.L2.cocotb_random: constrained-random FDCE session against the golden model."""

import cocotb
from flops_cocotb import random_session


@cocotb.test()
async def fdce_random(dut):
    await random_session(dut, "FDCE", cycles=2000)
