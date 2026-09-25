# SPDX-License-Identifier: Apache-2.0
"""``xut.runners.sim``: the runner-neutral checks shared by every simulator runner."""

from pathlib import Path

from xut.formats import xtr
from xut.runners.reject import SimOutcome
from xut.runners.sim import classify_run, vector_check
from xut.wrap import DutMap

HDR = {"runner": "iverilog", "flow": "rtl", "model": "m", "prim": "TOYFF", "cfg": "c", "seed": "0"}


def _cd(tmp_path: Path) -> Path:
    cd = tmp_path / "cfg-c"
    cd.mkdir()
    (cd / "stim.xvec").write_text("stim\n")
    return cd


def test_vector_check_with_an_empty_expectation_is_error(tmp_path):
    """Ruling S15, defence in depth behind validate: an expected trace without samples
    can never be a pass, whatever the simulator printed."""
    cd = _cd(tmp_path)
    (cd / "raw.txt").write_text("")
    m = DutMap("TOYFF", "7series", "c", {}, 1, 1, 1, [])
    r = vector_check(cd, m, [], xtr.Trace(dict(HDR)), HDR, True)
    assert r.status == "error" and "no samples" in r.reason


def test_classify_run_ladder():
    ok = "XUT_DONE t=5\n"
    assert classify_run("c", SimOutcome(True, "", 0, ok)) is None
    assert classify_run("c", SimOutcome(False, "", None, "")).reason == "compile failed"
    assert "rc 1" in classify_run("c", SimOutcome(True, "", 1, ok)).reason
    assert "Fatal: x" in classify_run("c", SimOutcome(True, "", 0, "Fatal: x\n" + ok)).reason
    assert "no XUT_DONE" in classify_run("c", SimOutcome(True, "", 0, "")).reason
    assert classify_run("c", SimOutcome(True, "", 0, ""), need_done=False) is None
