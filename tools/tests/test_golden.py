# SPDX-License-Identifier: Apache-2.0
import importlib
import importlib.util
from pathlib import Path

import pytest

from xut.catalog.unisim import HdlModule, HdlParam, HdlPort
from xut.formats.xvec import loads
from xut.golden import replay
from xut.wrap import build_map, spec_from_hdl
from xut_models.base import Model, ModelUnsupported, Out, bit_attr

#: The TOYFF fixture's golden model lives in the fixture tree's ``_shared/toy`` package,
#: where the TOYFF cocotb test imports it inside the container: one definition for both.
TOY_SHARED = Path(__file__).parent / "fixtures/tests/7series/register/_shared/toy"
_spec = importlib.util.spec_from_file_location("toy_golden", TOY_SHARED / "toy_golden.py")
assert _spec is not None and _spec.loader is not None
_toy_golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_toy_golden)
ToyDff = _toy_golden.ToyDff


MAP = build_map(
    spec_from_hdl(
        HdlModule(
            "TOYFF",
            Path("x"),
            [HdlPort("Q", "output", 1), HdlPort("C", "input", 1), HdlPort("D", "input", 1)],
            [HdlParam("INIT", "bits", 1, 0)],
        ),
        "c",
        {"INIT": 1},  # validate() checks the header's attr.* against the map
    )
)
VEC = """\
# xut-vec 2  prim=TOYFF cfg=c nin=1 nout=1 nclk=1 settle_ps=120000 seed=0 attr.INIT=1'b1
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=120000 sample S0
t=121000 edge clk0 r
t=122000 sample S1
t=126000 edge clk0 f
t=127000 set in[0]=1
t=128000 edge clk0 r
t=129000 sample S2
"""


def test_replay_trace_and_reach():
    trace, reach = replay(ToyDff, loads(VEC), MAP)
    assert {k: v["Q"] for k, v in trace.samples.items()} == {"S0": "1", "S1": "0", "S2": "1"}
    assert trace.kind == "expected" and trace.prov["S2"]["Q"] == "doc:1"
    assert "claim:TOYFF.C1" in reach.bins() and "port:D" in reach.bins()
    assert "attr:INIT=1'b1" in reach.bins()


def test_simultaneous_events_are_refused():
    text = VEC.replace(
        "t=127000 set in[0]=1\nt=128000 edge clk0 r",
        "t=128000 simultaneous edge clk0 r\nt=128000 simultaneous set in[0]=1",
    )
    with pytest.raises(ModelUnsupported, match="simultaneous"):
        replay(ToyDff, loads(text), MAP)


def test_x_stimulus_is_unsupported():
    with pytest.raises(ModelUnsupported):
        replay(ToyDff, loads(VEC.replace("in[0]=1", "in[0]=0bx")), MAP)


def test_out_validates_provenance():
    with pytest.raises(ValueError):
        Out("1", "because")
    with pytest.raises(ValueError):
        Out("2", "doc:3")


def test_registry_imports_digit_package():
    assert importlib.import_module("xut_models.7series") is not None


# --- replay semantics ------------------------------------------------------------------


def test_gsr_released_before_first_event():
    # validate() forces settle_ps past ROC_WIDTH, so glbl.v's GSR release (100 ns) always
    # falls before the first event: power_on, inputs driven to 0, then GSR=0.
    calls = []

    class Rec(ToyDff):
        def power_on(self):
            calls.append("power_on")
            super().power_on()

        def set_input(self, port, value):
            calls.append(f"set {port}={value}")
            super().set_input(port, value)

        def glbl(self, signal, value):
            calls.append(f"glbl {signal}={value}")
            super().glbl(signal, value)

        def clock_edge(self, port, rising):
            calls.append(f"edge {port}")
            super().clock_edge(port, rising)

    replay(Rec, loads(VEC), MAP)
    assert calls[:4] == ["power_on", "set D=0", "glbl GSR=0", "edge C"]


def test_free_clock_edges_are_expanded():
    text = """\
# xut-vec 2  prim=TOYFF cfg=c nin=1 nout=1 nclk=1 settle_ps=101000 seed=0 attr.INIT=1'b1
clock clk0 period=10000 phase=2500 duty=50 mode=free
t=102000 set in[0]=1
t=114000 sample S0
t=115000 set in[0]=0
t=127000 sample S1
"""
    vec = loads(text)
    from xut.golden import expand_free_clocks

    edges = [e for e in expand_free_clocks(vec) if e.op == "edge"]
    assert all(e.target == "clk0" for e in edges)
    assert [(e.t, e.value) for e in edges[:3]] == [(2500, "r"), (7500, "f"), (12500, "r")]
    trace, reach = replay(ToyDff, vec, MAP)
    # rise at 112.5 ns captures D=1; rise at 122.5 ns captures D=0 (phase 2500: no edge
    # races glbl's GSR release at 100 ns)
    assert trace.samples["S0"]["Q"] == "1" and trace.samples["S1"]["Q"] == "0"
    assert "port:C" in reach.bins()


def test_unchanged_port_not_reached():
    text = VEC.replace("t=127000 set in[0]=1\n", "")
    _, reach = replay(ToyDff, loads(text), MAP)
    assert "port:D" not in reach.bins()


def test_invalid_stimulus_is_refused():
    from xut.golden import InvalidStimulus

    # sample 500 ps after a clock edge: closer than the 1 ns minimum sample gap
    text = VEC.replace("t=129000 sample S2", "t=128500 sample S2")
    with pytest.raises(InvalidStimulus, match="S2") as exc:
        replay(ToyDff, loads(text), MAP)
    assert "refusing to replay" in str(exc.value)


def test_hw_unrenderable_but_valid_stimulus_replays():
    from xut.validate import validate

    # D changes 500 ps before a free-clock edge: legal for simulation, hw_renderable no.
    text = """\
# xut-vec 2  prim=TOYFF cfg=c nin=1 nout=1 nclk=1 settle_ps=101000 seed=0 attr.INIT=1'b1
clock clk0 period=10000 phase=2500 duty=50 mode=free
t=112000 set in[0]=1
t=114000 sample S0
"""
    vec = loads(text)
    report = validate(vec, MAP)
    assert report.ok and not report.hw_renderable
    trace, _ = replay(ToyDff, vec, MAP)
    assert trace.samples["S0"]["Q"] == "1"


def test_trace_header():
    trace, _ = replay(ToyDff, loads(VEC), MAP)
    assert trace.header["model"] == "golden" and trace.header["prim"] == "TOYFF"
    assert trace.header["cfg"] == "c" and trace.header["seed"] == "0"


def test_prim_mismatch_is_loud():
    from xut.golden import InvalidStimulus

    with pytest.raises(InvalidStimulus, match="prim=OTHER"):
        replay(ToyDff, loads(VEC.replace("prim=TOYFF", "prim=OTHER")), MAP)

    class Other(ToyDff):
        PRIM = "OTHER"

    with pytest.raises(ValueError, match="primitive mismatch"):
        replay(Other, loads(VEC), MAP)


def test_model_inputs_must_match_map():
    class Wider(ToyDff):
        @classmethod
        def inputs(cls):
            return {"C": 1, "D": 2}

    with pytest.raises(ValueError, match="model inputs"):
        replay(Wider, loads(VEC), MAP)


def test_model_outputs_checked_against_declaration():
    class BadOut(ToyDff):
        def outputs(self):
            return {"Q": Out("10", "doc:1")}

    class Missing(ToyDff):
        def outputs(self):
            return {}

    with pytest.raises(ValueError, match="declared width"):
        replay(BadOut, loads(VEC), MAP)
    with pytest.raises(ValueError, match="OUTPUTS"):
        replay(Missing, loads(VEC), MAP)


def test_unmodelled_glbl_is_unsupported():
    class NoGlbl(ToyDff):
        glbl = Model.glbl

    with pytest.raises(ModelUnsupported, match="GSR"):
        replay(NoGlbl, loads(VEC), MAP)


# --- base API ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("v", "want"),
    [(1, 1), ("1", 1), ("1'b0", 0), ("1'b1", 1), ("4'hA", 10), ("8'b1010_0101", 0xA5)],
)
def test_bit_attr(v, want):
    assert bit_attr(v) == want


def test_out_accepts_dont_care_only_with_doc_provenance():
    """Ruling S14 (spec §5.3): a bit may be masked only where the documentation declares
    it undefined. Where the docs are silent the model gives a definite inferred value."""
    from xut_models.base import ModelContractError

    assert Out("1-0", "doc:12").bits == "1-0"
    assert Out("1", "inferred:clock-edge-during-GSR").bits == "1"
    with pytest.raises(ModelContractError, match="don't-care"):
        Out("1-0", "inferred:clock-edge-during-GSR")
    # per-bit (LSB = 0): bit 0 is '-' with doc:3; bit 1 is '-' with an inferred tag
    assert Out("1-", ("doc:3", "inferred:y")).bits == "1-"
    with pytest.raises(ModelContractError, match="bit 1"):
        Out("-1", ("doc:3", "inferred:y"))
    assert issubclass(ModelContractError, ValueError)
    with pytest.raises(ValueError):
        Out("", "doc:1")
    with pytest.raises(ValueError):
        Out("x", "doc:1")
    with pytest.raises(ValueError):
        Out("1", "inferred:a=b")


# --- registry ----------------------------------------------------------------------------


@pytest.fixture
def fake_family(tmp_path, monkeypatch):
    import xut_models

    fam = tmp_path / "fakefam"
    fam.mkdir()
    (fam / "__init__.py").write_text("")
    (fam / "toyff.py").write_text(
        "from xut_models.base import Model\nclass M(Model):\n    PRIM = 'TOYFF'\nMODEL = M\n"
    )
    (fam / "wrongprim.py").write_text("from xut_models.base import Model\nMODEL = int\n")
    (fam / "broken.py").write_text("import xut_models.no_such_helper\n")
    monkeypatch.setattr(xut_models, "__path__", [*xut_models.__path__, str(tmp_path)])
    yield "fakefam"
    import sys

    for k in [k for k in sys.modules if k.startswith("xut_models.fakefam")]:
        del sys.modules[k]


def test_registry_get(fake_family):
    from xut_models import registry

    assert registry.get(fake_family, "TOYFF").PRIM == "TOYFF"
    with pytest.raises(LookupError, match="no golden model"):
        registry.get(fake_family, "NOPE")
    with pytest.raises(LookupError, match="no golden model"):
        registry.get("nofamily", "TOYFF")
    with pytest.raises(LookupError, match="is not a WRONGPRIM Model"):
        registry.get(fake_family, "WRONGPRIM")
    # A missing import inside an existing model is a bug, not "no model".
    with pytest.raises(ModuleNotFoundError, match="no_such_helper"):
        registry.get(fake_family, "BROKEN")


def test_models_are_stdlib_only():
    import ast
    import sys

    root = Path(__file__).resolve().parents[2] / "models" / "xut_models"
    files = sorted(root.rglob("*.py"))
    assert files
    for f in files:
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for n in names:
                top = n.split(".")[0]
                assert top == "xut_models" or top in sys.stdlib_module_names, (f, n)


# --- co-timed input changes (Ruling S6) -------------------------------------------------
#
# Invariant: the only unmarked events that may share a time are `set`s on disjoint bits,
# which Ruling S6 makes ONE atomic input change (e.g. VecBuilder.set(D=1, CE=1)); validate's
# lonely rule keeps every edge, glbl and async/gate set alone at its time, and no sample
# shares its time with a change. replay therefore applies all of a time step's sets before
# calling set_input, so no edge or sample can observe an intermediate state and the file
# order of the sets cannot change the trace.


class ToyDffCe(Model):
    PRIM = "TOYFFCE"
    CLOCKS = ("C",)
    OUTPUTS = {"Q": 1}

    @classmethod
    def inputs(cls):
        return {"C": 1, "CE": 1, "D": 1}

    def __init__(self, attrs):
        super().__init__(attrs)
        self.log = []
        type(self).last = self

    def power_on(self):
        self.q, self.gsr, self.ce, self.d = 0, 1, 0, 0

    def set_input(self, port, value):
        setattr(self, port.lower(), value)
        self.log.append(("set", port, value))

    def clock_edge(self, port, rising):
        self.log.append(("edge", rising, self.ce, self.d))
        if rising and not self.gsr and self.ce:
            self.q = self.d

    def glbl(self, signal, value):
        self.gsr = value

    def outputs(self):
        self.log.append(("sample", self.ce, self.d))
        return {"Q": Out(str(self.q), "doc:1")}


MAP_CE = build_map(
    spec_from_hdl(
        HdlModule(
            "TOYFFCE",
            Path("x"),
            [
                HdlPort("Q", "output", 1),
                HdlPort("C", "input", 1),
                HdlPort("CE", "input", 1),
                HdlPort("D", "input", 1),
            ],
            [],
        ),
        "c",
        {},
    )
)
VEC_CE = """\
# xut-vec 2  prim=TOYFFCE cfg=c nin=2 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=120000 sample S0
{sets}
t=128000 edge clk0 r
t=129000 sample S1
t=133000 edge clk0 f
t=134000 sample S2
"""
CE, D = "t={t} set in[0]=1", "t={t} set in[1]=1"  # in[0]=CE, in[1]=D (map order)


def _run_ce(sets):
    trace, _ = replay(ToyDffCe, loads(VEC_CE.format(sets="\n".join(sets))), MAP_CE)
    return trace, ToyDffCe.last.log


def test_cotimed_disjoint_sets_are_one_atomic_change():
    assert [b.port for b in MAP_CE.of("in")] == ["CE", "D"]
    trace, log = _run_ce([CE.format(t=127000), D.format(t=127000)])
    assert trace.samples["S1"]["Q"] == "1"
    # both inputs reach the model back to back, before the edge
    i = log.index(("set", "CE", 1))
    assert log[i : i + 3] == [("set", "CE", 1), ("set", "D", 1), ("edge", True, 1, 1)]
    # no edge or sample ever observed CE=1 with D=0 (or CE=0 with D=1)
    observed = [entry[-2:] for entry in log if entry[0] in ("edge", "sample")]
    assert (1, 0) not in observed and (0, 1) not in observed


def test_cotimed_sets_are_order_independent():
    a, log_a = _run_ce([CE.format(t=127000), D.format(t=127000)])
    b, log_b = _run_ce([D.format(t=127000), CE.format(t=127000)])
    split, _ = _run_ce([CE.format(t=126000), D.format(t=127000)])
    assert a.samples == b.samples == split.samples
    assert a.prov == b.prov == split.prov
    assert log_a == log_b  # set_input calls follow map order, not file order


def test_cotimed_sets_via_builder():
    from xut.stimgen import VecBuilder

    vb = VecBuilder(MAP_CE, seed=0)
    vb.sample()  # S0; labels are unique, so let the builder number them
    vb.set(D=1, CE=1)
    vb.cycle()
    vec = vb.build()
    changes = [e for e in vec.events if e.op == "set"]
    assert len({e.t for e in changes}) == 1 and len(changes) == 2  # co-timed, unmarked
    assert not any(e.simultaneous for e in changes)
    trace, _ = replay(ToyDffCe, vec, MAP_CE)
    assert trace.samples["S0"]["Q"] == "0" and "1" in {v["Q"] for v in trace.samples.values()}
    assert ("edge", True, 1, 1) in ToyDffCe.last.log


def test_cotimed_sets_on_one_wide_port_arrive_as_one_value():
    # Two co-timed disjoint sets on bits of ONE port: the model gets a single set_input
    # with the final value, never the intermediate 0b01 or 0b10.
    calls = []

    class Wide(Model):
        PRIM = "TOYW"
        OUTPUTS = {"Q": 1}

        @classmethod
        def inputs(cls):
            return {"D": 2}

        def power_on(self):
            pass

        def set_input(self, port, value):
            calls.append((port, value))

        def clock_edge(self, port, rising):
            pass

        def glbl(self, signal, value):
            pass

        def outputs(self):
            return {"Q": Out("0", "doc:1")}

    m = build_map(
        spec_from_hdl(
            HdlModule("TOYW", Path("x"), [HdlPort("Q", "output", 1), HdlPort("D", "input", 2)], []),
            "c",
            {},
        )
    )
    text = """\
# xut-vec 2  prim=TOYW cfg=c nin=2 nout=1 nclk=0 settle_ps=120000 seed=0
t=121000 set in[1]=1
t=121000 set in[0]=1
t=122000 sample S0
"""
    replay(Wide, loads(text), m)
    assert calls == [("D", 0), ("D", 3)]


# --- per-bit provenance ------------------------------------------------------------------


def test_per_bit_provenance_written_to_trace():
    from xut.formats.xtr import dumps
    from xut.formats.xtr import loads as xtr_loads
    from xut.golden import bit_prov

    class Mixed(ToyDff):
        OUTPUTS = {"Q": 1, "W": 3}

        def outputs(self):
            # W[2] undefined by the docs (-), W[1] documented, W[0] inferred; Q documented
            w = Out("-" + "0" + str(self.q), ("inferred:doc_silent", "doc:8", "doc:7"))
            return {"Q": Out(str(self.q), "doc:1"), "W": w}

    trace, _ = replay(Mixed, loads(VEC), MAP)
    token = trace.prov["S2"]["W"]
    assert trace.samples["S2"]["W"] == "-01"
    assert [bit_prov(token, i) for i in range(3)] == ["inferred:doc_silent", "doc:8", "doc:7"]
    assert bit_prov(trace.prov["S2"]["Q"], 0) == "doc:1"
    assert xtr_loads(dumps(trace)).prov == trace.prov  # round-trips through .xtr


def test_uniform_per_bit_provenance_collapses():
    class Same(ToyDff):
        def outputs(self):
            return {"Q": Out(str(self.q), ("doc:1",))}

    trace, _ = replay(Same, loads(VEC), MAP)
    assert trace.prov["S2"]["Q"] == "doc:1"


def test_per_bit_provenance_validated():
    with pytest.raises(ValueError, match="2 tags for 3 bits"):
        Out("01-", ("doc:1", "doc:2"))
    with pytest.raises(ValueError):
        Out("01", ("doc:1", "because"))
    with pytest.raises(ValueError):
        Out("0", ["doc:1"])
    with pytest.raises(ValueError):
        Out("0", "inferred:a,b")  # ',' separates per-bit tags in .xtr
    with pytest.raises(ValueError):
        Out("0", "inferred:has space")


# --- ruling S14: an inferred don't-care is refused at replay ------------------------------


def test_replay_refuses_an_inferred_dont_care():
    """PR B gate (b) #4: a model returning Out("-", "inferred:...") masked every output
    and gave a vacuous pass; now replay errors."""
    from xut_models.base import ModelContractError

    class Masking(ToyDff):
        def outputs(self):
            return {"Q": Out("-", "inferred:whatever")}

    with pytest.raises(ModelContractError, match="don't-care"):
        replay(Masking, loads(VEC), MAP)


def test_replay_model_contract_errors_are_named():
    from xut_models.base import ModelContractError

    class Wrong(ToyDff):
        OUTPUTS = {"Q": 2}

    with pytest.raises(ModelContractError):
        replay(Wrong, loads(VEC), MAP)


# --- port x class events (ruling S19) --------------------------------------------------


def _map(*ports):
    from xut.wrap import DutSpec, PortSpec

    return build_map(DutSpec("TOYX", "7series", "c", tuple(PortSpec(*p) for p in ports), ()))


def test_replay_reports_data_and_clock_events():
    _, reach = replay(ToyDff, loads(VEC), MAP)
    assert {"port:C:edge", "port:D:1"} <= reach.bins()
    assert "port:D:0" not in reach.bins()  # never written by a set


def test_data_events_per_bit_of_a_multi_bit_port():
    from xut.formats.xvec import Event
    from xut.golden import _data_events

    m = _map(("D", "input", 2, "data"), ("E", "input", 1, "data"), ("R", "input", 1, "async"))
    ev = Event(t=1, op="set", target="in", lsb=0, value="101")
    assert _data_events(m, ev) == {"D[0]:1", "D[1]:0", "E:1"}  # R is not data


def test_stimulus_events_async_and_inout():
    from xut.golden import _stimulus_events

    m = _map(("R", "input", 1, "async"), ("IO", "inout", 1, "inout"))
    pos = {(b.port, b.role): b.bit for b in m.of("in")}
    r, en, val = pos[("R", "")], pos[("IO", "drive_en")], pos[("IO", "drive_val")]

    def bits(**v):
        out = ["0"] * m.nin
        for k, x in v.items():
            out[{"r": r, "en": en, "val": val}[k]] = x
        return out

    assert _stimulus_events(m, bits(), bits(r="1")) == {"R:rise"}
    assert _stimulus_events(m, bits(r="1"), bits()) == {"R:fall"}
    assert _stimulus_events(m, bits(), bits(en="1", val="1")) == {"IO:drive1"}
    assert _stimulus_events(m, bits(en="1", val="1"), bits(en="1")) == {"IO:drive0"}
    assert _stimulus_events(m, bits(en="1"), bits()) == {"IO:release"}
    assert _stimulus_events(m, bits(), bits(val="1")) == set()  # not driven


def test_polarity_bins():
    from xut.golden import polarity_bins

    bins = {"port:CLR:rise", "port:CLR:fall", "port:G[1]:rise", "port:X:rise", "port:D:1"}
    active = {"CLR": "high", "G": "low"}
    assert polarity_bins(bins, active, {}) == {
        "port:CLR:assert",
        "port:CLR:release",
        "port:G[1]:release",
        "port:X:rise",
        "port:D:1",
    }
    # IS_CLR_INVERTED=1: the primitive sees a falling pin as its (high) active edge
    assert polarity_bins({"port:CLR:fall"}, active, {"IS_CLR_INVERTED": "1'b1"}) == {
        "port:CLR:assert"
    }
    assert polarity_bins({"port:CLR:fall"}, active, {"IS_CLR_INVERTED": "1'b0"}) == {
        "port:CLR:release"
    }
