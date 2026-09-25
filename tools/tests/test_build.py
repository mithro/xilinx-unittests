# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import yaml
from xut.catalog.build import build_all
from xut.catalog.model import load_entry
from xut.catalog.portclass import default_class

FIX = Path(__file__).parent / "fixtures"


def _toy_models(tmp_path):
    u = tmp_path / "unisims"
    u.mkdir()
    (u / "TOYFF.v").write_text(
        'module TOYFF #(parameter [0:0] INIT = 1\'b0, parameter MODE = "FAST", '
        "parameter [0:0] EXTRA = 1'b0)(output Q, input C, input D, output [15:0] DO);\n"
        "endmodule\n"
    )
    r = tmp_path / "retarget"
    r.mkdir()
    (r / "TOYLUT.v").write_text("module TOYLUT(output O, input I0); endmodule\n")
    return [u, r]


def test_build_writes_yaml_and_reports_mismatch(tmp_path):
    out = tmp_path / "catalog"
    report = build_all(
        FIX / "ug953_toy.txt", ["TOYFF", "TOYLUT", "GHOST"], out, _toy_models(tmp_path)
    )
    ff = yaml.safe_load((out / "TOYFF.yaml").read_text())
    assert ff["group"] == "REGISTER"
    assert [p["name"] for p in ff["ports"]] == ["Q", "C", "D", "DO"]
    assert {a["name"]: a["default"] for a in ff["attributes"]}["MODE"] == "FAST"
    # EXTRA is in UNISIM but not in UG953 table -> reported, still present
    assert any("TOYFF" in line and "EXTRA" in line for line in report)
    lut = yaml.safe_load((out / "TOYLUT.yaml").read_text())
    assert lut["model"]["library"] == "retarget"
    # GHOST: documented name with no model and no section -> reported, not crash
    assert any("GHOST" in line for line in report)


def test_overrides_merge(tmp_path):
    out = tmp_path / "catalog" / "7series"
    build_all(FIX / "ug953_toy.txt", ["TOYFF"], out, _toy_models(tmp_path))
    (out / "TOYFF.overrides.yaml").write_text(
        yaml.safe_dump(
            {
                "ports": {"D": {"cls": "async"}},
                "claims": [
                    {"id": "TOYFF.C1", "text": "Q follows D", "page": 10, "provenance": "doc:10"}
                ],
            }
        )
    )
    e = load_entry("7series", "TOYFF", tmp_path)
    assert {p["name"]: p["cls"] for p in e.ports}["D"] == "async"
    assert e.claims[0]["id"] == "TOYFF.C1"


def test_default_port_classes():
    assert default_class("FDRE", "C", "input") == "clock"
    assert default_class("FDCE", "CLR", "input") == "async"
    assert default_class("LDCE", "G", "input") == "gate"
    assert default_class("IOBUF", "IO", "inout") == "inout"
    assert default_class("MMCME2_ADV", "CLKOUT0", "output") == "clock_out"
    assert default_class("MMCME2_ADV", "LOCKED", "output") == "data"
    assert default_class("MMCME2_ADV", "DADDR", "input") == "drp"
    assert default_class("FDRE", "D", "input") == "data"
    assert default_class("IBUF", "I", "input") == "pad"
    assert default_class("BUFGCTRL", "I0", "input") == "clock"
    assert default_class("LUT2", "I0", "input") == "data"
