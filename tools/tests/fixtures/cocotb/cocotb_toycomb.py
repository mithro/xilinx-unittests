# SPDX-License-Identifier: Apache-2.0
"""TOYCOMB (xut tool tests only; model text in test_runner_cocotb.py): a combinational
model whose outputs are regs updated by ``always @(<inputs>)`` blocks, so an output is x
until one of its inputs has an event. The session never changes an input before its
first samples: it re-drives the all-zero idle value, as a LUT session does. The first
samples must still be defined, so the cocotb top must give every input a time-0 event
(x to 0) after the model's processes have reached their event controls."""

import os

import cocotb

from xut.cocotb_dut import XutDut

#: label -> (O, P) with every input 0 (O = ~(A | B), P = ~C), then A=1 (O=0).
EXPECTED = {"S0": ("1", "1"), "S1": ("1", "1"), "S2": ("0", "1")}


@cocotb.test()
async def first_samples_defined(dut: object) -> None:
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    got: dict[str, tuple[str, str]] = {}
    await x.settle()
    await x.set(A=0, B=0)  # the idle value again: no event
    v = x.sample("S0")
    got["S0"] = (v["O"], v["P"])
    await x.edge("C", False)  # the clock's idle value again: no event
    v = x.sample("S1")
    got["S1"] = (v["O"], v["P"])
    await x.set(A=1)
    v = x.sample("S2")
    got["S2"] = (v["O"], v["P"])
    x.close()
    assert got == EXPECTED, f"got {got}, expected {EXPECTED}"
