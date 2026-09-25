# SPDX-License-Identifier: Apache-2.0
"""The xsim runner (Vivado 2025.2, native; vector and sv styles; spec §4.3, §6).

Tests marked ``vivado`` need /opt/xilinx/Vivado/2025.2 and skip, with the reason,
without it. They run in pytest's ``tmp_path`` (xsim is native; the iverilog runs of the
CLI demos mount it at /xut-root). xsim uses
Vivado's precompiled ``unisims_ver``, which has no toy TOYFF, so the toy model is
compiled into ``work`` with ``XsimRunner(extra_files=[...])`` (tests only).
"""

import dataclasses
import json
import shlex
import subprocess
import textwrap
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from test_runner_iverilog import _copy_toy, make_model_source, toyff_model
from test_stimcompile import _Fdre

from xut import schemas
from xut.cli import main
from xut.container import RunTimeout
from xut.formats import xtr
from xut.modelsrc import ModelSource
from xut.paths import VIVADO_SETTINGS, VIVADO_SRC, repo_root
from xut.runners import RUNNERS
from xut.runners.base import RunContext, workdir
from xut.runners.python import PythonRunner
from xut.runners.reject import reject_result
from xut.runners.sim import ParamError, fatal_line, sv_check
from xut.runners.xsim import (
    LIBRARY_PATH_GUARD,
    MODEL_SOURCE,
    RUN_MARKER,
    XsimRunner,
    generic_value,
    render_script,
    run_script,
    split_log,
)
from xut.testspec import TestCase, discover

FIX = Path(__file__).parent / "fixtures"
VIVADO_MS = ModelSource(MODEL_SOURCE, VIVADO_SRC)


@pytest.fixture
def ctx(work):
    return RunContext(work, "rtl", VIVADO_MS)


def _toyff(work: Path, reject: bool = True) -> Path:
    f = work / "toy" / "TOYFF.v"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(toyff_model(reject))
    return f


def _case(tid: str, root: Path = FIX) -> TestCase:
    return next(c for c in discover(root) if c.id == tid)


def _result(d: Path) -> dict:
    data = json.loads((d / "result.json").read_text())
    schemas.validate(data, "result")
    return data


def _python(ctx: RunContext, case: TestCase) -> None:
    res = PythonRunner().run(case, ctx)
    assert res.status == "pass", res.reason


# --- no Vivado needed ------------------------------------------------------------------


def test_registry():
    assert RUNNERS["xsim"] is XsimRunner
    assert XsimRunner.name == "xsim" and XsimRunner.x_observable
    assert "cocotb" not in XsimRunner.styles


def _script(**kw: object) -> str:
    args = {
        "cd": Path("/w/cfg-a"),
        "files": ["xut_vector_tb.sv", "dut/xut_dut.v"],
        "top": "xut_vector_tb",
        "incs": [],
        "params": {},
        "defines": {},
    }
    args.update(kw)
    return render_script(**args)


def test_render_script_sources_vivado_only_in_the_subshell():
    text = _script()
    assert text.startswith("# SPDX-License-Identifier: Apache-2.0\n")
    before, sep, after = text.partition("bash -c ")
    assert sep and "settings64" not in before
    assert f"source {VIVADO_SETTINGS}" in after
    assert "set -e\n" in before and 'cd "$(dirname "$0")"' in before
    # the host's LIBRARY_PATH workaround is set inside the subshell only
    assert "LIBRARY_PATH" not in before and "LIBRARY_PATH=/usr/lib/x86_64-linux-gnu" in after
    for word in ("xvlog -sv", "xelab -L unisims_ver -L unimacro_ver", "work.glbl", RUN_MARKER):
        assert word in after, word
    assert after.rstrip().endswith("xsim xut_snap -R'")
    assert str(VIVADO_SRC / "glbl.v") in after


def test_render_script_is_valid_bash_with_quoted_literals():
    """Sized literals carry a single quote; the script must still parse (bash -n), and
    each -generic_top/-d argument must reach the tools as one word."""
    text = _script(params={"INIT": "1'bx", "S": '"A B"'}, defines={"X": "", "V": "3"})
    p = subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    inner = text.split("bash -c ", 1)[1]
    assert "-generic_top" in inner and "-d X" in inner and "-d V=3" in inner


def test_render_script_glbl_instance():
    text = _script(glbl_instance=True)
    assert "XUT_GLBL_INSTANCE" in text and "work.glbl" not in text


def test_split_log():
    out = split_log("INFO: analyzing\nERROR: [VRFC 10-1] boom\n", 1)
    assert (out.compiled_ok, out.run_rc, out.run_text) == (False, None, "")
    assert out.compile_text == "ERROR: [VRFC 10-1] boom\n"
    out = split_log(f"WARNING: fine\n{RUN_MARKER}\nXUT_DONE\n", 0)
    assert (out.compiled_ok, out.compile_text, out.run_rc, out.run_text) == (
        True,
        "WARNING: fine\n",
        0,
        "XUT_DONE\n",
    )
    # an ERROR or CRITICAL WARNING while compiling is a failed compile even if xsim ran
    for bad in ("ERROR: [XSIM 1] x", "CRITICAL WARNING: [VRFC 2] y"):
        out = split_log(f"{bad}\n{RUN_MARKER}\nXUT_DONE\n", 0)
        assert not out.compiled_ok and out.run_rc == 0
    # a plain WARNING (e.g. XSIM 43-3431 for LIBRARY_PATH) is not
    assert split_log(f"WARNING: [XSIM 43-3431] env\n{RUN_MARKER}\n", 0).compiled_ok
    # INFO lines and the 43-3431 warning never reach the reject rule's evidence
    out = split_log(
        f"INFO: a/error/b\nWARNING: [XSIM 43-3431] errors\nWARNING: w\n{RUN_MARKER}\n", 0
    )
    assert out.compile_text == "WARNING: w\n"


def test_fatal_line():
    assert fatal_line("x\nFatal: tb gives up\nTime: 1 ns\n") == "Fatal: tb gives up"
    assert fatal_line("XUT_PASS\n") is None


@pytest.mark.parametrize(
    ("value", "out"),
    [
        ("1'b1", "1'b1"),
        ("1'bx", "1'bx"),
        ("4'b10z1", "4'b10z1"),
        ("8'hxF", "8'hxF"),
        (1, "1"),
        ("-3", "-3"),
        ("1.5", "1.5"),
        ("2.0e3", "2.0e3"),
        (0.5, "0.5"),
        ('"ABC"', '"ABC"'),
    ],
)
def test_generic_value(value, out):
    assert generic_value("P", value) == out


@pytest.mark.parametrize("value", ["x", "abc", "TRUE", True, "a b", "1.", ".5", None])
def test_generic_value_refuses_bare_words(value):
    """xelab reads a bare word as a string and truncates it, silently (probe:
    test_xelab_generic_top_bare_word_is_a_silent_string)."""
    with pytest.raises(ParamError):
        generic_value("P", value)


def test_unavailable_for_another_model_source(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.runners.xsim.settings_available", lambda: True)
    ctx = RunContext(tmp_path, "rtl", ModelSource("unisim-gh-2020.1", tmp_path))
    assert XsimRunner().available(ctx) == (
        False,
        "xsim uses Vivado's precompiled unisims_ver (unisim-2025.2); requested unisim-gh-2020.1",
    )
    assert XsimRunner().available(dataclasses.replace(ctx, model_source=VIVADO_MS)) == (True, "")


def test_split_log_without_marker_is_not_reject_evidence():
    """Review I1: a compile that never reached xsim -R, with an unrelated syntax error
    and an INFO line whose path holds "illegal" and the primitive's name, is an
    error, never a rejection."""
    d = "/w/build/rtl/xsim/unisim-2025.2/7series.FDRE.L0.illegal_init/cfg-init_x"
    log = (
        f'INFO: [VRFC 10-2263] Analyzing SystemVerilog file "{d}/xut_vector_tb.sv" into work\n'
        f"ERROR: [VRFC 10-4982] syntax error near 'endmodule' [{d}/dut/xut_dut.v:9]\n"
    )
    out = split_log(log, 1)
    assert "INFO" not in out.compile_text
    r = reject_result("init_x", out, ["FDRE"])
    assert r.status == "error", r.reason


def test_render_script_config_dir_comment_is_one_line():
    text = _script(cd=Path("/w/evil\nrm -rf x/cfg-a"))
    assert "\nrm -rf" not in text
    p = subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr


def test_unavailable_without_vivado(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.runners.xsim.VIVADO_SETTINGS", tmp_path / "nope.sh")
    ok, why = XsimRunner().available(RunContext(tmp_path, "rtl", VIVADO_MS))
    assert not ok and "not installed" in why and "nope.sh" in why


def test_other_model_source_is_a_recorded_skip(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.runners.xsim.settings_available", lambda: True)
    ctx = RunContext(tmp_path, "rtl", ModelSource("unisim-gh-2020.1", tmp_path))
    res = XsimRunner().run(_case("7series.TOYFF.L1.sv_basic"), ctx)
    assert res.status == "skip" and "requested unisim-gh-2020.1" in res.reason
    data = _result(workdir(ctx, "xsim", res.test_id))
    assert data["status"] == "skip" and data["model_source"] == "unisim-gh-2020.1"


def test_cocotb_is_a_skip(tmp_path):
    case = dataclasses.replace(_case("7series.TOYFF.L1.sv_basic"), style="cocotb")
    res = XsimRunner().run(case, RunContext(tmp_path, "rtl", VIVADO_MS))
    assert (res.status, res.reason) == ("skip", "runner xsim does not run cocotb tests")


# --- xelab behaviour the runner relies on ----------------------------------------------

P_TOP = (
    "// SPDX-License-Identifier: Apache-2.0\nmodule top;\n  parameter [0:0] P = 1'b0;\n"
    '  parameter real R = 0.0;\n  parameter S = "abc";\n'
    '  initial $display("P=%b R=%f S=%s", P, R, S);\nendmodule\n'
)


def _xelab(work: Path, generic: str) -> tuple[int, str]:
    """Elaborate and run ``P_TOP`` with ``-generic_top <generic>`` (with the runner's
    own LIBRARY_PATH guard); the exit code and the log."""
    (work / "top.v").write_text(P_TOP)
    inner = (
        f"source {VIVADO_SETTINGS} && {LIBRARY_PATH_GUARD} && "
        "xvlog -sv top.v && xelab --debug off -generic_top "
        f"{shlex.quote(generic)} -s snap work.top && xsim snap -R"
    )
    log = work / "run.log"
    with log.open("w") as f:
        rc = subprocess.run(
            ["bash", "-c", inner], cwd=work, stdout=f, stderr=subprocess.STDOUT
        ).returncode
    return rc, log.read_text()


@pytest.mark.vivado
def test_xelab_generic_top_keeps_x_digits(work):
    """Unlike Icarus -P, xelab takes a sized literal with x digits as written."""
    rc, log = _xelab(work, "P=1'bx")
    assert rc == 0 and "P=x R=0.000000 S=abc" in log, log


@pytest.mark.vivado
def test_xelab_generic_top_bare_word_is_a_silent_string(work):
    """Why generic_value refuses bare words: `P=x` is the string "x" (0x78), truncated
    to P's one bit, with no error and no warning (other than LIBRARY_PATH's 43-3431)."""
    rc, log = _xelab(work, "P=x")
    assert rc == 0 and "P=0 " in log, log
    diags = [ln for ln in log.splitlines() if ("ERROR" in ln or "WARNING" in ln)]
    assert all("43-3431" in ln for ln in diags), diags


@pytest.mark.vivado
@pytest.mark.parametrize(
    ("generic", "shown"),
    [("R=1.5", "R=1.500000"), ("R=2e3", "R=2000.000000"), ('S="xyz"', "S=xyz")],
)
def test_xelab_generic_top_takes_reals_and_quoted_strings(work, generic, shown):
    """What generic_value lets through arrives as written."""
    rc, log = _xelab(work, generic)
    assert rc == 0 and shown in log, log


@pytest.mark.vivado
def test_xelab_generic_top_unknown_name_is_a_hard_error(work):
    """A misspelt attribute is never silently ignored: XSIM 43-3281, exit code 1."""
    rc, log = _xelab(work, "NOPE=1")
    assert rc == 1 and "ERROR: [XSIM 43-3281]" in log, log


# --- vector style ----------------------------------------------------------------------


@pytest.mark.vivado
def test_vector_toyff_passes(ctx, work, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = XsimRunner(extra_files=[_toyff(work)]).run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())
    t = xtr.load(d / "trace.xtr")
    assert list(t.samples) == [
        f"init{i}/{label}" for i in (0, 1) for label in ("start", "S0", "S1", "S2", "S3")
    ]
    assert t.header["runner"] == "xsim" and t.header["model"] == MODEL_SOURCE
    data = _result(d)
    assert data["tools"]["xsim"].startswith("Vivado Simulator v2025.2")
    assert data["container"] is None and data["model_source"] == MODEL_SOURCE
    for c in data["configs"]:
        assert c["status"] == "pass" and c["mismatches"] == 0
    cd = d / "cfg-init1"
    for f in ("xsim.sh", "run.log", "raw.txt", "trace.xtr", "xsim.dir", "xvlog.log"):
        assert (cd / f).exists(), f
    exp = xtr.load(workdir(ctx, "python", case.id) / "cfg-init1/expected.xtr")
    assert exp.samples == xtr.load(cd / "trace.xtr").samples
    # xsim's droppings stay in the configuration directory
    for stray in ("xsim.dir", "xvlog.log", "xelab.log", "webtalk.log"):
        assert not (repo_root() / stray).exists(), stray
        assert not (d / stray).exists(), stray
    assert not list(ctx.root.glob("build/.xut-versions-*"))


@pytest.mark.vivado
def test_vector_corrupted_expectation_fails(ctx, work, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    exp = workdir(ctx, "python", case.id) / "cfg-init1/expected.xtr"
    lines = exp.read_text().splitlines(keepends=True)
    i = next(i for i, ln in enumerate(lines) if "Q=" in ln and not ln.startswith("#"))
    lines[i] = lines[i].replace("Q=0", "Q=@").replace("Q=1", "Q=0").replace("Q=@", "Q=1")
    exp.write_text("".join(lines))
    res = XsimRunner(extra_files=[_toyff(work)]).run(case, ctx)
    by = {c.cfg: c for c in res.configs}
    assert res.status == "fail"
    assert by["init1"].status == "fail" and by["init1"].mismatches == 1
    assert by["init0"].status == "pass"


@pytest.mark.vivado
def test_vector_compile_failure_is_error(ctx, work, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    bad = work / "toy/TOYFF.v"
    bad.parent.mkdir(parents=True)
    bad.write_text("module TOYFF(; endmodule\n")
    res = XsimRunner(extra_files=[bad]).run(case, ctx)
    assert res.status == "error"
    assert all(c.reason == "compile failed" for c in res.configs)


@pytest.mark.vivado
def test_vector_early_end_is_error(ctx, work, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    m = _toyff(work)
    m.write_text(m.read_text().replace("  reg q;\n", "  reg q;\n  initial #110000 $finish;\n"))
    res = XsimRunner(extra_files=[m]).run(case, ctx)
    assert res.status == "error"
    assert all("ended early" in c.reason for c in res.configs)


@pytest.mark.vivado
def test_vector_defines_reach_xvlog(ctx, work, toy):
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    c2 = dataclasses.replace(ctx, defines={"XUT_T10_PROBE": "", "XUT_T10_VAL": "3"})
    res = XsimRunner(extra_files=[_toyff(work)]).run(case, c2)
    d = workdir(ctx, "xsim", case.id)
    assert res.status == "pass", res.reason
    script = (d / "cfg-init0/xsim.sh").read_text()
    assert "-d XUT_T10_PROBE " in script and "-d XUT_T10_VAL=3 " in script
    assert _result(d)["defines"] == {"XUT_T10_PROBE": "", "XUT_T10_VAL": "3"}


@pytest.mark.vivado
@pytest.mark.parametrize("reject", [True, False])
def test_reject_end_to_end(ctx, work, toy, reject):
    """The TOYFF reject fixture: xsim passes iff the model rejects INIT=1'bx."""
    case = _case("7series.TOYFF.L0.reject")
    _python(ctx, case)
    res = XsimRunner(extra_files=[_toyff(work, reject=reject)]).run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    log = (d / "run.log").read_text()
    if reject:
        assert res.status == "pass", log
        assert res.configs[0].reason == "rejected at runtime: Attribute Syntax Error: INIT=x"
    else:
        assert res.status == "fail", log
        assert res.configs[0].reason.startswith("expected rejection, got acceptance")
    t = xtr.load(d / "cfg-init_x/trace.xtr")
    assert t.samples == {} and t.header["expect"] == "reject"


@pytest.mark.vivado
def test_reject_with_missing_model_is_error(ctx, toy):
    """Ruling S13: unisims_ver has no TOYFF; that is an infrastructure error, never a
    rejection."""
    case = _case("7series.TOYFF.L0.reject")
    _python(ctx, case)
    res = XsimRunner().run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    assert res.status == "error", (res.reason, (d / "run.log").read_text())
    assert "infrastructure failure" in res.configs[0].reason
    assert "Module <TOYFF> not found" in res.configs[0].reason


# --- sv style --------------------------------------------------------------------------


@pytest.mark.vivado
def test_sv_fixture_passes(ctx):
    case = _case("7series.TOYFF.L1.sv_basic")
    res = XsimRunner().run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())
    t = xtr.load(d / "trace.xtr")
    assert t.samples == {"default/after_gsr": {"Q": "1"}, "default/after_clk": {"Q": "0"}}
    assert xtr.load(d / "cfg-default/trace.xtr").header["runner"] == "xsim"
    assert _result(d)["style"] == "sv"


@pytest.mark.vivado
def test_sv_fixture_passes_with_glbl_as_an_instance(ctx):
    class Inst(XsimRunner):
        glbl_instance = True

    case = _case("7series.TOYFF.L1.sv_basic")
    res = Inst().run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    assert res.status == "pass", (res.reason, (d / "run.log").read_text())
    assert "work.glbl" not in (d / "cfg-default/xsim.sh").read_text()


def _sv_variant(root: Path, old: str, new: str) -> TestCase:
    d = _copy_toy(root)
    tb = d / "sv/tb_toyff_basic.sv"
    text = tb.read_text()
    assert old in text
    tb.write_text(text.replace(old, new, 1))
    return _case("7series.TOYFF.L1.sv_basic", root)


@pytest.mark.vivado
def test_sv_wrong_expectation_fails(ctx, work):
    case = _sv_variant(work, '`XUT_CHECK("clk", q, 1\'b0)', '`XUT_CHECK("clk", q, 1\'b1)')
    res = XsimRunner().run(case, ctx)
    assert res.status == "fail"
    assert res.configs[0].reason.startswith("XUT_FAIL clk: got 0 expected 1")


@pytest.mark.vivado
def test_sv_syntax_error_is_compile_failed(ctx, work):
    case = _sv_variant(work, "wire q;", "wire q")
    res = XsimRunner().run(case, ctx)
    assert (res.status, res.configs[0].reason) == ("error", "compile failed")


@pytest.mark.vivado
def test_sv_dollar_error_fails(ctx, work):
    case = _sv_variant(work, "    xut_finish;", '    $error("tb says no");\n    xut_finish;')
    res = XsimRunner().run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    assert res.status == "fail", (res.reason, (d / "run.log").read_text())
    assert res.configs[0].reason == "Error: tb says no"


@pytest.mark.vivado
def test_sv_fatal_is_not_a_pass(ctx, work):
    case = _sv_variant(work, "    xut_finish;", '    $fatal(1, "tb gives up");')
    res = XsimRunner().run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    # xsim exits 0 after $fatal; its "Fatal:" line makes the configuration an error
    assert res.status == "error", (res.reason, (d / "run.log").read_text())
    assert res.configs[0].reason == "simulator reported Fatal: tb gives up"


@pytest.mark.vivado
def test_sv_attributes_become_generics(ctx, work):
    """Each configuration's attrs are -generic_top NAME=VAL; a sized literal with an x
    digit arrives as x (xelab keeps it, unlike Icarus -P)."""
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
            {"cfg": "x", "attrs": {"EXP": "1'bx"}},
            {"cfg": "bare", "attrs": {"EXP": "x"}},
        ],
    )
    res = XsimRunner().run(case, ctx)
    by = {c.cfg: c for c in res.configs}
    assert by["one"].status == "pass", by["one"].reason
    assert by["zero"].status == "fail" and "gsr" in by["zero"].reason
    assert by["x"].status == "fail" and "expected x" in by["x"].reason
    assert by["bare"].status == "error" and "quoted" in by["bare"].reason


# --- the CLI, end to end ---------------------------------------------------------------


@pytest.mark.vivado
@pytest.mark.container
def test_cli_python_iverilog_xsim_on_the_toyff_fixture(work, toy, monkeypatch, capsys):
    """`xut run --runner python --runner iverilog --runner xsim TOYFF` on a copy of the
    fixture tree: iverilog gets a toy model source (named unisim-2025.2, so xsim is
    available), xsim compiles the same TOYFF.v as an extra file."""
    _copy_toy(work)
    # Test-only label: the toy model source is NAMED unisim-2025.2 so that xsim is
    # available at all; it holds only TOYFF.v and a toy glbl, never real UNISIM.
    ms = dataclasses.replace(make_model_source(work / "ms"), name=MODEL_SOURCE)
    toyff = ms.unisims / "TOYFF.v"

    class ToyXsim(XsimRunner):
        def __init__(self) -> None:
            super().__init__(extra_files=[toyff])

    monkeypatch.setitem(RUNNERS, "xsim", ToyXsim)
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: work)
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": ms)
    args = ["run", "--runner", "python", "--runner", "iverilog", "--runner", "xsim"]
    args += ["--style", "vector", "--style", "sv", "TOYFF"]  # cocotb: test_runner_cocotb
    r = CliRunner().invoke(main, args)
    assert r.exit_code == 0, r.output
    summary = json.loads((work / f"build/rtl/summary-{MODEL_SOURCE}.json").read_text())
    got = {(x["test_id"], x["runner"]): x["status"] for x in summary["results"]}
    t = "7series.TOYFF.L1."
    assert got == {
        (f"{t}capture", "python"): "pass",
        ("7series.TOYFF.L0.reject", "python"): "pass",
        (f"{t}sv_basic", "python"): "skip",
        (f"{t}capture", "iverilog"): "pass",
        ("7series.TOYFF.L0.reject", "iverilog"): "pass",
        (f"{t}sv_basic", "iverilog"): "pass",
        (f"{t}capture", "xsim"): "pass",
        ("7series.TOYFF.L0.reject", "xsim"): "pass",
        (f"{t}sv_basic", "xsim"): "pass",
    }
    with capsys.disabled():
        print("\n[T10 demo: TOYFF summary]", {f"{k[0]} {k[1]}": v for k, v in got.items()})


# --- real UNISIM: FDRE through python, iverilog and xsim --------------------------------

FDRE_YAML = """\
# SPDX-License-Identifier: Apache-2.0
primitive: FDRE
family: 7series
work_unit: flops
doc_refs: [{guide: UG953, version: "2026.1", section: FDRE, page: 1}]
tests:
  - id: 7series.FDRE.L1.t10_smoke
    level: L1
    style: vector
    source: vectors/gen.py:smoke
    exercises: [port:D]
    attr_sampling: {INIT: [0, 1]}
    runners: {python: "yes", xsim: "yes", iverilog: "yes", verilator: "yes", hw: "no"}
    flows: [rtl]
    related: []
    gaps: []
"""

FDRE_GEN = '''\
# SPDX-License-Identifier: Apache-2.0
"""Task 10 smoke: the Task 7 FDRE golden-vs-testbench scenario as a generator."""


def smoke(ctx):
    for init in (0, 1):
        b = ctx.dut(f"init{init}", INIT=f"1'b{init}")
        b.sample("start")
        b.set(CE=1, D=1 - init)
        b.cycle("C")
        b.set(D=init, CE=0)
        b.cycle("C")
        b.set(R=1, CE=0, D=1)
        b.cycle("C")
        b.set(R=0, CE=1, D=1)
        b.cycle("C")
        b.glbl("GSR", 1)
        b.sample("gsr_on")
        b.set(D=0, CE=1)
        b.cycle("C")
        b.glbl("GSR", 0)
        b.sample("gsr_off")
        b.cycle("C")
        yield b.build()
'''


@pytest.mark.vivado
@pytest.mark.container
def test_cli_fdre_on_real_unisim(work, monkeypatch, capsys):
    """Real UNISIM FDRE: golden replay (a test-local model, as in Task 7), Icarus on
    Vivado's UNISIM sources and xsim on the precompiled unisims_ver all agree."""
    from xut.catalog import model as catalog_model

    real_root, real_load = repo_root(), catalog_model.load_entry
    d = work / "tests/7series/register/FDRE"
    (d / "vectors").mkdir(parents=True)
    (d / "test.yaml").write_text(FDRE_YAML)
    (d / "vectors/gen.py").write_text(textwrap.dedent(FDRE_GEN))
    monkeypatch.setattr(
        "xut.catalog.model.load_entry",
        lambda family, name, root: real_load(family, name, real_root),
    )
    monkeypatch.setattr("xut_models.registry.get", lambda family, prim: _Fdre.cls())
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: work)
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": VIVADO_MS)
    args = ["run", "--runner", "python", "--runner", "iverilog", "--runner", "xsim", "FDRE"]
    r = CliRunner().invoke(main, args)
    summary = json.loads((work / f"build/rtl/summary-{MODEL_SOURCE}.json").read_text())
    got = {(x["test_id"], x["runner"]): (x["status"], x["reason"]) for x in summary["results"]}
    assert r.exit_code == 0, (r.output, got)
    tid = "7series.FDRE.L1.t10_smoke"
    assert {k: v[0] for k, v in got.items()} == {
        (tid, "python"): "pass",
        (tid, "iverilog"): "pass",
        (tid, "xsim"): "pass",
    }
    xs = xtr.load(work / f"build/rtl/xsim/{MODEL_SOURCE}/{tid}/trace.xtr")
    iv = xtr.load(work / f"build/rtl/iverilog/{MODEL_SOURCE}/{tid}/trace.xtr")
    assert xs.samples == iv.samples and len({s["Q"] for s in xs.samples.values()}) == 2
    with capsys.disabled():
        print(
            "\n[T10 demo: FDRE summary]", json.dumps({f"{k[0]} {k[1]}": v for k, v in got.items()})
        )


def test_sv_check_counts_xsims_error_prefix(tmp_path):
    """xsim reports $error as ``Error: <msg>`` (vvp: ``ERROR:``); both fail the config."""
    cd = tmp_path / "cfg-c"
    cd.mkdir()
    (cd / "trace.body").write_text("")
    hdr = {"runner": "xsim", "flow": "rtl", "model": "m", "prim": "P", "cfg": "c", "seed": "0"}
    r = sv_check(cd, "Error: tb says no\nXUT_PASS\n", hdr)
    assert (r.status, r.reason) == ("fail", "Error: tb says no")


def test_run_script_timeout_kills_the_whole_group(tmp_path):
    """A timeout kills xsim.sh's children (xelab/xsim), not only bash."""
    (tmp_path / "xsim.sh").write_text("sleep 300 &\necho $! > child.pid\nwait\n")
    with pytest.raises(RunTimeout):
        run_script(tmp_path, 2)
    child = Path("/proc") / (tmp_path / "child.pid").read_text().strip()
    deadline = time.monotonic() + 10  # a SIGKILLed orphan may take a moment to be reaped
    while child.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not child.exists() or "\tZ" in (child / "status").read_text()


# --- ruling S15: zero evidence is never a pass ------------------------------------------


@pytest.mark.vivado
def test_vector_without_samples_is_error(ctx, work, toy):
    from test_runner_base import NO_SAMPLE_GEN, _tmp_toy

    case = _tmp_toy(work, NO_SAMPLE_GEN)
    assert PythonRunner().run(case, ctx).status == "error"
    res = XsimRunner(extra_files=[_toyff(work)]).run(case, ctx)
    assert res.status == "error" and "no samples" in res.configs[0].reason, res.reason


# --- ruling S15(b): an sv pass needs >= 1 XUT_CHECK and >= 1 checkpoint ----------------


@pytest.mark.vivado
def test_sv_testbench_calling_only_xut_finish_is_error(ctx, work):
    """PR B gate (a) M1: xut_finish alone used to print XUT_PASS and pass."""
    case = _sv_variant(work, "  initial begin\n", "  initial xut_finish;\n  initial begin\n")
    res = XsimRunner().run(case, ctx)
    d = workdir(ctx, "xsim", case.id)
    assert res.status == "error", (res.reason, (d / "run.log").read_text())
    assert "recorded no checks/samples" in res.configs[0].reason
    assert "XUT_CHECKS 0" in (d / "run.log").read_text()


@pytest.mark.vivado
def test_sv_checks_without_checkpoints_is_error(ctx, work):
    case = _sv_variant(work, '`XUT_POINT1("after_gsr", "Q", q)', "")
    tb = case.test_dir / "sv/tb_toyff_basic.sv"
    tb.write_text(tb.read_text().replace('`XUT_POINT1("after_clk", "Q", q)', ""))
    res = XsimRunner().run(case, ctx)
    assert res.status == "error" and "recorded no checks/samples" in res.configs[0].reason
    assert "3 XUT_CHECK(s) executed, 0 checkpoint(s)" in res.configs[0].reason


@pytest.mark.vivado
def test_sv_checkpoints_without_checks_is_error(ctx, work):
    case = _sv_variant(work, "wire q;", "wire q;")
    tb = case.test_dir / "sv/tb_toyff_basic.sv"
    text = tb.read_text()
    for label, exp in (("gsr", "1'b1"), ("clk", "1'b0"), ("gsr_pulse", "1'b1")):
        text = text.replace(f'`XUT_CHECK("{label}", q, {exp})', "")
    tb.write_text(text)
    res = XsimRunner().run(case, ctx)
    assert res.status == "error" and "0 XUT_CHECK(s) executed" in res.configs[0].reason


# --- PR B gate (a) N1: sv seed provenance ------------------------------------------------


@pytest.mark.vivado
def test_sv_testbench_receives_the_recorded_seed(ctx):
    """The seed in the configuration trace header, the test trace header and
    result.json seeds.stimulus is the one the testbench saw (XUT_SEED define)."""
    import dataclasses

    from xut.runners.base import seed_for

    case = _case("7series.TOYFF.L1.sv_basic")
    for c, want in (
        (ctx, seed_for(case, ctx)),
        (dataclasses.replace(ctx, seed=4000000000), 4000000000),
    ):
        res = XsimRunner().run(case, c)
        d = workdir(c, "xsim", case.id)
        assert res.status == "pass", (res.reason, (d / "run.log").read_text())
        assert f"XUT_SEED {want}" in (d / "run.log").read_text()
        assert xtr.load(d / "cfg-default/trace.xtr").header["seed"] == str(want)
        assert xtr.load(d / "trace.xtr").header["seed"] == str(want)
        assert _result(d)["seeds"]["stimulus"] == want


# --- ruling S13b: reject evidence is an error naming the illegal attribute ---------------


@pytest.mark.vivado
@pytest.mark.parametrize(
    ("line", "why"),
    [
        ('$display("Warning: INIT value is invalid, using default");', "without an error/fatal"),
        ('$display("XUT_ERROR bad op; Attribute Syntax Error: INIT");', "testbench error"),
        ('$display("Attribute Syntax Error: IS_C_INVERTED=%b", INIT);', "naming INIT"),
    ],
)
def test_reject_false_pass_paths_are_errors(ctx, work, toy, line, why):
    """PR B gate (b) #3: each of these used to pass the INIT reject test."""
    f = _toyff(work)
    f.write_text(f.read_text().replace('$display("Attribute Syntax Error: INIT=%b", INIT);', line))
    case = _case("7series.TOYFF.L0.reject")
    _python(ctx, case)
    res = XsimRunner(extra_files=[f]).run(case, ctx)
    assert why in (res.configs[0].reason or ""), res.configs[0].reason
    assert res.status == "error", (
        res.reason,
        (workdir(ctx, "xsim", case.id) / "run.log").read_text(),
    )


# --- runtime model diagnostics are never silently ignored (PR B gate (b) #7) -------------


@pytest.mark.vivado
def test_vector_model_error_fails_a_matching_trace(ctx, work, toy):
    f = _toyff(work)
    f.write_text(
        f.read_text().replace(
            "  reg q;\n", '  reg q;\n  initial #110000 $display("Error: TOYFF odd");\n'
        )
    )
    case = _case("7series.TOYFF.L1.capture")
    _python(ctx, case)
    res = XsimRunner(extra_files=[f]).run(case, ctx)
    assert res.status == "fail", res.reason
    for c in res.configs:
        assert (c.status, c.reason, c.mismatches) == (
            "fail",
            "model reported errors: Error: TOYFF odd",
            0,
        )
