# SPDX-License-Identifier: Apache-2.0
import json
import re
import shutil
from pathlib import Path

import pytest
from test_vz_rewrite import MODS

from xut.catalog.unisim import parse_module
from xut.container import SIM_IMAGE, image_digest
from xut.formats import xvec
from xut.modelsrc import ModelSource
from xut.validate import validate
from xut.verilatorize import driver, equiv
from xut.verilatorize.analyze import TransformError, analyze
from xut.verilatorize.equiv import (
    Checked,
    check_model,
    config_dir,
    config_key,
    equiv_stimulus,
)
from xut.verilatorize.rewrite import rewrite, write_text
from xut.wrap import build_map, spec_from_hdl

FIX = Path(__file__).parent / "fixtures" / "verilatorize"
GLBL = FIX / "glbl.v"
_no_image = shutil.which("docker") is None or image_digest(SIM_IMAGE) is None
#: Known divergences, pinned (never masked). VZIFELSE: C2 and E rise in one atomic input
#: change; `always @(C2 or E) if (C2) deassign q; else assign q = E;` then runs `deassign`
#: while the procedural continuous assign `q = E` is being re-evaluated for the new E. The
#: order of those two active-region events is undefined in Verilog: xsim keeps the old
#: value (0) for `{C2, E} = 2'b11` but the new one (1) for `{E, C2} = 2'b11` (the Task 14
#: report's probe), while the transform captures the override's current value (1). A race
#: in the original under coincident trigger changes (class nondeterminism), not a transform
#: bug; reported to the controller for a ruling.
RACES = {"VZIFELSE": r"pair\.C2\.E\.coincident\.u\.\d+ Q\[0\]: expected 0, got 1 \[value\]"}
#: MODS fixtures with a non-constant override expression: their oracle is xsim (S28b/S31).
NONCONST = {"vz_nonconst.v", "vz_multi.v", "vz_ifelse.v", "vz_ranges.v"}


def _map(path, model, attrs=None):
    spec = spec_from_hdl(parse_module(path, model), "default", attrs or {}, raw_clock_out=True)
    return build_map(spec)


def _stim(fname, model, seed=1):
    an = analyze(FIX / fname, model, GLBL)
    m = _map(FIX / fname, model)
    return an, m, equiv_stimulus(an, m, seed)


def _bits(m, port):
    return {b.bit for b in m.of("in") if b.port == port}


def _set_count(vec, m, port, value):
    """How many ``set`` events drive ``port`` to ``value`` (a full-width MSB-first string)."""
    bits = _bits(m, port)
    return sum(
        1
        for e in vec.events
        if e.op == "set" and set(range(e.lsb, e.msb + 1)) == bits and e.value == value
    )


# ---- the stimulus ----------------------------------------------------------------------------
def test_vztrig_stimulus_validates_and_pulses_every_trigger():
    an, m, vec = _stim("vz_trig.v", "VZTRIG")
    assert an.triggers == ["CLR", "PRE", "glbl.GSR"]
    report = validate(vec, m)
    assert report.errors == []
    assert vec.hw_renderable is False and vec.hw_reason == equiv.HW_REASON
    assert xvec.loads(xvec.dumps(vec)) == vec
    assert any(e.simultaneous for e in vec.events)
    assert sum(e.op == "glbl" and e.target == "GSR" and e.value == "1" for e in vec.events) >= 3
    assert _set_count(vec, m, "CLR", "1") >= 3 and _set_count(vec, m, "PRE", "1") >= 3
    labels = [e.target for e in vec.events if e.op == "sample"]
    overlap = {lb.split(".overlap.")[0] for lb in labels if ".overlap." in lb}
    assert len(overlap) == 3  # the pairs (CLR,PRE), (CLR,glbl.GSR), (PRE,glbl.GSR)
    for kind in ("nested", "coincident"):
        assert len({lb.split(f".{kind}.")[0] for lb in labels if f".{kind}." in lb}) == 3


def test_stimulus_is_deterministic_for_a_seed():
    _, _, a = _stim("vz_trig.v", "VZTRIG", seed=1)
    _, _, b = _stim("vz_trig.v", "VZTRIG", seed=1)
    _, _, c = _stim("vz_trig.v", "VZTRIG", seed=2)
    assert xvec.dumps(a) == xvec.dumps(b) != xvec.dumps(c)


def test_clocked_multi_trigger_stimulus_runs_the_enabler_around_every_pulse():
    """The brief's MMCMVZ shape test (ruling S31(2)): MMCMVZ is refused by the rewrite (S28),
    but analyze() still produces its analysis, so the stimulus shape is tested on it."""
    an, m, vec = _stim("vz_cone.v", "MMCMVZ")
    assert an.triggers == ["PWRDWN", "RST"] and an.enablers == ["CLKIN1"]
    assert validate(vec, m).errors == []
    clk = m.clock_name("CLKIN1")
    edges = [e.t for e in vec.events if e.op == "edge" and e.target == clk]
    for port in ("RST", "PWRDWN"):
        bits = _bits(m, port)
        pulses = [
            e.t
            for e in vec.events
            if e.op == "set" and set(range(e.lsb, e.msb + 1)) == bits and e.value == "1"
        ]
        assert len(pulses) >= 3, port
        for t in pulses:
            assert any(x < t for x in edges) and any(x > t for x in edges), (port, t)


def test_data_trigger_uses_set_and_clock_ports_cycle(tmp_path):
    an, m, vec = _stim("vz_select.v", "VZSEL")  # R: a data-class trigger; C a clock
    assert m.cls_of("R") == "data" and _set_count(vec, m, "R", "1") >= 3
    assert any(e.op == "edge" for e in vec.events)


def test_unknown_glbl_trigger_raises():
    an = Checked("VZTRIG", FIX / "vz_trig.v", ["glbl.JTAG_TCK"], [], False)
    with pytest.raises(TransformError, match="glbl.JTAG_TCK has no glbl channel"):
        equiv_stimulus(an, _map(FIX / "vz_trig.v", "VZTRIG"))


def test_trigger_that_is_not_an_input_raises():
    an = Checked("VZTRIG", FIX / "vz_trig.v", ["NOPE"], [], False)
    with pytest.raises(TransformError, match="NOPE is not an input port"):
        equiv_stimulus(an, _map(FIX / "vz_trig.v", "VZTRIG"))


@pytest.mark.parametrize("fname", sorted(MODS))
def test_every_fixture_stimulus_validates(fname):
    an, m, vec = _stim(fname, MODS[fname])
    assert validate(vec, m).errors == []
    assert an.nonconstant_overrides == (fname in NONCONST)


def test_config_key_and_dir():
    assert config_key({}) == config_key(None) == "default" == config_dir("default")
    k = config_key({"B": '"X Y"', "A": "1'b1"})
    assert k == 'A=1\'b1,B="X Y"'
    # injective (review minor 2): separators inside a value are escaped
    assert config_key({"A": "1,B=2"}) == "A=1\\,B\\=2" != config_key({"A": "1", "B": "2"})
    assert config_key({"A": "x\\,"}) != config_key({"A": "x\\", "": ""})
    d = config_dir(k)
    assert re.fullmatch(r"A_1_b1_B_X_Y-[0-9a-f]{8}", d)
    assert config_dir(config_key({"A": "1'b0"})) != config_dir(config_key({"A": "1_b0"}))


def test_xsim_unavailable_is_an_error_never_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.runners.xsim.settings_available", lambda: False)
    ms, an = _source(tmp_path, "vz_nonconst.v", "VZNONCONST")
    r = check_model(an, ms, tmp_path / "vz" / "equiv", lib=tmp_path / "vz")
    assert r.status == "error" and "Vivado 2025.2 is unavailable" in r.reason
    doc = json.loads((tmp_path / "vz" / "equiv" / "result.json").read_text())
    assert doc["status"] == "error" and doc["oracle"] == ""


def test_check_model_error_is_recorded_with_its_traceback(tmp_path, monkeypatch):
    ms, an = _source(tmp_path, "vz_trig.v", "VZTRIG")

    def boom(*a, **k):
        raise RuntimeError("stimulus exploded")

    monkeypatch.setattr(equiv, "equiv_stimulus", boom)
    out = tmp_path / "vz" / "equiv"
    r = check_model(an, ms, out, lib=tmp_path / "vz")
    assert (r.status, r.reason) == ("error", "RuntimeError: stimulus exploded")
    assert "stimulus exploded" in (out / "error.log").read_text()
    assert json.loads((out / "result.json").read_text())["status"] == "error"


# ---- container: the real check ------------------------------------------------------------------
def _source(tmp_path, fname, model):
    """A model source in ``tmp_path/src`` holding one fixture, and its analysis there."""
    uni = tmp_path / "src" / "unisims"
    uni.mkdir(parents=True, exist_ok=True)
    shutil.copy(GLBL, tmp_path / "src" / "glbl.v")
    shutil.copy(FIX / fname, uni / f"{model}.v")
    return ModelSource("test-src", tmp_path / "src"), analyze(uni / f"{model}.v", model, GLBL)


def _driver_check(tmp_path, monkeypatch, fname, model):
    ms, _ = _source(tmp_path, fname, model)
    out = tmp_path / "vz"
    monkeypatch.setattr(driver, "vz_dir", lambda ms: out)
    man = driver.verilatorize(ms, jobs=2, progress=lambda _line: None, check=True)
    return man.models[model], out


def _expect_all_pass(e, out, model):
    keys = [config_key(c) for c in e.generate_configs or [{}]]
    assert set(e.equiv) == set(keys)
    why = {
        k: json.loads((out / "equiv" / model / config_dir(k) / "result.json").read_text())
        for k in keys
    }
    assert all(v == "pass" for v in e.equiv.values()), {k: why[k]["reason"] for k in keys}
    return why


@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
@pytest.mark.parametrize("fname", sorted(set(MODS) - NONCONST))
def test_every_constant_fixture_is_equivalent_on_icarus(tmp_path, monkeypatch, fname):
    model = MODS[fname]
    e, out = _driver_check(tmp_path, monkeypatch, fname, model)
    assert e.status == "transformed"
    why = _expect_all_pass(e, out, model)
    assert {d["oracle"] for d in why.values()} == {"iverilog"}
    assert set(e.equiv_oracle.values()) == {"iverilog"}
    if model == "VZGEN":
        assert set(e.equiv) == {"default", "IS_C_INVERTED=1'b1"}


@pytest.mark.vivado
@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
@pytest.mark.parametrize("fname", sorted(NONCONST))
def test_every_nonconstant_fixture_is_equivalent_against_xsim(tmp_path, monkeypatch, fname):
    """The oracle is the original on xsim (S28b/S31); the transformed model on Icarus.

    VZIFELSE is not equivalent at exactly one sample, and the test pins it rather than
    hiding it (see RACES)."""
    model = MODS[fname]
    e, out = _driver_check(tmp_path, monkeypatch, fname, model)
    if model in RACES:
        why = json.loads((out / "equiv" / model / "default" / "result.json").read_text())
        mism = (out / "equiv" / model / "default" / "mismatches.txt").read_text().splitlines()
        assert e.equiv == {"default": "fail"} and why["oracle"] == "xsim", why["reason"]
        assert len(mism) == 1 and re.fullmatch(RACES[model], mism[0]), mism
        return
    why = _expect_all_pass(e, out, model)
    assert {d["oracle"] for d in why.values()} == {"xsim"}
    assert all("non-constant override" in d["oracle_reason"] for d in why.values())
    assert all(d["tools"]["xsim"].startswith("Vivado Simulator") for d in why.values())


@pytest.mark.vivado
@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
def test_forced_xsim_oracle_agrees_on_a_constant_fixture(tmp_path):
    """Both oracles agree where both are valid: VZTRIG against the original on xsim."""
    ms, an = _source(tmp_path, "vz_trig.v", "VZTRIG")
    lib = tmp_path / "vz"
    lib.mkdir()
    write_text(lib / "VZTRIG.v", rewrite(an))
    r = check_model(an, ms, lib / "equiv" / "VZTRIG", lib=lib, force_xsim=True)
    assert (r.status, r.oracle) == ("pass", "xsim"), r.reason


def _check_rewritten(tmp_path, fname, model, mutate=None):
    ms, an = _source(tmp_path, fname, model)
    lib = tmp_path / "vz"
    lib.mkdir()
    text = rewrite(an)
    if mutate is not None:
        new = mutate(text)
        assert new != text, "the mutation did not apply"
        text = new
    write_text(lib / f"{model}.v", text)
    return check_model(an, ms, lib / "equiv" / model / "default", lib=lib)


def _drop_guard(text):
    """``begin if (X__ovr_sel != 0) begin <capture> end end`` -> ``begin <capture> end``."""
    return re.sub(r"begin if \(\w+__ovr_sel != \d+'d0\) begin (.*?) end end", r"begin \1 end", text)


def _drop_capture(text):
    """deassign becomes ``X__ovr_sel = 0;`` alone: X__base keeps its pre-force value."""
    return re.sub(r"\w+__base = \w+__active\(\); ", "", text)


@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
def test_deassign_guard_keeps_an_unforced_deassign_a_no_op(tmp_path):
    r = _check_rewritten(tmp_path / "ok", "vz_guard.v", "VZGUARD")
    assert (r.status, r.oracle) == ("pass", "iverilog"), r.reason
    r = _check_rewritten(tmp_path / "noguard", "vz_guard.v", "VZGUARD", _drop_guard)
    assert r.status == "fail" and r.mismatches, r.reason
    assert any("base." in m for m in r.mismatches)  # visible before the first S pulse


@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
def test_mutated_rewrite_breaks_retention_and_the_check_fails(tmp_path):
    """The check can fail: a deassign without the X__base capture loses the forced value."""
    r = _check_rewritten(tmp_path, "vz_retain.v", "VZRETAIN", _drop_capture)
    assert r.status == "fail" and len(r.mismatches) >= 1, r.reason
    out = tmp_path / "vz" / "equiv" / "VZRETAIN" / "default"
    assert (out / "mismatches.txt").read_text().count("\n") == len(r.mismatches)
    doc = json.loads((out / "result.json").read_text())
    assert doc["status"] == "fail" and doc["mismatches"] == len(r.mismatches)
    assert doc["oracle"] == "iverilog"


_VZDEV = """// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module VZDEV (output Q, input C, input D, input R);
  parameter SIM_DEVICE = "7SERIES";
  parameter [0:0] BAD = 1'b0;
  reg q;
  assign Q = q;
  initial if (BAD) begin #1 $display("DRC Error : BAD is set on %m"); $finish; end
  always @(R) if (R) assign q = 1'b0; else deassign q;
  generate if (SIM_DEVICE == "VIRTEX6") begin : g6
    always @(posedge C) q <= ~D;
  end else begin : g7
    always @(posedge C) q <= D;
  end endgenerate
endmodule
"""


def _vzdev(tmp_path):
    uni = tmp_path / "src" / "unisims"
    uni.mkdir(parents=True)
    shutil.copy(GLBL, tmp_path / "src" / "glbl.v")
    (uni / "VZDEV.v").write_text(_VZDEV)
    ms = ModelSource("test-src", tmp_path / "src")
    an = analyze(uni / "VZDEV.v", "VZDEV", GLBL)
    lib = tmp_path / "vz"
    lib.mkdir()
    write_text(lib / "VZDEV.v", rewrite(an))
    return ms, an, lib


@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
def test_string_attribute_configuration_is_checked(tmp_path):
    """A quoted string literal reaches the wrapper; the .xvec header cannot hold it."""
    ms, an, lib = _vzdev(tmp_path)
    out = lib / "equiv" / "VZDEV" / "x"
    r = check_model(an, ms, out, {"SIM_DEVICE": '"VIRTEX6"'}, lib=lib)
    assert (r.status, r.config) == ("pass", 'SIM_DEVICE="VIRTEX6"'), r.reason
    assert '.SIM_DEVICE("VIRTEX6")' in (out / "dut" / "xut_dut.v").read_text()
    assert json.loads((out / "result.json").read_text())["attrs"] == {"SIM_DEVICE": '"VIRTEX6"'}


@pytest.mark.vivado
@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
def test_a_model_that_stops_itself_is_an_error_naming_its_message(tmp_path):
    """Icarus does not run the original to XUT_DONE, so the oracle falls back to xsim,
    which stops too: an error (never a pass), quoting the model's own message."""
    ms, an, lib = _vzdev(tmp_path)
    r = check_model(an, ms, lib / "equiv" / "VZDEV" / "bad", {"BAD": "1'b1"}, lib=lib)
    assert (r.status, r.oracle) == ("error", "xsim"), r.reason
    assert "both models stopped before the end of the stimulus" in r.reason, r.reason
    assert "DRC Error : BAD is set" in r.reason and "0 of " in r.reason, r.reason


def _plain_source(tmp_path, fname, model):
    ms, an = _source(tmp_path, fname, model)
    lib = tmp_path / "vz"
    lib.mkdir()
    return ms, an, lib


def test_missing_transformed_copy_is_an_error_not_a_self_comparison(tmp_path):
    """Review Important 1: with no lib/<MODEL>.v, Icarus -y would find the original."""
    ms, an, lib = _plain_source(tmp_path, "vz_retain.v", "VZRETAIN")
    r = check_model(an, ms, lib / "equiv" / "VZRETAIN" / "default", lib=lib)
    assert (r.status, r.oracle) == ("error", ""), r.reason
    assert "no transformed copy of VZRETAIN" in r.reason


def test_transformed_copy_identical_to_the_original_is_an_error(tmp_path):
    ms, an, lib = _plain_source(tmp_path, "vz_retain.v", "VZRETAIN")
    shutil.copy(an.path, lib / "VZRETAIN.v")
    r = check_model(an, ms, lib / "equiv" / "VZRETAIN" / "default", lib=lib)
    assert r.status == "error" and "is identical to the original" in r.reason, r.reason


def test_check_model_never_raises(tmp_path):
    """Review minor 4: even the output directory failing is an error result."""
    ms, an, lib = _plain_source(tmp_path, "vz_retain.v", "VZRETAIN")
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    r = check_model(an, ms, blocker / "out", lib=lib)
    assert r.status == "error" and "cannot record the result" in r.reason, r.reason
