# SPDX-License-Identifier: Apache-2.0
"""Claim-by-claim tests of the flops golden models (clean-room, UG953 v2026.1)."""

import pytest
from flop_recipes import KINDS

from xut_models.registry import get

PRIMS = ["FDRE"]  # FDSE added in Task 25, FDCE/FDPE in Task 26


def forced(prim):
    return 0 if KINDS[prim].ctrl in ("R", "CLR") else 1


def fresh(prim, **attrs):
    m = get("7series", prim)(attrs)
    m.power_on()
    for p in m.inputs():
        m.set_input(p, 0)
    m.glbl("GSR", 0)
    return m


def q(m):
    return m.outputs()["Q"]


def load(m, v):
    m.set_input("CE", 1)
    m.set_input("D", v)
    m.clock_edge("C", True)
    m.clock_edge("C", False)


@pytest.mark.parametrize("prim", PRIMS)
def test_c4_default_init_from_documentation(prim):
    default = 1 if prim in ("FDSE", "FDPE") else 0
    m = fresh(prim)
    assert q(m).bits == str(default) and q(m).prov.startswith("doc:")
    assert f"{prim}.C4" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
@pytest.mark.parametrize("init", [0, 1])
def test_c4_explicit_init(prim, init):
    assert q(fresh(prim, INIT=f"1'b{init}")).bits == str(init)


@pytest.mark.parametrize("prim", PRIMS)
def test_c1_capture_on_rising_edge_only(prim):
    m = fresh(prim, INIT="1'b0")
    m.set_input("CE", 1)
    m.set_input("D", 1)
    m.clock_edge("C", False)
    assert q(m).bits == "0"
    m.clock_edge("C", True)
    assert q(m).bits == "1" and f"{prim}.C1" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c2_ce_low_holds(prim):
    m = fresh(prim, INIT="1'b0")
    m.set_input("D", 1)
    m.clock_edge("C", True)
    assert q(m).bits == "0" and f"{prim}.C2" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
@pytest.mark.parametrize("ce", [0, 1])
def test_c3_control_overrides(prim, ce):
    k, f = KINDS[prim], forced(prim)
    m = fresh(prim)
    load(m, 1 - f)
    m.set_input("CE", ce)
    m.set_input("D", 1 - f)
    m.set_input(k.ctrl, 1)
    assert q(m).bits == (str(f) if k.is_async else str(1 - f))  # async: at once
    m.clock_edge("C", True)
    assert q(m).bits == str(f) and q(m).prov.startswith("doc:")
    m.set_input(k.ctrl, 0)
    assert q(m).bits == str(f)  # released: holds


@pytest.mark.parametrize("prim", PRIMS)
def test_c5_negative_edge(prim):
    m = fresh(prim, INIT="1'b0", IS_C_INVERTED="1'b1")
    m.set_input("CE", 1)
    m.set_input("D", 1)
    m.clock_edge("C", True)
    assert q(m).bits == "0"
    m.clock_edge("C", False)
    assert q(m).bits == "1" and f"{prim}.C5" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c6_control_active_low(prim):
    k, f = KINDS[prim], forced(prim)
    m = fresh(prim, **{f"IS_{k.ctrl}_INVERTED": "1'b1"})  # pin 0 -> active
    m.clock_edge("C", True)
    assert q(m).bits == str(f) and f"{prim}.C6" in m.claims_hit
    m.set_input(k.ctrl, 1)  # inactive now
    load(m, 1 - f)
    assert q(m).bits == str(1 - f)


@pytest.mark.parametrize("prim", PRIMS)
def test_c7_d_inverted(prim):
    m = fresh(prim, IS_D_INVERTED="1'b1")
    load(m, 0)
    assert q(m).bits == "1" and f"{prim}.C7" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_gsr_midrun_and_inferred_edge(prim):
    m = fresh(prim, INIT="1'b1")
    load(m, 0)
    m.glbl("GSR", 1)
    assert q(m) == q(fresh(prim, INIT="1'b1"))  # INIT, doc
    m.set_input("CE", 1)
    m.set_input("D", 0)
    m.clock_edge("C", True)
    assert q(m).bits == "1" and q(m).prov.startswith("inferred:")
    m.glbl("GSR", 0)
    load(m, 0)
    assert q(m).bits == "0"


@pytest.mark.parametrize("prim", [p for p in PRIMS if KINDS[p].is_async])
def test_gsr_versus_async_control_inferred_control_wins(prim):
    k, f = KINDS[prim], forced(prim)
    same = fresh(prim, INIT=f"1'b{f}")
    same.glbl("GSR", 1)
    same.set_input(k.ctrl, 1)
    assert q(same).bits == str(f) and q(same).prov.startswith("doc:")  # both rules agree
    m = fresh(prim, INIT=f"1'b{1 - f}")
    m.glbl("GSR", 1)
    m.set_input(k.ctrl, 1)
    assert q(m).bits == str(f) and q(m).prov.startswith("inferred:")
    m.glbl("GSR", 0)  # control still active: it wins
    assert q(m).bits == str(f) and q(m).prov.startswith("doc:")


@pytest.mark.parametrize("prim", PRIMS)
def test_gts_is_not_modelled(prim):
    from xut_models.base import ModelUnsupported

    with pytest.raises(ModelUnsupported):
        fresh(prim).glbl("GTS", 1)
