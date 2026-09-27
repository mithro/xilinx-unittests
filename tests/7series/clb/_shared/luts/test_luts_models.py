# SPDX-License-Identifier: Apache-2.0
"""Claim-by-claim tests of the luts golden models (clean-room, UG953 v2026.1).

The page numbers are literals here, never read from the model, so a wrong ``PAGE`` in a
model fails a test (step-2 review mutant M6).
"""

import random

import pytest
from luts_recipes import KINDS, ones, projection
from luts_recipes import lit as _lit

from xut_models.base import ModelContractError, ModelUnsupported
from xut_models.registry import get

LUTN = [f"LUT{n}" for n in range(1, 7)]
#: prim -> (Introduction page: the zero default, Logic Table page)
PAGES = {
    "LUT1": (488, 489),
    "LUT2": (491, 492),
    "LUT3": (494, 495),
    "LUT4": (497, 498),
    "LUT5": (500, 501),
    "LUT6": (504, 504),
    "LUT6_2": (509, 510),
}


def fresh(prim, **attrs):
    m = get("7series", prim)(attrs)
    m.power_on()
    for p in m.inputs():
        if p not in m.CLOCKS:
            m.set_input(p, 0)
    m.glbl("GSR", 0)
    return m


def drive(m, n, a):
    for i in range(n):
        m.set_input(f"I{i}", (a >> i) & 1)


def lit(prim, v):
    return _lit(KINDS[prim], v)


@pytest.mark.parametrize("prim", LUTN)
def test_c1_logic_table_every_address(prim):
    k = KINDS[prim]
    init = random.Random(prim).getrandbits(k.width)
    m = fresh(prim, INIT=lit(prim, init))
    for a in range(1 << k.n):
        drive(m, k.n, a)
        o = m.outputs()["O"]
        assert o.bits == str((init >> a) & 1), a
        assert o.prov == f"doc:{PAGES[prim][1]}"
    assert m.claims_hit == {f"{prim}.C1"}


@pytest.mark.parametrize(("prim", "j"), [(p, j) for p in LUTN for j in range(KINDS[p].n)])
def test_c1_input_order_projection(prim, j):
    k = KINDS[prim]
    m = fresh(prim, INIT=lit(prim, projection(k, j)))
    for a in range(1 << k.n):
        drive(m, k.n, a)
        assert m.outputs()["O"].bits == str((a >> j) & 1)


@pytest.mark.parametrize("prim", LUTN)
def test_c2_default_is_ground(prim):
    k = KINDS[prim]
    m = fresh(prim)
    for a in range(1 << k.n):
        drive(m, k.n, a)
        o = m.outputs()["O"]
        assert (o.bits, o.prov) == ("0", f"doc:{PAGES[prim][0]}")
    assert m.claims_hit == {f"{prim}.C2"}  # never C1: the default decided it


@pytest.mark.parametrize("prim", LUTN)
def test_explicit_zero_is_c1_not_c2(prim):
    m = fresh(prim, INIT=lit(prim, 0))
    assert m.outputs()["O"].bits == "0"
    assert m.claims_hit == {f"{prim}.C1"}


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2"])
def test_gsr_is_inferred_and_credits_nothing(prim):
    k = KINDS[prim]
    m = fresh(prim, INIT=lit(prim, ones(k)))
    m.glbl("GSR", 1)
    for a in range(1 << k.n):
        drive(m, k.n, a)
        for o in m.outputs().values():
            assert o.bits == "1" and o.prov.startswith("inferred:")
    assert m.claims_hit == set()
    m.glbl("GSR", 0)
    assert all(o.prov.startswith("doc:") for o in m.outputs().values())


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2", "CFGLUT5"])
def test_guards(prim):
    m = get("7series", prim)({})
    for call in (lambda: m.outputs(), lambda: m.set_input("I0", 1), lambda: m.glbl("GSR", 0)):
        with pytest.raises(ModelContractError):
            call()
    m.power_on()
    with pytest.raises(ModelContractError):
        m.set_input("I9", 0)
    with pytest.raises(ModelContractError):
        m.set_input("I0", 2)
    with pytest.raises(ModelUnsupported):
        m.glbl("GTS", 1)


def test_cfglut5_clock_edge_guards():
    m = get("7series", "CFGLUT5")({})
    with pytest.raises(ModelContractError):
        m.clock_edge("CLK", True)  # before power_on
    m.power_on()
    with pytest.raises(ModelContractError):
        m.clock_edge("CE", True)  # not a clock port
    with pytest.raises(ModelContractError):
        m.set_input("CLK", 1)  # a clock is driven with clock_edge


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2", "CFGLUT5"])
def test_init_wider_than_the_table_is_a_contract_error(prim):
    k = KINDS[prim]
    with pytest.raises(ModelContractError):
        get("7series", prim)({"INIT": 1 << k.width})


@pytest.mark.parametrize("prim", [*LUTN, "LUT6_2"])
def test_a_lut_has_no_clock(prim):
    with pytest.raises(ModelContractError):
        fresh(prim).clock_edge("C", True)


# -- LUT6_2 ------------------------------------------------------------------------------


def test_lut6_2_c1_c2_o6_full_o5_lower_half_ignoring_i5():
    init = random.Random("LUT6_2").getrandbits(64)
    m = fresh("LUT6_2", INIT=lit("LUT6_2", init))
    for a in range(64):
        drive(m, 6, a)
        out = m.outputs()
        assert out["O6"].bits == str((init >> a) & 1)
        assert out["O5"].bits == str((init >> (a & 31)) & 1)
        assert out["O5"].prov == out["O6"].prov == "doc:510"
    assert m.claims_hit == {"LUT6_2.C1", "LUT6_2.C2"}


def test_lut6_2_c3_default_and_c4_example():
    m = fresh("LUT6_2")
    assert {o.bits for o in m.outputs().values()} == {"0"}
    assert m.claims_hit == {"LUT6_2.C3"}
    m = fresh("LUT6_2", INIT="64'hFFFFFFFFFFFFFFFE")
    for a in range(64):
        drive(m, 6, a)
        out = m.outputs()
        assert out["O6"].bits == str(int(a != 0))  # 6-input OR
        assert out["O5"].bits == str(int(a & 31 != 0))  # 5-input OR of I4-I0
    assert m.claims_hit == {"LUT6_2.C1", "LUT6_2.C2", "LUT6_2.C4"}


def test_lut6_2_c4_not_hit_for_another_init():
    m = fresh("LUT6_2", INIT="64'hFFFFFFFFFFFFFFFC")
    m.outputs()
    assert "LUT6_2.C4" not in m.claims_hit


# -- CFGLUT5 -----------------------------------------------------------------------------

NON_UNIFORM = 0x1234_5678  # a pattern whose reads depend on the inferred bit order
ONES = 0xFFFF_FFFF


def cfg(init=None, **attrs):
    if init is not None:
        attrs["INIT"] = lit("CFGLUT5", init)
    return fresh("CFGLUT5", **attrs)


def edge(m, rising):
    m.clock_edge("CLK", rising)


def shift(m, bits, ce=1):
    """One full CLK cycle (rise, then fall) per bit, CE held; CE Low afterwards."""
    m.set_input("CE", ce)
    for b in bits:
        m.set_input("CDI", b)
        edge(m, True)
        edge(m, False)
    m.set_input("CE", 0)


def load(m, value):
    shift(m, [(value >> i) & 1 for i in reversed(range(32))])


def table(m):
    out = []
    for a in range(32):
        drive(m, 5, a)
        o = m.outputs()
        out.append((o["O6"].bits, o["O5"].bits))
    return out


def provs(m):
    return {o.prov for o in m.outputs().values()}


def test_cfglut5_non_uniform_power_on_is_read_but_credits_nothing():
    """S52: the reads follow the inferred order (C1/C2 are exercised) but credit nothing,
    and nor does power-on (C6): every value observed depends on the order."""
    init = random.Random("CFGLUT5").getrandbits(32) | 1  # never uniform
    m = cfg(init)
    for a, (o6, o5) in enumerate(table(m)):
        assert o6 == str((init >> a) & 1) and o5 == str((init >> (a & 15)) & 1)
    assert m.outputs()["O6"].prov.startswith("inferred:CFGLUT5_p348")
    assert m.claims_hit == set()


@pytest.mark.parametrize(("init", "bit"), [(0, "0"), (ONES, "1"), (None, "0")])
def test_cfglut5_uniform_contents_are_documented_and_credit_c1_c2_c6(init, bit):
    m = cfg(init)  # None: INIT unset, the all-zeroes default (p349)
    assert m.claims_hit == {"CFGLUT5.C6"}
    for o6, o5 in table(m):
        assert (o6, o5) == (bit, bit)
    for o in m.outputs().values():
        assert (o.bits, o.prov) == (bit, "doc:348")
    assert m.claims_hit == {"CFGLUT5.C1", "CFGLUT5.C2", "CFGLUT5.C6"}  # no C5: no shift yet


def test_cfglut5_31_ones_after_init_1_is_not_known_uniform():
    """Correctness review M1, counterexample 1: INIT=1 then 31 ones is all ones only under
    the inferred order (the other direction leaves 0xFFFFFFFE)."""
    m = cfg(1)
    shift(m, [1] * 31)
    assert m.contents == ONES and m.known is None
    assert provs(m) == {
        "inferred:CFGLUT5_p348_cites_O5/O6_tables_it_does_not_contain;"
        "O6_is_INIT[{I4..I0}]_as_in_the_LUT5_logic_table_(p501)",
        "inferred:O5_is_the_4-LUT_output_(p348);"
        "O5_is_INIT[{I3..I0}]_(the_lower_half)_as_for_LUT6_2's_O5_(p509)",
        "inferred:p348_gives_no_shift_direction;CDI_enters_INIT[0]_and_INIT[31]_drives_CDO",
    }
    assert m.claims_hit == set()


def test_cfglut5_one_shift_into_7fffffff_credits_nothing():
    """Counterexample 2: INIT=7fffffff then one 1 (the other direction gives bfffffff);
    a following CE-Low edge credits no C4 either."""
    m = cfg(0x7FFF_FFFF)
    shift(m, [1])
    assert m.contents == ONES and m.known is None
    table(m)
    edge(m, True)
    edge(m, False)
    assert m.claims_hit == set()


def test_cfglut5_32_equal_shifts_make_any_contents_known_uniform():
    m = cfg(NON_UNIFORM)
    shift(m, [1] * 31)
    assert m.known is None and m.claims_hit == set()
    shift(m, [1])
    assert m.known == 1 and "CFGLUT5.C3" in m.claims_hit
    assert {o.bits for o in m.outputs().values()} == {"1"}
    assert provs(m) == {"doc:348"}
    assert {"CFGLUT5.C1", "CFGLUT5.C2"} <= m.claims_hit
    # no C5: CDO's old value was not known, so a stuck CDO might agree (ruling S55)
    assert "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_same_value_shift_credits_no_c3_or_c7():
    """S55: shifting the value the contents already hold changes nothing observable."""
    for inverted in (0, 1):
        m = cfg(ONES, IS_CLK_INVERTED=f"1'b{inverted}")
        m.claims_hit.clear()
        shift(m, [1] * 40)
        assert m.known == 1 and m.shifts == 40
        assert not {"CFGLUT5.C3", "CFGLUT5.C7"} & m.claims_hit


def test_cfglut5_ce_low_edge_with_cdi_equal_to_known_credits_no_c4():
    m = cfg(ONES)
    m.claims_hit.clear()
    m.set_input("CE", 0)
    m.set_input("CDI", 1)  # equal to the contents: ignoring CE would show nothing
    edge(m, True)
    assert "CFGLUT5.C4" not in m.claims_hit
    m.set_input("CDI", 0)  # opposite: ignoring CE would flip a documented bit
    edge(m, False)
    edge(m, True)
    assert m.claims_hit == {"CFGLUT5.C4"}


def test_cfglut5_32_same_value_shifts_credit_no_c5():
    m = cfg(0)
    shift(m, [0] * 32)
    m.outputs()
    assert m.known == 0 and "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_c3_c5_credit_on_the_flip_to_the_opposite_uniform_value():
    m = cfg(0)
    shift(m, [1] * 31)
    assert m.claims_hit == {"CFGLUT5.C6"}  # still order-dependent: nothing yet
    shift(m, [1])
    m.outputs()
    assert {"CFGLUT5.C3", "CFGLUT5.C5"} <= m.claims_hit


@pytest.mark.parametrize("inverted", [0, 1])
def test_cfglut5_re_established_old_value_credits_no_c3_c5_or_c7(inverted):
    """Correctness re-review M7: INIT all ones, 20 zero-shifts unsampled, 32 one-shifts,
    then a sweep. Every sample is doc:348, and a never-shifting (or wrong-edge) model shows
    the same all ones throughout, so nothing here decides C3, C5 or C7."""
    m = cfg(ONES, IS_CLK_INVERTED=f"1'b{inverted}")
    shift(m, [0] * 20)
    shift(m, [1] * 32)
    assert m.known == 1
    assert set(table(m)) == {("1", "1")} and provs(m) == {"doc:348"}
    assert not {"CFGLUT5.C3", "CFGLUT5.C5", "CFGLUT5.C7"} & m.claims_hit


def test_cfglut5_re_established_opposite_value_credits_c3_c5():
    """The same run ending in the opposite value is new against the last known one."""
    m = cfg(ONES)
    shift(m, [1] * 5 + [0] * 20)
    assert m.known is None
    shift(m, [0] * 12)
    m.outputs()
    assert m.known == 0 and {"CFGLUT5.C3", "CFGLUT5.C5"} <= m.claims_hit


def test_cfglut5_an_opposite_bit_loses_known_uniform():
    m = cfg(ONES)
    shift(m, [1, 1])
    assert m.known == 1  # equal bits keep it
    shift(m, [0])
    assert m.known is None and m.outputs()["O6"].prov != "doc:348"


def test_cfglut5_reload_to_non_uniform_credits_no_c3():
    m = cfg(0xF0F0_F0F0)
    load(m, NON_UNIFORM)
    assert [o6 for o6, _ in table(m)] == [str((NON_UNIFORM >> a) & 1) for a in range(32)]
    assert m.claims_hit == set()


@pytest.mark.parametrize(("init", "credited"), [(ONES, True), (NON_UNIFORM, False)])
def test_cfglut5_c4_ce_low_holds_credited_only_when_known_uniform(init, credited):
    m = cfg(init)
    before = table(m)
    m.claims_hit.clear()
    m.set_input("CE", 0)
    for b in (1, 0, 1):
        m.set_input("CDI", b)
        edge(m, True)
        edge(m, False)
    assert m.claims_hit == ({"CFGLUT5.C4"} if credited else set())
    assert table(m) == before


@pytest.mark.parametrize("inverted", [0, 1])
def test_cfglut5_inactive_edge_with_ce_high_changes_nothing(inverted):
    """Correctness review M3: from known-uniform contents, the inactive edge with CE High
    and the opposite CDI leaves every address and CDO at the old value, doc:348."""
    m = cfg(0, IS_CLK_INVERTED=f"1'b{inverted}")
    if inverted:  # the inactive edge is the rise
        m.set_input("CE", 1)
        m.set_input("CDI", 1)
        edge(m, True)
    else:  # the inactive edge is the fall: rise first with CE Low
        edge(m, True)
        m.set_input("CE", 1)
        m.set_input("CDI", 1)
        edge(m, False)
    m.set_input("CE", 0)
    assert m.shifts == 0 and m.known == 0
    assert set(table(m)) == {("0", "0")} and provs(m) == {"doc:348"}


def test_cfglut5_c7_falling_edge_only():
    m = cfg(0, IS_CLK_INVERTED="1'b1")
    m.set_input("CE", 1)
    m.set_input("CDI", 1)
    edge(m, True)
    assert m.shifts == 0
    for _ in range(31):
        edge(m, False)
        edge(m, True)
    assert "CFGLUT5.C7" not in m.claims_hit  # 31 shifts: a mix, order-dependent
    edge(m, False)  # the 32nd: all ones, whatever the order
    assert m.known == 1 and m.outputs()["O6"].bits == "1"
    assert {"CFGLUT5.C3", "CFGLUT5.C7", "CFGLUT5.C5"} <= m.claims_hit


def test_cfglut5_cdo_order_is_inferred_and_random_data_credits_nothing():
    bits = [random.Random(i).randrange(2) for i in range(64)]
    m = cfg(NON_UNIFORM)
    m.set_input("CE", 1)
    seen = []
    for b in bits:
        m.set_input("CDI", b)
        edge(m, True)
        edge(m, False)
        seen.append(m.outputs()["CDO"].bits)
    old = [str((NON_UNIFORM >> i) & 1) for i in reversed(range(31))]  # INIT[30]..INIT[0]
    assert seen[:31] == old  # the inferred order (D5)
    assert seen[31:] == [str(b) for b in bits[:33]]
    assert "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_c5_not_hit_before_32_shifts():
    m = cfg(ONES)
    shift(m, [1] * 31)  # known-uniform all along, but no CDI bit has reached CDO yet
    m.outputs()
    assert m.known == 1 and "CFGLUT5.C5" not in m.claims_hit


def test_cfglut5_gsr_after_reload_is_inferred_until_32_more_shifts():
    m = cfg(NON_UNIFORM)
    load(m, 0xFFFF_0000)
    m.claims_hit.clear()
    m.glbl("GSR", 1)
    m.glbl("GSR", 0)
    assert table(m)[16] == ("1", "0")  # kept, not reloaded (inferred)
    assert all(o.prov.startswith("inferred:UG953_names_no_GSR") for o in m.outputs().values())
    shift(m, [0] * 31)
    assert m.outputs()["O6"].prov.startswith("inferred:UG953_names_no_GSR")
    assert m.claims_hit == set()  # S44: an inferred rule credits nothing
    shift(m, [0])
    assert provs(m) == {"doc:348"}  # 32 equal shifts: all zero whatever happened
    assert "CFGLUT5.C3" in m.claims_hit


def test_cfglut5_gsr_needs_no_gsr_inference_while_untouched():
    """No shift since power-on: "keep" and "reload INIT" agree, so no GSR tag."""
    m = cfg(0x0F0F_0F0F)
    m.glbl("GSR", 1)
    m.glbl("GSR", 0)
    assert not m.outputs()["O6"].prov.startswith("inferred:UG953_names_no_GSR")


def test_cfglut5_gsr_needs_no_gsr_inference_for_init_s_own_uniform_value():
    m = cfg(ONES)
    shift(m, [1] * 3)
    m.glbl("GSR", 1)
    m.glbl("GSR", 0)
    assert provs(m) == {"doc:348"}


def test_cfglut5_shift_under_gsr_credits_nothing():
    m = cfg(0)
    m.glbl("GSR", 1)
    m.claims_hit.clear()
    shift(m, [0])  # stays uniform, but under GSR: an inference decides it
    m.glbl("GSR", 0)
    assert m.claims_hit == set()
    assert m.outputs()["O6"].prov.startswith("inferred:UG953_names_no_GSR")
