# SPDX-License-Identifier: Apache-2.0
"""VZTRIG (tools/tests/fixtures/verilatorize/vz_trig.v) under cocotb (Task 13 review M3):
a release of the procedural ``assign`` (CLR/PRE falling) written through VPI in the SAME
time step as a rising clock edge, in both write orders. The vector testbench applies the
same step as one blocking input change then the edge (``xut_vector_tb.sv``); both must
give the original model's values: the ``deassign`` runs first, then the edge's
non-blocking ``q <= D`` wins. Sample labels match the vector test's.

The coincident step writes the two vectors itself, through ``XutDut``'s shadow (a tools
test fixture may use its private fields: ``XutDut.set``/``edge`` each wait a gap)."""

import os

import cocotb
from cocotb.triggers import Timer

from xut.cocotb_dut import XutDut

#: label -> Q under the original model's semantics (the vector test's expected.xtr)
EXPECTED = {
    "forced": "0",
    "rel_edge_a": "1",
    "clr2": "0",
    "rel_edge_b": "1",
    "pre": "1",
    "rel_edge_c": "0",
    "retain": "1",
    "after": "0",
}


async def coincident(x: XutDut, port: str, value: int, clk_first: bool) -> None:
    """``port`` <= ``value`` and a rising C, written in one time step."""
    x._shadow["in"] = x._merged(x._shadow["in"], port, value)
    x._shadow["clk"] = x._merged(x._shadow["clk"], "C", 1)
    for vec in ("clk", "in") if clk_first else ("in", "clk"):
        x._write(vec)
    await Timer(x.gap_ps, "ps")


@cocotb.test()
async def release_on_edge(dut: object) -> None:
    x = XutDut(dut, os.environ["XUT_MAP"], os.environ["XUT_TRACE"])
    got: dict[str, str] = {}
    await x.settle()
    await x.set(D=1)
    await x.set(CLR=1)
    got["forced"] = x.sample("forced")["Q"]
    await coincident(x, "CLR", 0, clk_first=False)
    got["rel_edge_a"] = x.sample("rel_edge_a")["Q"]
    await x.edge("C", False)
    await x.set(CLR=1)
    got["clr2"] = x.sample("clr2")["Q"]
    await coincident(x, "CLR", 0, clk_first=True)
    got["rel_edge_b"] = x.sample("rel_edge_b")["Q"]
    await x.edge("C", False)
    await x.set(D=0)
    await x.set(PRE=1)
    got["pre"] = x.sample("pre")["Q"]
    await coincident(x, "PRE", 0, clk_first=False)
    got["rel_edge_c"] = x.sample("rel_edge_c")["Q"]
    await x.edge("C", False)
    await x.set(PRE=1)
    await x.set(PRE=0)  # released without an edge: q keeps the forced value
    got["retain"] = x.sample("retain")["Q"]
    await x.edge("C", True)
    got["after"] = x.sample("after")["Q"]
    x.close()
    bad = {k: (v, EXPECTED[k]) for k, v in got.items() if v != EXPECTED[k]}
    assert not bad, f"(got, expected) per label: {bad}"
