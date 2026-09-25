# SPDX-License-Identifier: Apache-2.0
"""Tests for xut.wrap: the xut_dut wrapper, its map.json and the `xut wrap` CLI (spec §5.2)."""

import json
from pathlib import Path

import pyslang
import pytest
from click.testing import CliRunner

from xut.catalog.model import load_entry
from xut.catalog.unisim import HdlModule, HdlParam, HdlPort
from xut.cli import main
from xut.errors import XutError
from xut.paths import repo_root
from xut.wrap import (
    Bit,
    DutMap,
    DutSpec,
    PortSpec,
    WrapError,
    build_map,
    literal_value,
    render_attr,
    render_wrapper,
    spec_from_catalog,
    spec_from_hdl,
    write_dut,
)

FIX = Path(__file__).parent / "fixtures" / "wrap"


def _entry(name):
    return load_entry("7series", name, repo_root())


def _fdre():
    return _entry("FDRE")


def test_fdre_wrapper_text_matches_golden():
    spec = spec_from_catalog(_fdre(), "init1", {"INIT": "1'b1"})
    assert render_wrapper(spec, build_map(spec)) == (FIX / "FDRE_init1.v").read_text()


def test_fdre_map_bits():
    m = build_map(spec_from_catalog(_fdre(), "init1", {"INIT": 1}))
    assert (m.nclk, m.nin, m.nout) == (1, 3, 1)
    assert [(b.port, b.bit, b.cls) for b in m.of("in")] == [
        ("CE", 0, "data"),
        ("D", 1, "data"),
        ("R", 2, "data"),
    ]
    assert m.clock_name("C") == "clk0" and m.clock_port("clk0") == "C"
    assert m.attrs == {"INIT": "1'b1"}
    assert m.in_ports() == ["CE", "D", "R"] and m.out_ports() == ["Q"]
    assert m.cls_of("C") == "clock"
    assert DutMap.from_json(m.to_json()) == m


def test_attr_rendering_and_allowed_check():
    e = _fdre()
    assert spec_from_catalog(e, "c", {"IS_C_INVERTED": 1}).attrs == (("IS_C_INVERTED", "1'b1"),)
    with pytest.raises(WrapError, match="unknown attribute"):
        spec_from_catalog(e, "c", {"NOPE": 1})


def test_attrs_follow_catalog_order_and_only_explicit_ones_appear():
    spec = spec_from_catalog(_fdre(), "c", {"IS_R_INVERTED": "1'b1", "INIT": "1'b0"})
    assert spec.attrs == (("INIT", "1'b0"), ("IS_R_INVERTED", "1'b1"))
    assert spec_from_catalog(_fdre(), "c", {}).attrs == ()
    assert "#(" not in render_wrapper(*_spec_and_map(_fdre(), {}))


def _spec_and_map(entry, attrs, **kw):
    spec = spec_from_catalog(entry, "c", attrs, **kw)
    return spec, build_map(spec)


def test_literal_value():
    assert literal_value("1'b1") == 1
    assert literal_value("8'hA5") == 0xA5
    assert literal_value("4'd9") == 9
    assert literal_value("7") == 7
    assert literal_value("16'hbe_ef") == 0xBEEF
    assert literal_value("3'o7") == 7


@pytest.mark.parametrize("bad", ["4'bx01z", "8'hzz", "abc", "", "4'b2"])
def test_literal_value_rejects_undefined_or_garbage(bad):
    with pytest.raises(WrapError):
        literal_value(bad)


BITS8 = {"name": "A", "kind": "bits", "width": 8}
BITS1 = {"name": "B", "kind": "bits", "width": 1}
BITS64 = {"name": "W", "kind": "bits", "width": 64}
STR = {"name": "S", "kind": "string"}
INT = {"name": "N", "kind": "integer"}
REAL = {"name": "R", "kind": "real"}


@pytest.mark.parametrize(
    ("attr", "value", "lit"),
    [
        (BITS1, 1, "1'b1"),
        (BITS1, 0, "1'b0"),
        (BITS8, 0xA5, "8'ha5"),
        (BITS8, 3, "8'h03"),
        (BITS8, "8'hA5", "8'hA5"),
        (BITS8, "8'b1010_0101", "8'b1010_0101"),
        (BITS64, 2**64 - 1, "64'hffffffffffffffff"),
        (STR, "TRUE", '"TRUE"'),
        (STR, '"SYNC"', '"SYNC"'),
        (STR, 8, '"8"'),
        (INT, 12, "12"),
        (INT, "-3", "-3"),
        (REAL, 5, "5.0"),
        (REAL, "-360.000", "-360.0"),
        (REAL, 0.5, "0.5"),
        (REAL, 1e-5, "1e-05"),
    ],
)
def test_render_attr_preserves_kind(attr, value, lit):
    assert render_attr(attr, value) == lit


@pytest.mark.parametrize(
    ("attr", "value", "match"),
    [
        (BITS1, 2, "does not fit"),
        (BITS1, -1, "does not fit"),
        (BITS8, 256, "does not fit"),
        (BITS8, "4'hA", "8 bits"),  # sized literal of the wrong width
        (BITS8, "16'h00A5", "8 bits"),
        (BITS1, "1'b11", "does not fit"),
        (BITS8, "8'hxx", "x/z"),
        (BITS8, "165", "sized"),  # bare decimal: ambiguous for a bit vector
        (BITS8, True, "bool"),
        (BITS8, 1.0, "float"),
        (STR, True, "bool"),  # YAML `TRUE` parses to a bool: never render it as "True"
        (STR, 'A"B', "quote"),
        (STR, "A\nB", "newline"),
        (STR, 1.5, "float"),
        (INT, "1.5", "integer"),
        (INT, 2**31, "32-bit"),
        (INT, False, "bool"),
        (INT, 2.0, "float"),
        (REAL, "inf", "finite"),
        (REAL, "nan", "finite"),
        (REAL, "fast", "real"),
        (REAL, True, "bool"),
    ],
)
def test_render_attr_rejects(attr, value, match):
    with pytest.raises(WrapError, match=match):
        render_attr(attr, value)


def test_allowed_enumeration_enforced_unless_allow_illegal():
    dsp = _entry("DSP48E1")
    assert spec_from_catalog(dsp, "c", {"ACASCREG": 2}).attrs == (("ACASCREG", "2"),)
    with pytest.raises(WrapError, match=r"DSP48E1\.ACASCREG=3 is not one of"):
        spec_from_catalog(dsp, "c", {"ACASCREG": 3})
    assert spec_from_catalog(dsp, "c", {"ACASCREG": 3}, allow_illegal=True).attrs == (
        ("ACASCREG", "3"),
    )
    # an allowed-list value is still rendered in its kind even when illegal is allowed
    with pytest.raises(WrapError, match="integer"):
        spec_from_catalog(dsp, "c", {"ACASCREG": "x"}, allow_illegal=True)


def test_allowed_bits_compared_by_value():
    # IDDR.INIT_Q1 is a 1-bit vector whose allowed list is the bare decimals 0/1
    iddr = _entry("IDDR")
    assert spec_from_catalog(iddr, "c", {"INIT_Q1": "1'b1"}).attrs == (("INIT_Q1", "1'b1"),)


def test_allowed_range_is_not_an_enumeration():
    lut = _entry("LUT6")
    spec = spec_from_catalog(lut, "c", {"INIT": "64'h8000000000000000"})
    assert spec.attrs == (("INIT", "64'h8000000000000000"),)
    mm = _entry("MMCME2_ADV")
    assert spec_from_catalog(mm, "c", {"CLKFBOUT_MULT_F": "10.0"}, raw_clock_out=True).attrs == (
        ("CLKFBOUT_MULT_F", "10.0"),
    )


def _toy(ports, params=()):
    return HdlModule("TOYIO", Path("TOYIO.v"), [HdlPort(*p) for p in ports], list(params))


def test_inout_split_and_obs():
    spec = spec_from_hdl(_toy([("IO", "inout", 2), ("I", "input", 1), ("O", "output", 1)]), "d", {})
    m = build_map(spec)
    assert [(b.port, b.role, b.index) for b in m.of("in")] == [
        ("IO", "drive_en", 0),
        ("IO", "drive_en", 1),
        ("IO", "drive_val", 0),
        ("IO", "drive_val", 1),
        ("I", "", 0),
    ]
    assert [(b.port, b.role) for b in m.of("out")] == [("IO", "obs"), ("IO", "obs"), ("O", "")]
    assert m.in_ports() == ["I"] and m.out_ports() == ["IO", "O"]
    text = render_wrapper(spec, m)
    assert "assign IO__io[0] = in_vec[0] ? in_vec[2] : 1'bz;" in text
    assert "assign IO__io[1] = in_vec[1] ? in_vec[3] : 1'bz;" in text
    assert "assign out_vec[0] = IO__io[0];" in text
    assert "assign out_vec[1] = IO__io[1];" in text
    assert ".IO(IO__io)" in text


def test_multibit_ports_take_contiguous_lsb_first_slices():
    spec = spec_from_hdl(
        _toy([("A", "input", 4), ("CLK", "input", 1), ("B", "input", 1), ("Y", "output", 3)]),
        "d",
        {},
    )
    m = build_map(spec)
    assert [(b.port, b.index, b.bit) for b in m.port_bits("in", "A")] == [
        ("A", i, i) for i in range(4)
    ]
    assert m.port_bits("in", "B")[0].bit == 4
    assert m.clock_name("CLK") == "clk0"
    text = render_wrapper(spec, m)
    assert ".A(in_vec[3:0])" in text and ".B(in_vec[4])" in text and ".Y(out_vec[2:0])" in text


def test_hdl_attrs_rendered_by_param_kind():
    params = [HdlParam("INIT", "bits", 4, "4'h0"), HdlParam("MODE", "string", None, "A")]
    spec = spec_from_hdl(_toy([("O", "output", 1)], params), "d", {"INIT": 5, "MODE": "B"})
    assert spec.attrs == (("INIT", "4'h5"), ("MODE", '"B"'))
    with pytest.raises(WrapError, match="unknown attribute"):
        spec_from_hdl(_toy([("O", "output", 1)], params), "d", {"NOPE": 1})


def test_no_outputs_or_inputs_still_legal():
    spec = spec_from_hdl(_toy([("I", "input", 1)]), "d", {})
    m = build_map(spec)
    assert (m.nclk, m.nin, m.nout) == (0, 1, 0)
    text = render_wrapper(spec, m)
    assert "input  wire [0:0] clk," in text and "output wire [0:0] out_vec" in text
    assert "assign out_vec = 1'b0;" in text


def test_clock_out_needs_observers():
    mod = HdlModule(
        "BUFG", Path("BUFG.v"), [HdlPort("O", "output", 1), HdlPort("I", "input", 1)], []
    )
    with pytest.raises(WrapError, match="§5.4"):
        build_map(spec_from_hdl(mod, "d", {}))
    m = build_map(spec_from_hdl(mod, "d", {}, raw_clock_out=True))
    assert [b.cls for b in m.of("out")] == ["clock_out"]


def test_catalog_classes_are_used_and_recorded():
    """Classes come from the catalog (with overrides), not a hard-coded table."""
    with pytest.raises(WrapError, match=r"MMCME2_ADV\.CLKFBOUT.*§5\.4"):
        build_map(spec_from_catalog(_entry("MMCME2_ADV"), "c", {}))
    spec, m = _spec_and_map(_entry("MMCME2_ADV"), {}, raw_clock_out=True)
    assert {b.cls for b in m.port_bits("in", "DADDR")} == {"drp"}
    assert {b.cls for b in m.port_bits("out", "DO")} == {"drp"}
    assert {b.cls for b in m.port_bits("in", "RST")} == {"async"}
    assert [b.port for b in m.of("clk")] == ["CLKFBIN", "CLKIN1", "CLKIN2", "DCLK", "PSCLK"]
    dsp = build_map(spec_from_catalog(_entry("DSP48E1"), "c", {}))
    assert {b.cls for b in dsp.port_bits("in", "C")} == {"data"}
    ldce = build_map(spec_from_catalog(_entry("LDCE"), "c", {}))
    assert ldce.cls_of("GE") == "gate" and ldce.cls_of("G") == "gate"
    ibuf = build_map(spec_from_catalog(_entry("IBUF"), "c", {}))
    assert ibuf.cls_of("I") == "pad"


def test_every_catalog_primitive_wraps():
    names = sorted(
        f.stem
        for f in (repo_root() / "catalog" / "7series").glob("*.yaml")
        if not f.name.endswith(".overrides.yaml")
    )
    assert len(names) > 100
    for n in names:
        spec, m = _spec_and_map(_entry(n), {}, raw_clock_out=True)
        text = render_wrapper(spec, m)
        assert f"  {n} dut (" in text, n
        assert sum(b.vec == "clk" for b in m.bits) == m.nclk
        assert DutMap.from_json(m.to_json()) == m, n


def test_direction_class_mismatch_rejected():
    bad = DutSpec("T", "7series", "c", (PortSpec("O", "output", 1, "clock"),), ())
    with pytest.raises(WrapError, match=r"T\.O: output port cannot have class 'clock'"):
        build_map(bad)
    bad = DutSpec("T", "7series", "c", (PortSpec("I", "input", 1, "inout"),), ())
    with pytest.raises(WrapError, match="input port cannot have class 'inout'"):
        build_map(bad)
    bad = DutSpec("T", "7series", "c", (PortSpec("I", "input", 0, "data"),), ())
    with pytest.raises(WrapError, match="width"):
        build_map(bad)


def test_map_accessors_are_loud():
    m = build_map(spec_from_catalog(_fdre(), "c", {}))
    with pytest.raises(WrapError, match="not a clock"):
        m.clock_name("D")
    for bad in ("clk1", "clkX", "in0"):
        with pytest.raises(WrapError, match="clock"):
            m.clock_port(bad)
    with pytest.raises(WrapError, match="no port"):
        m.cls_of("NOPE")


def test_map_json_roundtrip_and_validation():
    m = build_map(spec_from_catalog(_fdre(), "c", {"INIT": 1}))
    d = json.loads(m.to_json())
    assert d["format"] == "xut-map 1"
    assert [b["port"] for b in d["bits"]] == ["Q", "C", "CE", "D", "R"]  # catalog order
    assert d["bits"][1] == {
        "vec": "clk",
        "bit": 0,
        "port": "C",
        "index": 0,
        "cls": "clock",
        "role": "",
    }
    with pytest.raises(WrapError, match="not an xut-map 1"):
        DutMap.from_json(json.dumps({**d, "format": "xut-map 9"}))
    with pytest.raises(WrapError, match="invalid JSON"):
        DutMap.from_json("{")
    with pytest.raises(WrapError, match="missing"):
        DutMap.from_json(json.dumps({k: v for k, v in d.items() if k != "nin"}))
    with pytest.raises(WrapError, match="unknown"):
        DutMap.from_json(json.dumps({**d, "extra": 1}))
    bad_bit = dict(d, bits=[{**d["bits"][0], "colour": "red"}] + d["bits"][1:])
    with pytest.raises(WrapError, match="bit 0"):
        DutMap.from_json(json.dumps(bad_bit))
    with pytest.raises(WrapError, match="nin=4"):
        DutMap.from_json(json.dumps({**d, "nin": 4}))
    swapped = dict(d, bits=d["bits"][:2] + [d["bits"][3], d["bits"][2]] + d["bits"][4:])
    with pytest.raises(WrapError, match="in_vec"):
        DutMap.from_json(json.dumps(swapped))


def test_map_load(tmp_path):
    m = write_dut(spec_from_catalog(_fdre(), "init1", {"INIT": "1'b1"}), tmp_path)
    assert DutMap.load(tmp_path / "xut_dut.map.json") == m
    assert isinstance(m.bits[0], Bit)


def _slang_errors(texts, incdir):
    sm = pyslang.SourceManager()
    sm.addUserDirectories(str(incdir))
    comp = pyslang.ast.Compilation()
    for text in texts:
        comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromText(text, sm))
    return [d for d in comp.getAllDiagnostics() if d.isError()], sm


def test_written_wrapper_elaborates_with_stub(tmp_path):
    m = write_dut(spec_from_catalog(_fdre(), "init1", {"INIT": "1'b1"}), tmp_path, cocotb_top=True)
    assert json.loads((tmp_path / "xut_dut.map.json").read_text())["format"] == "xut-map 1"
    vh = (tmp_path / "xut_cfg.vh").read_text()
    assert vh.startswith("// SPDX-License-Identifier: Apache-2.0\n")
    assert "`define XUT_NIN 3" in vh
    for f in ("xut_dut.v", "xut_cocotb_top.v"):
        assert (tmp_path / f).read_text().startswith("// SPDX-License-Identifier: Apache-2.0\n")
    stub = (
        "`timescale 1ps / 1ps\n"
        "module FDRE #(parameter [0:0] INIT = 1'b0)(output Q, input C, CE, D, R); endmodule\n"
        "module glbl; wire GSR; endmodule\n"
    )
    errors, sm = _slang_errors(
        [
            stub,
            (tmp_path / "xut_dut.v").read_text(),
            (tmp_path / "xut_cocotb_top.v").read_text(),
        ],
        tmp_path,
    )
    assert errors == [], pyslang.DiagnosticEngine.reportAll(sm, errors)
    assert m.nin == 3


def test_write_dut_without_cocotb_top(tmp_path):
    write_dut(spec_from_catalog(_fdre(), "c", {}), tmp_path / "new")
    assert sorted(p.name for p in (tmp_path / "new").iterdir()) == [
        "xut_cfg.vh",
        "xut_dut.map.json",
        "xut_dut.v",
    ]


def test_wrap_error_is_a_clean_cli_error():
    assert issubclass(WrapError, XutError) and issubclass(WrapError, ValueError)


# --- CLI ------------------------------------------------------------------------------


def test_cli_wrap_fdre(tmp_path):
    out = tmp_path / "wrap-demo"
    r = CliRunner().invoke(
        main, ["wrap", "FDRE", "--cfg", "init1", "--attr", "INIT=1'b1", "--out", str(out)]
    )
    assert r.exit_code == 0, r.output
    assert r.output == f"{out}: nclk=1 nin=3 nout=1\n"
    assert (out / "xut_dut.v").read_text() == (FIX / "FDRE_init1.v").read_text()
    assert not (out / "xut_cocotb_top.v").exists()


def test_cli_wrap_cocotb_top_and_allow_illegal(tmp_path):
    args = ["wrap", "DSP48E1", "--attr", "ACASCREG=3", "--out", str(tmp_path)]
    r = CliRunner().invoke(main, args)
    assert r.exit_code == 1 and "Error: DSP48E1.ACASCREG=3 is not one of" in r.output
    r = CliRunner().invoke(main, [*args, "--allow-illegal", "--cocotb-top"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "xut_cocotb_top.v").is_file()
    assert DutMap.load(tmp_path / "xut_dut.map.json").cfg == "default"


@pytest.mark.parametrize(
    ("args", "match"),
    [
        (["FDRE", "--attr", "INIT"], "--attr 'INIT' is not NAME=VALUE"),
        (["FDRE", "--attr", "INIT=1'b1", "--attr", "INIT=1'b0"], "--attr INIT given twice"),
        (["NOSUCHPRIM"], "no catalog entry for NOSUCHPRIM"),
        (["BUFGCTRL"], "§5.4"),
    ],
)
def test_cli_wrap_errors_are_clean(tmp_path, args, match):
    r = CliRunner().invoke(main, ["wrap", *args, "--out", str(tmp_path)])
    assert r.exit_code != 0
    assert "Traceback" not in r.output
    assert match in r.output, r.output


def test_cli_wrap_raw_clock_out(tmp_path):
    r = CliRunner().invoke(main, ["wrap", "BUFGCTRL", "--raw-clock-out", "--out", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert DutMap.load(tmp_path / "xut_dut.map.json").cls_of("O") == "clock_out"
