# SPDX-License-Identifier: Apache-2.0
"""The verilator runner (two X-seed runs per configuration) and its iverilog-vz companion
(spec §5.6, §6, §6.2; Task 15, ruling S35).

The hermetic tests fake ``ensure_model`` (or use the transform on toy sources, which needs
no simulator). The ``container`` tests run under pytest's tmp_path, with toy model
sources whose verilatorized directory is ``<tmp>/build/verilatorized/<source>/``."""

import dataclasses
import json
import shutil
import textwrap
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner
from test_runner_base import TOY_ENTRY
from test_runner_iverilog import FIX, _copy_toy, make_model_source

from xut import run as run_mod
from xut import schemas
from xut.catalog.model import CatalogEntry
from xut.cli import main
from xut.container import NativeExecutor
from xut.formats import xtr, xvec
from xut.modelsrc import ModelSource
from xut.runners import RUNNERS
from xut.runners import verilator as vl
from xut.runners.base import RunContext, RunResult, python_dir, workdir
from xut.runners.iverilog import IverilogRunner
from xut.runners.python import PythonRunner
from xut.runners.verilator import (
    X_STIMULUS,
    IverilogVzRunner,
    VerilatorRunner,
    blocked,
    build_failure,
    verilator_argv,
    x_seeds,
)
from xut.stimgen import VecBuilder
from xut.testspec import TestCase, discover
from xut.verilatorize import driver
from xut.verilatorize.driver import ModelEntry, ensure_model, model_attrs, vz_dir
from xut.verilatorize.equiv import EquivResult
from xut.wrap import spec_from_catalog, write_dut

VZ_FIX = Path(__file__).parent / "fixtures" / "verilatorize"
VL_FIX = Path(__file__).parent / "fixtures" / "verilator"


def _case(tid: str, root: Path = FIX) -> TestCase:
    return next(c for c in discover(root) if c.id == tid)


def _result(d: Path) -> dict:
    data = json.loads((d / "result.json").read_text())
    schemas.validate(data, "result")
    return data


def _log(ctx: RunContext, runner: str, case: TestCase) -> str:
    p = workdir(ctx, runner, case.id) / "run.log"
    return p.read_text() if p.is_file() else "(no run.log)"


@pytest.fixture
def ctx(work):
    return RunContext(work, "rtl", make_model_source(work / "ms"))


@pytest.fixture(autouse=True)
def _fresh_entries(monkeypatch):
    """ensure_model's per-process caches must not leak between tests."""
    monkeypatch.setattr(driver, "_ENTRIES", {})
    monkeypatch.setattr(driver, "_TOOLS", {})
    monkeypatch.setattr(driver, "_CHECKED", set())


# --- no container needed ---------------------------------------------------------------


def test_x_seeds():
    assert x_seeds(0) == (1, 2)
    assert x_seeds(17) == (35, 36)
    assert x_seeds(2**30) == (1, 2)  # wraps modulo 2**31, never 0
    assert x_seeds(2**31 - 1) == (2**31 - 1, 2)
    for s in (0, 1, 12345, 2**30 - 1, 2**31, 2**32 + 7):
        a, b = x_seeds(s)
        assert a != b and 0 < a < 2**31 and 0 < b < 2**31


def test_registry():
    assert RUNNERS["verilator"] is VerilatorRunner and RUNNERS["iverilog-vz"] is IverilogVzRunner
    assert VerilatorRunner.name == "verilator" and not VerilatorRunner.x_observable
    assert IverilogVzRunner.name == "iverilog-vz" and IverilogVzRunner.x_observable
    assert issubclass(IverilogVzRunner, IverilogRunner)


def test_glbl_mode(tmp_path):
    """Step 1 spike (Verilator 5.048): glbl is a second top, never an instance
    (XUT_GLBL_INSTANCE is not defined), for vector and sv builds alike."""
    assert VerilatorRunner.glbl_instance is False
    ms = make_model_source(tmp_path / "ms")
    ctx = RunContext(tmp_path, "rtl", ms, defines={"A": "", "B": "2"})
    argv = verilator_argv(NativeExecutor(), ctx, tmp_path / "vz", ["tb.sv", str(ms.glbl)], [])
    assert argv[:3] == ["verilator", "--binary", "--timing"]
    assert "-Wno-MULTITOP" in argv and str(ms.glbl) == argv[-1]
    assert not any("XUT_GLBL_INSTANCE" in a for a in argv)
    # warnings are not waived beyond -Wno-fatal/-Wno-MULTITOP (ruling S35.5)
    assert not {"-Wno-lint", "-Wno-style"} & set(argv)
    i = argv.index("-y")
    assert argv[i : i + 4] == ["-y", str(tmp_path / "vz"), "-y", str(ms.unisims)]
    assert [a for a in argv if a.startswith("+define+")] == ["+define+A", "+define+B=2"]
    for flag in ("--x-assign", "--x-initial"):
        assert argv[argv.index(flag) + 1] == "unique"


def test_with_companions():
    assert run_mod.with_companions(["verilator"]) == ["verilator", "iverilog-vz"]
    assert run_mod.with_companions(["iverilog-vz", "verilator"]) == ["iverilog-vz", "verilator"]
    assert run_mod.with_companions(["python", "iverilog"]) == ["python", "iverilog"]


def test_run_tests_runs_iverilog_vz_with_verilator(ctx, monkeypatch):
    ran = []

    def fake(name):
        def run(self, case, ctx):
            ran.append(name)
            return RunResult(case.id, name, ctx.flow, case.style, "pass", None)

        return run

    for name in ("verilator", "iverilog-vz"):
        monkeypatch.setattr(RUNNERS[name], "run", fake(name))
    sv = _case("7series.TOYFF.L1.sv_basic")
    run_mod.run_tests([sv], ["verilator"], ctx)
    assert sorted(ran) == ["iverilog-vz", "verilator"]


def test_build_failure_explains_the_inherent_tristate_case():
    log = "%Error-UNSUPPORTED: dut/xut_dut.v:13:6: Unsupported: tristate in top-level IO: 'CE'\n"
    why = build_failure("%Warning-X: w\n" + log + "%Error: Exiting due to 1 error(s)\n")
    assert why.startswith("compile failed: %Error-UNSUPPORTED: dut/xut_dut.v:13:6:")
    assert "inherent" in why and "=== 1'bz" in why
    assert build_failure("%Error: x.v:1: syntax error\n") == (
        "compile failed: %Error: x.v:1: syntax error"
    )
    assert "no %Error line" in build_failure("make: *** [x] Error 2\n")


def _entry(status: str, **kw: object) -> ModelEntry:
    return ModelEntry(status, "sha", **kw)


@pytest.mark.parametrize(
    ("entry", "want"),
    [
        (_entry("unchanged"), None),
        (_entry("transformed", equiv={"default": "pass"}), None),
        (_entry("unsupported", reason="nested generate"), "verilatorize cannot transform "),
        (_entry("transformed", equiv={"default": "fail"}, equiv_reason={"default": "3"}),
         "transform-bug: Icarus equivalence fail for TOYFF default blocks Verilator results"),
        (_entry("transformed", equiv={"default": "error"}, equiv_reason={"default": "DRC"}),
         "equivalence check error for TOYFF default: DRC blocks Verilator results (spec §6.2)"),
        (_entry("transformed", equiv={"x": "pass"}),
         "equivalence check error for TOYFF default: no result blocks"),
    ],
)  # fmt: skip
def test_blocked_maps_every_non_pass_to_an_error_reason(entry, want):
    got = blocked(entry, "TOYFF", "default")
    assert got == want if want is None else got.startswith(want), got


def _python(ctx: RunContext, case: TestCase) -> None:
    res = PythonRunner().run(case, ctx)
    assert res.status == "pass", res.reason


@pytest.fixture
def no_container(monkeypatch):
    """The runners believe the simulator image is there (nothing reaches it)."""
    for cls in (VerilatorRunner, IverilogVzRunner):
        monkeypatch.setattr(cls, "available", lambda self, ctx: (True, ""))
        monkeypatch.setattr(cls, "tools", lambda self, ctx: {})
        monkeypatch.setattr(cls, "container", lambda self, ctx: None)


def _fake_ensure(monkeypatch, entry: ModelEntry) -> list:
    calls = []

    def fake(ms, prim, attrs=None, *, root=None, log=print, check=True):
        calls.append((prim, dict(attrs or {}), root, check))
        return entry

    monkeypatch.setattr(vl, "ensure_model", fake)
    return calls


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (_entry("unsupported", reason="TOYFF: nested generate"),
         "verilatorize cannot transform TOYFF: TOYFF: nested generate"),
        (_entry("transformed", equiv={"default": "fail", "INIT=1'b1": "fail"},
                equiv_reason={"default": "2 mismatch(es)", "INIT=1'b1": "2 mismatch(es)"}),
         "transform-bug: "),
        (_entry("transformed", equiv={"default": "error", "INIT=1'b1": "error"},
                equiv_reason={"default": "xsim unavailable", "INIT=1'b1": "xsim unavailable"}),
         "equivalence check error for TOYFF "),
        # an unchanged model over a transformed dependency is gated like a transformed one
        (_entry("unchanged", depends_on_transformed=["TOYSUB"],
                equiv={"default": "fail", "INIT=1'b1": "fail"}),
         "transform-bug: "),
        (_entry("unchanged", depends_on_unsupported=["TOYSUB"]),
         "verilatorize cannot transform TOYSUB in the hierarchy of TOYFF"),
    ],
)  # fmt: skip
def test_a_blocking_model_is_an_error_never_a_pass_or_skip(
    ctx, toy, no_container, monkeypatch, entry, reason
):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    calls = _fake_ensure(monkeypatch, entry)
    res = VerilatorRunner().run(case, ctx)
    assert res.status == "error"
    assert [c.status for c in res.configs] == ["error", "error"]
    assert all(c.reason.startswith(reason) for c in res.configs), res.configs
    first = [("TOYFF", {}, ctx.root, False)]  # transform the hierarchy, then check
    if entry.gated and not (entry.status == "unsupported" or entry.depends_on_unsupported):
        assert calls == [
            c for i in (0, 1) for c in (*first, ("TOYFF", {"INIT": f"1'b{i}"}, ctx.root, True))
        ]
    else:
        assert calls == first * 2
    assert not list(workdir(ctx, "verilator", case.id).glob("cfg-*/obj"))  # never built


def test_iverilog_vz_skips_an_untransformable_model(ctx, toy, no_container, monkeypatch):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    _fake_ensure(monkeypatch, _entry("unsupported", reason="TOYFF: nested generate"))
    res = IverilogVzRunner().run(case, ctx)
    assert res.status == "skip"
    assert {c.reason for c in res.configs} == {"model not transformed: TOYFF: nested generate"}


X_GEN = """
def gen(ctx):
    b = ctx.dut("xd", INIT=0)
    b.set(D="x")
    b.cycle("C")
    yield b.build()
    b = ctx.dut("ok", INIT=1)
    b.cycle("C")
    yield b.build()
"""


def test_x_stimulus_is_an_error_on_verilator(ctx, toy, no_container, monkeypatch, work):
    from test_runner_base import _tmp_toy

    case = _tmp_toy(work, X_GEN)
    _python(ctx, case)
    _fake_ensure(monkeypatch, _entry("unsupported", reason="stop here"))
    res = VerilatorRunner().run(case, ctx)
    got = {c.cfg: c.reason for c in res.configs}
    assert got["xd"] == X_STIMULUS == "2-state simulator cannot apply x stimulus"
    assert got["ok"].startswith("verilatorize cannot transform")  # x-free: gated as usual


def test_x_stimulus_is_skipped_when_declared_unsupported(ctx, toy, no_container, work):
    from test_runner_base import _tmp_toy

    case = _tmp_toy(work, X_GEN)
    _python(ctx, case)
    case = dataclasses.replace(
        case,
        runners={**case.runners, "verilator": "unsupported"},
        unsupported_reasons={**case.unsupported_reasons, "verilator": "x inputs"},
    )
    assert VerilatorRunner().run(case, ctx).status == "skip"
    assert IverilogVzRunner().run(case, ctx).status == "skip"


# --- ensure_model (the transform runs on the host; the check is faked) ------------------


@pytest.fixture
def vzsrc(tmp_path):
    uni = tmp_path / "src" / "unisims"
    uni.mkdir(parents=True)
    shutil.copy(VZ_FIX / "glbl.v", tmp_path / "src" / "glbl.v")
    shutil.copy(VZ_FIX / "vz_generate.v", uni / "VZGEN.v")
    shutil.copy(VZ_FIX / "vz_bad_select.v", uni / "VZBADSEL.v")
    (uni / "PLAIN.v").write_text(
        "// SPDX-License-Identifier: Apache-2.0\nmodule PLAIN (output O, input I);\n"
        "  assign O = I;\nendmodule\n"
    )
    return ModelSource("vz-src", tmp_path / "src")


def _fake_check(monkeypatch, status: str = "pass", reason: str = "", tools: str = "T1") -> list:
    calls = []
    lock = threading.Lock()
    monkeypatch.setattr(driver, "sim_tools", lambda ms, work: tools)

    def fake(an, ms, out_dir, attrs=None, *, lib=None, seed=1, force_xsim=False):
        from xut.verilatorize.equiv import config_key

        with lock:
            calls.append((an.model, dict(attrs or {}), Path(lib)))
        return EquivResult(an.model, status, reason, config=config_key(attrs), oracle="iverilog")

    monkeypatch.setattr("xut.verilatorize.equiv.check_model", fake)
    return calls


def test_ensure_model_transforms_on_demand_under_the_run_root(vzsrc, tmp_path, monkeypatch):
    calls = _fake_check(monkeypatch)
    lines = []
    e = ensure_model(vzsrc, "PLAIN", {}, root=tmp_path, log=lines.append)
    out = vz_dir(vzsrc, tmp_path)
    assert out == tmp_path / "build/verilatorized/vz-src"
    assert e.status == "unchanged" and calls == []
    assert (out / "manifest.json").is_file() and lines[0].startswith("progress: done=0")
    bad = ensure_model(vzsrc, "VZBADSEL", {}, root=tmp_path, log=lines.append)
    assert bad.status == "unsupported" and "select" in bad.reason and calls == []
    # only the requested models were transformed
    assert sorted(driver.Manifest.load(out / "manifest.json").models) == ["PLAIN", "VZBADSEL"]


def test_ensure_model_checks_each_configuration_once_and_records_it(vzsrc, tmp_path, monkeypatch):
    calls = _fake_check(monkeypatch, "fail", "1 mismatch(es) against the original on iverilog")
    out = vz_dir(vzsrc, tmp_path)
    e = ensure_model(vzsrc, "VZGEN", {"IS_C_INVERTED": 1}, root=tmp_path, log=print)
    assert e.status == "transformed" and (out / "VZGEN.v").is_file()
    assert calls == [("VZGEN", {"IS_C_INVERTED": "1'b1"}, out)]
    # the same configuration spelled as a literal, and a testbench-only parameter: no recheck
    ensure_model(vzsrc, "VZGEN", {"IS_C_INVERTED": "1'b1", "TB_ONLY": 3}, root=tmp_path)
    assert len(calls) == 1
    ensure_model(vzsrc, "VZGEN", {}, root=tmp_path, log=print)
    assert [c[1] for c in calls] == [{"IS_C_INVERTED": "1'b1"}, {}]
    man = driver.Manifest.load(out / "manifest.json").models["VZGEN"]
    assert man.equiv == {"IS_C_INVERTED=1'b1": "fail", "default": "fail"}
    assert man.equiv_reason["default"].startswith("1 mismatch(es)")
    assert man.equiv_oracle["default"] == "iverilog"
    assert man.equiv_tools == {"IS_C_INVERTED=1'b1": "T1", "default": "T1"}
    assert blocked(man, "VZGEN", "default").startswith("transform-bug: ")


def test_ensure_model_is_safe_from_many_threads(vzsrc, tmp_path, monkeypatch):
    calls = _fake_check(monkeypatch)
    transforms = []
    real = driver.verilatorize

    def counting(*a, **kw):
        transforms.append(a[1])
        return real(*a, **kw)

    monkeypatch.setattr(driver, "verilatorize", counting)
    errors = []

    def one(i: int) -> None:
        try:
            m = ("VZGEN", "PLAIN")[i % 2]
            ensure_model(vzsrc, m, {"IS_C_INVERTED": i % 4 // 2} if m == "VZGEN" else {},
                         root=tmp_path, log=lambda s: None)  # fmt: skip
        except Exception as e:  # reported below
            errors.append(e)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(map(tuple, transforms)) == [("PLAIN",), ("VZGEN",)]
    # IS_C_INVERTED=0 is the default configuration (canonical keys, review M5)
    assert sorted(c[1].get("IS_C_INVERTED", "-") for c in calls) == ["-", "1'b1"]
    man = driver.Manifest.load(vz_dir(vzsrc, tmp_path) / "manifest.json")
    assert man.models["VZGEN"].equiv == {"default": "pass", "IS_C_INVERTED=1'b1": "pass"}


def test_model_attrs_keeps_declared_parameters_as_literals(vzsrc):
    assert model_attrs(vzsrc, "VZGEN", {"IS_C_INVERTED": 1, "OTHER": "x"}) == {
        "IS_C_INVERTED": "1'b1"
    }
    # a value equal to the default is the default configuration (review M5)
    assert model_attrs(vzsrc, "VZGEN", {"IS_C_INVERTED": 0}) == {}
    assert model_attrs(vzsrc, "VZGEN", {"IS_C_INVERTED": "1'b0"}) == {}
    assert model_attrs(vzsrc, "VZGEN", None) == {}


# --- container: the toy fixtures on Verilator --------------------------------------------


@pytest.mark.container
def test_vector_toyff_passes_with_two_x_seeds(ctx, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = VerilatorRunner().run(case, ctx)
    d = workdir(ctx, "verilator", case.id)
    assert res.status == "pass", (res.reason, _log(ctx, "verilator", case))
    data = _result(d)
    stim = data["seeds"]["stimulus"]
    assert data["seeds"]["x"] == list(x_seeds(stim)) and len(set(data["seeds"]["x"])) == 2
    assert data["x_dependence"] is False
    assert data["tools"]["verilator"].startswith("Verilator 5.")
    for cfg in ("init0", "init1"):
        cd = d / f"cfg-{cfg}"
        assert json.loads((cd / "xdep.json").read_text()) == {
            "x_dependence": False,
            "seeds": list(x_seeds(stim)),
            "mismatches": [],
        }
        for s in x_seeds(stim):
            assert (cd / f"xseed-{s}" / "raw.txt").is_file()
        assert (cd / "obj" / "simx").is_file() and (cd / "build.log").is_file()
        assert xtr.load(cd / "trace.xtr").header["runner"] == "verilator"
    man = driver.Manifest.load(vz_dir(ctx.model_source, ctx.root) / "manifest.json")
    assert man.models["TOYFF"].status == "unchanged"
    # the companion: Icarus on the verilatorized directory
    vz = IverilogVzRunner().run(case, ctx)
    assert vz.status == "pass", (vz.reason, _log(ctx, "iverilog-vz", case))
    assert str(vz_dir(ctx.model_source, ctx.root).name) in _log(ctx, "iverilog-vz", case)


UNINIT = """\
// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module TOYFF #(parameter [0:0] INIT = 1'b0) (output wire Q, input wire C, input wire D);
  reg [31:0] u;  // never written: its value is the X-initialisation seed's
  assign Q = ^u;
endmodule
"""


@pytest.mark.container
def test_uninitialised_output_is_x_dependence_but_a_masked_bit_still_passes(work, toy):
    ms = make_model_source(work / "ms")
    (ms.unisims / "TOYFF.v").write_text(UNINIT)
    case = dataclasses.replace(_case("7series.TOYFF.L1.capture"))
    ctx = RunContext(work, "rtl", ms, seed=3)
    _python(ctx, case)
    for exp in python_dir(ctx, case).glob("cfg-*/expected.xtr"):
        t = xtr.load(exp)
        for label in t.samples:
            t.samples[label]["Q"] = "-"
            t.prov.get(label, {}).pop("Q", None)
        xtr.dump(t, exp)
    res = VerilatorRunner().run(case, ctx)
    d = workdir(ctx, "verilator", case.id)
    assert res.status == "pass", (res.reason, _log(ctx, "verilator", case))
    data = _result(d)
    assert data["x_dependence"] is True, [
        (d / f"cfg-{c}" / "xdep.json").read_text() for c in ("init0", "init1")
    ]
    xd = json.loads((d / "cfg-init0/xdep.json").read_text())
    assert xd["x_dependence"] and xd["mismatches"]


@pytest.mark.container
def test_xut_run_verilator_also_runs_iverilog_vz(work, toy, monkeypatch):
    _copy_toy(work)
    ms = make_model_source(work / "ms")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: work)
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": ms)
    args = ["run", "--runner", "python", "--runner", "verilator", "7series.TOYFF.L1.capture"]
    r = CliRunner().invoke(main, args)
    assert r.exit_code == 0, r.output
    for runner in ("verilator", "iverilog-vz"):
        d = work / "build/rtl" / runner / "toyff-test/7series.TOYFF.L1.capture"
        assert _result(d)["status"] == "pass", runner
    summary = json.loads((work / "build/rtl/summary-toyff-test.json").read_text())
    assert {x["runner"] for x in summary["results"]} == {"python", "verilator", "iverilog-vz"}


@pytest.fixture
def shared_toy(monkeypatch):
    from test_runner_cocotb import _shared_dirs

    monkeypatch.setattr(TestCase, "shared_dirs", property(_shared_dirs))
    monkeypatch.setattr("xut.catalog.model.load_entry", lambda family, name, root: TOY_ENTRY)


@pytest.mark.container
def test_cocotb_toyff_passes_on_verilator_and_iverilog_vz(ctx, shared_toy):
    case = dataclasses.replace(_case("7series.TOYFF.L2.cocotb_capture"))
    res = VerilatorRunner().run(case, ctx)
    d = workdir(ctx, "verilator", case.id)
    assert res.status == "pass", (res.reason, _log(ctx, "verilator", case))
    data = _result(d)
    seeds = list(x_seeds(data["seeds"]["stimulus"]))
    assert data["seeds"]["x"] == seeds and data["x_dependence"] is False
    for cfg in ("init0", "init1"):
        for s in seeds:
            plus = f"XUT_COCOTB plusargs: +verilator+seed+{s} +verilator+rand+reset+2"
            assert plus in (d / f"cfg-{cfg}/xseed-{s}/run.log").read_text()
        t = xtr.load(d / f"cfg-{cfg}/trace.xtr")
        assert t.header["runner"] == "verilator" and len(t.samples) == 20
    vz = IverilogVzRunner().run(case, ctx)
    assert vz.status == "pass", (vz.reason, _log(ctx, "iverilog-vz", case))


@pytest.mark.container
def test_sv_toyff_passes_on_verilator(ctx):
    """glbl as a second top: the DUT's glbl.GSR and the testbench's glbl.GSR_int writes."""
    case = _case("7series.TOYFF.L1.sv_basic")
    res = VerilatorRunner().run(case, ctx)
    d = workdir(ctx, "verilator", case.id)
    assert res.status == "pass", (res.reason, _log(ctx, "verilator", case))
    t = xtr.load(d / "trace.xtr")
    assert t.samples == {"default/after_gsr": {"Q": "1"}, "default/after_clk": {"Q": "0"}}
    assert _result(d)["x_dependence"] is False
    assert "XUT_GLBL_INSTANCE" not in (d / "cfg-default/build.log").read_text()


@pytest.mark.container
def test_reject_config_on_verilator(ctx, toy):
    """TOYFF's L0 reject drives INIT=1'bx. Verilator keeps the x literal of the parameter,
    the model's own check fires at run time, and the shared reject rule passes it on that
    evidence (review M6: the observed outcome is pinned); no X-seed comparison."""
    case = _case("7series.TOYFF.L0.reject")
    _python(ctx, case)
    res = VerilatorRunner().run(case, ctx)
    d = workdir(ctx, "verilator", case.id)
    log = _log(ctx, "verilator", case)
    assert res.status == "pass", (res.reason, log)
    [c] = res.configs
    assert c.reason.startswith("rejected at runtime: Attribute Syntax Error: INIT"), c.reason
    assert not list(d.glob("cfg-*/xdep.json")) and _result(d)["x_dependence"] is None


ZCMP = """\
// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module TOYFF #(parameter [0:0] INIT = 1'b0) (output wire Q, input wire C, input wire D);
  reg q;
  always @(posedge C or posedge glbl.GSR)
    if (glbl.GSR) q <= INIT;
    else if (D !== 1'bz) q <= D;  // an input compared with z, as the FD* models do
  assign Q = q;
endmodule
"""


@pytest.mark.container
def test_input_compared_with_z_passes_after_the_z_compare_rewrite(work, toy):
    """Ruling S38: the input's z-compare is rewritten, so Verilator builds the model
    (S35.3 found it could not) and the result is a pass, as on Icarus."""
    ms = make_model_source(work / "ms")
    (ms.unisims / "TOYFF.v").write_text(ZCMP)
    ctx = RunContext(work, "rtl", ms)
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    for runner in (VerilatorRunner, IverilogVzRunner, IverilogRunner):
        res = runner().run(case, ctx)
        assert res.status == "pass", (runner.name, res.reason, _log(ctx, runner.name, case))
    e = driver.Manifest.load(vz_dir(ms, work) / "manifest.json").models["TOYFF"]
    assert (e.rewrites, e.equiv) == (["zcmp"], {"default": "pass", "INIT=1'b1": "pass"})
    assert "1'bz" not in (vz_dir(ms, work) / "TOYFF.v").read_text()


@pytest.mark.container
def test_z_compare_in_enabled_disabled_code_is_the_inherent_tristate_error(work, toy):
    """A z-compare the syntax tree cannot see (preprocessor-disabled code, here enabled by
    a define) still reaches Verilator: the runner explains the inherent error (S35.3)."""
    ms = make_model_source(work / "ms")
    (ms.unisims / "TOYFF.v").write_text(
        ZCMP.replace(
            "    else if (D !== 1'bz) q <= D;",
            "`ifdef XUT_ZDEMO\n    else if (D !== 1'bz) q <= D;\n`else\n    else q <= D;\n`endif",
        )
    )
    ctx = RunContext(work, "rtl", ms, defines={"XUT_ZDEMO": ""})
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = VerilatorRunner().run(case, ctx)
    assert res.status == "error"
    for c in res.configs:
        assert "Unsupported: tristate in top-level IO: 'D'" in c.reason and "inherent" in c.reason
    assert IverilogRunner().run(case, ctx).status == "pass"  # the model itself is fine


# --- Task 13 review M3: a VPI release coincident with a clock edge -----------------------

VZTRIG_ENTRY = CatalogEntry(
    name="VZTRIG",
    family="7series",
    group="REGISTER",
    subgroup="SDR",
    description="verilatorize fixture: several triggers, glbl.GSR among them",
    doc={"guide": "UG953", "edition": "2026.1", "page": 1},
    model={"library": "unisims", "file": "VZTRIG.v"},
    ports=[
        {"name": "Q", "direction": "output", "width": 1, "cls": "data", "doc_function": "Q"},
        {"name": "C", "direction": "input", "width": 1, "cls": "clock", "doc_function": "C"},
        {"name": "D", "direction": "input", "width": 1, "cls": "data", "doc_function": "D"},
        {"name": "CLR", "direction": "input", "width": 1, "cls": "async", "doc_function": "CLR"},
        {"name": "PRE", "direction": "input", "width": 1, "cls": "async", "doc_function": "PRE"},
    ],
    attributes=[],
)

VZTRIG_YAML = """\
# SPDX-License-Identifier: Apache-2.0
primitive: VZTRIG
family: 7series
work_unit: toy
doc_refs: [{guide: UG953, version: "2026.1", section: VZTRIG, page: 1}]
tests:
  - id: 7series.VZTRIG.L1.release_on_edge
    level: L1
    style: vector
    source: vectors/gen.py:gen
    exercises: []
    attr_sampling: {}
    runners:
      {python: "yes", xsim: "unsupported", iverilog: "yes", verilator: "yes", hw: "unsupported"}
    unsupported_reasons: {xsim: "fixture", hw: "fixture"}
    flows: [rtl]
    related: []
    gaps: []
  - id: 7series.VZTRIG.L2.cocotb_release_on_edge
    level: L2
    style: cocotb
    source: cocotb/cocotb_vztrig.py
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


def _release_vec(m) -> xvec.Vec:
    """The cocotb fixture's sequence as a vector stimulus: each coincident step is one
    input change plus the rising edge (``simultaneous``)."""
    b = VecBuilder(m, seed=1)
    b.set(D=1)
    b.async_("CLR", 1)
    b.sample("forced")
    for label, port, after in (("rel_edge_a", "CLR", "clr2"), ("rel_edge_b", "CLR", None)):
        with b.simultaneous():
            b.async_(port, 0)
            b.edge("C", True)
        b.sample(label)
        b.edge("C", False)
        if after:
            b.async_("CLR", 1)
            b.sample(after)
    b.set(D=0)
    b.async_("PRE", 1)
    b.sample("pre")
    with b.simultaneous():
        b.async_("PRE", 0)
        b.edge("C", True)
    b.sample("rel_edge_c")
    b.edge("C", False)
    b.async_("PRE", 1)
    b.async_("PRE", 0)
    b.sample("retain")
    b.edge("C", True)
    b.sample("after")
    return b.build()


def _fake_python_run(ctx: RunContext, case: TestCase, expected: dict[str, str]) -> None:
    """The python run's directory for VZTRIG (no golden model): its wrapper, stimulus and
    the expected trace ``expected`` (label -> Q)."""
    d = python_dir(ctx, case)
    cd = d / "cfg-default"
    m = write_dut(spec_from_catalog(VZTRIG_ENTRY, "default", {}), cd / "dut")
    xvec.dump(_release_vec(m), cd / "stim.xvec")
    t = xtr.Trace({"runner": "python", "flow": "rtl", "model": "golden", "seed": "1"})
    for label, q in expected.items():
        t.add(label, {"Q": q})
    xtr.dump(t, cd / "expected.xtr")
    (d / "configs.json").write_text('["default"]\n')


@pytest.mark.container
def test_vpi_release_coincident_with_an_edge_matches_the_vector_testbench(work, monkeypatch):
    """Task 13 review M3 / ruling S35.4, on the transformed deassign fixture VZTRIG: a
    release written through cocotb/VPI in the same step as a rising edge (either write
    order) gives the same Q as the vector testbench's blocking drive, on Verilator, and
    both match the original model on Icarus."""
    from test_runner_cocotb import _shared_dirs

    sys_path = VL_FIX / "cocotb_vztrig.py"
    expected = dict(
        line.split(": ")
        for line in textwrap.dedent("""\
            forced: 0
            rel_edge_a: 1
            clr2: 0
            rel_edge_b: 1
            pre: 1
            rel_edge_c: 0
            retain: 1
            after: 0""").splitlines()
    )
    tdir = work / "tests/7series/register/VZTRIG"
    (tdir / "cocotb").mkdir(parents=True)
    (tdir / "vectors").mkdir()
    (tdir / "test.yaml").write_text(VZTRIG_YAML)
    (tdir / "vectors/gen.py").write_text("# SPDX-License-Identifier: Apache-2.0\n")
    shutil.copy(sys_path, tdir / "cocotb/cocotb_vztrig.py")
    src = work / "ms"
    (src / "unisims").mkdir(parents=True)
    shutil.copy(VZ_FIX / "vz_trig.v", src / "unisims/VZTRIG.v")
    shutil.copy(VZ_FIX / "glbl.v", src / "glbl.v")
    ms = ModelSource("vztrig-test", src)
    ctx = RunContext(work, "rtl", ms)
    monkeypatch.setattr(TestCase, "shared_dirs", property(_shared_dirs))
    monkeypatch.setattr("xut.catalog.model.load_entry", lambda f, n, r: VZTRIG_ENTRY)
    vec_case, coco = discover(work)
    _fake_python_run(ctx, vec_case, expected)

    orig = IverilogRunner().run(vec_case, ctx)  # the original model: expected is its truth
    assert orig.status == "pass", (orig.reason, _log(ctx, "iverilog", vec_case))
    res = {}
    for runner in (VerilatorRunner, IverilogVzRunner):
        for case in (vec_case, coco):
            r = runner().run(case, ctx)
            res[(runner.name, case.style)] = r
            assert r.status == "pass", (
                runner.name,
                case.id,
                r.reason,
                _log(ctx, runner.name, case),
            )
    man = driver.Manifest.load(vz_dir(ms, work) / "manifest.json").models["VZTRIG"]
    assert man.status == "transformed" and man.equiv == {"default": "pass"}
    d = workdir(ctx, "verilator", coco.id)
    got = {k.removeprefix("default/"): v["Q"] for k, v in xtr.load(d / "trace.xtr").samples.items()}
    assert got == expected
    vd = workdir(ctx, "verilator", vec_case.id)
    vgot = {
        k.removeprefix("default/"): v["Q"] for k, v in xtr.load(vd / "trace.xtr").samples.items()
    }
    assert vgot == expected


def test_ensure_model_rechecks_stale_verdicts_as_check_does(vzsrc, tmp_path, monkeypatch):
    """Concern 2 / ruling S38: a kept pass/fail is rechecked when the simulators changed; an
    error is rechecked (once per process); a current pass is kept."""
    calls = _fake_check(monkeypatch, "error", "DRC")
    ensure_model(vzsrc, "VZGEN", {}, root=tmp_path, log=print)
    ensure_model(vzsrc, "VZGEN", {}, root=tmp_path, log=print)  # once per process
    assert len(calls) == 1
    for name, value in (("_ENTRIES", {}), ("_CHECKED", set()), ("_TOOLS", {})):
        monkeypatch.setattr(driver, name, value)
    calls = _fake_check(monkeypatch, "pass")
    ensure_model(vzsrc, "VZGEN", {}, root=tmp_path, log=print)  # the error is rechecked
    assert len(calls) == 1
    for name, value in (("_ENTRIES", {}), ("_CHECKED", set()), ("_TOOLS", {})):
        monkeypatch.setattr(driver, name, value)
    calls = _fake_check(monkeypatch, "pass")
    ensure_model(vzsrc, "VZGEN", {}, root=tmp_path, log=print)  # current pass: kept
    assert calls == []
    for name, value in (("_ENTRIES", {}), ("_CHECKED", set()), ("_TOOLS", {})):
        monkeypatch.setattr(driver, name, value)
    calls = _fake_check(monkeypatch, "pass", tools="T2")
    e = ensure_model(vzsrc, "VZGEN", {}, root=tmp_path, log=print)  # other simulators
    assert len(calls) == 1 and e.equiv_tools["default"] == "T2"
    man = driver.Manifest.load(vz_dir(vzsrc, tmp_path) / "manifest.json").models["VZGEN"]
    assert (man.equiv["default"], man.equiv_tools["default"]) == ("pass", "T2")


ZTOY = """\
// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module TOYFF #(parameter [0:0] INIT = 1'b0) (output wire Q, input wire C, input wire D,
                                             input wire E);
  reg q;
  always @(posedge C or posedge glbl.GSR)
    if (glbl.GSR) q <= INIT;
    else if (E || (E === 1'bz)) q <= D;  // E defaults to enabled when unconnected
  assign Q = q;
endmodule
"""


def test_an_unconnected_input_of_a_z_compare_model_is_an_error(
    work, toy, no_container, monkeypatch
):
    """TOY_ENTRY has no port E, so the wrapper leaves it unconnected: the z-compare
    rewrite would turn the floating-input default into "disabled" (ruling S38 guard)."""
    ms = make_model_source(work / "ms")
    (ms.unisims / "TOYFF.v").write_text(ZTOY)
    ctx = RunContext(work, "rtl", ms)
    _fake_check(monkeypatch)
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    for runner in (VerilatorRunner, IverilogVzRunner):
        res = runner().run(case, ctx)
        assert res.status == "error", runner.name
        assert all("input port(s) E of TOYFF left unconnected" in c.reason for c in res.configs)
    e = driver.Manifest.load(vz_dir(ms, work) / "manifest.json").models["TOYFF"]
    assert e.rewrites == ["zcmp"]


Z_GEN = """
def gen(ctx):
    b = ctx.dut("zd", INIT=0)
    b.set(D="z")
    b.cycle("C")
    yield b.build()
"""


def test_a_z_stimulus_into_a_z_compare_model_is_an_error_on_iverilog_vz(
    work, toy, no_container, monkeypatch
):
    from test_runner_base import _tmp_toy

    ms = make_model_source(work / "ms")
    (ms.unisims / "TOYFF.v").write_text(ZCMP)
    ctx = RunContext(work, "rtl", ms)
    _fake_check(monkeypatch)
    case = _tmp_toy(work, Z_GEN)
    PythonRunner().run(case, ctx)
    res = IverilogVzRunner().run(case, ctx)
    assert [c.reason for c in res.configs] == [
        "stimulus drives z into a model with the z-compare rewrite (ruling S38)"
    ]
    assert VerilatorRunner().run(case, ctx).configs[0].reason == X_STIMULUS


# --- review I1/I2: the sv guard and gate on the elaborated testbench -----------------------

SV_BODY = """\
// SPDX-License-Identifier: Apache-2.0
// included by tb_toy_inc.sv, which defines PRIM (the flops testbench layout)
`include "xut_trace.svh"
reg c = 1'b0, d = 1'b0, e = 1'b1;
wire q0, q1;
`PRIM #(.INIT(1'b0)) u0 (.Q(q0), .C(c), .D(d), .E(e));
`PRIM #(.INIT(1'b1)) u1 (.Q(q1), .C(c), .D(d), .E(e));
initial begin
  #120000;
  `XUT_CHECK("gsr", q1, 1'b1)
  `XUT_POINT1("after_gsr", "Q", q1)
  xut_finish;
end
"""


def _sv_tree(work: Path, body: str = SV_BODY) -> TestCase:
    """TOYFF's sv test as the flops layout: the testbench defines PRIM and includes its
    body from the unit's _shared dir (found through TestCase.shared_dirs)."""
    d = _copy_toy(work)
    (d / "sv/tb_toy_inc.sv").write_text(
        "// SPDX-License-Identifier: Apache-2.0\n`timescale 1ps / 1ps\n"
        '`define PRIM TOYFF\nmodule tb_toy_inc;\n`include "toy_body.svh"\nendmodule\n'
    )
    shared = work / "tests/7series/register/_shared/toy"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "toy_body.svh").write_text(body)
    sv = next(c for c in discover(work) if c.id == "7series.TOYFF.L1.sv_basic")
    return dataclasses.replace(sv, source="sv/tb_toy_inc.sv")


@pytest.fixture
def ztoy(work, monkeypatch):
    """A gated TOYFF (its E input defaults through a z-compare) and the Task 18 shared dirs."""
    from test_runner_cocotb import _shared_dirs

    monkeypatch.setattr(TestCase, "shared_dirs", property(_shared_dirs))
    ms = make_model_source(work / "ms")
    (ms.unisims / "TOYFF.v").write_text(ZTOY)
    return RunContext(work, "rtl", ms)


def test_sv_instances_are_found_through_includes_and_macros(work, ztoy):
    from xut.runners.verilator import sv_instances

    insts = sv_instances(_sv_tree(work), ztoy, "TOYFF", 5)
    assert [(i.path, i.attrs, i.undriven, i.zdriven) for i in insts] == [
        ("tb_toy_inc.u0", {"INIT": 0}, [], []),
        ("tb_toy_inc.u1", {"INIT": 1}, [], []),
    ]


@pytest.mark.parametrize(
    ("old", "new", "why"),
    [
        (", .E(e));\n`PRIM #(.INIT(1'b1))", ");\n`PRIM #(.INIT(1'b1))",
         "tb_toy_inc.u0: input port(s) E of TOYFF not driven"),
        (".E(e));\ninitial", ".E());\ninitial", "tb_toy_inc.u1: input port(s) E of TOYFF"),
        (".E(e));\ninitial", ".E(1'bz));\ninitial", "E (tied to z)"),
        ("reg c", "localparam ZP = 1'bz;\nreg c", None),
    ],
)  # fmt: skip
def test_sv_guard_sees_an_input_left_open_in_an_included_file(
    work, ztoy, no_container, monkeypatch, old, new, why
):
    """Review I1: the mutant leaves E (defaulted by a z-compare) open inside the included
    .svh; the S38 guard must refuse it on both runners."""
    body = SV_BODY.replace(old, new)
    if why is None:  # a z-valued parameter tied to the port
        body = body.replace(".E(e));\ninitial", ".E(ZP));\ninitial")
        why = "E (tied to z)"
    case = _sv_tree(work, body)
    _fake_check(monkeypatch)
    for runner in (VerilatorRunner, IverilogVzRunner):
        res = runner().run(case, ztoy)
        assert res.status == "error", (runner.name, res.reason)
        assert why in res.configs[0].reason, res.configs[0].reason


def test_sv_gate_checks_every_instantiated_parameterisation(work, ztoy, no_container, monkeypatch):
    """Review I2: the testbench instantiates INIT=0 and INIT=1; test.yaml's configuration
    has no attributes. Both are checked, and a failing INIT=1 verdict blocks Verilator."""
    case = _sv_tree(work)
    calls = _fake_check(monkeypatch, "pass")
    import xut.verilatorize.equiv as equiv

    passing = equiv.check_model

    def split(an, ms, out_dir, attrs=None, **kw):
        r = passing(an, ms, out_dir, attrs, **kw)
        if attrs:
            r.status, r.reason = "fail", "3 mismatch(es) against the original on iverilog"
        return r

    monkeypatch.setattr(equiv, "check_model", split)
    res = VerilatorRunner().run(case, ztoy)
    assert res.status == "error"
    assert res.configs[0].reason.startswith(
        "transform-bug: Icarus equivalence fail for TOYFF INIT=1'b1"
    ), res.configs[0].reason
    assert sorted(str(c[1]) for c in calls) == ["{'INIT': \"1'b1\"}", "{}"]


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (
            "".join(ln for ln in SV_BODY.splitlines(True) if "`PRIM" not in ln),
            "no instance of TOYFF found",
        ),
        (SV_BODY.replace(".E(e)", ".NOPE(e)"), "does not elaborate"),
        (SV_BODY.replace("`PRIM", "OTHER"), "unknown module 'OTHER'"),
    ],
)
def test_sv_guard_fails_closed(work, ztoy, no_container, monkeypatch, body, why):
    _fake_check(monkeypatch)
    res = VerilatorRunner().run(_sv_tree(work, body), ztoy)
    assert res.status == "error" and why in res.configs[0].reason, res.configs[0].reason


def test_sv_on_an_ungated_model_needs_no_instances(ctx, no_container, monkeypatch):
    """TOYFF's own sv fixture instantiates its own flop, not TOYFF: an ungated model needs
    neither verdicts nor the guard, so nothing fails closed (the run then builds)."""
    from xut.runners.verilator import gate_config

    case = _case("7series.TOYFF.L1.sv_basic")
    assert gate_config(case, "default", ctx, 1, lambda _l: None, verdicts=True) is None


TOYSUB_PARENT = """\
// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module TOYFF #(parameter [0:0] INIT = 1'b0) (output wire Q, input wire C, input wire D);
  TOYSUB #(.INIT(INIT)) u (.Q(Q), .C(C), .D(D));
endmodule
"""


@pytest.mark.container
def test_parent_over_a_transformed_child_on_the_runners(work, toy):
    """Review C1 end to end: TOYFF itself needs no rewrite, but its TOYSUB compares D with
    z. The runners gate TOYFF on the hierarchy's equivalence and build it over the vz
    TOYSUB, whatever ran before."""
    ms = make_model_source(work / "ms")
    (ms.unisims / "TOYFF.v").write_text(TOYSUB_PARENT)
    (ms.unisims / "TOYSUB.v").write_text(ZCMP.replace("module TOYFF", "module TOYSUB"))
    ctx = RunContext(work, "rtl", ms)
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    for runner in (VerilatorRunner, IverilogVzRunner):
        res = runner().run(case, ctx)
        assert res.status == "pass", (runner.name, res.reason, _log(ctx, runner.name, case))
    e = driver.Manifest.load(vz_dir(ms, work) / "manifest.json").models
    assert (e["TOYFF"].status, e["TOYFF"].depends_on_transformed) == ("unchanged", ["TOYSUB"])
    assert e["TOYFF"].equiv == {"default": "pass", "INIT=1'b1": "pass"}
    assert sorted(f.name for f in vz_dir(ms, work).glob("*.v")) == ["TOYSUB.v"]
