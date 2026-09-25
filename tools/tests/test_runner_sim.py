# SPDX-License-Identifier: Apache-2.0
"""``xut.runners.sim``: the runner-neutral checks shared by every simulator runner."""

from pathlib import Path

from xut.formats import xtr
from xut.runners.reject import SimOutcome
from xut.runners.sim import classify_run, vector_check
from xut.wrap import Bit, DutMap

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
    assert _sv(tmp_path, "a  Q=1\n", "XUT_SEED 0\nXUT_CHECKS 2\nXUT_PASS\n").status == "pass"


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


# --- PR B gate (a) N1: the seed an sv testbench receives is the one recorded -------------


def test_sv_seed_seen_by_the_testbench_must_match_the_header(tmp_path):
    ok = "XUT_SEED 0\nXUT_CHECKS 1\nXUT_PASS\n"
    assert _sv(tmp_path, "a  Q=1\n", ok).status == "pass"
    r = _sv(tmp_path, "a  Q=1\n", ok.replace("XUT_SEED 0", "XUT_SEED 7"))
    assert r.status == "error" and "seed" in r.reason


def test_sv_seed_define():
    import pytest

    from xut.runners.sim import ParamError, sv_seed_define

    assert sv_seed_define(0) == "64'd0" and sv_seed_define(2**64 - 1) == f"64'd{2**64 - 1}"
    for bad in (-1, 2**64):
        with pytest.raises(ParamError, match="seed"):
            sv_seed_define(bad)


# --- runtime model diagnostics are never silently ignored --------------------------------


def _vec_ok(tmp_path: Path, run_text: str, raw: str = "S 0 1\n"):
    cd = tmp_path / "cfg-c"
    cd.mkdir(exist_ok=True)
    (cd / "stim.xvec").write_text("stim\n")
    (cd / "raw.txt").write_text(raw)
    m = DutMap("TOYFF", "7series", "c", {}, 1, 1, 1, [Bit("out", 0, "Q", 0, "data")])
    exp = xtr.Trace(dict(HDR))
    exp.add("S0", {"Q": "1"})
    return vector_check(cd, m, ["S0"], exp, HDR, True, run_text)


def test_model_errors_fail_a_matching_vector_run(tmp_path):
    """PR B gate (b) #7: the trace matches, but the model reported an error."""
    assert _vec_ok(tmp_path, "XUT_DONE t=5\n").status == "pass"
    for line in (
        "Error: [Unisim FDRE-1] something the model disliked",
        "ERROR: tb.sv:3: $error from the model",
        "Fatal: model gave up",
        "Attribute Syntax Error : The attribute INIT on FDRE is odd",
    ):
        r = _vec_ok(tmp_path, f"{line}\nXUT_DONE t=5\n")
        assert r.status == "fail" and r.reason.startswith("model reported errors: "), line
        assert line in r.reason


def test_model_warnings_and_info_are_not_errors(tmp_path):
    for line in ("WARNING: [Unisim FDRE-2] odd", "INFO: nothing is an error here", "Note: x"):
        assert _vec_ok(tmp_path, f"{line}\nXUT_DONE t=5\n").status == "pass", line


def test_model_errors_and_mismatches_are_both_reported(tmp_path):
    r = _vec_ok(tmp_path, "Error: odd\nXUT_DONE\n", raw="S 0 0\n")
    assert r.status == "fail" and r.mismatches == 1
    assert r.reason.startswith("model reported errors: Error: odd; ") and "Q" in r.reason
