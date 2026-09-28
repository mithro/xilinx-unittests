# SPDX-License-Identifier: Apache-2.0
"""TOYNEG (xut tool tests only; model text in test_runner_cocotb.py): a negedge-sensitive
model, `always @(negedge C) f <= 1;`. It pins review M8's must-fix: the cocotb top must
give ``clk`` no time-0 edge. Before the fix, barriering ``clk`` the same way as
``in_vec`` turned its x-to-0 declaration value into a real (negedge) event on Icarus,
which this session's single sample would have caught."""

import os

import cocotb

from xut.cocotb_dut import XutDut


@cocotb.test()
async def no_time0_clock_edge(dut: object) -> None:
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    await x.settle()
    v = x.sample("S0")
    x.close()
    assert v["F"] == "0", f"F was set: a time-0 clock edge fired ({v})"
