# SPDX-License-Identifier: Apache-2.0
"""TOYCOMB (xut tool tests only; model text in test_runner_cocotb.py): a combinational
model whose output is a reg updated by an ``always @(<inputs>)`` block, so it is x until
one of its inputs has an event. The session never changes an input before its first
samples: it re-drives the all-zero idle value, as a LUT session does. The first samples
must still be defined, so the cocotb top must give in_vec a time-0 event (x to 0) after
the model's processes have reached their event controls. (This model has no clock port:
that half moved to TOYNEG (review M8), since clk keeps its declaration initialiser and
so never has a time-0 event of its own to give an ``always @(C)`` block.)"""

import os

import cocotb

from xut.cocotb_dut import XutDut

#: label -> O with every input 0 (O = ~(A | B)), then A=1 (O=0).
EXPECTED = {"S0": "1", "S1": "1", "S2": "0"}


@cocotb.test()
async def first_samples_defined(dut: object) -> None:
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    got: dict[str, str] = {}
    await x.settle()
    await x.set(A=0, B=0)  # the idle value again: no event
    got["S0"] = x.sample("S0")["O"]
    await x.set(A=0, B=0)  # the idle value again, again: still no event
    got["S1"] = x.sample("S1")["O"]
    await x.set(A=1)
    got["S2"] = x.sample("S2")["O"]
    x.close()
    assert got == EXPECTED, f"got {got}, expected {EXPECTED}"
