# SPDX-License-Identifier: Apache-2.0
"""The shared expect=reject rule (rulings S13, S13a, S13b): pass only on positive
evidence -- an error/fatal diagnostic naming one of the configuration's declared
illegal attributes."""

import pytest

from xut.formats import xtr
from xut.runners.reject import SimOutcome, reject_check, reject_result

ATTRS = ["INIT"]
UNISIM_MSG = (
    "Attribute Syntax Error : The attribute INIT on FDRE instance xut_vector_tb.dut.u "
    "is set to x.  Legal values for this attribute are 1'b0 or 1'b1."
)


def _r(out, illegal=ATTRS):
    return reject_result("c", out, illegal)


def test_runtime_rejection_naming_the_attribute_passes():
    r = _r(SimOutcome(True, "", 0, UNISIM_MSG + "\nTOYFF.v:6: $finish called at 0\n"))
    assert r.status == "pass" and r.reason.startswith("rejected at runtime: Attribute Syntax")


def test_attribute_match_is_case_insensitive_whole_word():
    assert _r(SimOutcome(True, "", 0, "DRC Error: init is illegal\n")).status == "pass"
    # INIT_00 is another attribute, not INIT
    assert _r(SimOutcome(True, "", 0, "Error: INIT_00 is illegal\n")).status == "error"


def test_compile_rejection_naming_the_attribute_passes():
    out = SimOutcome(False, "dut.v:3: error: parameter INIT value 1'bx not allowed\n", None, "")
    r = _r(out)
    assert r.status == "pass" and r.reason.startswith("rejected at compile/elaboration: ")


def test_acceptance_fails():
    r = _r(SimOutcome(True, "", 0, "XUT_DONE t=130000\n"))
    assert r.status == "fail" and r.reason.startswith("expected rejection, got acceptance")


@pytest.mark.parametrize(
    "compile_text",
    [
        "xut_dut.v:7: error: Unknown module type: TOYFF\n2 error(s) during elaboration.\n",
        "xut_vector_tb.sv:20: Include file xut_cfg.vh not found\n",
        "docker: Error response from daemon: INIT mount failed\n",
        "error: Unable to open input file INIT.v\n",
        "iverilog: cannot find INIT: No such file or directory\n",
    ],
)
def test_infrastructure_failure_is_error_even_if_it_names_the_attribute(compile_text):
    r = _r(SimOutcome(False, compile_text, None, ""))
    assert r.status == "error" and r.reason.startswith("infrastructure failure")


def test_compile_failure_without_evidence_is_error_with_diagnostics():
    r = _r(SimOutcome(False, "x.v:1: syntax error\nI give up.\n", None, ""))
    assert r.status == "error" and "naming INIT" in r.reason and "syntax error" in r.reason


def test_runtime_without_evidence_is_error():
    r = _r(SimOutcome(True, "", 0, "x.v:9: $finish called at 5 (1ps)\n"))
    assert r.status == "error" and "without XUT_DONE" in r.reason


def test_nonzero_exit_is_error_even_with_evidence():
    r = _r(SimOutcome(True, "", 1, UNISIM_MSG + "\n"))
    assert r.status == "error" and "rc 1" in r.reason


def test_a_reject_config_must_name_its_illegal_attribute():
    """Ruling S13b: no fallback to the primitive's name, or to any attribute."""
    r = _r(SimOutcome(True, "", 0, "Error: FDRE is unhappy\n"), illegal=[])
    assert r.status == "error" and r.reason.startswith("reject config must name its illegal")
    assert _r(SimOutcome(True, "", 0, "Error: FDRE is unhappy\n")).status == "error"


def test_reject_check_writes_header_only_trace(tmp_path):
    cd = tmp_path / "cfg-c"
    cd.mkdir()
    (cd / "stim.xvec").write_text("stim\n")
    hdr = {"runner": "r", "flow": "rtl", "model": "m", "seed": "0", "cfg": "c"}
    r = reject_check(cd, SimOutcome(True, "", 0, UNISIM_MSG), ATTRS, hdr)
    assert r.status == "pass" and r.stimulus_sha256 and r.trace_sha256
    t = xtr.load(cd / "trace.xtr")
    assert t.samples == {} and t.header == {**hdr, "expect": "reject"}


# --- ruling S13a: evidence never comes from INFO lines or from file paths ---------------

ILLEGAL_DIR = "/work/build/rtl/x/unisim-2025.2/7series.FDRE.L0.illegal_init/cfg-init_x"


@pytest.mark.parametrize(
    "compile_text",
    [
        # xsim style: an INFO line whose path holds "illegal" and the attribute name
        f'INFO: [VRFC 10-2263] Analyzing SystemVerilog file "{ILLEGAL_DIR}/INIT/dut.v"\n'
        f"ERROR: [VRFC 10-4982] syntax error near 'endmodule' [{ILLEGAL_DIR}/tb.sv:3]\n",
        # iverilog style: the only name and diagnostic word are in the path
        f"{ILLEGAL_DIR}/INIT/xut_dut.v:3: syntax error\n",
        # a quoted path in an error line
        f'ERROR: cannot parse "{ILLEGAL_DIR}/INIT.v" near line 3\n',
        "NOTE: INIT is illegal here (a note is never evidence)\n",
    ],
)
def test_path_or_info_words_are_not_evidence(compile_text):
    r = _r(SimOutcome(False, compile_text, None, ""))
    assert r.status == "error", r.reason


def test_runtime_path_words_are_not_evidence():
    run = (
        "Error: tb says no\n"
        f"Time: 1 ns  Process: /tb/Initial  File: {ILLEGAL_DIR}/INIT/invalid.sv Line: 3\n"
    )
    assert _r(SimOutcome(True, "", 0, run)).status == "error"


def test_evidence_beside_a_path_still_counts():
    """Stripping paths keeps the rest of the line: a real diagnostic naming INIT passes."""
    text = f"{ILLEGAL_DIR}/dut.v:3: error: parameter INIT value 1'bx not allowed\n"
    r = _r(SimOutcome(False, text, None, ""))
    assert r.status == "pass", r.reason
    run = f"Error: [Unisim FDRE-1] The attribute INIT is illegal. File: {ILLEGAL_DIR}/x.v\n"
    assert _r(SimOutcome(True, "", 0, run)).status == "pass"


# --- ruling S13b: the false-pass paths of PR B gate review (b) #3 -----------------------


@pytest.mark.parametrize(
    ("run", "illegal"),
    [
        # the reviewer's probe 1: a warning naming a (legal) attribute
        ("WARNING: attribute USE_MULT has an invalid combination\n", ["AREG"]),
        # a warning is the model ACCEPTING the value, even when it names the illegal one
        ("Warning: INIT value is invalid, using default\n", ["INIT"]),
        ("WARNING: [Unisim FDRE-3] INIT is illegal, using 1'b0\n", ["INIT"]),
        ("tb.v:12: warning: parameter INIT is out of range\n", ["INIT"]),
        ("INFO: INIT is illegal\n", ["INIT"]),
    ],
)
def test_a_warning_is_never_evidence(run, illegal):
    r = _r(SimOutcome(True, "", 0, run + "tb.v:9: $finish called at 5 (1ps)\n"), illegal)
    assert r.status == "error", r.reason


def test_a_testbench_error_is_never_a_rejection():
    """The reviewer's probe 2: XUT_ERROR (rc 0, no XUT_DONE) plus a line naming INIT."""
    run = "XUT_ERROR bad op 9 at pc 3\nError: [Unisim FDRE-1] INIT is illegal\n"
    r = _r(SimOutcome(True, "", 0, run))
    assert r.status == "error" and "XUT_ERROR" in r.reason
    r = _r(SimOutcome(False, "Error: INIT is illegal\n", None, ""), ["INIT"])
    assert r.status == "pass"  # the XUT_ERROR rule looks at the run, not the words


def test_evidence_must_name_an_illegal_attribute():
    """The reviewer's probe 3: {AREG (illegal), USE_MULT (legal)}; a model $finish on a
    USE_MULT diagnostic must not pass the AREG reject test."""
    run = "Error: [Unisim DSP48E1-4] USE_MULT is not allowed with this configuration\n"
    assert _r(SimOutcome(True, "", 0, run), ["AREG"]).status == "error"
    assert _r(SimOutcome(True, "", 0, run.replace("USE_MULT", "AREG")), ["AREG"]).status == "pass"


@pytest.mark.parametrize(
    "line",
    [
        "Error: [Unisim FDRE-1] INIT is illegal",
        "ERROR: [VRFC 10-1] INIT value not allowed",
        "Fatal: INIT out of range",
        "%Error: dut.v:3: INIT is invalid",
        "Attribute Syntax Error : The attribute INIT on FDRE is set to x.",
        "dut.v:3: error: parameter INIT value 1'bx not allowed",
    ],
)
def test_error_and_fatal_lines_are_evidence(line):
    assert _r(SimOutcome(True, "", 0, line + "\n")).status == "pass"
