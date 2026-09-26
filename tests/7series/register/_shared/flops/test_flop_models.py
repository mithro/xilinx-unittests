# SPDX-License-Identifier: Apache-2.0
"""Claim-by-claim tests of the flops golden models (clean-room, UG953 v2026.1)."""

import pytest
from flop_recipes import KINDS

from xut_models.base import ModelContractError, ModelUnsupported
from xut_models.registry import get

PRIMS = ["FDRE"]  # FDSE added in Task 25, FDCE/FDPE in Task 26

# UG953 v2026.1 (Introduction/Logic-Table page, Attributes page), pinned here as literals
# -- independently of the model class under test -- so a wrong PAGE/ATTR_PAGE constant is
# actually caught (ruling S32(3)); checked against catalog/7series/<PRIM>.overrides.yaml.
_PAGES = {
    "FDRE": (375, 376),
    "FDSE": (378, 379),
    "FDCE": (369, 370),
    "FDPE": (372, 373),
}


def forced(prim):
    return KINDS[prim].forced


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
    default = KINDS[prim].init_default
    m = fresh(prim)
    assert q(m).bits == str(default) and q(m).prov.startswith("doc:")
    assert f"{prim}.C4" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
@pytest.mark.parametrize("init", [0, 1])
def test_c4_explicit_init(prim, init):
    assert q(fresh(prim, INIT=f"1'b{init}")).bits == str(init)


@pytest.mark.parametrize("prim", PRIMS)
def test_power_on_hits_only_gsr_init(prim):
    """Ruling S32(2): kills the mutant that credits every claim at power-on."""
    m = get("7series", prim)({})
    assert m.claims_hit == set()  # nothing is decided before power-on
    m.power_on()
    assert m.claims_hit == {f"{prim}.C4"}  # only GSR->INIT; C1-C3, C5-C7 stay unhit


@pytest.mark.parametrize("prim", PRIMS)
def test_c1_capture_on_rising_edge_only(prim):
    m = fresh(prim, INIT="1'b0")
    m.set_input("CE", 1)
    m.set_input("D", 1)
    m.clock_edge("C", False)
    assert q(m).bits == "0"
    m.clock_edge("C", True)
    assert q(m).bits == "1" and f"{prim}.C1" in m.claims_hit
    assert q(m).prov == f"doc:{_PAGES[prim][0]}"  # plain capture: PAGE
    assert f"{prim}.C2" not in m.claims_hit  # CE was High throughout
    assert f"{prim}.C3" not in m.claims_hit  # the control was never active
    assert f"{prim}.C7" not in m.claims_hit  # D was never inverted


@pytest.mark.parametrize("prim", PRIMS)
def test_c2_ce_low_holds(prim):
    m = fresh(prim, INIT="1'b0")
    m.set_input("D", 1)
    m.clock_edge("C", True)
    assert q(m).bits == "0" and f"{prim}.C2" in m.claims_hit
    assert f"{prim}.C1" not in m.claims_hit  # no capture happened


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
def test_c3_not_hit_while_control_stays_inactive(prim):
    m = fresh(prim)
    load(m, 1)
    load(m, 0)
    assert q(m).bits == "0" and f"{prim}.C3" not in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c5_negative_edge(prim):
    m = fresh(prim, INIT="1'b0", IS_C_INVERTED="1'b1")
    m.set_input("CE", 1)
    m.set_input("D", 1)
    m.clock_edge("C", True)
    assert q(m).bits == "0"
    m.clock_edge("C", False)
    assert q(m).bits == "1" and f"{prim}.C5" in m.claims_hit
    assert q(m).prov == f"doc:{_PAGES[prim][1]}"  # inverted-edge capture: ATTR_PAGE


@pytest.mark.parametrize("prim", PRIMS)
def test_c5_control_force_on_inverted_edge(prim):
    """R4: a synchronous control's force at an inverted active edge must pin
    ATTR_PAGE, not PAGE, and must hit C5 (mutant N9: `_force` ignores `inverted`)."""
    k, f = KINDS[prim], forced(prim)
    if k.is_async:
        pytest.skip("async controls act at once, not at a clock edge")
    m = fresh(prim, IS_C_INVERTED="1'b1")
    m.set_input(k.ctrl, 1)
    m.clock_edge("C", True)  # rising: not the active edge under inversion
    m.clock_edge("C", False)  # falling: the active edge; the control forces here
    assert q(m).bits == str(f)
    assert q(m).prov == f"doc:{_PAGES[prim][1]}"  # ATTR_PAGE, not PAGE
    assert f"{prim}.C5" in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c5_not_hit_when_ce_low(prim):
    """Ruling S32(1)/(2): an active (falling) edge that CE Low ignores decides
    nothing C5-relevant, so it must not credit C5 (the reviewer's false-hit case)."""
    default = KINDS[prim].init_default
    m = fresh(prim, IS_C_INVERTED="1'b1")  # CE stays Low the whole time
    m.clock_edge("C", True)  # rising: not the active edge under inv_c
    m.clock_edge("C", False)  # falling: the active edge, but CE Low holds
    assert q(m).bits == str(default)
    assert f"{prim}.C2" in m.claims_hit  # the active edge did hit ce_hold
    assert f"{prim}.C5" not in m.claims_hit  # ...but decided nothing C5-relevant


@pytest.mark.parametrize("prim", PRIMS)
def test_free_running_clock_under_gsr_hits_nothing(prim):
    """Ruling S32(2): a free-running (inverted) clock while GSR holds INIT, with CE
    never raised, must hit only C4 -- not C1, C2 or C5 -- and must not disturb Q's
    doc: provenance with a needless inferred: retag (Minor 7)."""
    m = fresh(prim, INIT="1'b1", IS_C_INVERTED="1'b1")
    m.glbl("GSR", 1)
    m.set_input("D", 1)  # CE stays Low throughout
    for rising in (True, False, True, False, True, False):
        m.clock_edge("C", rising)
    assert m.claims_hit == {f"{prim}.C4"}
    assert q(m).bits == "1" and q(m).prov == f"doc:{_PAGES[prim][0]}"


@pytest.mark.parametrize("prim", PRIMS)
def test_c6_control_active_low(prim):
    k, f = KINDS[prim], forced(prim)
    m = fresh(prim, **{f"IS_{k.ctrl}_INVERTED": "1'b1"})  # active-Low: pin 0 -> active
    m.set_input(k.ctrl, 1)  # inactive first...
    load(m, 1 - f)  # ...so this capture is real, not a fluke of INIT
    assert q(m).bits == str(1 - f) and f"{prim}.C6" not in m.claims_hit
    m.set_input(k.ctrl, 0)  # pin 0 -> active under the inversion
    m.clock_edge("C", True)
    assert q(m).bits == str(f) and f"{prim}.C6" in m.claims_hit
    assert q(m).prov == f"doc:{_PAGES[prim][1]}"  # control forced via inversion: ATTR_PAGE
    m.set_input(k.ctrl, 1)  # inactive now
    load(m, 1 - f)
    assert q(m).bits == str(1 - f)


@pytest.mark.parametrize("prim", PRIMS)
def test_c6_not_hit_from_gsr_edge_probe(prim):
    """R2: the GSR-edge branch's bare ``_ctrl_active()`` check (whether to re-tag Q
    as ``inferred:``) must not itself credit C6 (mutant N2)."""
    k = KINDS[prim]
    m = fresh(prim, **{f"IS_{k.ctrl}_INVERTED": "1'b1"})
    m.glbl("GSR", 1)
    m.set_input(k.ctrl, 0)  # inverted: pin Low -> active
    m.clock_edge("C", True)  # the GSR-edge branch runs the bare probe
    assert f"{prim}.C6" not in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c7_d_inverted(prim):
    m = fresh(prim, IS_D_INVERTED="1'b1")
    load(m, 0)
    assert q(m).bits == "1" and f"{prim}.C7" in m.claims_hit
    assert q(m).prov == f"doc:{_PAGES[prim][1]}"  # inverted-D capture: ATTR_PAGE


@pytest.mark.parametrize("prim", PRIMS)
def test_c7_not_hit_when_ce_low(prim):
    """R3: the C7 (inv_d) non-hit is pinned for a CE-Low edge, not only for
    IS_D_INVERTED=0 (mutant N6 hits C7 on every edge)."""
    m = fresh(prim, IS_D_INVERTED="1'b1")
    m.set_input("D", 1)  # CE stays Low: the edge below is a no-op
    m.clock_edge("C", True)
    assert f"{prim}.C7" not in m.claims_hit


@pytest.mark.parametrize("prim", PRIMS)
def test_c7_not_hit_when_control_active(prim):
    """R3: the C7 (inv_d) non-hit is pinned when the control forces Q instead of a
    capture deciding it (mutant N6 hits C7 on every edge)."""
    k = KINDS[prim]
    m = fresh(prim, IS_D_INVERTED="1'b1")
    m.set_input("CE", 1)
    m.set_input("D", 1)
    m.set_input(k.ctrl, 1)
    if not k.is_async:
        m.clock_edge("C", True)
    assert f"{prim}.C7" not in m.claims_hit


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
    assert q(m).bits == "1" and q(m).prov.startswith("inferred:")  # release keeps the retag
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
    assert f"{prim}.C3" in m.claims_hit  # ruling S30: the control claim still hits
    m.glbl("GSR", 0)  # control still active: it wins
    assert q(m).bits == str(f) and q(m).prov.startswith("doc:")


@pytest.mark.parametrize("prim", PRIMS)
def test_gts_is_not_modelled(prim):
    with pytest.raises(ModelUnsupported):
        fresh(prim).glbl("GTS", 1)


@pytest.mark.parametrize("prim", PRIMS)
def test_unknown_port_is_rejected(prim):
    m = fresh(prim)
    with pytest.raises(ModelContractError):
        m.set_input("BOGUS", 1)
    with pytest.raises(ModelContractError):
        m.clock_edge("NOTC", True)


@pytest.mark.parametrize("prim", PRIMS)
def test_set_input_before_power_on_is_rejected(prim):
    """R5: ``golden.replay`` always calls ``power_on()`` first (golden.py:209); a
    direct caller that skips it must not get silently-wrong state instead of an error."""
    m = get("7series", prim)({})
    with pytest.raises(ModelContractError):
        m.set_input("D", 0)


@pytest.mark.parametrize("prim", PRIMS)
def test_clock_edge_before_power_on_is_rejected(prim):
    m = get("7series", prim)({})
    with pytest.raises(ModelContractError):
        m.clock_edge("C", True)


@pytest.mark.parametrize("prim", PRIMS)
def test_input_value_other_than_0_or_1_is_rejected(prim):
    """R5: ``xut.golden._port_value`` already refuses x/z before it ever calls
    ``set_input`` (x stimulus is covered by sv tests, not the model, spec §5.6), so this
    guards only a direct/misbehaving caller, never golden replay."""
    m = fresh(prim)
    with pytest.raises(ModelContractError):
        m.set_input("D", 2)
