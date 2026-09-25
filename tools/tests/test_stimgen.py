# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.catalog.model import load_entry
from xut.formats.xvec import dumps, loads
from xut.paths import repo_root
from xut.stimgen import BuilderError, GenContext, VecBuilder
from xut.validate import validate
from xut.wrap import build_map, spec_from_catalog


def _b(prim="FDCE", **kw):
    # raw_clock_out: BUFGCTRL (two clocks, gate/async inputs) drives a clock_out port
    entry = load_entry("7series", prim, repo_root())
    m = build_map(spec_from_catalog(entry, "c", {}, raw_clock_out=True))
    return VecBuilder(m, seed=3, **kw), m


def _check(b, m):
    """Every builder output parses back unchanged and has no validation errors."""
    v = b.build()
    assert loads(dumps(v)) == v
    r = validate(v, m)
    assert r.errors == []
    return v, r


def test_cycle_timeline():
    b, m = _b("FDRE")
    b.set(CE=1, D=1)
    b.cycle()
    ev = [(e.t, e.op, e.target, e.value) for e in b.build().events]
    assert ev[:6] == [
        (120000, "set", "in", "1"),
        (120000, "set", "in", "1"),
        (121000, "edge", "clk0", "r"),
        (122000, "sample", "S0", ""),
        (126000, "edge", "clk0", "f"),
        (127000, "sample", "S1", ""),
    ]


def test_every_builder_output_validates():
    b, m = _b()
    b.init(CLR=0)
    b.set(CE=1, D=1)
    b.cycle()
    b.async_("CLR", 1)
    b.sample()
    b.async_("CLR", 0)
    b.glbl("GSR", 1)
    b.sample()
    b.glbl("GSR", 0)
    b.cycle(n=3)
    with b.simultaneous():
        b.edge("C", True)
        b.async_("CLR", 1)
    b.sample()
    v = b.build()
    r = validate(v, m)
    assert r.errors == []
    assert not r.hw_renderable
    assert loads(dumps(v)) == v


def test_hw_recipe_is_hw_renderable():
    b, m = _b()
    b.set(CE=1, D=1)
    b.cycle(n=2)
    b.async_("CLR", 1)
    b.sample()
    b.async_("CLR", 0)
    b.set(D=0)
    b.cycle()
    b.glbl("GSR", 1)
    b.sample()
    b.glbl("GSR", 0)
    b.wait(3000)
    b.sample("final")
    _, r = _check(b, m)
    assert r.hw_renderable, r.hw_reasons


def test_async_right_after_an_edge_keeps_its_separation():
    b, m = _b(async_sep_ps=2500)
    b.cycle(sample=False)
    b.edge("C", True)
    b.async_("CLR", 1)
    b.edge("C", False)
    v, _ = _check(b, m)
    ts = [(e.t, e.op) for e in v.events if e.op in ("edge", "set")]
    assert ts[-3:] == [(130000, "edge"), (132500, "set"), (135000, "edge")]


def test_set_refuses_async_ports():
    b, _ = _b()
    with pytest.raises(BuilderError, match="async_"):
        b.set(CLR=1)


def test_unknown_port():
    b, _ = _b()
    with pytest.raises(BuilderError, match="no in_vec port"):
        b.set(Q=1)


def test_same_port_twice_moves_later():
    b, m = _b()
    b.set(D=1, CE=1)
    b.set(D=0)
    v, _ = _check(b, m)
    assert [(e.t, e.lsb, e.value) for e in v.events if e.op == "set"] == [
        (120000, 2, "1"),
        (120000, 0, "1"),
        (121000, 2, "0"),
    ]


def test_same_port_twice_in_one_instant_is_refused():
    b, _ = _b()
    with pytest.raises(BuilderError, match="twice"), b.simultaneous():
        b.async_("CLR", 1)
        b.async_("CLR", 0)


def test_disjoint_sets_share_a_time():
    b, m = _b()
    b.set(CE=1)
    b.set(D=1)
    v, _ = _check(b, m)
    assert [e.t for e in v.events if e.op == "set"] == [120000, 120000]


def test_edges_must_alternate():
    b, _ = _b()
    with pytest.raises(BuilderError, match="alternate"):
        b.edge("C", False)
    b.edge("C", True)
    with pytest.raises(BuilderError, match="alternate"):
        b.edge("C", True)


def test_simultaneous_needs_two_events():
    b, _ = _b()
    with pytest.raises(BuilderError, match="at least two"), b.simultaneous():
        b.edge("C", True)


def test_simultaneous_refuses_sample_and_time():
    b, _ = _b()
    for fn in (b.sample, lambda: b.wait(10), b.cycle):
        with pytest.raises(BuilderError, match="simultaneous"), b.simultaneous():
            fn()


def test_value_tracks_inputs():
    b, _ = _b()
    b.init(CLR=1)
    b.set(D=1)
    assert (b.value("CLR"), b.value("D"), b.value("CE")) == (1, 1, 0)


def test_init_after_timed_event_is_refused():
    b, _ = _b()
    b.set(D=1)
    with pytest.raises(BuilderError, match="init"):
        b.init(CE=1)


@pytest.mark.parametrize(
    "kw,msg",
    [
        ({"gap_ps": 999}, "gap_ps=999 is below"),
        ({"async_sep_ps": 500}, "async_sep_ps=500 is below"),
        ({"settle_ps": 100_000}, "settle_ps"),
    ],
)
def test_spacing_below_the_validator_minimum_is_refused(kw, msg):
    with pytest.raises(BuilderError, match=msg):
        _b(**kw)


def test_separation_is_recorded_and_used_by_validate():
    import dataclasses

    from xut.validate import MIN_SEP_PS

    b, m = _b(async_sep_ps=2500)
    b.edge("C", True)
    b.async_("CLR", 1)
    v, _ = _check(b, m)
    assert v.header["async_sep_ps"] == "2500" and MIN_SEP_PS == 1000
    # Moving the async change to 1500 ps after the edge breaks the recorded separation.
    v.events = [dataclasses.replace(e, t=e.t - 1000) if e.op == "set" else e for e in v.events]
    assert any("async_sep_ps=2500" in e for e in validate(v, m).errors)


def test_period_too_short():
    with pytest.raises(BuilderError, match="period"):
        _b(period_ps=4000)


def test_header_carries_attrs_and_seed():
    m = build_map(spec_from_catalog(load_entry("7series", "FDRE", repo_root()), "i1", {"INIT": 1}))
    v = VecBuilder(m, seed=9).build()
    assert v.attrs == {"INIT": "1'b1"} and v.seed == 9 and v.events[-1].op == "end"


def test_gencontext_records_specs():
    ctx = GenContext("7series", "FDRE", seed=5)
    b = ctx.dut("init1", INIT=1)
    assert "init1" in ctx.specs and b.build().cfg == "init1"
    with pytest.raises(BuilderError, match="twice"):
        ctx.dut("init1", INIT=0)
    assert ctx.rng.random() == GenContext("7series", "FDRE", seed=5).rng.random()


@pytest.mark.parametrize("prim", ["FDCE", "FDPE", "FDRE", "BUFGCTRL", "FIFO18E1", "SRLC32E"])
@pytest.mark.parametrize("seed", range(20))
def test_random_builder_programs_validate(prim, seed):
    """Review Focus 3: whatever sequence of calls a generator makes, the builder's
    output parses back unchanged and validates with no errors; and it is hardware
    renderable exactly when no simultaneous() group was used (Ruling S8)."""
    import random

    rng = random.Random(seed)
    b, m = _b(prim)
    data = [p for p in m.in_ports() if m.cls_of(p) not in ("async", "gate")]
    asyncs = [p for p in m.in_ports() if m.cls_of(p) in ("async", "gate")]
    clocks = list(dict.fromkeys(bit.port for bit in m.of("clk")))
    level = dict.fromkeys(clocks, False)
    width = {p: len(m.port_bits("in", p)) for p in m.in_ports()}

    def rand(p):
        return rng.randrange(1 << width[p])  # multi-bit data values (FIFO18E1.DI, SRLC32E.A)

    b.init(**{p: rand(p) for p in rng.sample(m.in_ports(), rng.randint(0, len(m.in_ports())))})
    used_sim = False
    for _ in range(40):
        op = rng.choice(["set", "async", "cycle", "edge", "sample", "wait", "glbl", "sim"])
        if op == "set" and data:
            b.set(**{p: rand(p) for p in rng.sample(data, rng.randint(1, len(data)))})
        elif op == "async" and asyncs:
            p = rng.choice(asyncs)
            b.async_(p, 1 - b.value(p))
        elif op == "cycle" and clocks:
            c = rng.choice(clocks)
            if not level[c]:
                b.cycle(c, n=rng.randint(1, 2), sample=rng.random() < 0.5)
        elif op == "edge" and clocks:
            c = rng.choice(clocks)
            level[c] = not level[c]
            b.edge(c, level[c])
        elif op == "sample":
            b.sample()
        elif op == "wait":
            b.wait(rng.randint(0, 3000))
        elif op == "glbl":
            b.glbl("GSR", rng.randint(0, 1))
        elif op == "sim" and clocks and asyncs:
            c, p = rng.choice(clocks), rng.choice(asyncs)
            level[c] = not level[c]
            used_sim = True
            with b.simultaneous():
                b.edge(c, level[c])
                b.async_(p, 1 - b.value(p))
    _, r = _check(b, m)
    assert r.hw_renderable == (not used_sim), r.hw_reasons


def test_glbl_is_spaced_like_async():
    b, m = _b(async_sep_ps=2500)
    b.edge("C", True)
    b.glbl("GSR", 1)
    b.edge("C", False)
    b.async_("CLR", 1)
    b.glbl("GSR", 0)
    v, r = _check(b, m)
    assert r.hw_renderable
    ts = [(e.t, e.op) for e in v.events if e.op != "end"]
    assert ts == [
        (120000, "edge"),
        (122500, "glbl"),
        (125000, "edge"),
        (127500, "set"),
        (130000, "glbl"),
    ]


# --- A2: the builder refuses a label the format cannot hold, at the call


@pytest.mark.parametrize("label", ["bad label", "S#1", "a|b", ""])
def test_sample_refuses_bad_labels_at_call_time(label):
    b, _ = _b()
    with pytest.raises(BuilderError, match="label"):
        b.sample(label)


def test_sample_refuses_duplicate_labels():
    b, _ = _b()
    b.sample("S0")
    with pytest.raises(BuilderError, match="duplicate"):
        b.sample("S0")
    b2, _ = _b()
    b2.sample("S1")
    with pytest.raises(BuilderError, match="duplicate"):  # the auto label S1 is taken
        b2.sample()
        b2.sample()
