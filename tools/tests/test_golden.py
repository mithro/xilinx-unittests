# SPDX-License-Identifier: Apache-2.0
import importlib
from pathlib import Path

import pytest

from xut.catalog.unisim import HdlModule, HdlPort
from xut.formats.xvec import loads
from xut.golden import replay
from xut.wrap import build_map, spec_from_hdl
from xut_models.base import Model, ModelUnsupported, Out, bit_attr


class ToyDff(Model):
    PRIM = "TOYFF"
    CLOCKS = ("C",)
    OUTPUTS = {"Q": 1}

    @classmethod
    def inputs(cls):
        return {"C": 1, "D": 1}

    def power_on(self):
        self.q, self.gsr = bit_attr(self.attrs.get("INIT", 0)), 1

    def set_input(self, port, value):
        setattr(self, port.lower(), value)

    def clock_edge(self, port, rising):
        if rising and not self.gsr:
            self.q = self.d
            self.hit("TOYFF.C1")

    def glbl(self, signal, value):
        self.gsr = value

    def outputs(self):
        return {"Q": Out(str(self.q), "doc:1")}


MAP = build_map(
    spec_from_hdl(
        HdlModule(
            "TOYFF",
            Path("x"),
            [HdlPort("Q", "output", 1), HdlPort("C", "input", 1), HdlPort("D", "input", 1)],
            [],
        ),
        "c",
        {},
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
# xut-vec 2  prim=TOYFF cfg=c nin=1 nout=1 nclk=1 settle_ps=101000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=free
t=102000 set in[0]=1
t=112000 sample S0
t=113000 set in[0]=0
t=127000 sample S1
"""
    vec = loads(text)
    from xut.golden import expand_free_clocks

    edges = [e for e in expand_free_clocks(vec) if e.op == "edge"]
    assert all(e.target == "clk0" for e in edges)
    assert [(e.t, e.value) for e in edges[:3]] == [(0, "r"), (5000, "f"), (10000, "r")]
    trace, reach = replay(ToyDff, vec, MAP)
    # rise at 110 ns captures D=1; rise at 120 ns captures D=0
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
# xut-vec 2  prim=TOYFF cfg=c nin=1 nout=1 nclk=1 settle_ps=101000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=free
t=109500 set in[0]=1
t=112000 sample S0
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


def test_out_accepts_dont_care_and_inferred():
    assert Out("1-0", "inferred:clock-edge-during-GSR").bits == "1-0"
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
