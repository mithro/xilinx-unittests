# SPDX-License-Identifier: Apache-2.0
"""The luts unit's guards: xut.unitkit's set, plus the unit's own invariants."""

import pytest
from luts_recipes import KINDS
from luts_tests import (
    FAMILY,
    ROOT,
    UNIT,
    both_edges,
    init_reversed,
    inversion_ignored,
)
from luts_tests import tests_for as _tests_for  # aliased: pytest would collect "tests_for"

from xut import unitkit
from xut.testspec import TestCase
from xut.unitkit import UnitGuards
from xut_models.registry import get

_CFGLUT5 = get(FAMILY, "CFGLUT5")


class TestLutsUnit(UnitGuards):
    unit = UNIT


def test_cfglut5_never_declares_verilator():
    for e, _ in _tests_for(KINDS["CFGLUT5"]):
        assert e["runners"]["verilator"] == "unsupported", e["id"]
        assert "ruling S28" in e["unsupported_reasons"]["verilator"], e["id"]


def _vector_cases(prim: str) -> list[TestCase]:
    return [c for c in unitkit.cases(ROOT, FAMILY, prim) if c.style == "vector"]


def _edge_polarity() -> TestCase:
    return next(c for c in _vector_cases("CFGLUT5") if c.id.endswith(".L1.edge_polarity"))


@pytest.mark.parametrize("factory", [both_edges, inversion_ignored])
def test_edge_mutants_fail_documented_bits(factory):
    """Correctness review M3: L1.edge_polarity catches these on doc: bits, so a wrong-edge
    simulator is a doc-vs-model finding, not folded into the bit-order doc-gap."""
    assert unitkit.doc_mismatches(_edge_polarity(), ROOT, factory(_CFGLUT5)) > 0


def test_the_golden_model_agrees_with_itself():
    assert unitkit.doc_mismatches(_edge_polarity(), ROOT, _CFGLUT5) == 0


@pytest.mark.parametrize("prim", [p for p in KINDS if not KINDS[p].reconfig])
def test_the_reversed_init_order_fails_a_c1_crediting_configuration(prim):
    """Ruling S55, the LUT INIT bit-order mutants: the unit's C1 mutant (neighbouring
    addresses swapped) is in UnitGuards; the reversed order must be caught as well."""
    mutant = init_reversed(get(FAMILY, prim))
    assert any(unitkit.mutant_fails(c, ROOT, f"{prim}.C1", mutant) for c in _vector_cases(prim))
