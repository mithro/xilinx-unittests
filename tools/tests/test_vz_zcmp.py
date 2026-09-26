# SPDX-License-Identifier: Apache-2.0
"""The z-compare rewrite of ``xut verilatorize`` (ruling S38): an input port compared with
z becomes the constant a driven input gives; anything else z-compared is refused; the
equivalence check proves it (and catches a wrong constant); the validity guards."""

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from xut.container import SIM_IMAGE, image_digest
from xut.formats.xvec import Event
from xut.modelsrc import ModelSource
from xut.verilatorize import driver, zcmp
from xut.verilatorize.analyze import TransformError
from xut.verilatorize.driver import transform_one
from xut.verilatorize.equiv import Checked, check_model

FIX = Path(__file__).parent / "fixtures" / "verilatorize"
GLBL = FIX / "glbl.v"
_no_image = shutil.which("docker") is None or image_digest(SIM_IMAGE) is None

HEAD = "// SPDX-License-Identifier: Apache-2.0\n`timescale 1ps/1ps\n"


def _model(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / f"{name}.v"
    f.write_text(HEAD + textwrap.dedent(body))
    return f


def test_rewrites_both_operand_orders_selects_and_inequality(tmp_path):
    text, found = zcmp.rewrite_text((FIX / "vz_zcmp.v").read_text(), "VZZCMP")
    assert [(z.op, z.port, z.const) for z in found] == [
        ("===", "CE", "1'b0"),
        ("!==", "CLR", "1'b1"),
        ("!==", "R", "1'b1"),
        ("===", "S", "1'b0"),
        ("!==", "S", "1'b1"),
    ]
    assert "wire ce_en = CE || (1'b0);" in text
    assert "if (CLR && (1'b1)) q <= 1'b0;" in text
    assert "else if ((1'b1) && R) q <= 1'b0;" in text
    assert "assign O[0] = (1'b0) ? 1'b1 : S[0];" in text
    assert "assign O[1] = (1'b1) ? S[1] : 1'b0;" in text
    assert "1'bz" not in text.split("\n", 3)[3] and zcmp.leftover(text) == 0


def test_a_z_compare_only_model_is_transformed(tmp_path):
    shutil.copy(FIX / "vz_zcmp.v", tmp_path / "VZZCMP.v")
    out = tmp_path / "out"
    out.mkdir()
    e = transform_one(tmp_path / "VZZCMP.v", GLBL, out)
    assert (e.status, e.rewrites) == ("transformed", ["zcmp"])
    assert e.triggers == [] and not e.nonconstant_overrides
    assert any("5 comparison(s) of input port(s) CE, CLR, R, S" in n for n in e.notes)
    assert "=== 1'bz" not in (out / "VZZCMP.v").read_text()


def test_shadow_and_z_compare_rewrites_compose(tmp_path):
    f = _model(
        tmp_path,
        "VZBOTH",
        """\
        module VZBOTH (output Q, input C, input D, input CLR);
          reg q;
          assign Q = q;
          always @(CLR) if (CLR && (CLR !== 1'bz)) assign q = 1'b0; else deassign q;
          always @(posedge C) q <= D;
        endmodule
        """,
    )
    (tmp_path / "o").mkdir()
    e = transform_one(f, GLBL, tmp_path / "o")
    assert (e.status, e.rewrites) == ("transformed", ["shadow", "zcmp"]), e.reason
    text = (tmp_path / "o" / "VZBOTH.v").read_text()
    assert "q__ovr_sel" in text and "(1'b1)" in text and "1'bz" not in text


def test_disabled_code_leftover_is_noted(tmp_path):
    f = _model(
        tmp_path,
        "VZLEFT",
        """\
        module VZLEFT (output O, input I);
        `ifdef XIL_TIMING
          assign O = (I === 1'bz) ? 1'b1 : I;
        `else
          assign O = (I === 1'bz) ? 1'b0 : I;
        `endif
        endmodule
        """,
    )
    (tmp_path / "o").mkdir()
    e = transform_one(f, GLBL, tmp_path / "o")
    assert e.status == "transformed"
    assert any("1 z-literal comparison(s) remain in preprocessor-disabled" in n for n in e.notes)


REFUSED = {
    "internal net": """\
        module M (output O, input I);
          wire i_in = I;
          assign O = (i_in === 1'bz) ? 1'b0 : i_in;
        endmodule
        """,
    "inout port": """\
        module M (output O, inout IO);
          assign O = (IO === 1'bz) ? 1'b0 : IO;
        endmodule
        """,
    "expression": """\
        module M (output O, input A, input B);
          assign O = ((A & B) === 1'bz) ? 1'b0 : A;
        endmodule
        """,
    "`==` with": """\
        module M (output O, input I);
          assign O = (I == 1'bz) ? 1'b0 : I;
        endmodule
        """,
    "not the primary module": """\
        module M (output O, input I);
          H h (.O(O), .I(I));
        endmodule
        module H (output O, input I);
          assign O = (I === 1'bz) ? 1'b0 : I;
        endmodule
        """,
    "case item with a z literal": """\
        module M (output reg O, input I);
          always @(I) case (I) 1'bz: O = 1'b1; default: O = I; endcase
        endmodule
        """,
    "internal net I": """\
        module M (output reg O, input I);
          function f(input I); f = (I === 1'bz); endfunction
          always @(I) O = f(I);
        endmodule
        """,
}


@pytest.mark.parametrize("what", sorted(REFUSED))
def test_other_z_compares_are_refused_loudly(tmp_path, what):
    f = _model(tmp_path, "M", REFUSED[what])
    with pytest.raises(TransformError, match=what.split()[0].strip("`")):
        zcmp.find(f, "M")
    (tmp_path / "o").mkdir()
    e = transform_one(f, GLBL, tmp_path / "o")
    assert e.status == "unsupported" and what.split()[0].strip("`") in e.reason


def test_guard_helpers():
    class M:
        bits = [
            type("B", (), {"vec": v, "port": p, "role": r})()
            for v, p, r in (("clk", "C", ""), ("in", "D", ""), ("in", "D", ""),
                            ("in", "IO", "drive_en"))
        ]  # fmt: skip

    class V:
        events = [Event(0, "set", "in", 0, 0, "1"), Event(5, "set", "in", 1, 0, "z0")]

    assert zcmp.connected(M()) == {"C": 1, "D": 2}  # per bit; inout drive bits excluded
    assert zcmp.drives_z(V())
    V.events = V.events[:1]
    assert not zcmp.drives_z(V())


def _zsource(tmp_path: Path) -> ModelSource:
    uni = tmp_path / "src" / "unisims"
    uni.mkdir(parents=True)
    shutil.copy(GLBL, tmp_path / "src" / "glbl.v")
    shutil.copy(FIX / "vz_zcmp.v", uni / "VZZCMP.v")
    return ModelSource("zcmp-src", tmp_path / "src")


def _subject(ms: ModelSource) -> Checked:
    return Checked("VZZCMP", ms.unisims / "VZZCMP.v", [], [], False, ("zcmp",))


def test_equivalence_refuses_an_undriven_input_or_a_z_stimulus(tmp_path, monkeypatch):
    ms = _zsource(tmp_path)
    lib = tmp_path / "vz"
    lib.mkdir()
    transform_one(ms.unisims / "VZZCMP.v", ms.glbl, lib)
    # S is 2 bits wide: one driven bit leaves it undriven too (review M3)
    monkeypatch.setattr(zcmp, "connected", lambda m: {"C": 1, "D": 1, "S": 1})
    r = check_model(_subject(ms), ms, tmp_path / "a", {}, lib=lib)
    assert r.status == "error" and "CE, CLR, R, S of VZZCMP left unconnected" in r.reason, r
    monkeypatch.undo()
    monkeypatch.setattr(zcmp, "drives_z", lambda vec: True)
    r = check_model(_subject(ms), ms, tmp_path / "b", {}, lib=lib)
    assert (r.status, r.reason) == ("error", zcmp.Z_STIMULUS)


def test_equivalence_stimulus_drives_every_input_of_a_z_compare_model(tmp_path):
    from xut.catalog.unisim import parse_module
    from xut.verilatorize.equiv import equiv_stimulus
    from xut.wrap import spec_from_hdl, write_dut

    ms = _zsource(tmp_path)
    m = write_dut(
        spec_from_hdl(parse_module(ms.unisims / "VZZCMP.v", "VZZCMP"), "default", {}),
        tmp_path / "dut",
    )
    vec = equiv_stimulus(_subject(ms), m)
    for port in ("CE", "R", "D", "S", "CLR"):
        bits = {b.bit for b in m.port_bits("in", port)}
        seen = {
            e.value[e.msb - b]
            for e in vec.events
            if e.op == "set"
            for b in bits
            if e.lsb <= b <= e.msb
        }
        assert seen >= {"0", "1"}, (port, seen)
    assert any(label.startswith("zcmp.") for label in (e.target for e in vec.events))


@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
def test_z_compare_fixture_is_equivalent_and_a_wrong_constant_fails(tmp_path, monkeypatch):
    ms = _zsource(tmp_path)
    out = tmp_path / "vz"
    monkeypatch.setattr(driver, "vz_dir", lambda ms: out)
    man = driver.verilatorize(ms, progress=lambda _line: None, check=True)
    e = man.models["VZZCMP"]
    assert (e.status, e.rewrites, e.equiv) == ("transformed", ["zcmp"], {"default": "pass"})
    assert e.equiv_oracle == {"default": "iverilog"}
    # the mutation: `P === 1'bz` rewritten to 1'b1 (a floating input) must be caught
    monkeypatch.setitem(zcmp._CMP, zcmp._SX.CaseEqualityExpression, ("===", "1'b1"))
    bad = tmp_path / "bad"
    bad.mkdir()
    assert transform_one(ms.unisims / "VZZCMP.v", ms.glbl, bad).status == "transformed"
    r = check_model(_subject(ms), ms, bad / "equiv", {}, lib=bad)  # under the mount
    doc = json.loads((bad / "equiv" / "result.json").read_text())
    assert r.status == "fail" and r.mismatches, (r.reason, doc)
