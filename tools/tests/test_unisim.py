# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest
from xut.catalog.unisim import HdlParam, HdlPort, find_model, parse_module
from xut.paths import VIVADO_UNISIM, repo_root

FIX = Path(__file__).parent / "fixtures" / "unisim"


def test_ansi_ports():
    m = parse_module(FIX / "TOYANSI.v", "TOYANSI")
    assert m.ports == [
        HdlPort("Q", "output", 1),
        HdlPort("D", "input", 4),
        HdlPort("IO", "inout", 1),
    ]


def test_params_decoded_and_filtered():
    m = parse_module(FIX / "TOYANSI.v", "TOYANSI")
    by = {p.name: p for p in m.params}
    assert set(by) == {"INIT", "IOSTANDARD", "DEPTH", "PERIOD"}  # no LOC, no HIDDEN
    assert by["IOSTANDARD"] == HdlParam("IOSTANDARD", "string", None, "DEFAULT")
    assert by["INIT"] == HdlParam("INIT", "bits", 1, "1'b1")
    assert by["DEPTH"].kind == "integer" and by["DEPTH"].default == 4
    assert by["PERIOD"].kind == "real" and by["PERIOD"].default == 10.0


def test_non_ansi():
    m = parse_module(FIX / "TOYOLD.v", "TOYOLD")
    assert [p.width for p in m.ports] == [16, 14, 1]
    assert {p.name: p.default for p in m.params}["INIT_00"] == "256'h0"


def test_find_model_prefers_first_dir(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "X.v").write_text("module X; endmodule\n")
    assert find_model("X", [tmp_path / "a", tmp_path / "b"]) == (tmp_path / "b" / "X.v", "b")
    assert find_model("Y", [tmp_path / "a"]) is None


@pytest.mark.skipif(not VIVADO_UNISIM.is_dir(), reason="Vivado not installed")
def test_real_iobuf_strings():
    m = parse_module(VIVADO_UNISIM / "IOBUF.v", "IOBUF")
    assert {p.name: p.default for p in m.params}["IOSTANDARD"] == "DEFAULT"


@pytest.mark.skipif(not VIVADO_UNISIM.is_dir(), reason="Vivado not installed")
def test_real_models_sanity():
    by = {p.name: p for p in parse_module(VIVADO_UNISIM / "FDRE.v", "FDRE").params}
    assert by["INIT"] == HdlParam("INIT", "bits", 1, "1'b0")
    assert not {"LOC", "MSGON", "XON"} & set(by)
    ram = parse_module(VIVADO_UNISIM / "RAMB18E1.v", "RAMB18E1")
    rp = {p.name: p for p in ram.params}
    assert rp["INIT_00"] == HdlParam("INIT_00", "bits", 256, "256'h0")
    assert rp["RAM_MODE"].kind == "string" and rp["RAM_MODE"].default == "TDP"
    mm = {p.name: p for p in parse_module(VIVADO_UNISIM / "MMCME2_ADV.v", "MMCME2_ADV").params}
    assert mm["CLKIN1_PERIOD"].kind == "real"
    assert mm["BANDWIDTH"].default == "OPTIMIZED"


@pytest.mark.skipif(not VIVADO_UNISIM.is_dir(), reason="Vivado not installed")
def test_all_unisims_parse():
    """Every UNISIM model's header must extract without raising."""
    ok, failures = 0, []
    for f in sorted(VIVADO_UNISIM.glob("*.v")):
        try:
            parse_module(f, f.stem)
            ok += 1
        except Exception as e:  # collect every failure for the log
            failures.append(f"{f.name}: {type(e).__name__}: {e}")
    log = repo_root() / ".cache" / "unisim_parse_all.log"
    log.parent.mkdir(exist_ok=True)
    log.write_text(f"parsed {ok} failed {len(failures)}\n" + "".join(x + "\n" for x in failures))
    print(f"parsed {ok} failed {len(failures)} (log: {log})")
    assert not failures, failures[:10]
