# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.hw import image
from xut.hw.compile import HwUnrenderable, compile_program, t0_bits
from xut.stimgen import VecBuilder
from xut.wrap import Bit, DutMap


def _map(nin=2, clk=True, cls="data") -> DutMap:
    bits = [Bit("in", 0, "D", 0, "data"), Bit("in", 1, "R", 0, cls), Bit("out", 0, "Q", 0, "data")]
    if clk:
        bits.insert(0, Bit("clk", 0, "C", 0, "clock"))
    return DutMap("TOYFF", "7series", "c0", {}, int(clk), nin, 1, bits)


def test_t0_is_the_initialisation_and_order_is_kept():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.init(R=1)
    b.set(D=1)
    b.cycle("C")  # rise, sample, fall
    b.set(D=0, R=0)
    b.sample("s2")
    vec = b.build()
    assert t0_bits(vec, m) == "10"  # R=1 (bit 1), D=0
    p = compile_program(vec, m)
    assert p.t0 == "10"
    ops = [image.decode(w)[0] for w in p.words]
    assert ops[:2] == [image.OP_SET, image.OP_COMMIT]  # D=1
    assert image.OP_EDGE in ops and ops[-1] == image.OP_END
    assert list(p.labels) == [e.target for e in vec.events if e.op == "sample"]


def test_co_timed_disjoint_sets_are_one_commit():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.set(D=1, R=1)
    b.sample("s")
    p = compile_program(b.build(), m)
    assert [image.decode(w)[0] for w in p.words].count(image.OP_COMMIT) == 1


def test_unrenderable_reasons_are_the_validators():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.set(D="x")
    b.sample("s")
    with pytest.raises(HwUnrenderable, match="x/z"):
        compile_program(b.build(), m)


def test_glbl_is_unrenderable():
    m = _map()
    b = VecBuilder(m, seed=1)
    b.glbl("GSR", 1)
    b.glbl("GSR", 0)
    b.sample("s")
    with pytest.raises(HwUnrenderable, match="GSR"):
        compile_program(b.build(), m)


def test_expect_reject_is_unrenderable():
    m = _map()
    b = VecBuilder(m, seed=1, expect="reject", illegal=["INIT"])
    b.sample("s")
    with pytest.raises(HwUnrenderable, match="reject"):
        compile_program(b.build(), m)
