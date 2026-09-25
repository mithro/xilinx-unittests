# SPDX-License-Identifier: Apache-2.0
"""The iverilog runner (vector and sv styles) and ``xut_trace.svh`` (spec §4.3, §6).

The container tests run in pytest's ``tmp_path``: the runner mounts a run root outside
the repository at /xut-root (``executor_for(..., ctx.root)``), so the container sees
every file without writing into the worktree's build/. The
vector tests use a toy model source whose ``unisims/TOYFF.v`` is written here: no
UNISIM model is needed.
"""

import dataclasses
import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from xut import schemas
from xut.cli import main
from xut.container import DockerExecutor
from xut.formats import xtr
from xut.modelsrc import ModelSource
from xut.runners import RUNNERS
from xut.runners.base import RunContext, workdir
from xut.runners.iverilog import IverilogRunner, IverilogVzRunner, param_value
from xut.runners.python import PythonRunner
from xut.runners.sim import HDL, ParamError, sv_check
from xut.testspec import TestCase, discover

FIX = Path(__file__).parent / "fixtures"
TOY_DIR = FIX / "tests/7series/register/TOYFF"
TB_DIR = FIX / "tb"

REJECT_LINE = (
    "  initial if (INIT !== 1'b0 && INIT !== 1'b1) begin\n"
    '    $display("Attribute Syntax Error: INIT=%b", INIT);\n'
    "    $finish;\n"
    "  end\n"
)


def toyff_model(reject: bool = True) -> str:
    """A plain DFF with a glbl.GSR preset to INIT; optionally rejects an illegal INIT."""
    return (
        "// SPDX-License-Identifier: Apache-2.0\n"
        "`timescale 1ps / 1ps\n"
        "module TOYFF #(parameter [0:0] INIT = 1'b0) (output wire Q, input wire C, "
        "input wire D);\n" + (REJECT_LINE if reject else "") + "  reg q;\n"
        "  always @(posedge C or posedge glbl.GSR)\n"
        "    if (glbl.GSR) q <= INIT;\n"
        "    else q <= D;\n"
        "  assign Q = q;\n"
        "endmodule\n"
    )


def _toy_glbl() -> str:
    """toy_dut.v's glbl module, as the toy model source's glbl.v."""
    text = (TB_DIR / "toy_dut.v").read_text()
    return (
        "// SPDX-License-Identifier: Apache-2.0\n`timescale 1ps / 1ps\n"
        + text[text.index("module glbl;") :]
    )


def make_model_source(d: Path, reject: bool = True) -> ModelSource:
    (d / "unisims").mkdir(parents=True)
    (d / "unisims/TOYFF.v").write_text(toyff_model(reject))
    (d / "glbl.v").write_text(_toy_glbl())
    return ModelSource("toyff-test", d)


def test_toy_glbl_is_toy_duts():
    assert "module glbl;" in _toy_glbl() and "GSR_int" in _toy_glbl()


@pytest.fixture
def ctx(work):
    return RunContext(work, "rtl", make_model_source(work / "ms"))


def _case(tid: str, root: Path = FIX) -> TestCase:
    return next(c for c in discover(root) if c.id == tid)


def _result(d: Path) -> dict:
    data = json.loads((d / "result.json").read_text())
    schemas.validate(data, "result")
    return data


def _copy_toy(root: Path) -> Path:
    d = root / "tests/7series/register/TOYFF"
    shutil.copytree(TOY_DIR, d, ignore=shutil.ignore_patterns("__pycache__"))
    return d


# --- no container needed ---------------------------------------------------------------


def test_registry():
    assert RUNNERS["iverilog"] is IverilogRunner
    assert IverilogRunner.name == "iverilog" and IverilogRunner.x_observable
    # the iverilog-vz stub exists but nothing can select it until Task 15
    assert IverilogVzRunner.name == "iverilog-vz" and "iverilog-vz" not in RUNNERS


HDR = {"runner": "iverilog", "flow": "rtl", "model": "m", "prim": "TOYFF", "cfg": "c", "seed": "0"}


def test_sv_check(tmp_path):
    cd = tmp_path / "cfg-c"
    cd.mkdir()
    (cd / "trace.body").write_text("a  Q=1\nb  Q=0\n")
    r = sv_check(cd, "XUT_CHECKS 2\nXUT_PASS\n", HDR)
    assert (r.status, r.reason) == ("pass", None)
    t = xtr.load(cd / "trace.xtr")
    assert t.header == HDR and t.samples == {"a": {"Q": "1"}, "b": {"Q": "0"}}
    assert r.trace_sha256
    r = sv_check(cd, "XUT_FAIL clk: got 1 expected 0 at 5\nXUT_FAIL 1 check(s) failed\n", HDR)
    assert (r.status, r.reason) == ("fail", "XUT_FAIL clk: got 1 expected 0 at 5")
    r = sv_check(cd, "nothing\n", HDR)
    assert r.status == "error" and "XUT_PASS" in r.reason


def test_sv_check_malformed_body_is_error(tmp_path):
    cd = tmp_path / "cfg-c"
    cd.mkdir()
    (cd / "trace.body").write_text("a Q=2\n")
    r = sv_check(cd, "XUT_PASS\n", HDR)
    assert r.status == "error" and "trace.body" in r.reason
    assert not (cd / "trace.xtr").exists()


@pytest.mark.parametrize(
    ("value", "out"),
    [
        ("1'b1", "1'b1"),
        ("4'hA", "4'hA"),
        (1, "1"),
        ("7", "7"),
        ("-3", "-3"),
        ('"ABC"', '"ABC"'),
        ("1.5", "1.5"),
        ("2.0e3", "2.0e3"),
        ("-0.25", "-0.25"),
        ("1e-3", "1e-3"),
        (0.5, "0.5"),
    ],
)
def test_param_value(value, out):
    assert param_value("P", value) == out


@pytest.mark.parametrize("value", ["1'bx", "4'b10z1", "8'hxF", "'bx", True, "a b", "1.", ".5"])
def test_param_value_refuses_what_icarus_cannot_take(value):
    """Icarus 12 -P rejects x/z digits and then compiles with the DEFAULT value and exit
    code 0; the runner never passes such a value (probe: test_icarus_P_*)."""
    with pytest.raises(ParamError):
        param_value("P", value)


def test_trace_include_source():
    text = (HDL / "xut_trace.svh").read_text()
    assert text.startswith("// SPDX-License-Identifier: Apache-2.0\n")
    for name in ("XUT_CHECK(", "XUT_CHECKN(", "XUT_POINT1(", "XUT_POINT2(", "xut_finish"):
        assert name in text
    assert "`ifdef XUT_GLBL_INSTANCE" in text and "glbl glbl ();" in text
    # a line comment starting with the word Verilator is a Verilator pragma (BADVLTPRAGMA)
    assert not any(ln.lstrip().startswith("// Verilator") for ln in text.splitlines())


def test_fixture_cases():
    ids = [c.id for c in discover(FIX)]
    assert ids == [
        "7series.TOYFF.L1.capture",
        "7series.TOYFF.L0.reject",
        "7series.TOYFF.L1.sv_basic",
        "7series.TOYFF.L2.cocotb_capture",
    ]
    sv = _case("7series.TOYFF.L1.sv_basic")
    assert (sv.style, sv.source, sv.configs) == (
        "sv",
        "sv/tb_toyff_basic.sv",
        [{"cfg": "default", "attrs": {}}],
    )


# --- Icarus behaviour the runner relies on ---------------------------------------------

P_TOP = (
    "// SPDX-License-Identifier: Apache-2.0\nmodule top;\n  parameter [0:0] P = 1'b0;\n"
    '  initial $display("P=%b", P);\nendmodule\n'
)


def _icarus(work: Path, *args: str) -> str:
    (work / "top.v").write_text(P_TOP)
    ex, log = DockerExecutor(root=work), work / "run.log"
    if ex.run(["iverilog", "-g2012", "-o", "s.vvp", *args, "top.v"], work, log, 120) == 0:
        ex.run(["vvp", "-n", "s.vvp"], work, log, 120)
    return log.read_text()


@pytest.mark.container
def test_icarus_P_takes_a_sized_literal(work):
    """sv tests pass attributes as -P<top>.<NAME>=<literal>; Icarus 12 takes 1'b1."""
    assert "P=1" in _icarus(work, "-Ptop.P=1'b1")


@pytest.mark.container
def test_icarus_P_x_is_an_error_but_exit_0(work):
    """Why param_value refuses x/z and the runner scans the compile log for errors:
    Icarus reports an invalid -P value but exits 0 and keeps the default."""
    log = _icarus(work, "-Ptop.P=1'bx")
    assert "error: invalid digit" in log and "P=0" in log


# --- vector style ----------------------------------------------------------------------


def _python(ctx: RunContext, case: TestCase) -> None:
    res = PythonRunner().run(case, ctx)
    assert res.status == "pass", res.reason


@pytest.mark.container
def test_vector_toyff_passes(ctx, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = IverilogRunner().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())
    t = xtr.load(d / "trace.xtr")
    assert list(t.samples) == [
        f"init{i}/{label}" for i in (0, 1) for label in ("start", "S0", "S1", "S2", "S3")
    ]
    assert t.header["runner"] == "iverilog" and t.header["model"] == "toyff-test"
    data = _result(d)
    assert data["tools"]["iverilog"].startswith("Icarus Verilog version")
    assert data["container"]["digest"].startswith("sha256:")
    assert data["defines"] == {} and data["model_source"] == "toyff-test"
    for c in data["configs"]:
        assert c["status"] == "pass" and c["mismatches"] == 0
        assert c["stimulus_sha256"] and c["trace_sha256"]
    cd = d / "cfg-init1"
    for f in ("dut/xut_dut.v", "stim.xvec", "stim.memh", "raw.txt", "trace.xtr", "sim.vvp"):
        assert (cd / f).is_file(), f
    assert (cd / "mismatches.txt").read_text() == ""
    # the expected trace and the actual one agree sample for sample
    exp = xtr.load(workdir(ctx, "python", case.id) / "cfg-init1/expected.xtr")
    assert {k: v for k, v in exp.samples.items()} == xtr.load(cd / "trace.xtr").samples


@pytest.mark.container
def test_vector_toyff_passes_under_tmp_path(tmp_path, toy):
    """A run rooted outside the checkout: executor_for mounts it at /xut-root."""
    ctx = RunContext(tmp_path, "rtl", make_model_source(tmp_path / "ms"))
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = IverilogRunner().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    # without the /xut-root mount, guest() raises for the config dir: an error result
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())


@pytest.mark.container
def test_vector_corrupted_expectation_fails(ctx, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    exp = workdir(ctx, "python", case.id) / "cfg-init1/expected.xtr"
    lines = exp.read_text().splitlines(keepends=True)
    i = next(i for i, ln in enumerate(lines) if "Q=" in ln and not ln.startswith("#"))
    lines[i] = lines[i].replace("Q=0", "Q=@").replace("Q=1", "Q=0").replace("Q=@", "Q=1")
    exp.write_text("".join(lines))
    res = IverilogRunner().run(case, ctx)
    data = _result(workdir(ctx, "iverilog", case.id))
    by = {c["cfg"]: c for c in data["configs"]}
    assert res.status == "fail"
    assert by["init1"]["status"] == "fail" and by["init1"]["mismatches"] == 1
    assert by["init0"]["status"] == "pass"
    mm = (workdir(ctx, "iverilog", case.id) / "cfg-init1/mismatches.txt").read_text()
    assert len(mm.splitlines()) == 1 and "Q" in by["init1"]["reason"]


@pytest.mark.container
def test_vector_missing_expected_trace_is_error(ctx, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    (workdir(ctx, "python", case.id) / "cfg-init0/expected.xtr").unlink()
    res = IverilogRunner().run(case, ctx)
    data = _result(workdir(ctx, "iverilog", case.id))
    by = {c["cfg"]: c for c in data["configs"]}
    assert res.status == "error"
    assert by["init0"]["status"] == "error" and "no expected trace" in by["init0"]["reason"]
    assert by["init1"]["status"] == "pass"


@pytest.mark.container
def test_vector_compile_failure_is_error(work, toy):
    ctx = RunContext(work, "rtl", make_model_source(work / "ms"))
    (work / "ms/unisims/TOYFF.v").write_text("module TOYFF(; endmodule\n")
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error"
    assert all(c.reason == "compile failed" for c in res.configs)


@pytest.mark.container
def test_vector_early_end_is_error(work, toy):
    """A model that $finishes before END: `simulation ended early`, never a pass."""
    ctx = RunContext(work, "rtl", make_model_source(work / "ms"))
    m = work / "ms/unisims/TOYFF.v"
    m.write_text(m.read_text().replace("  reg q;\n", "  reg q;\n  initial #110000 $finish;\n"))
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error"
    assert all("ended early" in c.reason for c in res.configs)


@pytest.mark.container
@pytest.mark.parametrize("reject", [True, False])
def test_reject_end_to_end(work, toy, reject):
    """Review (b) round 2, N1: python writes the reject configuration (dut, stimulus,
    header-only expected trace); iverilog passes iff the model rejects INIT=1'bx."""
    ctx = RunContext(work, "rtl", make_model_source(work / "ms", reject=reject))
    case = _case("7series.TOYFF.L0.reject")
    _python(ctx, case)
    py = workdir(ctx, "python", case.id)
    assert json.loads((py / "configs.json").read_text()) == ["init_x"]
    for f in ("dut/xut_dut.v", "stim.xvec", "expected.xtr"):
        assert (py / "cfg-init_x" / f).is_file(), f
    assert xtr.load(py / "cfg-init_x/expected.xtr").samples == {}
    res = IverilogRunner().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    log = (d / "run.log").read_text()
    if reject:
        assert res.status == "pass", log
        assert res.configs[0].reason == "rejected at runtime: Attribute Syntax Error: INIT=x"
    else:
        assert res.status == "fail"
        assert res.configs[0].reason.startswith("expected rejection, got acceptance")
    t = xtr.load(d / "cfg-init_x/trace.xtr")  # the evidence: a header-only trace
    assert t.samples == {} and t.header["expect"] == "reject" and t.header["cfg"] == "init_x"
    c = _result(d)["configs"][0]
    assert c["stimulus_sha256"] and c["trace_sha256"]


@pytest.mark.container
def test_reject_with_missing_model_is_error(work, toy):
    """Ruling S13: a build that fails for an infrastructure reason (here: no TOYFF.v)
    is an error, never a rejection."""
    ctx = RunContext(work, "rtl", make_model_source(work / "ms"))
    (work / "ms/unisims/TOYFF.v").unlink()
    case = _case("7series.TOYFF.L0.reject")
    _python(ctx, case)
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error", res.reason
    assert "Unknown module type: TOYFF" in res.configs[0].reason


@pytest.mark.container
def test_reject_silent_finish_is_error(work, toy):
    """A model that stops without saying why is not evidence of a rejection."""
    ctx = RunContext(work, "rtl", make_model_source(work / "ms"))
    m = work / "ms/unisims/TOYFF.v"
    m.write_text(m.read_text().replace('$display("Attribute Syntax Error: INIT=%b", INIT);', ""))
    case = _case("7series.TOYFF.L0.reject")
    _python(ctx, case)
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error" and "without XUT_DONE" in res.configs[0].reason


@pytest.mark.container
def test_vector_nonzero_simulator_exit_is_error(work, toy):
    ctx = RunContext(work, "rtl", make_model_source(work / "ms"))
    m = work / "ms/unisims/TOYFF.v"
    m.write_text(
        m.read_text().replace("  reg q;\n", '  reg q;\n  initial #125000 $fatal(1, "boom");\n')
    )
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error"
    assert all(c.reason.startswith("simulator exited with rc") for c in res.configs)


@pytest.mark.container
def test_vector_defines_reach_the_compiler(ctx, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    c2 = dataclasses.replace(ctx, defines={"XUT_T9_PROBE": "", "XUT_T9_VAL": "3"})
    res = IverilogRunner().run(case, c2)
    d = workdir(ctx, "iverilog", case.id)
    assert res.status == "pass"
    log = (d / "run.log").read_text()
    assert "-DXUT_T9_PROBE " in log and "-DXUT_T9_VAL=3 " in log
    assert _result(d)["defines"] == {"XUT_T9_PROBE": "", "XUT_T9_VAL": "3"}


# --- sv style ------------------------------------------------------------------------


@pytest.mark.container
def test_sv_fixture_passes(ctx):
    case = _case("7series.TOYFF.L1.sv_basic")
    res = IverilogRunner().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())
    t = xtr.load(d / "trace.xtr")
    assert t.samples == {"default/after_gsr": {"Q": "1"}, "default/after_clk": {"Q": "0"}}
    cfg_t = xtr.load(d / "cfg-default/trace.xtr")
    assert cfg_t.header["runner"] == "iverilog" and cfg_t.header["cfg"] == "default"
    data = _result(d)
    assert data["style"] == "sv" and data["tools"]["iverilog"]


@pytest.mark.container
def test_sv_fixture_passes_with_glbl_as_an_instance(ctx):
    """The XUT_GLBL_INSTANCE strategy (Verilator's fallback, Task 15): xut_trace.svh
    instantiates glbl inside the testbench, which is then the only glbl; the DUT's
    glbl.GSR and the testbench's glbl.GSR_int writes both reach it."""

    class Inst(IverilogRunner):
        glbl_instance = True

    case = _case("7series.TOYFF.L1.sv_basic")
    res = Inst().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    log = (d / "run.log").read_text()
    assert res.status == "pass", (res.reason, log)
    assert "-DXUT_GLBL_INSTANCE" in log and "-s glbl" not in log
    assert list(xtr.load(d / "trace.xtr").samples) == ["default/after_gsr", "default/after_clk"]


def _sv_variant(root: Path, old: str, new: str) -> TestCase:
    d = _copy_toy(root)
    tb = d / "sv/tb_toyff_basic.sv"
    text = tb.read_text()
    assert old in text
    tb.write_text(text.replace(old, new, 1))
    return _case("7series.TOYFF.L1.sv_basic", root)


@pytest.mark.container
def test_sv_wrong_expectation_fails(ctx, work):
    case = _sv_variant(work, '`XUT_CHECK("clk", q, 1\'b0)', '`XUT_CHECK("clk", q, 1\'b1)')
    res = IverilogRunner().run(case, ctx)
    assert res.status == "fail"
    assert res.configs[0].reason.startswith("XUT_FAIL clk: got 0 expected 1")
    # the checkpoints are still recorded
    d = workdir(ctx, "iverilog", case.id)
    assert "default/after_clk" in xtr.load(d / "trace.xtr").samples


@pytest.mark.container
def test_sv_syntax_error_is_compile_failed(ctx, work):
    case = _sv_variant(work, "wire q;", "wire q")
    res = IverilogRunner().run(case, ctx)
    assert (res.status, res.configs[0].status, res.configs[0].reason) == (
        "error",
        "error",
        "compile failed",
    )


@pytest.mark.container
def test_sv_checkpoint_at_time_0(ctx, work):
    """xut_trace.svh opens trace.body lazily: a checkpoint at time 0 is recorded."""
    case = _sv_variant(
        work, "  initial begin\n", '  initial `XUT_POINT1("t0", "Q", q)\n  initial begin\n'
    )
    res = IverilogRunner().run(case, ctx)
    assert res.status == "pass", res.reason
    d = workdir(ctx, "iverilog", case.id)
    assert xtr.load(d / "trace.xtr").samples["default/t0"] == {"Q": "x"}


@pytest.mark.container
def test_sv_dollar_error_fails(ctx, work):
    """$error does not change vvp's exit code; its ERROR: line makes the config fail."""
    case = _sv_variant(work, "    xut_finish;", '    $error("tb says no");\n    xut_finish;')
    res = IverilogRunner().run(case, ctx)
    assert res.status == "fail"
    assert (
        res.configs[0].reason.startswith("ERROR:") and "tb_toyff_basic.sv" in res.configs[0].reason
    )


@pytest.mark.container
def test_sv_nonzero_simulator_exit_is_error(ctx, work):
    case = _sv_variant(work, "    xut_finish;", '    $fatal(1, "tb gives up");')
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error" and res.configs[0].reason.startswith("simulator exited with rc")


@pytest.mark.container
def test_tools_leaves_no_stray_directory(ctx):
    IverilogRunner().run(_case("7series.TOYFF.L1.sv_basic"), ctx)
    build = ctx.root / "build"
    assert not list(build.glob(".xut-versions-*"))
    assert not list(build.glob("**/_v"))


@pytest.mark.container
def test_sv_attributes_become_top_parameters(ctx, work):
    """Each configuration's attrs are -P<stem>.<NAME>=<value>; the sized literal arrives."""
    d = _copy_toy(work)
    tb = d / "sv/tb_toyff_basic.sv"
    tb.write_text(
        tb.read_text()
        .replace("module tb_toyff_basic;", "module tb_toyff_basic;\n  parameter [0:0] EXP = 1'b0;")
        .replace('`XUT_CHECK("gsr", q, 1\'b1)', '`XUT_CHECK("gsr", q, EXP)')
    )
    case = dataclasses.replace(
        _case("7series.TOYFF.L1.sv_basic", work),
        configs=[
            {"cfg": "one", "attrs": {"EXP": "1'b1"}},
            {"cfg": "zero", "attrs": {"EXP": "1'b0"}},
        ],
    )
    res = IverilogRunner().run(case, ctx)
    by = {c.cfg: c for c in res.configs}
    assert by["one"].status == "pass", by["one"].reason
    assert by["zero"].status == "fail" and "gsr" in by["zero"].reason
    log = (workdir(ctx, "iverilog", case.id) / "cfg-one/run.log").read_text()
    assert "-Ptb_toyff_basic.EXP=1'b1" in log


@pytest.mark.container
def test_sv_x_attribute_is_error_not_default(ctx, work):
    """An attribute Icarus -P cannot express is an error with the reason, never a run
    with the default value."""
    case = dataclasses.replace(
        _case("7series.TOYFF.L1.sv_basic"),
        configs=[{"cfg": "x", "attrs": {"EXP": "1'bx"}}],
    )
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error" and "1'bx" in res.configs[0].reason


@pytest.mark.container
def test_compile_log_error_with_exit_0_is_compile_failed(ctx, work, monkeypatch):
    """Belt and braces: any `error:` from the compiler fails the compile even at exit 0."""
    monkeypatch.setattr("xut.runners.iverilog.param_value", lambda name, v: str(v))
    case = dataclasses.replace(
        _case("7series.TOYFF.L1.sv_basic"),
        configs=[{"cfg": "x", "attrs": {"EXP": "1'bx"}}],
    )
    d = _copy_toy(work)
    tb = d / "sv/tb_toyff_basic.sv"
    tb.write_text(
        tb.read_text().replace(
            "module tb_toyff_basic;", "module tb_toyff_basic;\n  parameter [0:0] EXP = 1'b0;"
        )
    )
    case = dataclasses.replace(case, test_dir=d)
    res = IverilogRunner().run(case, ctx)
    assert (res.status, res.configs[0].reason) == ("error", "compile failed")


# --- the CLI, end to end ---------------------------------------------------------------


@pytest.mark.container
def test_cli_python_then_iverilog_on_the_fixture(work, toy, monkeypatch):
    """`xut run --runner python --runner iverilog --style vector --style sv TOYFF` on a
    copy of the fixture tree (the cocotb fixture has its own demo in test_runner_cocotb)."""
    _copy_toy(work)
    ms = make_model_source(work / "ms")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: work)
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": ms)
    args = [
        "run",
        "--runner",
        "python",
        "--runner",
        "iverilog",
        "--style",
        "vector",
        "--style",
        "sv",
    ]
    r = CliRunner().invoke(main, [*args, "TOYFF"])
    assert r.exit_code == 0, r.output
    summary = json.loads((work / "build/rtl/summary.json").read_text())
    got = {(x["test_id"], x["runner"]): x["status"] for x in summary["results"]}
    assert got == {
        ("7series.TOYFF.L1.capture", "python"): "pass",
        ("7series.TOYFF.L0.reject", "python"): "pass",
        ("7series.TOYFF.L1.capture", "iverilog"): "pass",
        ("7series.TOYFF.L0.reject", "iverilog"): "pass",
        ("7series.TOYFF.L1.sv_basic", "python"): "skip",
        ("7series.TOYFF.L1.sv_basic", "iverilog"): "pass",
    }


# --- ruling S15: zero evidence is never a pass ------------------------------------------


@pytest.mark.container
def test_vector_without_samples_is_error(work, toy):
    from test_runner_base import NO_SAMPLE_GEN, _tmp_toy

    ctx = RunContext(work, "rtl", make_model_source(work / "ms"))
    case = _tmp_toy(work, NO_SAMPLE_GEN)
    assert PythonRunner().run(case, ctx).status == "error"
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error" and "no samples" in res.configs[0].reason, res.reason


# --- ruling S15(b): an sv pass needs >= 1 XUT_CHECK and >= 1 checkpoint ----------------


@pytest.mark.container
def test_sv_testbench_calling_only_xut_finish_is_error(ctx, work):
    """PR B gate (a) M1: xut_finish alone used to print XUT_PASS and pass."""
    case = _sv_variant(work, "  initial begin\n", "  initial xut_finish;\n  initial begin\n")
    res = IverilogRunner().run(case, ctx)
    d = workdir(ctx, "iverilog", case.id)
    assert res.status == "error", (res.reason, (d / "run.log").read_text())
    assert "recorded no checks/samples" in res.configs[0].reason
    assert "XUT_CHECKS 0" in (d / "run.log").read_text()


@pytest.mark.container
def test_sv_checks_without_checkpoints_is_error(ctx, work):
    case = _sv_variant(work, '`XUT_POINT1("after_gsr", "Q", q)', "")
    tb = case.test_dir / "sv/tb_toyff_basic.sv"
    tb.write_text(tb.read_text().replace('`XUT_POINT1("after_clk", "Q", q)', ""))
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error" and "recorded no checks/samples" in res.configs[0].reason
    assert "3 XUT_CHECK(s) executed, 0 checkpoint(s)" in res.configs[0].reason


@pytest.mark.container
def test_sv_checkpoints_without_checks_is_error(ctx, work):
    case = _sv_variant(work, "wire q;", "wire q;")
    tb = case.test_dir / "sv/tb_toyff_basic.sv"
    text = tb.read_text()
    for label, exp in (("gsr", "1'b1"), ("clk", "1'b0"), ("gsr_pulse", "1'b1")):
        text = text.replace(f'`XUT_CHECK("{label}", q, {exp})', "")
    tb.write_text(text)
    res = IverilogRunner().run(case, ctx)
    assert res.status == "error" and "0 XUT_CHECK(s) executed" in res.configs[0].reason
