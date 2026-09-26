# SPDX-License-Identifier: Apache-2.0
import re
import shutil
from pathlib import Path

import pytest

from xut.container import SIM_IMAGE, DockerExecutor, image_digest
from xut.paths import repo_root
from xut.verilatorize.analyze import TransformError, analyze, generate_configs
from xut.verilatorize.rewrite import check_clean, rewrite, write_text

FIX = Path(__file__).parent / "fixtures" / "verilatorize"
GLBL = FIX / "glbl.v"
# The spec §6.2 fixture set (Task 14 equivalence-checks every one of these).
MODS = {
    "vz_single.v": "VZSINGLE",
    "vz_multi.v": "VZMULTI",
    "vz_retain.v": "VZRETAIN",
    "vz_nonconst.v": "VZNONCONST",
    "vz_trig.v": "VZTRIG",
    "vz_select.v": "VZSEL",
    "vz_task.v": "VZTASK",
    "vz_shift.v": "VZSHIFT",
    "vz_delay.v": "VZDELAY",
    "vz_async.v": "VZASYNC",
    "vz_cone.v": "MMCMVZ",
    "vz_gate.v": "BUFVZ",
    "vz_sub.v": "VZSUB",
    "vz_generate.v": "VZGEN",
    "vz_ranges.v": "VZRANGE",
    "vz_ifelse.v": "VZIFELSE",
}
# Ruling S18 fixtures: stale reads, real/integer forced regs, helper modules, `output reg`
# ports, no-op deassigns, never-written variables.
S18_MODS = {
    "vz_stale.v": "VZSTALE",
    "vz_rao.v": "VZRAO",
    "vz_real.v": "VZREAL",
    "vz_loopwait.v": "VZLOOPWAIT",
    "vz_initforce.v": "VZINIT",
    "vz_helper.v": "VZHELPER",
    "vz_portreg.v": "VZPORTREG",
    "vz_noopdeassign.v": "VZNOOP",
    "vz_constvar.v": "VZCONST",
}
ALL = {**MODS, **S18_MODS}


def W(name):  # the X__base declaration, with its Verilator BLKANDNBLK waiver
    return f"/* verilator lint_off BLKANDNBLK */ {name} /* verilator lint_on BLKANDNBLK */"


def _rw(fname):
    return rewrite(analyze(FIX / fname, ALL[fname], GLBL))


@pytest.mark.parametrize("fname", sorted(ALL))
def test_output_is_clean_and_elaborates_in_every_generate_config(fname):
    out = _rw(fname)
    assert out.startswith("// SPDX-License-Identifier: Apache-2.0\n")
    check_clean(out, ALL[fname], GLBL, generate_configs(FIX / fname, ALL[fname]))


def test_vztrig_golden_fragments():
    out = _rw("vz_trig.v")
    assert (
        f"reg {W('q__base')}; reg [1:0] q__ovr_sel = 2'd0; wire q; wire q__ovr_1; "
        "wire q__ovr_2; wire q__ovr_3;\n"
    ) in out
    assert "    if (gsr_in) q__ovr_sel = 2'd1;\n" in out
    assert "    else if (CLR) q__ovr_sel = 2'd2;\n" in out
    assert "    else if (PRE) q__ovr_sel = 2'd3;\n" in out
    assert (
        "    else begin if (q__ovr_sel != 2'd0) begin q__base = q__active(); "
        "q__ovr_sel = 2'd0; end end\n"
    ) in out
    assert "always @(posedge C) q__base <= D;" in out
    assert (
        "  // xut verilatorize: shadow-register override muxes (spec §6.2)\n"
        "  assign q__ovr_1 = 1'b0;\n"
        "  assign q__ovr_2 = 1'b0;\n"
        "  assign q__ovr_3 = 1'b1;\n"
        "  assign q = (q__ovr_sel == 2'd0) ? q__base : (q__ovr_sel == 2'd1) ? q__ovr_1 : "
        "(q__ovr_sel == 2'd2) ? q__ovr_2 : q__ovr_3;\n"
    ) in out
    # the deassign captures the ACTIVE override expression's value, never the net q (S18)
    assert (
        "  function q__active();\n"
        "    if (q__ovr_sel == 2'd1) q__active = 1'b0;\n"
        "    else if (q__ovr_sel == 2'd2) q__active = 1'b0;\n"
        "    else q__active = 1'b1;\n"
        "  endfunction\nendmodule"
    ) in out
    assert "q__base = q;" not in out


def test_deassign_in_then_arm_keeps_its_else():
    out = _rw("vz_ifelse.v")
    assert (
        "if (C2) begin if (q__ovr_sel != 1'd0) begin q__base = q__active(); "
        "q__ovr_sel = 1'd0; end end\n    else q__ovr_sel = 1'd1;"
    ) in out
    assert "always @(posedge C) q__base <= D;" in out
    assert "assign q = (q__ovr_sel == 1'd0) ? q__base : q__ovr_1;" in out  # one override
    assert "  function q__active();\n    q__active = E;\n  endfunction" in out


def test_delay_and_blocking_form_preserved():
    out = _rw("vz_delay.v")
    assert "q__base <= #100 D;" in out


def test_self_reference_reads_overridden_value():
    out = _rw("vz_shift.v")
    assert "data__base <= {data[2:0], D};" in out


def test_select_writes_renamed():
    out = _rw("vz_select.v")
    assert "v__base[0] <=" in out and "v__base[2:1] <=" in out


def test_task_write_renamed():
    out = _rw("vz_task.v")
    assert "      r__base = val;" in out


def test_both_generate_arms_rewritten():
    out = _rw("vz_generate.v")
    assert out.count("r__base <=") == 2  # posedge arm and negedge arm


def test_packed_range_preserved():
    out = _rw("vz_ranges.v")
    assert "wire [4:1] a;" in out and "wire [0:3] b;" in out and "wire signed [7:0] c;" in out
    assert "wire [4:1] a__ovr_1;" in out and "wire signed [7:0] c__ovr_1;" in out
    assert "function signed [7:0] c__active();" in out and "function [0:3] b__active();" in out
    assert f"reg [4:1] {W('a__base')};" in out and f"reg signed [7:0] {W('c__base')};" in out


def test_missed_rename_is_caught():
    an = analyze(FIX / "vz_generate.v", "VZGEN", GLBL)
    # drop the g_neg arm's write (textually first): only IS_C_INVERTED=1'b1 elaborates it
    an.forced["r"].writes = set(sorted(an.forced["r"].writes, key=lambda w: w.start)[1:])
    with pytest.raises(TransformError, match="IS_C_INVERTED"):  # the failing config is named
        check_clean(rewrite(an), "VZGEN", GLBL, generate_configs(FIX / "vz_generate.v", "VZGEN"))


def test_leftover_procedural_assign_is_caught():
    an = analyze(FIX / "vz_single.v", "VZSINGLE", GLBL)
    an.forced["q"].deassigns = []
    with pytest.raises(TransformError, match="procedural assign/deassign remains"):
        check_clean(rewrite(an), "VZSINGLE", GLBL, [{}])


# ---- ruling S18 --------------------------------------------------------------------------------
def test_stale_reads_substituted():
    out = _rw("vz_stale.v")
    # after `assign r = A;` the read sees the active override's value, typed as r
    assert "begin r__ovr_sel = 1'd1; r__now = A; end\n      x = r__now;" in out
    # after `deassign r;` the read sees r__base, which the deassign just loaded
    assert "r__ovr_sel = 1'd0; end end\n      y = r__base;" in out
    assert "reg r__now;" in out
    out = _rw("vz_rao.v")
    assert "begin r__ovr_sel = 1'd1; r__now = 1'b0; end\n    x = r__now;" in out


def test_no_snapshot_without_stale_reads():
    out = _rw("vz_trig.v")
    assert "__now" not in out


def test_real_forced_reg_is_a_real_variable():
    out = _rw("vz_real.v")
    assert f"real {W('rv__base')}; reg [0:0] rv__ovr_sel = 1'd0; real rv; real rv__ovr_1;" in out
    assert "  assign rv = (rv__ovr_sel == 1'd0) ? rv__base : rv__ovr_1;" in out
    assert "  function real rv__active();\n    rv__active = 1.5;\n  endfunction" in out
    assert "always @(posedge C) rv__base = rv + 1.0;" in out


def test_integer_forced_reg_keeps_signed_32_bits():
    out = _rw("vz_loopwait.v")
    assert (
        f"integer {W('cnt__base')}; reg [0:0] cnt__ovr_sel = 1'd0; wire signed [31:0] cnt;"
    ) in out
    assert "function signed [31:0] cnt__active();" in out
    assert "cnt__base = cnt + 1;" in out


def test_initialisation_force_keeps_the_initial_value():
    out = _rw("vz_initforce.v")
    assert (
        f"reg [3:0] {W('data__base')} = 4'h5; reg [0:0] data__ovr_sel = 1'd0; wire [3:0] data;"
    ) in out
    assert "data__base = data__active();" in out


def test_output_reg_port_becomes_a_net():
    out = _rw("vz_portreg.v")
    assert f"  output  [1:0] Q; reg [1:0] {W('Q__base')}; reg [0:0] Q__ovr_sel = 1'd0; " in out
    assert "wire [1:0] Q;" not in out
    assert "Q__base <= {Q[0], D};" in out


def test_helper_module_rewritten_in_place():
    out = _rw("vz_helper.v")
    core, top = out.split("module VZHELPER ")
    assert f"reg {W('q__base')};" in core and "always @(posedge C) q__base <= D;" in core
    assert "assign q = (q__ovr_sel == 1'd0) ? q__base : q__ovr_1;\n" in core
    assert core.rstrip().endswith("endfunction\nendmodule")
    assert "__ovr" not in top


def test_noop_deassign_becomes_a_null_statement():
    out = _rw("vz_noopdeassign.v")
    assert "    else ;\n" in out and "deassign q" not in out
    assert "__base" not in out  # q is not transformed


# ---- refusals ---------------------------------------------------------------------------------
def _write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    return f


def test_forcing_in_implicit_sensitivity_block_is_refused(tmp_path):
    src = (FIX / "vz_single.v").read_text()
    f = _write(tmp_path, "vz_star.v", re.sub(r"always @\([^)]*\)", "always @*", src, count=1))
    with pytest.raises(TransformError, match="implicit sensitivity"):
        rewrite(analyze(f, "VZSINGLE", GLBL))


def test_override_reading_a_generate_local_constant_is_refused(tmp_path):
    f = _write(
        tmp_path,
        "vz_genlocal.v",
        """// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module VZGL (output Q, input C, input D, input R);
  localparam V = 1'b0;
  reg r;
  assign Q = r;
  generate if (1) begin : g
    localparam V = 1'b1;
    always @(R) if (R) assign r = V; else deassign r;
  end endgenerate
  always @(posedge C) r <= D;
endmodule
""",
    )
    with pytest.raises(TransformError, match="reads V, which is declared in an enclosing"):
        rewrite(analyze(f, "VZGL", GLBL))


def test_name_collision_is_refused(tmp_path):
    src = (FIX / "vz_single.v").read_text().replace("  reg q;", "  reg q;\n  wire q__base;")
    f = _write(tmp_path, "vz_clash.v", src)
    with pytest.raises(TransformError, match="q__base is already used"):
        rewrite(analyze(f, "VZSINGLE", GLBL))


def test_non_ascii_model_round_trips(tmp_path):
    src = (FIX / "vz_trig.v").read_bytes().replace(b"several", b"s\xc3\xa9veral \xff")
    f = tmp_path / "vz_trig.v"
    f.write_bytes(src)
    out = rewrite(analyze(f, "VZTRIG", GLBL))
    write_text(tmp_path / "out.v", out)
    raw = (tmp_path / "out.v").read_bytes()
    assert b"s\xc3\xa9veral \xff" in raw and b"q__base <= D;" in raw
    check_clean(out, "VZTRIG", GLBL, [{}])


# ---- container: Verilator and Icarus accept every transformed fixture --------------------------
_no_image = shutil.which("docker") is None or image_digest(SIM_IMAGE) is None


@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
@pytest.mark.parametrize("fname", sorted(ALL))
def test_verilator_and_icarus_accept_transformed(fname):
    model = ALL[fname]
    work = repo_root() / "build" / "vz-lint" / model
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    write_text(work / fname, _rw(fname))
    shutil.copy(GLBL, work / "glbl.v")
    log = work / "lint.log"
    ex = DockerExecutor()
    rc = ex.run(
        ["verilator", "--lint-only", "--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style",
         "-Wno-MULTITOP", fname, "glbl.v"],
        cwd=work, log=log, timeout_s=120,
    )  # fmt: skip
    assert rc == 0, log.read_text()
    rc = ex.run(
        ["iverilog", "-g2012", "-o", "sim.vvp", "-s", model, "-s", "glbl", fname, "glbl.v"],
        cwd=work, log=log, timeout_s=120,
    )  # fmt: skip
    assert rc == 0, log.read_text()
