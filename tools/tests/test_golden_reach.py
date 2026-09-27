# SPDX-License-Identifier: Apache-2.0
"""xut.golden.attr_bins / coverage_reach: bins_reached is named like coverage_bins (spec §9)."""

from xut.catalog.model import load_entry
from xut.formats.xvec import loads
from xut.golden import Reach, attr_bins, coverage_reach
from xut.paths import repo_root
from xut.status import coverage_bins

ATTRS = [
    {"name": "INIT", "allowed": ["Any 64-bit HEX value"]},
    {"name": "IS_C_INVERTED", "allowed": ["1'b0", "1'b1"]},
    {"name": "WIDTH", "allowed": []},
]


def test_attr_bins_name_only_set_non_enumerated_attributes():
    assert attr_bins(ATTRS, {"INIT": "64'h1", "IS_C_INVERTED": "1'b1"}) == {"attr:INIT"}
    assert attr_bins(ATTRS, {"WIDTH": 4}) == {"attr:WIDTH"}
    assert attr_bins(ATTRS, {}) == set()  # a default reaches no attribute bin


def test_coverage_reach_names_lut6_bins_as_coverage_bins_does():
    lit = "64'h8000000000000001"
    vec = loads(
        "# xut-vec 2  prim=LUT6 cfg=c nin=6 nout=1 nclk=0 settle_ps=120000 seed=0 "
        f"attr.INIT={lit}\nt=121000 set in[0]=1\nt=122000 sample S0\n"
    )
    reach = Reach(ports={"O", "I0"}, attrs=dict(vec.attrs), events={"I0:1"})
    got = coverage_reach(load_entry("7series", "LUT6", repo_root()), vec, reach)
    assert {"attr:INIT", "port:O", "port:I0", "port:I0:1"} <= got
    assert got - set(coverage_bins(load_entry("7series", "LUT6", repo_root()))) == {
        f"attr:INIT={lit}"
    }


def test_coverage_reach_keeps_polarity_renaming():
    vec = loads(
        "# xut-vec 2  prim=FDCE cfg=c nin=4 nout=1 nclk=1 settle_ps=120000 seed=0 "
        "attr.IS_CLR_INVERTED=1'b1\nclock  clk0  period=10000 phase=0 duty=50 mode=stepped\n"
        "t=121000 sample S0\n"
    )
    entry = load_entry("7series", "FDCE", repo_root())
    entry.ports = [dict(p, active="high") if p["name"] == "CLR" else p for p in entry.ports]
    reach = Reach(events={"CLR:fall"})  # the pin falls: an active-Low CLR asserts
    assert "port:CLR:assert" in coverage_reach(entry, vec, reach)
