# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from xut.catalog.ug953 import split_sections

TXT = (Path(__file__).parent / "fixtures" / "ug953_toy.txt").read_text()


def test_sections_found_with_group_and_page():
    s = split_sections(TXT, ["TOYFF", "TOYLUT"])
    assert s["TOYFF"].group == "REGISTER" and s["TOYFF"].subgroup == "SDR"
    assert s["TOYFF"].page == 10
    assert s["TOYLUT"].page == 11
    assert s["TOYFF"].description == "Toy flip-flop for parser tests"


def test_ports_parsed_including_bus():
    p = split_sections(TXT, ["TOYFF"])["TOYFF"].ports
    assert p["C"] == {"direction": "input", "width": 1, "function": "Clock input."}
    assert p["DO"]["width"] == 16


def test_attributes_parsed():
    a = split_sections(TXT, ["TOYFF"])["TOYFF"].attributes
    assert a["INIT"] == {"type": "BINARY", "allowed": ["1'b0", "1'b1"], "default": "1'b0"}
    assert a["MODE"]["allowed"] == ['"FAST"', '"SLOW"']


def test_design_entry():
    d = split_sections(TXT, ["TOYFF"])["TOYFF"].design_entry
    assert d == {"instantiation": "Yes", "inference": "Recommended", "ip_catalog": "No"}


def test_missing_section_is_absent_not_error():
    assert "NOPE" not in split_sections(TXT, ["NOPE"])


# ---- real-layout quirks (synthetic fixture imitating pdftotext -layout output) ----

LAY = (Path(__file__).parent / "fixtures" / "ug953_layouts.txt").read_text()


def _ram():
    return split_sections(LAY, ["TOYRAM"])["TOYRAM"]


def test_wrapped_description_and_page():
    s = _ram()
    assert s.description == "Toy block memory with a long title that wraps onto a second line"
    assert s.page == 20
    assert s.group == "BLOCKRAM"


def test_port_bus_forms_and_ranges():
    p = _ram().ports
    assert p["ADDRA"]["width"] == 16
    assert p["ADDRB"]["width"] == 14
    assert p["DOA"] == {"direction": "output", "width": 32, "function": "Toy output bus."}
    for n in ("Q1", "Q2", "CE1", "CE2", "SHIFTIN1", "SHIFTIN2", "D1", "D2"):
        assert p[n]["width"] == 1, n
    assert p["Q2"]["direction"] == "output"


def test_port_function_on_line_above_and_page_break():
    p = _ram().ports
    assert p["CLKA"]["function"] == "Toy clock."
    # continues after a page footer and a repeated table header
    assert p["RSTA"]["function"] == "Toy reset with a long description"
    assert p["WEA"]["width"] == 4
    # non-7-series directions and prose rows are not ports
    assert "INTERNAL_TCK" not in p and "LUT" not in p
    assert len(p) == 14


def test_design_entry_variants():
    assert _ram().design_entry == {
        "instantiation": "Yes",
        "inference": "Recommended",
        "ip_catalog": "Yes",
        "macro_support": "Yes",
    }


def test_attribute_names_wrapped_grouped_ranged():
    a = _ram().attributes
    expected = {
        "RDADDR_COLL_HW",
        "SIM_COLL_CHECK",
        "DOA_REG",
        "DOB_REG",
        "EN_ECC",
        "IS_CLK_INVERTED",
        *(f"INIT_{i:02X}" for i in range(16)),
        "INITP_00",
        "INITP_01",
        "SRVAL_A",
        "SRVAL_B",
        "WIDTH",
        "SRVAL",
        "CLKOUT0_DIVIDE_F",
        "CLKOUT0_PHASE",
        "CLKOUT1_PHASE",
        "CLKOUT2_PHASE",
        "CLKOUT4_CASCADE",
    }
    assert set(a) == expected


def test_attribute_cells():
    a = _ram().attributes
    assert a["RDADDR_COLL_HW"] == {
        "type": "STRING",
        "allowed": ['"DELAYED_WRITE"', '"PERFORMANCE"'],
        "default": '"DELAYED_WRITE"',
    }
    assert a["SIM_COLL_CHECK"]["allowed"] == ['"ALL"', '"GEN_X"', '"NONE"', '"WARN"']
    assert a["SIM_COLL_CHECK"]["default"] == '"ALL"'
    assert a["DOB_REG"] == {"type": "DECIMAL", "allowed": ["0", "1"], "default": "0"}
    assert a["EN_ECC"] == {"type": "BOOLEAN", "allowed": ["FALSE", "TRUE"], "default": "FALSE"}
    assert a["IS_CLK_INVERTED"]["allowed"] == ["1'b0", "1'b1"]  # 1-bit range enumerated
    assert a["INIT_0F"] == {"type": "HEX", "allowed": ["256 bit HEX"], "default": "All zeros"}
    assert a["SRVAL_B"]["type"] == "HEX"
    assert a["WIDTH"]["allowed"] == ["0", "1", "2", "4", "9"]
    assert a["WIDTH"]["default"] == "0"
    assert a["SRVAL"]["allowed"] == ["Any 72-Bit Value"]
    assert a["SRVAL"]["default"] == "All zeros"
    assert a["CLKOUT0_DIVIDE_F"]["type"] == "FLOAT"
    assert a["CLKOUT0_DIVIDE_F"]["allowed"] == ["1.000 to 128.000"]
    assert a["CLKOUT0_DIVIDE_F"]["default"] == "1.000"
    assert a["CLKOUT1_PHASE"]["allowed"] == ["-360.000 to 360.000"]
    assert a["CLKOUT1_PHASE"]["default"] == "0.000"
    assert a["CLKOUT4_CASCADE"]["default"] == "FALSE"


def test_attribute_lists_and_mid_word_wraps():
    a = split_sections(LAY, ["TOYPLL"])["TOYPLL"].attributes
    assert set(a) == {
        "CLKFBOUT_MULT",
        "CLKFBOUT_PHASE",
        "CLKIN1_PERIOD",
        "CLKIN2_PERIOD",
        "CLKIN3_PERIOD",
        *(f"CLKOUT{i}_PHASE" for i in range(5)),
        "TAB_58",
        *(f"TAB_5{c}" for c in "9ABDEF"),
        "STARTUP_WAIT",
        # "CLKFBOUT_USE_FINE_PS to CLKOUT2_USE_FINE_PS": feedback plus CLKOUT0..2
        "CLKFBOUT_USE_FINE_PS",
        *(f"CLKOUT{i}_USE_FINE_PS" for i in range(3)),
    }
    assert a["CLKFBOUT_PHASE"] == {
        "type": "FLOAT",
        "allowed": ["-360.000 to 360.000"],
        "default": "0.000",
    }
    assert a["CLKIN1_PERIOD"]["type"] == "FLOAT"
    assert a["CLKIN1_PERIOD"]["allowed"] == ["0.000 to 100.000"]
    assert a["CLKIN3_PERIOD"]["allowed"] == ["0.000 to 52.631"]
    assert a["CLKOUT4_PHASE"]["default"] == "0.000"
    assert a["TAB_58"]["allowed"] == ["16'h0000 to 16'hffff"]
    assert a["TAB_5F"]["type"] == "HEX"
    assert a["STARTUP_WAIT"]["allowed"] == ['"FALSE"', '"TRUE"']


def test_attribute_values_wrapped_mid_word_and_shifted_columns():
    a = split_sections(LAY, ["TOYIO"])["TOYIO"].attributes
    assert set(a) == {
        "CLK_EDGE",
        "INIT_Q1",
        "REF_FREQ",
        "ALMOST_EMPTY",
        "SPREAD",
        "WMODE_A",
        "WMODE_B",
    }
    assert a["CLK_EDGE"] == {
        "type": "STRING",
        "allowed": ['"OPPOSITE_EDGE"', '"SAME_EDGE"', '"SAME_EDGE_PIPELINED"'],
        "default": '"OPPOSITE_EDGE"',
    }
    assert a["REF_FREQ"] == {"type": "FLOAT", "allowed": ["190-210", "290-310"], "default": "200.0"}
    assert a["ALMOST_EMPTY"] == {"type": "DECIMAL", "allowed": ["1", "2"], "default": "1"}
    assert a["SPREAD"]["allowed"] == ['"CENTER_HIGH"', '"CENTER_LOW"', '"DOWN_HIGH"', '"DOWN_LOW"']
    assert a["SPREAD"]["default"] == '"CENTER_HIGH"'
    assert a["WMODE_B"] == {
        "type": "STRING",
        "allowed": ['"WRITE_FIRST"', '"NO_CHANGE"', '"READ_FIRST"'],
        "default": '"WRITE_FIRST"',
    }


def test_names_from_text_skips_macros():
    from xut.catalog.ug953 import names_from_text

    macro = "XPM_TOY\nParameterized Macro: Toy macro\n\n    MACRO_GROUP: XPM\n\n"
    unimacro = "BRAM_TOY\nMacro: Toy unimacro\n\n    MACRO_GROUP: BRAM\n\n"
    assert names_from_text(macro + unimacro + TXT) == ["TOYFF", "TOYLUT"]
    assert names_from_text(LAY) == ["TOYRAM", "TOYPLL", "TOYIO", "TOYSER", "TOYDUP"]


def test_port_functions_from_vertically_centred_cells():
    s = split_sections(LAY, ["TOYSER"])["TOYSER"]
    f = {n: p["function"] for n, p in s.ports.items()}
    assert f["TSLIP"] == "Toy slip first line that runs on over"
    assert f["TCE1"] == f["TCE2"] == "Toy enable module first line."
    assert f["TCLK"] == "The toy high-speed clock input clocks in"
    assert f["TDIV"] == "Toy divided clock with a five line"
    assert f["TSEL"] == "Toy select."
    # a first line that starts lowercase cannot be trusted: blank + flagged
    assert f["TODD"] == ""
    assert s.review == ["port TODD function"]


def test_open_list_fragment_goes_down_and_duplicate_is_the_default():
    a = split_sections(LAY, ["TOYDUP"])["TOYDUP"].attributes
    assert a["SIM_DEV"]["allowed"] == []
    assert a["USE_DIS"]["allowed"] == ['"TRUE"', '"FALSE"']
    assert a["IFACE"]["allowed"] == ['"MEM"', '"MEM_DDR3"', '"MEM_QDR"', '"NET"', '"OVER"']
    assert a["IFACE"]["default"] == '"MEM"'
    assert a["IODLY"]["allowed"] == ['"NONE"', '"BOTH"']


def test_split_values_strips_whitespace_inside_quotes():
    """RAMB18E1 SIM_COLLISION_CHECK wraps as `"GENERATE_X_ONLY` / `", "NONE",` in the
    UG953 text; the joined cell must not keep the space before the closing quote."""
    from xut.catalog.ug953 import _split_values

    assert _split_values('"ALL", "GENERATE_X_ONLY ", "NONE", "WARNING_ONLY"') == [
        '"ALL"',
        '"GENERATE_X_ONLY"',
        '"NONE"',
        '"WARNING_ONLY"',
    ]


def test_split_values_enumerates_one_bit_binary_range():
    """`1'b0 to 1'b1` (every IS_*_INVERTED) is two discrete values, so each polarity gets
    its own coverage bin (spec §4.2, §9); wider ranges stay ranges."""
    from xut.catalog.ug953 import _split_values

    assert _split_values("1'b0 to 1'b1") == ["1'b0", "1'b1"]
    assert _split_values("16'h0000 to 16'hffff") == ["16'h0000 to 16'hffff"]
    assert _split_values("1 to 128") == ["1 to 128"]
