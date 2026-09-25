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


# --- ruling S15(b): an sv pass needs >= 1 executed XUT_CHECK and >= 1 checkpoint --------


def _sv(tmp_path: Path, body: str, log: str):
    from xut.runners.sim import sv_check

    cd = tmp_path / "cfg-c"
    cd.mkdir(exist_ok=True)
    (cd / "trace.body").write_text(body)
    return sv_check(cd, log, HDR)


def test_sv_pass_needs_checks_and_samples(tmp_path):
    assert _sv(tmp_path, "a  Q=1\n", "XUT_CHECKS 2\nXUT_PASS\n").status == "pass"


def test_sv_testbench_that_only_calls_xut_finish_is_error(tmp_path):
    """PR B gate (a) M1 / (b) #2: xut_finish alone printed XUT_PASS with no evidence."""
    r = _sv(tmp_path, "", "XUT_CHECKS 0\nXUT_PASS\n")
    assert r.status == "error" and "recorded no checks/samples" in r.reason


def test_sv_checks_without_checkpoints_is_error(tmp_path):
    r = _sv(tmp_path, "", "XUT_CHECKS 3\nXUT_PASS\n")
    assert r.status == "error" and "recorded no checks/samples" in r.reason


def test_sv_checkpoints_without_checks_is_error(tmp_path):
    r = _sv(tmp_path, "a  Q=1\n", "XUT_CHECKS 0\nXUT_PASS\n")
    assert r.status == "error" and "recorded no checks/samples" in r.reason


def test_sv_without_a_check_count_is_error(tmp_path):
    """A testbench that prints XUT_PASS itself (not through xut_finish) proves nothing."""
    r = _sv(tmp_path, "a  Q=1\n", "XUT_PASS\n")
    assert r.status == "error" and "XUT_CHECKS" in r.reason


def test_sv_failure_still_wins(tmp_path):
    r = _sv(tmp_path, "", "XUT_FAIL gsr: got 0 expected 1 at 5\nXUT_CHECKS 1\n")
    assert r.status == "fail"
