# SPDX-License-Identifier: Apache-2.0
import re
import shlex
import shutil
from dataclasses import replace

import pytest
from hw_toy import TOYFF_V, toy_map, toy_spec

from xut.hw.slots import (
    DUT_BUFG_BUDGET,
    HW_HDL,
    HW_INCLUDES,
    HW_SOURCES,
    MAX_SLOTS,
    SELFTEST_SLOTS,
    SlotBuild,
    SlotError,
    dut_slot,
    maxin,
    maxout,
    normalize_wrapper,
    pack,
    render_cfg_vh,
    render_slots,
    timing_tcl,
)
from xut.wrap import render_wrapper


def _toy_slot(init: int, cfg: str | None = None, t0: str = "0") -> SlotBuild:
    cfg = cfg or f"init{init}"
    m = toy_map(cfg, init)
    return dut_slot(m, render_wrapper(toy_spec(cfg, init), m), t0)


def _dut(i: int, nclk: int = 1, prim: str = "FDRE") -> SlotBuild:
    """A distinct (by digest) packable DUT slot; its wrapper is never elaborated."""
    return SlotBuild("dut", 1, 1, nclk, "0", f"module xut_dut (\n// variant {i}\n", prim)


#: A 20-bit (two-chunk) DUT: out_vec = ~in_vec, no clock. Elaborated by the Icarus test.
WIDE_WRAPPER = """// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module xut_dut (
  input  wire [0:0]  clk,
  input  wire [19:0] in_vec,
  output wire [19:0] out_vec
);
  assign out_vec = ~in_vec;
endmodule
"""
WIDE = SlotBuild("dut", 20, 20, 0, "1010" * 5, WIDE_WRAPPER, "LUT1")


def test_normalized_wrappers_do_not_depend_on_the_cfg_name():
    a, b = _toy_slot(1, "x"), _toy_slot(1, "y")
    assert a.wrapper == b.wrapper and a.digest() == b.digest()
    assert _toy_slot(0).digest() != a.digest()
    assert _toy_slot(1, t0="1").digest() != a.digest()  # t0 is baked into the bitstream


def test_normalize_refuses_a_file_without_exactly_one_wrapper():
    with pytest.raises(SlotError):
        normalize_wrapper("module other (); endmodule\n")


@pytest.mark.parametrize("t0", ["", "00", "x", "2"])
def test_dut_slot_refuses_a_bad_t0(t0):
    m = toy_map("c", 0)
    with pytest.raises(SlotError, match="t0"):
        dut_slot(m, render_wrapper(toy_spec("c", 0), m), t0)


def test_render_slots():
    text = render_slots((*SELFTEST_SLOTS, _toy_slot(0), _toy_slot(1, t0="1")))
    assert "module xut_dut_s2 (" in text and "module xut_dut_s3 (" in text
    assert "module xut_dut (" not in text
    assert "reg [0:0] in_s3 = 1'b1;" in text  # t0 as the flip-flops' INIT
    assert len(re.findall(r"\bBUFG u_bufg_s", text)) == 3  # counter + two toy clocks
    assert (
        "8'd2: begin cur_in <= {15'd0, in_s2}; cur_out <= {15'd0, out_s2}; cur_noutw <= 16'd1; end"
        in text
    )
    assert "if (edge_we && sel == 8'd3 && edge_idx == 12'd0) dclk_s3_0 <= edge_val;" in text


def test_render_slots_multi_chunk():
    slots = (*SELFTEST_SLOTS, WIDE)
    assert maxin(slots) == 32 and maxout(slots) == 20  # in_vec rounds up to whole chunks
    text = render_slots(slots)
    assert "reg [19:0] in_s2 = 20'b10101010101010101010;" in text
    assert "in_s2 <= in_nxt[19:0];" in text
    assert "8'd2: begin cur_in <= {12'd0, in_s2}; cur_out <= out_s2; cur_noutw <= 16'd20;" in text


def test_render_slots_requires_the_self_test_first():
    with pytest.raises(SlotError, match="self-test"):
        render_slots((_toy_slot(0), *SELFTEST_SLOTS))


@pytest.mark.parametrize(
    "slots, match",
    [
        ((SlotBuild("passthrough", 8, 8, 0, "0" * 8), SELFTEST_SLOTS[1]), "self-test"),
        ((*SELFTEST_SLOTS, SELFTEST_SLOTS[0]), "slot 2 is a passthrough"),
        ((*SELFTEST_SLOTS, _dut(0, DUT_BUFG_BUDGET), _dut(1)), "BUFG budget"),
        ((*SELFTEST_SLOTS, *(_dut(i, 0) for i in range(MAX_SLOTS - 1))), "MAX_SLOTS"),
    ],
    ids=["selftest-contents", "non-dut", "clock-budget", "max-slots"],
)
def test_the_generators_validate_the_slot_list(slots, match):
    for gen in (render_slots, lambda s: render_cfg_vh(s, 0, 64, 16), lambda s: timing_tcl(s, 16)):
        with pytest.raises(SlotError, match=match):
            gen(slots)


@pytest.mark.parametrize(
    "maxwords, margin, match",
    [(0, 16, "maxwords"), (65536, 16, "maxwords"), (64, 2, "margin"), (64, 256, "margin")],
)
def test_cfg_vh_validates_its_fields(maxwords, margin, match):
    with pytest.raises(SlotError, match=match):
        render_cfg_vh(SELFTEST_SLOTS, 0, maxwords, margin)


def test_pack_respects_the_clock_budget_and_is_order_independent():
    slots = [_dut(i) for i in range(DUT_BUFG_BUDGET + 2)]
    groups = pack(slots)
    assert [len(g) for g in groups] == [DUT_BUFG_BUDGET, 2]
    shuffled = list(reversed(slots))
    assert [[shuffled[i].digest() for i in g] for g in pack(shuffled)] == [
        [slots[i].digest() for i in g] for g in groups
    ]
    fat = SlotBuild("dut", 1, 1, DUT_BUFG_BUDGET + 1, "0", "module xut_dut (\n", "FDRE")
    with pytest.raises(SlotError, match="clocks"):
        pack([fat])


def test_pack_splits_at_max_slots():
    groups = pack([_dut(i, 0, "LUT1") for i in range(MAX_SLOTS + 10)])
    per = MAX_SLOTS - len(SELFTEST_SLOTS)
    assert [len(g) for g in groups] == [per, MAX_SLOTS + 10 - per]


def test_pack_places_identical_slots_once():
    a, b = _toy_slot(0, "x"), _toy_slot(0, "y")  # same digest: one slot in the bitstream
    slots = [replace(s, label="FDRE") for s in (a, b, _toy_slot(1))]
    groups = pack(slots)
    assert sorted(i for g in groups for i in g) == [0, 2]


def test_pack_refuses_a_non_dut():
    with pytest.raises(SlotError, match="not a DUT"):
        pack([SELFTEST_SLOTS[1]])


@pytest.mark.parametrize(
    "prim",
    [
        "FDRE",
        "FDCE",
        "LUT1",
        "LUT6_2",
        "CFGLUT5",
        "CARRY4",
        "MUXF7",
        "MUXF8",
        "SRL16E",
        "SRLC32E",
        "RAM32X1S",
        "RAM32M",
        "RAM64X1D",
        "RAM64M",
        "RAM128X1D",
        "RAM256X1S",
        "ROM64X1",
        "ROM256X1",
    ],
)
def test_pack_accepts_slice_primitives(prim):
    assert pack([_dut(0, 1, prim)]) == [[0]]


@pytest.mark.parametrize(
    "prim",
    [
        "TOYFF",
        "BUFG",
        "BUFGCE",
        "MMCME2_ADV",
        "PLLE2_BASE",
        "RAMB36E1",
        "RAMB18E1",
        "DSP48E1",
        "IDDR",
        "BUFR",
        "STARTUPE2",
        "MUXF9",
    ],
)
def test_pack_fails_closed_on_primitives_needing_resource_budgets(prim):
    want = (
        f"hw packing: {prim} needs resource budgeting (BUFG/MMCM/BRAM/DSP/IO/region) "
        "— not yet supported"
    )
    with pytest.raises(SlotError, match=re.escape(want)):
        pack([_dut(0, 1, prim)])


@pytest.mark.parametrize("prim", ["LDCE", "LDPE"])
def test_pack_fails_closed_on_latches_until_their_gate_path_is_constrained(prim):
    want = (
        f"hw packing: {prim} is a latch; its gate path out of the DUT is not yet "
        "timing-constrained — not yet supported"
    )
    with pytest.raises(SlotError, match=re.escape(want)):
        pack([_dut(0, 1, prim)])


def test_timing_tcl_guards_every_object_query():
    tcl = timing_tcl((*SELFTEST_SLOTS, _toy_slot(0)), margin=16)
    assert tcl.count("create_generated_clock") == 2
    for line in tcl.splitlines():
        if "[get_" in line and not line.startswith("proc"):
            assert "xut_must" in line, line
    assert "set xut_margin_ns 140.000" in tcl


def _top_level_options(line: str) -> list[str]:
    """The ``-options`` of a Tcl command line outside any ``[...]`` substitution."""
    words = shlex.split(line.replace("[", " [ ").replace("]", " ] "), posix=False)
    top, depth = [], 0
    for w in words:
        depth += w == "["
        depth -= w == "]"
        if depth == 0 and w.startswith("-"):
            top.append(w)
    return top


def test_timing_tcl_datapath_only_delays_have_a_start_and_an_end():
    """Vivado refuses ``set_max_delay -datapath_only`` without a ``-from`` (Constraints
    18-540), which would abort every harness build. The into-the-DUT delay is every path
    from in_vec (``-from`` alone, so no endpoint kind is missed); the out-of-the-DUT delay
    is from the DUT clocks to the capture register (``-from`` and ``-to``)."""
    tcl = timing_tcl((*SELFTEST_SLOTS, _toy_slot(0), WIDE), margin=16)
    delays = [ln for ln in tcl.splitlines() if ln.startswith("set_max_delay")]
    assert len(delays) == 2
    opts = [_top_level_options(ln) for ln in delays]
    for line, o in zip(delays, opts, strict=True):
        assert "-datapath_only" in o and "-from" in o, line
    assert "-from [xut_must in_s [get_cells" in delays[0] and "-to" not in opts[0]
    assert "-to" in opts[1]
    assert "-from [xut_must dclk [get_clocks dclk_s*]]" in delays[1]
    assert "-to [xut_must cur_out [get_pins" in delays[1]


def test_top_level_options_ignores_bracketed_ones():
    assert _top_level_options("a -x [b -from c] -to [d]") == ["-x", "-to"]


def test_timing_tcl_validates_the_margin():
    with pytest.raises(SlotError, match="margin"):
        timing_tcl(SELFTEST_SLOTS, 2)


def test_cfg_vh():
    vh = render_cfg_vh((*SELFTEST_SLOTS, _toy_slot(0)), 0x1234ABCD, 8192, 16)
    assert "`define XUT_HW_BUILD_ID 32'h1234abcd" in vh and "`define XUT_HW_NSLOTS 3" in vh
    assert "`define XUT_HW_MAXIN 16" in vh and "`define XUT_HW_MAXOUT 16" in vh


@pytest.mark.container
def test_harness_elaborates_on_icarus(tmp_path):
    """The whole harness, with two toy DUTs and a two-chunk one, elaborates on Icarus
    ``-Wall`` with no diagnostic at all."""
    from xut.container import executor_for
    from xut.modelsrc import resolve

    ms = resolve("auto")
    d = tmp_path / "elab"
    d.mkdir()
    slots = (*SELFTEST_SLOTS, _toy_slot(0), _toy_slot(1, t0="1"), WIDE)
    (d / "xut_hw_slots.v").write_text(render_slots(slots))
    (d / "xut_hw_cfg.vh").write_text(render_cfg_vh(slots, 0x12345678, 64, 16))
    for f in (*HW_SOURCES, *HW_INCLUDES):
        shutil.copy(HW_HDL / f, d / f)
    shutil.copy(TOYFF_V, d / "TOYFF.v")
    ex = executor_for(ms, tmp_path)
    libs = [a for p in ms.search for a in ("-y", ex.guest(p))]
    files = [ex.guest(d / f) for f in (*HW_SOURCES, "xut_hw_slots.v", "TOYFF.v")]
    argv = [
        "iverilog",
        "-g2012",
        "-Wall",
        "-o",
        ex.guest(d / "harness.vvp"),
        "-s",
        "xut_hw_top",
        "-I",
        ex.guest(d),
        *libs,
        "-Y",
        ".v",
        *files,
    ]
    rc = ex.run(argv, cwd=d, log=d / "elab.log", timeout_s=300)
    text = (d / "elab.log").read_text()
    # The log is the "$ <argv>" line xut writes, then Icarus's own output: none at all.
    diagnostics = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("$ ")]
    assert rc == 0 and diagnostics == [], text
    assert (d / "harness.vvp").is_file()
