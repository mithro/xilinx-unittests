# SPDX-License-Identifier: Apache-2.0
"""The cocotb style on the iverilog runner: ``xut.cocotb_dut.XutDut``, the in-container
launcher ``tools/xut/hdl/cocotb_run.py`` and ``cocotb_check`` (spec §4.3).

cocotb is not installed on the host: the hermetic tests import ``xut.cocotb_dut``
against a small fake of the three cocotb names it uses. The ``container`` tests run
the TOYFF cocotb fixture for real, under pytest's tmp_path (mounted at /xut-root).
"""

import asyncio
import dataclasses
import importlib
import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner
from test_runner_base import TOY_ENTRY
from test_runner_iverilog import make_model_source

from xut import schemas, stimgen, validate, wrap
from xut.cli import main
from xut.container import NativeExecutor
from xut.formats import xtr
from xut.modelsrc import ModelSource
from xut.runners import RUNNERS
from xut.runners.base import RunContext, seed_for, workdir
from xut.runners.iverilog import IverilogRunner
from xut.runners.python import PythonRunner
from xut.runners.sim import COCOTB_BUILD_FAILED, COCOTB_RUN, cocotb_check, cocotb_command
from xut.testspec import TestCase, discover
from xut.wrap import DutSpec, PortSpec, build_map

FIX = Path(__file__).parent / "fixtures"
REGISTER = FIX / "tests/7series/register"
TOY_SHARED = REGISTER / "_shared/toy"
CASE_ID = "7series.TOYFF.L2.cocotb_capture"


def _case(root: Path = FIX) -> TestCase:
    return next(c for c in discover(root) if c.id == CASE_ID)


@pytest.fixture
def toy_catalog(monkeypatch):
    """TOYFF's catalog entry only (a cocotb test needs no golden-model registry)."""
    monkeypatch.setattr("xut.catalog.model.load_entry", lambda family, name, root: TOY_ENTRY)


def _result(d: Path) -> dict:
    data = json.loads((d / "result.json").read_text())
    schemas.validate(data, "result")
    return data


# --- XutDut against a fake cocotb ------------------------------------------------------


class _Sim:
    now = 0


class _Timer:
    def __init__(self, t, unit="step"):
        assert unit == "ps"
        self.t = t

    def __await__(self):
        _Sim.now += self.t
        return iter(())


class _H:
    def __init__(self, value=0):
        self.value = value


@pytest.fixture
def cocotb_dut(monkeypatch):
    """``xut.cocotb_dut`` imported against a fake ``cocotb`` (triggers, simtime)."""
    _Sim.now = 0
    cocotb = types.ModuleType("cocotb")
    triggers = types.ModuleType("cocotb.triggers")
    triggers.Timer = _Timer
    simtime = types.ModuleType("cocotb.simtime")
    simtime.get_sim_time = lambda unit="step": _Sim.now
    for name, mod in (("cocotb", cocotb), ("cocotb.triggers", triggers)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setitem(sys.modules, "cocotb.simtime", simtime)
    monkeypatch.delitem(sys.modules, "xut.cocotb_dut", raising=False)
    return importlib.import_module("xut.cocotb_dut")


def _fake_dut(out: str = "0"):
    return types.SimpleNamespace(
        clk=_H(), in_vec=_H(), out_vec=_H(out), glbl=types.SimpleNamespace(GSR_int=_H(1))
    )


WIDE = DutSpec(
    "TOYW",
    "7series",
    "c1",
    (
        PortSpec("Q", "output", 2, "data"),
        PortSpec("C", "input", 1, "clock"),
        PortSpec("A", "input", 3, "data"),
        PortSpec("R", "input", 1, "async"),
        PortSpec("IO", "inout", 1, "inout"),
    ),
    (("INIT", "2'b10"),),
)


def _map(tmp_path: Path, spec: DutSpec = WIDE) -> Path:
    p = tmp_path / "map.json"
    p.write_text(build_map(spec).to_json())
    return p


def test_constants_match_the_vector_flow(cocotb_dut):
    """XutDut cannot import xut.stimgen/validate/wrap in the container: pin its copies."""
    assert cocotb_dut.SETTLE_PS == stimgen.DEFAULT_SETTLE_PS
    assert cocotb_dut.GAP_PS == validate.DEFAULT_GAP_PS
    assert cocotb_dut.MAP_FORMAT == wrap.MAP_FORMAT


def test_cocotb_dut_imports_only_cocotb_and_the_formats():
    """It runs inside the container, where xut's dependencies are not installed."""
    import ast

    tree = ast.parse((Path(wrap.__file__).parent / "cocotb_dut.py").read_text())
    mods = {
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in n.names
    }
    extra = {m for m in mods if m.split(".")[0] not in sys.stdlib_module_names}
    assert extra == {"cocotb.simtime", "cocotb.triggers", "xut.formats"}


def test_ports_attrs_and_initial_drive(cocotb_dut, tmp_path):
    dut = _fake_dut()
    dut.clk.value = dut.in_vec.value = None
    x = cocotb_dut.XutDut(dut, _map(tmp_path), tmp_path / "t.xtr", header={})
    assert x.attrs == {"INIT": "2'b10"}
    assert x.in_ports == ["A", "R", "IO__drive_en", "IO__drive_val"]
    assert x.clocks == ["C"] and x.out_ports == ["Q", "IO"]
    assert (dut.clk.value, dut.in_vec.value) == (0, 0)  # every input starts at 0


def test_set_edge_value_and_spacing(cocotb_dut, tmp_path):
    dut = _fake_dut()
    x = cocotb_dut.XutDut(dut, _map(tmp_path), tmp_path / "t.xtr", header={})
    m = build_map(WIDE)

    def bit(port, i=0, role=""):
        return m.port_bits("in", port, role)[i].bit

    asyncio.run(x.set(A=5, R=1))
    want = (1 << bit("A", 0)) | (1 << bit("A", 2)) | (1 << bit("R"))
    assert dut.in_vec.value == want and _Sim.now == 1000
    assert (x.value("A"), x.value("R"), x.value("C")) == (5, 1, 0)
    asyncio.run(x.set(IO__drive_en=1))
    assert x.value("IO__drive_en") == 1 and x.value("A") == 5
    asyncio.run(x.edge("C", True))
    assert dut.clk.value == 1 and x.value("C") == 1 and _Sim.now == 3000
    asyncio.run(x.cycle("C", n=2))
    assert dut.clk.value == 0 and _Sim.now == 7000
    before = dut.in_vec.value
    with pytest.raises(ValueError, match="does not fit"):  # checked before any write
        asyncio.run(x.set(R=0, A=8))
    assert dut.in_vec.value == before and x.value("R") == 1
    with pytest.raises(KeyError, match="no port 'C'"):  # a clock is driven with edge()
        asyncio.run(x.set(C=1))
    with pytest.raises(KeyError):
        asyncio.run(x.set(Q=1))
    with pytest.raises(ValueError, match="one-bit"):
        asyncio.run(x.edge("A", True))
    with pytest.raises(TypeError):
        asyncio.run(x.set(R=True))


def test_settle_and_gsr(cocotb_dut, tmp_path):
    dut = _fake_dut()
    x = cocotb_dut.XutDut(dut, _map(tmp_path), tmp_path / "t.xtr", header={})
    asyncio.run(x.set(R=1))
    asyncio.run(x.settle())
    assert _Sim.now == 120_000
    asyncio.run(x.settle())  # already settled: one gap
    assert _Sim.now == 121_000
    asyncio.run(x.gsr(1))
    assert dut.glbl.GSR_int.value == 1 and _Sim.now == 122_000


def test_min_event_gap_from_the_map(cocotb_dut, tmp_path):
    x = cocotb_dut.XutDut(
        _fake_dut(),
        _map(tmp_path, dataclasses.replace(WIDE, min_event_gap_ps=2500)),
        tmp_path / "t.xtr",
        header={},
    )
    asyncio.run(x.edge("C", True))
    assert _Sim.now == 2500


def test_get_slices_out_vec_lowercase(cocotb_dut, tmp_path):
    m = build_map(WIDE)
    q = [b.bit for b in m.port_bits("out", "Q")]
    io = m.port_bits("out", "IO", "obs")[0].bit
    bits = ["0"] * m.nout
    bits[q[1]], bits[q[0]], bits[io] = "X", "1", "Z"
    dut = _fake_dut("".join(reversed(bits)))  # str(LogicArray) is MSB first, upper case
    x = cocotb_dut.XutDut(dut, _map(tmp_path), tmp_path / "t.xtr", header={})
    assert x.get("Q") == "x1" and x.get("IO") == "z"
    with pytest.raises(KeyError):
        x.get("A")


def test_sample_and_close_write_an_xtr(cocotb_dut, tmp_path, monkeypatch):
    for k, v in {"XUT_RUNNER": "iverilog", "XUT_MODEL": "toy", "XUT_SEED": "42"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("XUT_FLOW", raising=False)
    dut = _fake_dut("0101")
    x = cocotb_dut.XutDut(dut, _map(tmp_path), tmp_path / "t.xtr")
    assert x.sample("S0", {"Q": ("doc:1", "inferred:x")}) == x.sample("S1", {"Q": "doc:2"})
    x.sample("S2")
    with pytest.raises(xtr.XtrError):
        x.sample("bad label")
    x.close()
    t = xtr.load(tmp_path / "t.xtr")
    assert t.header == {
        "runner": "iverilog",
        "flow": "rtl",
        "model": "toy",
        "seed": "42",
        "prim": "TOYW",
        "cfg": "c1",
    }
    assert list(t.samples) == ["S0", "S1", "S2"]
    assert t.prov["S0"] == {"Q": "doc:1,inferred:x"} and t.prov["S1"] == {"Q": "doc:2"}


def test_default_header_needs_the_runner_environment(cocotb_dut, tmp_path, monkeypatch):
    monkeypatch.delenv("XUT_MODEL", raising=False)
    monkeypatch.setenv("XUT_RUNNER", "iverilog")
    monkeypatch.setenv("XUT_SEED", "1")
    with pytest.raises(KeyError, match="XUT_MODEL"):
        cocotb_dut.XutDut(_fake_dut(), _map(tmp_path), tmp_path / "t.xtr")


def test_rejects_a_foreign_map(cocotb_dut, tmp_path):
    p = tmp_path / "m.json"
    p.write_text('{"format": "other"}')
    with pytest.raises(ValueError, match="xut-map"):
        cocotb_dut.XutDut(_fake_dut(), p, tmp_path / "t.xtr")


# --- the launcher's pure parts ---------------------------------------------------------


@pytest.fixture(scope="module")
def launcher():
    spec = importlib.util.spec_from_file_location("cocotb_run", COCOTB_RUN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # cocotb_tools is imported only inside main()
    return mod


def test_launcher_build_args(launcher):
    assert launcher.build_args("icarus", "/u", None, []) == ["-y", "/u", "-Y", ".v"]
    assert launcher.build_args("icarus", "/u", "/r", ["/vz"]) == [
        *("-y", "/vz", "-y", "/u", "-y", "/r"),
        *("-Y", ".v"),
    ]
    assert launcher.build_args("verilator", "/u", None, ["/vz"]) == [
        *("--timing", "-Wno-fatal"),
        *("--x-assign", "unique", "--x-initial", "unique"),
        *("-y", "/vz", "-y", "/u", "+libext+.v"),
    ]


def test_launcher_plusargs_and_defines(launcher):
    assert launcher.plusargs("icarus", None) == []
    assert launcher.plusargs("verilator", 7) == ["+verilator+seed+7", "+verilator+rand+reset+2"]
    with pytest.raises(SystemExit):
        launcher.plusargs("verilator", None)
    for bad in (0, -1):  # +verilator+seed+0 picks a random seed: not reproducible
        with pytest.raises(SystemExit, match="must be > 0"):
            launcher.plusargs("verilator", bad)
    assert launcher.defines(["A", "B=3"]) == {"A": 1, "B": "3"}
    a = launcher.parse(
        [
            *("--sim", "icarus", "--work", "w", "--module", "m", "--test-dir", "t"),
            *("--unisims", "u", "--glbl", "g", "--seed", "5", "--shared", "s1"),
            *("--shared", "s2"),
        ]
    )
    assert (a.seed, a.shared, a.retarget, a.lib_first) == (5, ["s1", "s2"], None, [])


def test_cocotb_command(tmp_path):
    case = _case()
    ms = make_model_source(tmp_path / "ms")
    ctx = RunContext(tmp_path, "rtl", ms, defines={"P": "", "Q": "2"})
    cd = tmp_path / "cfg-init0"
    argv, env = cocotb_command(NativeExecutor(), "icarus", case, cd, ctx, "iverilog", 9)
    assert argv[:2] == ["python3", str(COCOTB_RUN)]
    text = " ".join(argv)
    assert f"--work {cd}" in text and "--module cocotb_toyff" in text
    assert f"--test-dir {case.test_dir / 'cocotb'}" in text
    assert f"--unisims {ms.unisims} --glbl {ms.glbl} --seed 9" in text
    assert "--define P --define Q=2" in text and f"--shared {TOY_SHARED}" in text
    assert "--retarget" not in text and "--x-seed" not in text
    assert env["PYTHONPATH"].split(":") == [
        str(COCOTB_RUN.parents[2]),
        str(COCOTB_RUN.parents[3] / "models"),
        str(case.test_dir / "cocotb"),
        str(TOY_SHARED),
    ]
    assert env["XUT_MAP"] == "dut/xut_dut.map.json" and env["XUT_TRACE"] == "trace.xtr"
    assert (env["XUT_SEED"], env["XUT_RUNNER"], env["XUT_MODEL"]) == ("9", "iverilog", ms.name)


# --- cocotb_check ------------------------------------------------------------------------

HDR = {"runner": "iverilog", "flow": "rtl", "model": "m", "prim": "TOYFF", "cfg": "c", "seed": "3"}


def _xml(cd: Path, cases: str, seed: int = 3) -> None:
    cd.mkdir(exist_ok=True)
    (cd / "results.xml").write_text(
        '<testsuites name="results"><testsuite name="all" package="all">'
        f'<property name="random_seed" value="{seed}" />{cases}</testsuite></testsuites>'
    )


def _tc(name: str = "t", inner: str = "") -> str:
    return f'<testcase name="{name}" classname="mod">{inner}</testcase>'


def _trace(cd: Path, **over: str) -> None:
    t = xtr.Trace({**HDR, **over})
    t.add("S0", {"Q": "1"})
    xtr.dump(t, cd / "trace.xtr")


def test_cocotb_check_pass(tmp_path):
    cd = tmp_path / "cfg-c"
    _xml(cd, _tc())
    _trace(cd)
    r = cocotb_check(cd, 0, 3, HDR)
    assert (r.cfg, r.status, r.reason) == ("c", "pass", None) and r.trace_sha256


@pytest.mark.parametrize(
    ("cases", "rc", "status", "reason"),
    [
        (
            _tc("a") + _tc("b", '<failure error_type="AssertionError" error_msg="Q=0, model 1" />'),
            1,
            "fail",
            "mod.b: Q=0, model 1",
        ),
        (
            _tc("a", '<failure error_type="SimFailure" error_msg="Simulator shut down" />'),
            1,
            "error",
            "mod.a: SimFailure: Simulator shut down",
        ),
        (
            _tc("a", '<failure error_type="KeyError" error_msg="\'X\'" />'),
            1,
            "error",
            "mod.a: KeyError: 'X'",
        ),
        ("", 1, "error", "no cocotb test ran (none found, or all skipped)"),
        (_tc("a", "<skipped />"), 1, "error", "no cocotb test ran (none found, or all skipped)"),
        (_tc(), 1, "error", "cocotb launcher exited with rc 1"),
    ],
)
def test_cocotb_check_classification(tmp_path, cases, rc, status, reason):
    cd = tmp_path / "cfg-c"
    _xml(cd, cases)
    _trace(cd)
    r = cocotb_check(cd, rc, 3, HDR)
    assert (r.status, r.reason) == (status, f"{reason} [seed 3]")  # every reason names it


def test_a_crash_is_never_hidden_by_an_earlier_assertion(tmp_path):
    cd = tmp_path / "cfg-c"
    _xml(
        cd,
        _tc("a", '<failure error_type="AssertionError" error_msg="Q=0, model 1" />')
        + _tc("b", '<failure error_type="SimFailure" error_msg="Simulator shut down" />'),
    )
    _trace(cd)
    r = cocotb_check(cd, 1, 3, HDR)
    assert (r.status, r.reason) == ("error", "mod.b: SimFailure: Simulator shut down [seed 3]")


@pytest.mark.parametrize("trace", ["missing", "header-only"])
def test_a_pass_without_samples_is_an_error(tmp_path, trace):
    """Review T11 I1: a passing test that recorded nothing is no evidence of a check."""
    cd = tmp_path / "cfg-c"
    _xml(cd, _tc())
    if trace == "header-only":
        xtr.dump(xtr.Trace(dict(HDR)), cd / "trace.xtr")
    r = cocotb_check(cd, 0, 3, HDR)
    assert (r.status, r.reason) == ("error", "cocotb test recorded no samples [seed 3]")
    assert (r.trace_sha256 is not None) == (trace == "header-only")


def test_cocotb_check_errors(tmp_path, launcher):
    cd = tmp_path / "cfg-c"
    cd.mkdir()
    r = cocotb_check(cd, 1, 3, HDR)
    assert r.status == "error" and "no results.xml" in r.reason
    assert launcher.BUILD_FAILED == COCOTB_BUILD_FAILED
    assert cocotb_check(cd, COCOTB_BUILD_FAILED, 3, HDR).reason == "compile failed [seed 3]"
    (cd / "results.xml").write_text("<testsuites")
    assert "unreadable results.xml" in cocotb_check(cd, 1, 3, HDR).reason
    _xml(cd, _tc(), seed=4)
    assert cocotb_check(cd, 0, 3, HDR).reason == "results.xml random_seed ['4'] is not 3 [seed 3]"
    _xml(cd, _tc())
    _trace(cd, model="other")
    r = cocotb_check(cd, 0, 3, HDR)
    assert r.status == "error" and "trace.xtr header {'model': 'other'}" in r.reason
    (cd / "trace.xtr").write_text("nonsense\n")
    assert "malformed trace.xtr" in cocotb_check(cd, 0, 3, HDR).reason


def test_model_errors_fail_a_passing_cocotb_run(tmp_path):
    """Runtime model diagnostics are never silently ignored (PR B gate (b) #7): an
    error/fatal line in run.log fails a configuration whose cocotb test passed."""
    cd = tmp_path / "cfg-c"
    _xml(cd, _tc())
    _trace(cd)
    (cd / "run.log").write_text("   0.00ns INFO     cocotb   Running tests\n")
    assert cocotb_check(cd, 0, 3, HDR).status == "pass"
    (cd / "run.log").write_text("Error: [Unisim TOYFF-1] model complains\n")
    r = cocotb_check(cd, 0, 3, HDR)
    assert r.status == "fail" and r.reason == (
        "model reported errors: Error: [Unisim TOYFF-1] model complains [seed 3]"
    )


def test_fixture_declares_the_cocotb_test():
    c = _case()
    assert (c.style, c.source, [x["cfg"] for x in c.configs]) == (
        "cocotb",
        "cocotb/cocotb_toyff.py",
        ["init0", "init1"],
    )
    assert (TOY_SHARED / "toy_golden.py").is_file()


def test_python_and_xsim_skip_cocotb(tmp_path, toy_catalog):
    ctx = RunContext(tmp_path, "rtl", make_model_source(tmp_path / "ms"))
    res = PythonRunner().run(_case(), ctx)
    assert (res.status, res.reason) == ("skip", "declared unsupported: cocotb test")
    res = RUNNERS["xsim"]().run(_case(), ctx)
    assert (res.status, res.reason) == ("skip", "declared unsupported: cocotb has no xsim backend")


# --- container: the TOYFF cocotb fixture on Icarus ---------------------------------------


@pytest.fixture
def ctx(tmp_path):
    return RunContext(tmp_path, "rtl", make_model_source(tmp_path / "ms"))


def _one_cfg(case: TestCase) -> TestCase:
    return dataclasses.replace(case, configs=case.configs[:1])


@pytest.mark.container
def test_cocotb_toyff_passes(ctx, toy_catalog):
    case = _case()
    res = IverilogRunner().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())
    data = _result(d)
    seed = seed_for(case, ctx)
    assert data["style"] == "cocotb" and data["seeds"] == {"stimulus": seed, "x": []}
    assert data["tools"]["cocotb"] == "2.0.1" and data["model_source"] == "toyff-test"
    for cfg in ("init0", "init1"):
        cd = d / f"cfg-{cfg}"
        t = xtr.load(cd / "trace.xtr")
        assert list(t.samples) == [f"S{n}" for n in range(20)]
        assert t.header == {
            "runner": "iverilog",
            "flow": "rtl",
            "model": "toyff-test",
            "seed": str(seed),
            "prim": "TOYFF",
            "cfg": cfg,
        }
        assert all(v == {"Q": "doc:1"} for v in t.prov.values())
        assert set(v["Q"] for v in t.samples.values()) == {"0", "1"}
        assert (cd / "dut/xut_cocotb_top.v").is_file()
        assert f'name="random_seed" value="{seed}"' in (cd / "results.xml").read_text()
    top = xtr.load(d / "trace.xtr")
    assert len(top.samples) == 40 and top.header["seed"] == str(seed)
    assert [c["trace_sha256"] is not None for c in data["configs"]] == [True, True]


@pytest.mark.container
def test_cocotb_seed_reproduces_the_session(tmp_path, toy_catalog):
    """The same --seed reproduces the trace exactly; another seed drives other D values."""
    ms = make_model_source(tmp_path / "ms")
    case = _one_cfg(_case())

    def trace(root: str, seed: int) -> xtr.Trace:
        ctx = RunContext(tmp_path / root, "rtl", ms, seed=seed)
        res = IverilogRunner().run(case, ctx)
        assert res.status == "pass", res.reason
        return xtr.load(workdir(ctx, "iverilog", case.id) / "cfg-init0/trace.xtr")

    a, b, c = trace("a", 7), trace("b", 7), trace("c", 8)
    assert a == b
    assert a.samples != c.samples  # 20 random bits: equal only with probability 2**-20
    assert (a.header["seed"], c.header["seed"]) == ("7", "8")


@pytest.mark.container
def test_cocotb_model_mismatch_fails(ctx, toy_catalog):
    """A UNISIM model that disagrees with the golden model: fail, with the assertion."""
    m = ctx.model_source.unisims / "TOYFF.v"
    m.write_text(m.read_text().replace("else q <= D;", "else q <= ~D;"))
    res = IverilogRunner().run(_one_cfg(_case()), ctx)
    assert res.status == "fail", res.reason
    assert res.configs[0].reason.startswith("cocotb_toyff.toyff_capture: 20 mismatch(es)")
    # the trace is still the evidence of what the simulator did
    assert res.configs[0].trace_sha256


@pytest.mark.container
def test_cocotb_attributes_reach_the_dut(ctx, toy_catalog):
    """A model that ignores INIT fails init1 only: the configuration's attributes reach
    both the wrapper (xut_dut.v) and XutDut.attrs (the golden model)."""
    m = ctx.model_source.unisims / "TOYFF.v"
    m.write_text(m.read_text().replace("if (glbl.GSR) q <= INIT;", "if (glbl.GSR) q <= 1'b0;"))
    res = IverilogRunner().run(_case(), ctx)
    by = {c.cfg: c for c in res.configs}
    assert (by["init0"].status, by["init1"].status) == ("pass", "fail"), res.reason
    assert "after GSR: Q=0, model 1 (INIT=1'b1)" in by["init1"].reason


@pytest.mark.container
def test_cocotb_simulator_stopping_early_is_error(ctx, toy_catalog):
    m = ctx.model_source.unisims / "TOYFF.v"
    m.write_text(m.read_text().replace("  reg q;\n", "  reg q;\n  initial #125000 $finish;\n"))
    res = IverilogRunner().run(_one_cfg(_case()), ctx)
    assert res.status == "error"
    assert "SimFailure" in res.configs[0].reason, res.configs[0].reason


@pytest.mark.container
def test_cocotb_import_failure_is_error(ctx, toy_catalog, tmp_path):
    """Without its shared directory the test module cannot import ToyDff: error."""
    bare = tmp_path / "bare"  # TOYFF without tests/7series/register/_shared/toy
    shutil.copytree(REGISTER / "TOYFF", bare / "tests/7series/register/TOYFF")
    case = _one_cfg(_case(bare))
    assert case.shared_dirs == []
    res = IverilogRunner().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    assert res.status == "error"
    assert "no results.xml" in res.configs[0].reason
    assert "No module named 'toy_golden'" in (d / "run.log").read_text()


@pytest.mark.container
def test_cocotb_compile_failure_is_error(ctx, toy_catalog):
    (ctx.model_source.unisims / "TOYFF.v").write_text("module TOYFF(; endmodule\n")
    res = IverilogRunner().run(_one_cfg(_case()), ctx)
    assert res.status == "error" and res.configs[0].reason.startswith("compile failed [seed ")
    log = (workdir(ctx, "iverilog", _case().id) / "run.log").read_text()
    assert "XUT_COCOTB build failed" in log and "syntax error" in log


@pytest.mark.container
def test_cli_python_iverilog_cocotb_on_the_toyff_fixture(tmp_path, toy_catalog, monkeypatch):
    """`xut run --runner python --runner iverilog --style cocotb --seed 7` on a copy of
    the fixture tree (TOYFF and its _shared/toy) rooted at tmp_path."""
    work = tmp_path / "root"
    shutil.copytree(REGISTER, work / "tests/7series/register")
    ms = make_model_source(tmp_path / "ms")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: work)
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": ms)
    args = ["run", "--runner", "python", "--runner", "iverilog", "--style", "cocotb"]
    r = CliRunner().invoke(main, [*args, "--seed", "7"])
    assert r.exit_code == 0, r.output
    summary = json.loads((work / "build/rtl/summary-toyff-test.json").read_text())
    got = {(x["test_id"], x["runner"]): x["status"] for x in summary["results"]}
    assert got == {(CASE_ID, "python"): "skip", (CASE_ID, "iverilog"): "pass"}
    d = work / "build/rtl/iverilog/toyff-test" / CASE_ID
    assert _result(d)["seeds"]["stimulus"] == 7
    assert xtr.load(d / "cfg-init1/trace.xtr").header["seed"] == "7"
    print("\n[T11 demo: xut run --runner python --runner iverilog --style cocotb]")
    print(r.output)


@pytest.mark.container
def test_cocotb_model_error_fails_with_the_seed(ctx, toy_catalog):
    """A UNISIM model that reports an error while matching the golden model: fail
    (never silently ignored), and the reason names the seed to reproduce it."""
    m = ctx.model_source.unisims / "TOYFF.v"
    m.write_text(
        m.read_text().replace(
            "  reg q;\n", '  reg q;\n  initial #110000 $display("Error: TOYFF odd");\n'
        )
    )
    case = _one_cfg(_case())
    res = IverilogRunner().run(case, ctx)
    assert res.status == "fail", res.reason
    seed = seed_for(case, ctx)
    assert res.configs[0].reason == f"model reported errors: Error: TOYFF odd [seed {seed}]"


# --- PR #10 must-fix 6: no z stimulus into a z-compare model (ruling S38) ------------------


def test_z_marks_agree(cocotb_dut):
    from xut.runners import sim

    assert sim.Z_MARK == cocotb_dut.Z_MARK


@pytest.mark.parametrize("op", ["set", "edge", "gsr"])
def test_a_z_written_through_xutdut_is_refused_and_marked(cocotb_dut, tmp_path, op):
    x = cocotb_dut.XutDut(_fake_dut(), _map(tmp_path), tmp_path / "t.xtr", header={})
    call = {"set": lambda: x.set(R="z"), "edge": lambda: x.edge("C", "z"),
            "gsr": lambda: x.gsr("z")}[op]  # fmt: skip
    with pytest.raises(cocotb_dut.ZStimulusError, match="drives z"):
        asyncio.run(call())
    assert "drives z" in (tmp_path / cocotb_dut.Z_MARK).read_text()


def test_a_z_written_to_the_handle_is_refused_under_xut_no_z(cocotb_dut, tmp_path, monkeypatch):
    """A test that bypasses XutDut: under verilator/iverilog-vz (XUT_NO_Z=1) the read-back
    of in_vec refuses it at the next operation or sample."""
    dut = _fake_dut()
    x = cocotb_dut.XutDut(dut, _map(tmp_path), tmp_path / "t.xtr", header={})
    dut.in_vec.value = "0z00"
    asyncio.run(x.set(R=1))  # not under XUT_NO_Z: not checked
    monkeypatch.setenv("XUT_NO_Z", "1")
    x = cocotb_dut.XutDut(dut, _map(tmp_path), tmp_path / "t.xtr", header={})
    dut.in_vec.value = "0z00"
    with pytest.raises(cocotb_dut.ZStimulusError, match="in_vec = 0z00"):
        x.sample("S0")


def test_cocotb_check_reports_a_z_stimulus_as_an_error(tmp_path):
    cd = tmp_path / "cfg-c"
    _xml(cd, _tc("t", '<failure message="boom" />'))
    _trace(cd)
    (cd / "xut_z_stimulus.txt").write_text("TOYFF: R='z' drives z\n")
    r = cocotb_check(cd, 1, 3, HDR)
    assert r.status == "error" and "cocotb test drove z into the DUT: TOYFF: R='z'" in r.reason


def test_cocotb_command_sets_xut_no_z_for_the_verilator_runners(tmp_path):
    ms = make_model_source(tmp_path / "ms")
    ctx = RunContext(tmp_path, "rtl", ms)
    case = next(c for c in discover(FIX) if c.style == "cocotb")
    for runner, want in (("verilator", "1"), ("iverilog-vz", "1"), ("iverilog", "0")):
        _, env = cocotb_command(NativeExecutor(), "icarus", case, tmp_path, ctx, runner, 1)
        assert env["XUT_NO_Z"] == want


# --- the time-0 barrier: a combinational model sees its inputs' first value --------------

TOYCOMB_ENTRY = dataclasses.replace(
    TOY_ENTRY,
    name="TOYCOMB",
    description="toy combinational model: regs updated by always @(inputs)",
    model={"library": "unisims", "file": "TOYCOMB.v"},
    ports=[
        {"name": "O", "direction": "output", "width": 1, "cls": "data", "doc_function": "O"},
        {"name": "P", "direction": "output", "width": 1, "cls": "data", "doc_function": "P"},
        {"name": "C", "direction": "input", "width": 1, "cls": "clock", "doc_function": "C"},
        {"name": "A", "direction": "input", "width": 1, "cls": "data", "doc_function": "A"},
        {"name": "B", "direction": "input", "width": 1, "cls": "data", "doc_function": "B"},
    ],
    attributes=[],
)

#: Outputs held in regs that only an input event updates (as a behavioural LUT model's).
TOYCOMB_MODEL = """\
// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module TOYCOMB (output wire O, output wire P, input wire C, input wire A, input wire B);
  reg o, p;
  always @(A or B) o = ~(A | B);
  always @(C) p = ~C;
  assign O = o;
  assign P = p;
endmodule
"""

TOYCOMB_YAML = """\
# SPDX-License-Identifier: Apache-2.0
primitive: TOYCOMB
family: 7series
work_unit: toy
doc_refs: [{guide: UG953, version: "2026.1", section: TOYCOMB, page: 1}]
tests:
  - id: 7series.TOYCOMB.L2.cocotb_first_samples
    level: L2
    style: cocotb
    source: cocotb/cocotb_toycomb.py
    exercises: []
    attr_sampling: {}
    configs: [{cfg: default, attrs: {}}]
    runners:
      {python: "no", xsim: "unsupported", iverilog: "yes", verilator: "yes", hw: "unsupported"}
    unsupported_reasons: {python: "cocotb", xsim: "fixture", hw: "fixture"}
    flows: [rtl]
    related: []
    gaps: []
"""


def test_cocotb_top_drives_inputs_by_a_time0_nonblocking_update():
    """No declaration initialiser on clk/in_vec (a time-0 value that no process sees as an
    event): x until a time-0 non-blocking update, as xut_vector_tb.sv's barrier."""
    text = wrap.render_cocotb_top(build_map(WIDE))
    decls = [ln.split("//")[0].strip() for ln in text.splitlines() if ln.startswith("  reg ")]
    assert decls == ["reg  [`XUT_NCLK-1:0] clk;", "reg  [`XUT_NIN-1:0]  in_vec;"]
    assert "clk <= {`XUT_NCLK{1'b0}};" in text and "in_vec <= {`XUT_NIN{1'b0}};" in text


@pytest.mark.container
@pytest.mark.parametrize("runner", ["iverilog", "verilator", "iverilog-vz"])
def test_cocotb_first_samples_of_a_combinational_model_are_defined(work, monkeypatch, runner):
    """luts harness-error: with the inputs initialised to 0 in their declaration, an
    ``always @(inputs)`` model on Icarus never ran, and the session's idle writes of the
    same 0 made no event, so the first samples were x. The session checks them itself."""
    tdir = work / "tests/7series/register/TOYCOMB"
    (tdir / "cocotb").mkdir(parents=True)
    (tdir / "test.yaml").write_text(TOYCOMB_YAML)
    shutil.copy(FIX / "cocotb/cocotb_toycomb.py", tdir / "cocotb/cocotb_toycomb.py")
    src = work / "ms"
    make_model_source(src)
    (src / "unisims/TOYCOMB.v").write_text(TOYCOMB_MODEL)
    ctx = RunContext(work, "rtl", ModelSource("toycomb-test", src))
    monkeypatch.setattr("xut.catalog.model.load_entry", lambda f, n, r: TOYCOMB_ENTRY)
    (case,) = discover(work)
    res = RUNNERS[runner]().run(case, ctx)
    d = workdir(ctx, runner, case.id)
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())
    got = {k: (v["O"], v["P"]) for k, v in xtr.load(d / "trace.xtr").samples.items()}
    assert got == {
        "default/S0": ("1", "1"),
        "default/S1": ("1", "1"),
        "default/S2": ("0", "1"),
    }
