# SPDX-License-Identifier: Apache-2.0
import json
import shutil
from pathlib import Path

import pytest

from xut.container import SIM_IMAGE, DockerExecutor, image_digest
from xut.errors import XutError
from xut.formats.xvec import free_clock_edges, loads
from xut.paths import repo_root
from xut.stimcompile import OPS, TB, compile_vec, raw_to_trace, write_stim
from xut.wrap import Bit, DutMap

FIX = Path(__file__).parent / "fixtures" / "tb"

M = DutMap(
    "TOY",
    "7series",
    "c",
    {},
    1,
    3,
    1,
    [
        Bit("clk", 0, "C", 0, "clock"),
        Bit("in", 0, "D", 0, "data"),
        Bit("in", 1, "CLR", 0, "async"),
        Bit("in", 2, "U", 0, "data"),
        Bit("out", 0, "Q", 0, "data"),
    ],
)
VEC = loads("""\
# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=120000 sample S0
t=121000 set in[2:0]=0b0x1
t=122000 edge clk0 r
t=123000 sample S1
t=125000 set in[1]=1
t=127000 sample S2
t=128000 end
""")


def _decode(w):
    return (w >> 120, (w >> 96) & 0xFFFFFF, (w >> 64) & 0xFFFFFFFF, w & ((1 << 64) - 1))


def test_words():
    c = compile_vec(VEC, M)
    assert c.labels == ["S0", "S1", "S2"]
    w = c.words
    assert w[0] == (4 << 120) | (0 << 96) | (0 << 64) | 120000  # SAMPLE 0
    assert w[1] == (1 << 120) | (0 << 96) | (1 << 64) | 121000  # in[0]=1
    assert w[2] == (1 << 120) | (1 << 96) | (2 << 64) | 121000  # in[1]=x
    assert w[3] == (1 << 120) | (2 << 96) | (0 << 64) | 121000  # in[2]=0
    assert w[4] == (2 << 120) | (0 << 96) | (1 << 64) | 122000  # EDGE r
    assert w[-1] >> 120 == 15


def test_free_clock_words():
    """compile_vec starts/stops the TB generator exactly where free_runs says, and the
    edges the TB then produces (rise at start, fall after high, one per period, none
    after a low-phase stop) are the free_clock_edges list; golden replays the same list."""
    from xut.formats.xvec import free_clock_edges, free_runs
    from xut.golden import expand_free_clocks

    v = loads("""\
# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=free
t=120000 clock_start clk0
t=137000 clock_stop clk0
t=150000 end
""")
    ((c, start, stop),) = free_runs(v)
    w = compile_vec(v, M).words
    ops = [(x >> 120, (x >> 96) & 0xFFFFFF, (x >> 64) & 0xFFFFFFFF, x & ((1 << 64) - 1)) for x in w]
    assert (5, 0, 5000, start) in ops and (6, 0, 5000, start) in ops  # CLK_HI, CLK_START
    assert (7, 0, 0, stop) in ops  # CLK_STOP
    assert [(e.t, e.value) for e in expand_free_clocks(v) if e.op == "edge"] == [
        (e.t, e.value) for e in free_clock_edges(v)
    ]


def test_raw_to_trace():
    t = raw_to_trace("S 0 1\nS 1 x\nS 2 0\n", ["S0", "S1", "S2"], M, {"runner": "iverilog"})
    assert {k: v["Q"] for k, v in t.samples.items()} == {"S0": "1", "S1": "x", "S2": "0"}


# --- compiler details beyond the brief --------------------------------------------------

FREE = """\
# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=@PHASE@ duty=30 mode=free
t=120000 sample S0
t=130500 end
"""


@pytest.mark.parametrize("phase", [0, 2500])
def test_implicit_free_clock_starts_at_phase(phase):
    """A free clock without clock_start runs from max(0, phase), like free_runs."""
    v = loads(FREE.replace("@PHASE@", str(phase)))
    ops = [_decode(w) for w in compile_vec(v, M).words]
    assert ops[:2] == [(5, 0, 3000, phase), (6, 0, 7000, phase)]  # high 30 %, low 70 %
    assert not any(op == OPS["clk_stop"] for op, *_ in ops)


def test_words_are_time_ordered_and_stable():
    v = loads("""\
# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=0 set in[2]=1
t=0 set in[0]=1
t=120000 set in[2]=0
t=120000 set in[0]=0
t=121000 sample A
""")
    ops = [_decode(w) for w in compile_vec(v, M).words]
    assert ops == [
        (1, 2, 1, 0),
        (1, 0, 1, 0),
        (1, 2, 0, 120000),
        (1, 0, 0, 120000),
        (4, 0, 0, 121000),
        (15, 0, 0, 122000),
    ]  # END appended 1 ns after


def test_write_stim(tmp_path):
    c = write_stim(VEC, M, tmp_path)
    lines = (tmp_path / "stim.memh").read_text().splitlines()
    assert [int(x, 16) for x in lines] == c.words and all(len(x) == 32 for x in lines)
    vh = (tmp_path / "stim.vh").read_text()
    assert vh.startswith("// SPDX-License-Identifier: Apache-2.0\n")
    assert f"`define XUT_MAXOPS {len(c.words)}\n" in vh
    assert json.loads((tmp_path / "labels.json").read_text()) == ["S0", "S1", "S2"]


def test_compile_refuses_a_stimulus_for_another_wrapper():
    other = DutMap("TOY", "7series", "c", {}, 1, 2, 1, M.bits[:3] + M.bits[4:])
    with pytest.raises(XutError, match="nin"):
        compile_vec(VEC, other)


def test_compile_refuses_a_malformed_in_memory_vec():
    v = loads(
        "# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0\n"
        "t=120000 sample S0\n"
    )
    v.events.append(v.events[0])  # duplicate label: the parser would refuse it
    with pytest.raises(XutError, match="duplicate label"):
        compile_vec(v, M)


def test_compile_refuses_a_free_clock_with_an_empty_phase():
    """period*duty//100 == 0 would make the TB generator spin at one time step."""
    v = loads(FREE.replace("@PHASE@", "0").replace("period=10000", "period=3"))
    with pytest.raises(XutError, match="high"):
        compile_vec(v, M)


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("S 3 1\n", "sample 3"),  # no such sample
        ("S 0 10\n", "width"),  # nout=1, two bits
        ("S 0 1\nS 0 1\n", "twice"),
        ("S 0 2\n", "bits"),
        ("hello\n", "line 1"),
    ],
)
def test_raw_to_trace_is_strict(raw, match):
    with pytest.raises(XutError, match=match):
        raw_to_trace(raw, ["S0"], M, {})


def test_raw_to_trace_maps_ports_msb_first():
    m = DutMap(
        "W",
        "7series",
        "c",
        {},
        0,
        1,
        4,
        [
            Bit("in", 0, "I", 0, "data"),
            Bit("out", 0, "A", 0, "data"),
            Bit("out", 1, "B", 0, "data"),
            Bit("out", 2, "B", 1, "data"),
            Bit("out", 3, "C", 0, "data"),
        ],
    )
    # out_vec = {C, B[1], B[0], A} printed MSB first
    t = raw_to_trace("S 0 1z0x\n", ["L"], m, {"runner": "r"})
    assert t.samples == {"L": {"A": "x", "B": "z0", "C": "1"}}
    assert t.header == {"runner": "r"}


def test_tb_source():
    text = TB.read_text()
    assert text.startswith("// SPDX-License-Identifier: Apache-2.0\n")
    assert "`ifdef XUT_GLBL_INSTANCE" in text and "glbl glbl ();" in text
    assert "$fatal" not in text


# --- the testbench in the xut-sim container ----------------------------------------------

needs_sim = [
    pytest.mark.container,
    pytest.mark.skipif(
        shutil.which("docker") is None or image_digest(SIM_IMAGE) is None,
        reason="xut-sim image not built",
    ),
]


@needs_sim[0]
@needs_sim[1]
def test_tb_replays_on_iverilog():
    work = repo_root() / "build" / "tbtest"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    write_stim(VEC, M, work)
    (work / "xut_cfg.vh").write_text("`define XUT_NCLK 1\n`define XUT_NIN 3\n`define XUT_NOUT 1\n")
    shutil.copy(Path(__file__).parent / "fixtures/tb/toy_dut.v", work / "toy_dut.v")
    shutil.copy(TB, work / "tb.sv")
    ex, log = DockerExecutor(), work / "run.log"
    assert (
        ex.run(
            [
                "iverilog",
                "-g2012",
                "-o",
                "sim.vvp",
                "-s",
                "xut_vector_tb",
                "-s",
                "glbl",
                "-I",
                ".",
                "tb.sv",
                "toy_dut.v",
            ],
            cwd=work,
            log=log,
            timeout_s=120,
        )
        == 0
    )
    assert ex.run(["vvp", "-n", "sim.vvp"], cwd=work, log=log, timeout_s=120) == 0
    assert "XUT_DONE" in log.read_text()
    t = raw_to_trace((work / "raw.txt").read_text(), ["S0", "S1", "S2"], M, {})
    # S0: GSR preset -> 1; S1: clocked D=1 -> 1; S2: async CLR -> 0
    assert {k: v["Q"] for k, v in t.samples.items()} == {"S0": "1", "S1": "1", "S2": "0"}


def _iverilog(work, vec, m, dut_files, *, ex=None, lib=(), defines=(), glbl_top=True):
    """Compile and run the vector testbench in ``work``; return (log text, raw.txt or None)."""
    ex = ex or DockerExecutor(root=work)
    write_stim(vec, m, work)
    if not (work / "xut_cfg.vh").is_file():
        (work / "xut_cfg.vh").write_text(
            f"`define XUT_NCLK {max(1, m.nclk)}\n`define XUT_NIN {max(1, m.nin)}\n"
            f"`define XUT_NOUT {max(1, m.nout)}\n"
        )
    shutil.copy(TB, work / "xut_vector_tb.sv")
    log = work / "run.log"
    tops = ["-s", "xut_vector_tb"] + (["-s", "glbl"] if glbl_top else [])
    argv = [
        "iverilog",
        "-g2012",
        "-o",
        "sim.vvp",
        *tops,
        "-I",
        ".",
        *lib,
        *[f"-D{d}" for d in defines],
        "xut_vector_tb.sv",
        *dut_files,
    ]
    assert ex.run(argv, cwd=work, log=log, timeout_s=300) == 0, log.read_text()
    assert ex.run(["vvp", "-n", "sim.vvp"], cwd=work, log=log, timeout_s=300) == 0, log.read_text()
    text = log.read_text()
    raw = work / "raw.txt"
    return text, raw.read_text() if raw.is_file() else None


PM = DutMap(
    "PROBE",
    "7series",
    "c",
    {},
    1,
    4,
    6,
    [Bit("clk", 0, "C", 0, "clock")]
    + [Bit("in", i, "I", i, "data") for i in range(4)]
    + [Bit("out", 0, "MID", 0, "data")]
    + [Bit("out", 1 + i, "CNT", i, "data") for i in range(3)]
    + [Bit("out", 4, "COMB", 0, "data"), Bit("out", 5, "CAP", 0, "data")],
)
PHDR = "# xut-vec 2  prim=PROBE cfg=c nin=4 nout=6 nclk=1 settle_ps=120000 seed=0\n"


def _probe(tmp_path, text, **kw):
    vec = loads(PHDR + text)
    shutil.copy(FIX / "probe_dut.v", tmp_path / "probe_dut.v")
    log, raw = _iverilog(tmp_path, vec, PM, ["probe_dut.v"], **kw)
    assert "XUT_DONE" in log, log
    labels = compile_vec(vec, PM).labels
    return vec, raw_to_trace(raw, labels, PM, {}).samples


@needs_sim[0]
@needs_sim[1]
def test_tb_time0_values_reach_waiting_processes(tmp_path):
    """UNISIM combinational models only react to input changes (Task 4): the time-0
    values must be applied once every DUT process waits, so an always @(in) block sees
    x -> 0 and its output is 0, not x. Both an explicit t=0 set and the implicit 0."""
    for sub, init in (("explicit", "t=0 set in[3:0]=0\n"), ("implicit", "")):
        work = tmp_path / sub
        work.mkdir()
        _, s = _probe(
            work,
            "clock clk0 period=10000 phase=0 duty=50 mode=stepped\n"
            + init
            + "t=120000 sample S0\n",
        )
        assert s["S0"]["COMB"] == "0", sub
        assert s["S0"]["MID"] == "0" and s["S0"]["CNT"] == "000"  # no clock edge at t=0


@needs_sim[0]
@needs_sim[1]
def test_tb_cotimed_sets_are_atomic(tmp_path):
    """Ruling S6: co-timed disjoint sets are one atomic input change. A process waiting
    on in_vec[1:0] never sees 01 or 10 on 00 <-> 11, whether the change is one line or
    two lines in either order."""
    _, s = _probe(
        tmp_path,
        """\
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=0 set in[1:0]=0
t=120000 set in[0]=1
t=120000 set in[1]=1
t=121000 sample A
t=122000 set in[1]=0
t=122000 set in[0]=0
t=123000 sample B
t=124000 set in[1:0]=3
t=125000 sample C
""",
    )
    assert [s[k]["MID"] for k in "ABC"] == ["0", "0", "0"]


@needs_sim[0]
@needs_sim[1]
def test_tb_simultaneous_edge_sees_new_data(tmp_path):
    """A `simultaneous` group is applied at one time step before the DUT wakes, so a
    rising edge captures the NEW data whatever the file order (golden replay refuses
    such groups; they are for sim-vs-sim checks only)."""
    for order in ("edge_first", "set_first"):
        work = tmp_path / order
        work.mkdir()
        edge, st = "t=121000 simultaneous edge clk0 r\n", "t=121000 simultaneous set in[3]=1\n"
        _, s = _probe(
            work,
            "clock clk0 period=10000 phase=0 duty=50 mode=stepped\n"
            "t=120000 sample S0\n"
            + (edge + st if order == "edge_first" else st + edge)
            + "t=122000 sample S1\n",
        )
        assert (s["S0"]["CAP"], s["S1"]["CAP"], s["S1"]["CNT"]) == ("0", "1", "001"), order


@needs_sim[0]
@needs_sim[1]
def test_tb_free_clock_matches_free_clock_edges(tmp_path):
    """The TB generator produces exactly the rises of xvec.free_clock_edges: start,
    stop in a low phase, restart; the data captured at each rise is the latest set."""
    vec, s = _probe(
        tmp_path,
        """\
clock clk0 period=10000 phase=0 duty=30 mode=free
t=120000 clock_start clk0
t=121000 set in[3]=1
t=124000 sample A
t=137000 clock_stop clk0
t=138000 sample B
t=141000 set in[3]=0
t=150000 sample C
t=160000 clock_start clk0
t=162000 sample D
t=175000 clock_stop clk0
t=176000 sample E
""",
    )
    edges = free_clock_edges(vec)
    for label, t in (("A", 124000), ("B", 138000), ("C", 150000), ("D", 162000), ("E", 176000)):
        rises = sum(1 for e in edges if e.value == "r" and e.t <= t)
        assert int(s[label]["CNT"], 2) == rises % 8, (label, rises, s[label])
    assert [s[k]["CAP"] for k in "ABCDE"] == ["0", "1", "1", "0", "0"]


@needs_sim[0]
@needs_sim[1]
def test_tb_glbl_instance_mode(tmp_path):
    """The XUT_GLBL_INSTANCE fallback (Verilator, Task 15): glbl is an instance inside
    the testbench, not a second top; the DUT's upward glbl.GSR and the testbench's
    glbl.GSR_int writes both resolve to it."""
    shutil.copy(FIX / "toy_dut.v", tmp_path / "toy_dut.v")
    vec = loads(VEC_GLBL)
    log, raw = _iverilog(
        tmp_path, vec, M, ["toy_dut.v"], defines=["XUT_GLBL_INSTANCE"], glbl_top=False
    )
    assert "XUT_DONE" in log
    t = raw_to_trace(raw, compile_vec(vec, M).labels, M, {})
    assert {k: v["Q"] for k, v in t.samples.items()} == {"S0": "1", "S1": "0", "S2": "1"}


VEC_GLBL = """\
# xut-vec 2  prim=TOY cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=120000 sample S0
t=121000 edge clk0 r
t=122000 sample S1
t=123000 glbl GSR=1
t=124000 glbl GSR=0
t=125000 sample S2
"""


@needs_sim[0]
@needs_sim[1]
def test_tb_glbl_channel(tmp_path):
    """glbl GSR writes from the stimulus reach glbl (second top) and the DUT."""
    shutil.copy(FIX / "toy_dut.v", tmp_path / "toy_dut.v")
    vec = loads(VEC_GLBL)
    log, raw = _iverilog(tmp_path, vec, M, ["toy_dut.v"])
    assert "XUT_DONE" in log
    t = raw_to_trace(raw, compile_vec(vec, M).labels, M, {})
    # S0 GSR preset; S1 clocked D=0; S2 a GSR pulse presets again
    assert {k: v["Q"] for k, v in t.samples.items()} == {"S0": "1", "S1": "0", "S2": "1"}


@needs_sim[0]
@needs_sim[1]
def test_tb_reports_a_missing_end(tmp_path):
    """Without END the testbench says so instead of printing XUT_DONE."""
    shutil.copy(FIX / "toy_dut.v", tmp_path / "toy_dut.v")
    write_stim(VEC, M, tmp_path)
    memh = tmp_path / "stim.memh"
    lines = memh.read_text().splitlines(keepends=True)[:-1]
    memh.write_text("".join(lines))
    (tmp_path / "stim.vh").write_text(f"`define XUT_MAXOPS {len(lines)}\n")
    (tmp_path / "xut_cfg.vh").write_text(
        "`define XUT_NCLK 1\n`define XUT_NIN 3\n`define XUT_NOUT 1\n"
    )
    shutil.copy(TB, tmp_path / "xut_vector_tb.sv")
    ex, log = DockerExecutor(root=tmp_path), tmp_path / "run.log"
    assert (
        ex.run(
            [
                "iverilog",
                "-g2012",
                "-o",
                "sim.vvp",
                "-s",
                "xut_vector_tb",
                "-s",
                "glbl",
                "-I",
                ".",
                "xut_vector_tb.sv",
                "toy_dut.v",
            ],
            tmp_path,
            log,
            120,
        )
        == 0
    )
    ex.run(["vvp", "-n", "sim.vvp"], tmp_path, log, 120)
    text = log.read_text()
    assert "XUT_DONE" not in text and "XUT_ERROR stimulus has no END operation" in text


# --- golden replay and the testbench agree (FDRE on real UNISIM) -------------------------


class _Fdre:
    """A test-local FDRE model (not a golden model: those live in models/xut_models and
    come from the flops unit). Q <- INIT while GSR; on a rising C: R -> 0, else CE -> D."""

    @staticmethod
    def cls():
        from xut_models.base import Model, Out, bit_attr

        class Fdre(Model):
            PRIM = "FDRE"
            CLOCKS = ("C",)
            OUTPUTS = {"Q": 1}

            @classmethod
            def inputs(cls):
                return {"C": 1, "CE": 1, "D": 1, "R": 1}

            def power_on(self):
                self.init = bit_attr(self.attrs.get("INIT", 0))
                self.q, self.gsr, self.ce, self.d, self.r = self.init, 1, 0, 0, 0

            def set_input(self, port, value):
                setattr(self, port.lower(), value)

            def clock_edge(self, port, rising):
                if rising and not self.gsr:
                    self.q = 0 if self.r else (self.d if self.ce else self.q)

            def glbl(self, signal, value):
                self.gsr = value
                if value:
                    self.q = self.init

            def outputs(self):
                return {"Q": Out(str(self.q), "inferred:test_model")}

        return Fdre


FDRE_STEPPED = """\
clock clk0 period=10000 phase=0 duty=50 mode=stepped
t=120000 sample S0
t=121000 set in[0]=1
t=121000 set in[1]=@D1@
t=122000 edge clk0 r
t=123000 sample S1
t=127000 edge clk0 f
t=128000 set in[1]=@D0@
t=128000 set in[0]=0
t=129000 edge clk0 r
t=130000 sample S2
t=131000 edge clk0 f
t=132000 set in[2:0]=0b101
t=133000 edge clk0 r
t=134000 sample S3
t=135000 edge clk0 f
t=136000 set in[2:0]=0b011
t=137000 edge clk0 r
t=138000 sample S4
t=139000 glbl GSR=1
t=140000 sample S5
t=141000 edge clk0 f
t=142000 set in[2:0]=0b010
t=143000 edge clk0 r
t=144000 sample S6
t=145000 glbl GSR=0
t=146000 sample S7
t=147000 edge clk0 f
t=149000 edge clk0 r
t=150000 sample S8
"""

FDRE_FREE = """\
clock clk0 period=10000 phase=0 duty=50 mode=free
t=120000 clock_start clk0
t=121000 set in[1:0]=0b@D1@1
t=124000 sample S0
t=131000 sample S1
t=132000 set in[1]=@D0@
t=137000 clock_stop clk0
t=138000 sample S2
t=160000 clock_start clk0
t=162000 sample S3
t=163000 set in[1]=@D1@
t=166000 set in[2]=1
t=172000 sample S4
t=173000 set in[2]=0
t=177000 clock_stop clk0
t=178000 sample S5
"""


@needs_sim[0]
@needs_sim[1]
@pytest.mark.parametrize("init", [0, 1])
@pytest.mark.parametrize("stim", ["stepped", "free"])
def test_tb_agrees_with_golden_replay_on_fdre(tmp_path, init, stim):
    """The same valid stimulus through golden replay and through the testbench on real
    UNISIM FDRE (Icarus, every model source) gives the same trace: co-timed CE/D sets,
    sync reset, a glbl GSR pulse, stepped and free-running clocks (start/stop/restart)."""
    from xut.catalog.model import load_entry
    from xut.formats.xtr import compare
    from xut.golden import replay
    from xut.modelsrc import model_sources
    from xut.validate import validate
    from xut.wrap import spec_from_catalog, write_dut

    srcs = list(model_sources().values())
    if not srcs:
        pytest.skip("no UNISIM model source (install Vivado 2025.2 or init the submodule)")
    cfg = f"init{init}"
    d1, d0 = str(1 - init), str(init)  # D values that move Q away from INIT and back
    body = (FDRE_STEPPED if stim == "stepped" else FDRE_FREE).replace("@D1@", d1)
    body = body.replace("@D0@", d0)
    vec = loads(
        f"# xut-vec 2  prim=FDRE cfg={cfg} nin=3 nout=1 nclk=1 settle_ps=120000 "
        f"seed=0 attr.INIT=1'b{init}\n" + body
    )
    spec = spec_from_catalog(
        load_entry("7series", "FDRE", repo_root()), cfg, {"INIT": f"1'b{init}"}
    )
    for src in srcs:
        from xut.container import Mount

        work = tmp_path / src.name
        m = write_dut(spec, work)
        report = validate(vec, m)
        assert report.ok, report.errors
        expected, _ = replay(_Fdre.cls(), vec, m)
        assert len(set(v["Q"] for v in expected.samples.values())) == 2  # Q really moves
        ex = DockerExecutor(root=work, mounts=(Mount(src.src.resolve(), f"/models/{src.name}"),))
        lib = [a for p in src.search for a in ("-y", ex.guest(p))] + ["-Y", ".v"]
        log, raw = _iverilog(work, vec, m, ["xut_dut.v", ex.guest(src.glbl)], ex=ex, lib=lib)
        assert "XUT_DONE" in log, log
        actual = raw_to_trace(raw, compile_vec(vec, m).labels, m, {"runner": "iverilog"})
        assert list(actual.samples) == list(expected.samples)
        assert compare(expected, actual) == [], (src.name, actual.samples, expected.samples)


@needs_sim[0]
@needs_sim[1]
@pytest.mark.parametrize(
    ("init_line", "o"),
    [("", "1"), ("t=0 set in[5:0]=0x3f\n", "1"), ("t=0 set in[5:0]=0x01\n", "0")],
)
def test_tb_time0_values_define_unisim_lut6(tmp_path, init_line, o):
    """UNISIM LUT6 (combinational) is defined at the first sample from the time-0 values
    alone, including the implicit all-zero inputs: no later input change is needed."""
    from xut.catalog.model import load_entry
    from xut.container import Mount
    from xut.modelsrc import model_sources
    from xut.wrap import spec_from_catalog, write_dut

    srcs = list(model_sources().values())
    if not srcs:
        pytest.skip("no UNISIM model source (install Vivado 2025.2 or init the submodule)")
    lit = "64'h8000000000000001"
    spec = spec_from_catalog(load_entry("7series", "LUT6", repo_root()), "c", {"INIT": lit})
    vec = loads(
        f"# xut-vec 2  prim=LUT6 cfg=c nin=6 nout=1 nclk=0 settle_ps=120000 seed=0 "
        f"attr.INIT={lit}\n" + init_line + "t=120000 sample S0\n"
    )
    for src in srcs:
        work = tmp_path / src.name
        m = write_dut(spec, work)
        ex = DockerExecutor(root=work, mounts=(Mount(src.src.resolve(), f"/models/{src.name}"),))
        lib = [a for p in src.search for a in ("-y", ex.guest(p))] + ["-Y", ".v"]
        log, raw = _iverilog(work, vec, m, ["xut_dut.v", ex.guest(src.glbl)], ex=ex, lib=lib)
        assert "XUT_DONE" in log, log
        assert raw_to_trace(raw, ["S0"], m, {}).samples == {"S0": {"O": o}}, src.name


# --- the same testbench on Verilator (portability; the runner itself is Task 15) ---------

PROBE_FREE = """\
clock clk0 period=10000 phase=0 duty=30 mode=free
t=120000 clock_start clk0
t=121000 set in[0]=1
t=121000 set in[1]=1
t=121000 set in[3]=1
t=124000 sample A
t=137000 clock_stop clk0
t=138000 sample B
t=141000 set in[3]=0
t=150000 sample C
t=160000 clock_start clk0
t=162000 sample D
t=175000 clock_stop clk0
t=176000 sample E
"""


def _verilator(work, vec, m, dut_files, *, glbl_instance):
    ex = DockerExecutor(root=work)
    write_stim(vec, m, work)
    (work / "xut_cfg.vh").write_text(
        f"`define XUT_NCLK {max(1, m.nclk)}\n`define XUT_NIN {max(1, m.nin)}\n"
        f"`define XUT_NOUT {max(1, m.nout)}\n"
    )
    shutil.copy(TB, work / "xut_vector_tb.sv")
    log = work / "run.log"
    mode = ["-DXUT_GLBL_INSTANCE", "--top-module", "xut_vector_tb"] if glbl_instance else []
    argv = [
        "verilator",
        "--binary",
        "--timing",
        "-Wno-fatal",
        "-I.",
        *mode,
        "-o",
        "simx",
        "xut_vector_tb.sv",
        *dut_files,
    ]
    assert ex.run(argv, cwd=work, log=log, timeout_s=600) == 0, log.read_text()
    assert ex.run(["./obj_dir/simx"], cwd=work, log=log, timeout_s=120) == 0, log.read_text()
    text = log.read_text()
    assert text.count("XUT_DONE") == 1 and "XUT_ERROR" not in text, text
    return raw_to_trace((work / "raw.txt").read_text(), compile_vec(vec, m).labels, m, {})


@needs_sim[0]
@needs_sim[1]
@pytest.mark.parametrize("glbl_instance", [False, True], ids=["glbl_top", "glbl_instance"])
def test_tb_on_verilator_matches_icarus(tmp_path, glbl_instance):
    """The testbench builds and runs on Verilator 5.048 --timing, with glbl as a second
    top or (XUT_GLBL_INSTANCE) inside the testbench, and gives Icarus's samples: free
    clock start/stop/restart, co-timed sets, the time-0 barrier, glbl GSR writes, and
    exactly one XUT_DONE (Verilator's $finish does not stop the process at once)."""
    for name, text, m, dut, hdr in (
        ("probe", PROBE_FREE, PM, "probe_dut.v", PHDR),
        ("glbl", VEC_GLBL.split("\n", 1)[1], M, "toy_dut.v", VEC_GLBL.split("\n", 1)[0] + "\n"),
    ):
        vec = loads(hdr + text)
        vl, iv = tmp_path / f"{name}-vl", tmp_path / f"{name}-iv"
        vl.mkdir()
        iv.mkdir()
        shutil.copy(FIX / dut, vl / dut)
        shutil.copy(FIX / dut, iv / dut)
        got = _verilator(vl, vec, m, [dut], glbl_instance=glbl_instance)
        _, raw = _iverilog(iv, vec, m, [dut])
        want = raw_to_trace(raw, compile_vec(vec, m).labels, m, {})
        assert got.samples == want.samples, name
