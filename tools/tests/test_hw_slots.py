# SPDX-License-Identifier: Apache-2.0
import re
import shutil

import pytest
from hw_toy import TOYFF_V, toy_map, toy_spec

from xut.hw.slots import (
    DUT_BUFG_BUDGET,
    HW_HDL,
    HW_INCLUDES,
    HW_SOURCES,
    SELFTEST_SLOTS,
    SlotBuild,
    SlotError,
    dut_slot,
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


def test_normalized_wrappers_do_not_depend_on_the_cfg_name():
    a, b = _toy_slot(1, "x"), _toy_slot(1, "y")
    assert a.wrapper == b.wrapper and a.digest() == b.digest()
    assert _toy_slot(0).digest() != a.digest()
    assert _toy_slot(1, t0="1").digest() != a.digest()  # t0 is baked into the bitstream


def test_normalize_refuses_a_file_without_exactly_one_wrapper():
    with pytest.raises(SlotError):
        normalize_wrapper("module other (); endmodule\n")


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


def test_render_slots_requires_the_self_test_first():
    with pytest.raises(SlotError, match="self-test"):
        render_slots((_toy_slot(0), *SELFTEST_SLOTS))


def test_pack_respects_the_clock_budget_and_is_order_independent():
    slots = [_toy_slot(i % 2, f"c{i}", t0=str(i // 2 % 2)) for i in range(DUT_BUFG_BUDGET + 2)]
    groups = pack(slots)
    assert [len(g) for g in groups] == [DUT_BUFG_BUDGET, 2]
    shuffled = list(reversed(slots))
    assert [[shuffled[i].digest() for i in g] for g in pack(shuffled)] == [
        [slots[i].digest() for i in g] for g in groups
    ]
    fat = SlotBuild("dut", 1, 1, DUT_BUFG_BUDGET + 1, "0", "module xut_dut (\n", "X")
    with pytest.raises(SlotError, match="clocks"):
        pack([fat])


def test_timing_tcl_guards_every_object_query():
    tcl = timing_tcl((*SELFTEST_SLOTS, _toy_slot(0)), margin=16)
    assert tcl.count("create_generated_clock") == 2
    for line in tcl.splitlines():
        if "[get_" in line and not line.startswith("proc"):
            assert "xut_must" in line, line
    assert "set xut_margin_ns 140.000" in tcl


def test_cfg_vh():
    vh = render_cfg_vh((*SELFTEST_SLOTS, _toy_slot(0)), 0x1234ABCD, 8192, 16)
    assert "`define XUT_HW_BUILD_ID 32'h1234abcd" in vh and "`define XUT_HW_NSLOTS 3" in vh
    assert "`define XUT_HW_MAXIN 16" in vh and "`define XUT_HW_MAXOUT 16" in vh


@pytest.mark.container
def test_harness_elaborates_on_icarus(tmp_path):
    from xut.container import executor_for
    from xut.modelsrc import resolve

    ms = resolve("auto")
    d = tmp_path / "elab"
    d.mkdir()
    slots = (*SELFTEST_SLOTS, _toy_slot(0), _toy_slot(1, t0="1"))
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
        "-tnull",
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
    assert rc == 0 and "error" not in text.lower(), text
