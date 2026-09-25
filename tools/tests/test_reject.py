# SPDX-License-Identifier: Apache-2.0
"""The shared expect=reject rule (ruling S13): pass only on positive evidence."""

import pytest

from xut.formats import xtr
from xut.runners.reject import SimOutcome, reject_check, reject_result

ATTRS = ["INIT"]
UNISIM_MSG = (
    "Attribute Syntax Error : The attribute INIT on FDRE instance xut_vector_tb.dut.u "
    "is set to x.  Legal values for this attribute are 1'b0 or 1'b1."
)


def _r(out, attrs=ATTRS, prim="FDRE"):
    return reject_result("c", out, attrs, prim)


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


def test_no_attributes_falls_back_to_the_primitive():
    assert _r(SimOutcome(True, "", 0, "Error: FDRE is unhappy\n"), attrs=[]).status == "pass"
    assert _r(SimOutcome(True, "", 0, "Error: FDRE is unhappy\n")).status == "error"


def test_reject_check_writes_header_only_trace(tmp_path):
    cd = tmp_path / "cfg-c"
    cd.mkdir()
    (cd / "stim.xvec").write_text("stim\n")
    hdr = {"runner": "r", "flow": "rtl", "model": "m", "seed": "0", "cfg": "c"}
    r = reject_check(cd, SimOutcome(True, "", 0, UNISIM_MSG), ATTRS, "FDRE", hdr)
    assert r.status == "pass" and r.stimulus_sha256 and r.trace_sha256
    t = xtr.load(cd / "trace.xtr")
    assert t.samples == {} and t.header == {**hdr, "expect": "reject"}
