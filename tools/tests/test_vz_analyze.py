# SPDX-License-Identifier: Apache-2.0
import functools
import re
from pathlib import Path

import pytest

from xut.verilatorize.analyze import (
    TransformError,
    analyze,
    generate_configs,
    has_procedural_assign,
)

FIX = Path(__file__).parent / "fixtures" / "verilatorize"
GLBL = FIX / "glbl.v"

CASES = {
    "vz_single.v": ("VZSINGLE", {"CLR"}, set()),
    "vz_multi.v": ("VZMULTI", {"A", "B"}, set()),
    "vz_retain.v": ("VZRETAIN", {"S"}, set()),
    "vz_nonconst.v": ("VZNONCONST", {"S"}, set()),
    "vz_trig.v": ("VZTRIG", {"glbl.GSR", "CLR", "PRE"}, set()),
    "vz_select.v": ("VZSEL", {"R"}, set()),
    "vz_task.v": ("VZTASK", {"R"}, set()),
    "vz_shift.v": ("VZSHIFT", {"R"}, set()),
    "vz_delay.v": ("VZDELAY", {"R"}, set()),
    "vz_async.v": ("VZASYNC", {"glbl.GSR"}, set()),
    "vz_cone.v": ("MMCMVZ", {"RST", "PWRDWN"}, {"CLKIN1"}),
    "vz_gate.v": ("BUFVZ", {"glbl.GSR", "CLR"}, set()),
    "vz_sub.v": ("VZSUB", {"CLR"}, set()),
    "vz_generate.v": ("VZGEN", {"R"}, set()),
    "vz_ifelse.v": ("VZIFELSE", {"C2", "E"}, set()),
}


@pytest.mark.parametrize("fname", sorted(CASES))
def test_triggers_and_enablers(fname):
    module, trig, en = CASES[fname]
    a = analyze(FIX / fname, module, GLBL)
    assert set(a.triggers) == trig
    assert set(a.enablers) == en


def test_multi_writer_overrides_in_source_order():
    a = analyze(FIX / "vz_multi.v", "VZMULTI", GLBL)
    (x,) = a.forced.values()
    exprs = [a.text[e.start : e.end] for _, e in x.overrides]
    assert exprs == ["1'b1", "D"] and len(x.deassigns) == 2


def test_select_and_task_writes_are_collected():
    sel = analyze(FIX / "vz_select.v", "VZSEL", GLBL).forced["v"]
    t = analyze(FIX / "vz_task.v", "VZTASK", GLBL).forced["r"]
    assert len(sel.writes) == 2 and len(t.writes) == 1


def test_self_referencing_read_is_not_a_write():
    x = analyze(FIX / "vz_shift.v", "VZSHIFT", GLBL).forced["data"]
    text = (FIX / "vz_shift.v").read_text()
    assert [text[s.start : s.end] for s in x.writes] == ["data"]  # only the lvalue


@pytest.mark.parametrize(
    "fname,module,msg",
    [
        ("vz_bad_force.v", "VZFORCE", "force/release"),
        ("vz_bad_select.v", "VZBADSEL", "select or concatenation"),
        ("vz_bad_local.v", "VZLOCAL", "reads local"),
        ("vz_bad_self.v", "VZSELF", "reads r"),
        ("vz_bad_ansi.v", "VZANSI", "ANSI output reg"),
        ("vz_bad_macro.v", "VZMACRO", "macro expansion"),
        ("vz_bad_undriven.v", "VZUNDRIVEN", "cannot resolve the driver of en"),
        ("vz_bad_blackbox.v", "VZBLACKBOX", "driven by an instance output"),
        ("vz_bad_genparam.v", "VZBADGEN", "cannot enumerate generate configurations"),
        ("vz_bad_nestgen.v", "VZNESTGEN", "nested generate conditions"),
        # review fix round 1: silent-miss paths now refused
        (
            "vz_bad_helpgen.v",
            "VZG3",
            r"generate branch at line 13 \(module VZG3_HLP\): no generate configuration",
        ),
        ("vz_bad_wrap.v", "VZWRAP", "cannot determine statically which override of r"),
        ("vz_bad_looptask.v", "VZLOOPT", "cannot determine statically which override of r"),
        ("vz_bad_hier.v", "VZHIER", "hierarchical write to VZHIER.en"),
        ("vz_bad_fork.v", "VZFORK", "fork/join"),
    ],
)
def test_refusals(fname, module, msg):
    with pytest.raises(TransformError, match=msg) as e:
        analyze(FIX / fname, module, GLBL)
    assert e.value.model == module
    assert str(e.value).startswith(f"{module}: ")


def test_prescan():
    assert has_procedural_assign(FIX / "vz_single.v")
    assert not has_procedural_assign(GLBL)


def test_generate_configs_cover_both_arms():
    assert generate_configs(FIX / "vz_generate.v", "VZGEN") == [{}, {"IS_C_INVERTED": "1'b1"}]
    a = analyze(FIX / "vz_generate.v", "VZGEN", GLBL)
    text = a.text
    # the writes in BOTH generate arms are collected, not only the default elaboration's
    assert len(a.forced["r"].writes) == 2
    assert all(text[w.start : w.end] == "r" for w in a.forced["r"].writes)


def test_always_loop_with_trailing_event_control():
    a = analyze(FIX / "vz_loopwait.v", "VZLOOPWAIT", GLBL)
    assert a.triggers == ["S"] and a.enablers == []
    assert a.forced["r"].dims == "signed [4:1] "
    assert a.forced["cnt"].dims == "signed [31:0] "  # integer, spelled as its vector type
    text = a.text
    decl = a.forced["r"].decl_name
    assert text[decl.start : decl.end] == "r"
    assert text[a.forced["r"].decl_end - 1] == ";"
    assert text[a.endmodule : a.endmodule + 9] == "endmodule"


# ---- syntax-level generate helpers ------------------------------------------------------------
def _tree(path):
    import pyslang

    return pyslang.syntax.SyntaxTree.fromFile(str(path))


def test_generate_helpers_on_vz_generate():
    from xut.verilatorize.analyze import (
        _generate_constructs,
        _identifiers,
        _is_one_bit,
        _literals_compared_with,
        _module_parameters,
    )

    t = _tree(FIX / "vz_generate.v")
    assert _module_parameters(t, "VZGEN") == {"IS_C_INVERTED": "1'b0"}
    assert _is_one_bit(t, "VZGEN", "IS_C_INVERTED")
    (c,), nested = _generate_constructs(t, "VZGEN")
    assert nested == [] and len(c.arms) == 2
    assert _identifiers(c.conds[0]) == {"IS_C_INVERTED"}
    assert _literals_compared_with(c.conds, "IS_C_INVERTED", "1'b0") == []  # none compared


def test_generate_helpers_on_vz_bad_genparam():
    from xut.verilatorize.analyze import (
        _generate_constructs,
        _identifiers,
        _is_one_bit,
        _literals_compared_with,
        _module_parameters,
    )

    t = _tree(FIX / "vz_bad_genparam.v")
    assert _module_parameters(t, "VZBADGEN") == {"WIDTH": "4", "DEPTH": "8"}
    assert not _is_one_bit(t, "VZBADGEN", "WIDTH")
    (c,), _ = _generate_constructs(t, "VZBADGEN")
    assert _identifiers(c.conds[0]) == {"WIDTH", "DEPTH"}
    assert _literals_compared_with(c.conds, "WIDTH", "4") == []


def _write(tmp_path, body):
    f = tmp_path / "VZCFG.v"
    f.write_text(
        f"// SPDX-License-Identifier: Apache-2.0\nmodule VZCFG (input C);\n{body}\nendmodule\n"
    )
    return f


def test_generate_configs_literals_localparams_case_and_chains(tmp_path):
    f = _write(
        tmp_path,
        """
  parameter MODE = "A";
  parameter integer N = 2;
  parameter [1:0] SEL = 2'b00;
  localparam IS_B = (MODE == "B");
  generate
    if (IS_B) begin : g_b end
    else if (N > 4) begin : g_n end
  endgenerate
  generate
    case (SEL)
      2'b01: begin : g_1 end
      2'b10: begin : g_2 end
      default: begin : g_d end
    endcase
  endgenerate
""",
    )
    cfgs = generate_configs(f, "VZCFG")
    assert cfgs[0] == {}
    # MODE via the localparam, N around the relational literal, SEL from the case items;
    # the else-if chain is one construct, so MODE and N are combined
    assert {"MODE": '"B"'} in cfgs and {"N": "5"} in cfgs and {"MODE": '"B"', "N": "5"} in cfgs
    assert {"SEL": "2'b01"} in cfgs and {"SEL": "2'b10"} in cfgs
    # choices (the catalog's allowed values) take precedence
    assert generate_configs(f, "VZCFG", {"MODE": ['"A"'], "N": ["2"], "SEL": ["2'b00"]}) == [{}]
    with pytest.raises(TransformError, match="cannot enumerate generate configurations: .* > 2"):
        generate_configs(f, "VZCFG", limit=2)


def test_untaken_generate_branch_writing_a_forced_reg_is_refused():
    # choices restricted to the default: g_neg is never elaborated, and it writes r
    with pytest.raises(
        TransformError,
        match=r"generate branch at line 12 \(module VZGEN\): no generate configuration",
    ):
        analyze(FIX / "vz_generate.v", "VZGEN", GLBL, {"IS_C_INVERTED": ["1'b0"]})


def test_procedural_assign_in_another_module(tmp_path):
    src = (
        (FIX / "vz_sub.v")
        .read_text()
        .replace(
            "assign o = ~i;",
            "reg r; assign o = r;\n  always @(i) if (i) assign r = 1'b0; else deassign r;",
        )
    )
    (tmp_path / "vz_sub2.v").write_text(src)
    # instantiated helper: analysed as its own module, triggers traced through the instance
    a = analyze(tmp_path / "vz_sub2.v", "VZSUB", GLBL)
    assert set(a.submodules) == {"VZSUB_INV"}
    assert a.submodules["VZSUB_INV"].forced["r"].triggers == {"CLR"}
    # a module the analysed model never instantiates is refused
    (tmp_path / "vz_sub3.v").write_text(
        src.replace("VZSUB_INV u (.o(clr_n), .i(CLR));", "assign clr_n = ~CLR;")
    )
    with pytest.raises(TransformError, match="is in module VZSUB_INV, which VZSUB does not"):
        analyze(tmp_path / "vz_sub3.v", "VZSUB", GLBL)


def test_uncalled_task_with_procedural_assign_is_refused(tmp_path):
    src = (
        (FIX / "vz_single.v")
        .read_text()
        .replace("  assign Q = q;", "  assign Q = q;\n  task t; assign q = 1'b1; endtask")
    )
    (tmp_path / "vz_single2.v").write_text(src)
    with pytest.raises(TransformError, match="never elaborated"):
        analyze(tmp_path / "vz_single2.v", "VZSINGLE", GLBL)


# ---- every UNISIM model with procedural assign/deassign ----------------------------------------
# The analysis must either succeed or refuse with a TransformError; never crash, never
# silently drop. Refusals are pinned so a change in coverage is a visible test change.
# (Reasons: task-12 report, "Model sweep".)
EXPECT_REFUSED = {
    # known limitation (ruling S18.5): nested generate conditions
    "RAMB18E1": "nested generate conditions",
    "RAMB36E1": "nested generate conditions",
}
# Derived triggers/enablers pinned for the pilot and representative models.
EXPECT_TRIGGERS = {
    "FDRE": (["glbl.GSR"], []),
    "FDSE": (["glbl.GSR"], []),
    "FDCE": (["CLR", "glbl.GSR"], []),
    "FDPE": (["PRE", "glbl.GSR"], []),
    "BUFR": (["CLR", "glbl.GSR"], []),
    "IDDR": (["R", "S", "glbl.GSR"], []),
    "ODDR": (["R", "S", "glbl.GSR"], []),
    "ODDRE1": (["SR", "glbl.GSR"], ["C"]),
    "PLLE3_ADV": (["PWRDWN", "RST"], ["CLKIN"]),
    # ruling S18: formerly refused
    "SRL16E": (["CLK"], []),
    "SRLC32E": (["CLK"], []),
    "CFGLUT5": (["CLK"], []),
    "FIFO18E1": (["RDEN", "RST", "WREN", "glbl.GSR"], ["RDCLK", "WRCLK"]),
    "ISERDESE1": (["glbl.GSR"], []),
    "OSERDESE1": (["glbl.GSR"], []),
}
# MMCME2_ADV, the spec's worked example: rst_int (RST|PWRDWN, registered on the selected
# input clock) forces these regs, so both RST and PWRDWN are triggers, the clock enablers.
EXPECT_REG_TRIGGERS = {
    ("MMCME2_ADV", "clkout_en0"): ({"PWRDWN", "RST"}, {"CLKIN1", "CLKIN2", "CLKINSEL"}),
    ("MMCME2_ADV", "pll_locked_tmp2"): (
        {"PWRDWN", "RST", "glbl.GSR"},
        {"CLKIN1", "CLKIN2", "CLKINSEL"},
    ),
}
EXPECT_NOTES = {
    "PLLE2_ADV": [
        "PLLE2_ADV.clk0_div_fint_odd: never written; treated as constant",
        "PLLE2_ADV.clkfb_div_fint_odd: never written; treated as constant",
    ],
}
PILOT = ("FDRE", "FDSE", "FDCE", "FDPE")


@functools.cache
def _forced_models(ms):
    out = []
    for d in ms.search:
        for f in sorted(d.glob("*.v")):
            if has_procedural_assign(f):
                out.append(f)
    return out


def _source(name):
    from xut.modelsrc import model_sources

    ms = model_sources().get(name)
    if ms is None:
        pytest.skip(f"model source {name} not available")
    return ms


def _check_model(ms, f):
    if f.stem in EXPECT_REFUSED:
        with pytest.raises(TransformError, match=re.escape(EXPECT_REFUSED[f.stem])):
            analyze(f, f.stem, ms.glbl)
        return
    a = analyze(f, f.stem, ms.glbl)
    assert (a.forced or a.submodules) and a.triggers
    if f.stem in EXPECT_TRIGGERS:
        assert (a.triggers, a.enablers) == EXPECT_TRIGGERS[f.stem]
    for (model, reg), (trig, en) in EXPECT_REG_TRIGGERS.items():
        if model == f.stem:
            assert (a.forced[reg].triggers, a.forced[reg].enablers) == (trig, en)
    if f.stem in EXPECT_NOTES:
        assert [n for n in a.notes if "never written" in n] == EXPECT_NOTES[f.stem]
    if f.stem.startswith("MMCME"):
        assert {x.type for x in a.forced.values()} == {"reg", "integer", "real"}


@pytest.mark.slow  # parses all 249 models with pyslang (~30 s)
def test_submodule_has_40_forced_models():
    # spec §6.2: "The construct appears in 40 of 249 UNISIM models" (the submodule's count)
    ms = _source("unisim-gh-2020.1")
    assert len(_forced_models(ms)) == 40


@pytest.mark.parametrize("prim", PILOT)
def test_pilot_models_submodule(prim):
    ms = _source("unisim-gh-2020.1")
    _check_model(ms, ms.unisims / f"{prim}.v")


@pytest.mark.slow
@pytest.mark.parametrize("source", ["unisim-gh-2020.1", "unisim-2025.2"])
def test_every_forced_model(source):
    ms = _source(source)
    models = _forced_models(ms)
    assert len(models) >= 40
    failures = []
    for f in models:
        try:
            _check_model(ms, f)
        except Exception as e:  # collect every model's failure, then report them all
            failures.append(f"{f.stem}: {type(e).__name__}: {str(e)[:300]}")
    assert not failures, "\n".join(failures)


def test_task_output_argument_local_and_event_are_traced(tmp_path):
    f = tmp_path / "vz_tout.v"
    f.write_text("""// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module VZTOUT (output Q, input C, input D, input R, input P);
  reg r, en;
  event ev;
  task get; input i; output o; begin o = i; end endtask
  always @(R) get(R, en);
  always @(P) begin : b
    integer k = 1;
    if (P && k) -> ev;
  end
  always @(en or ev)
    if (en) assign r = 1'b0;
    else deassign r;
  always @(posedge C) r <= D;
  assign Q = r;
endmodule
""")
    a = analyze(f, "VZTOUT", GLBL)
    assert a.triggers == ["P", "R"] and a.enablers == []


# ---- ruling S18 --------------------------------------------------------------------------------
def test_stale_reads_after_assign_and_deassign_are_recorded():
    a = analyze(FIX / "vz_stale.v", "VZSTALE", GLBL)
    x = a.forced["r"]
    assert a.triggers == ["S"]
    ((ovr, _),) = x.overrides
    got = {
        (a.text[r.span.start : r.span.end], a.text[r.span.start - 4 : r.span.start], r.active)
        for r in x.stale_reads
    }
    assert got == {("r", "x = ", ovr), ("r", "y = ", None)}
    assert a.text[ovr.start : ovr.end] == "assign r = A;"


def test_stale_read_with_ambiguous_active_override_is_refused(tmp_path):
    src = (FIX / "vz_stale.v").read_text().replace("      y = r;\n", "")
    src = src.replace(
        "  always @(posedge C) r <= D;",
        "  always @(S) begin\n    if (S) assign r = A;\n    x = r;\n  end\n"
        "  always @(posedge C) r <= D;",
    )
    (tmp_path / "vz_amb.v").write_text(src)
    with pytest.raises(TransformError, match="cannot determine statically which override of r"):
        analyze(tmp_path / "vz_amb.v", "VZSTALE", GLBL)


def test_stale_read_in_an_event_control_or_override_is_refused(tmp_path):
    src = (FIX / "vz_stale.v").read_text().replace("      x = r;", "      @(r) x = 1'b0;")
    (tmp_path / "vz_ev.v").write_text(src)
    with pytest.raises(TransformError, match="r is read in an event control"):
        analyze(tmp_path / "vz_ev.v", "VZSTALE", GLBL)


def test_initialisation_force_polls_the_clock():
    a = analyze(FIX / "vz_initforce.v", "VZINIT", GLBL)
    assert a.triggers == ["C"] and a.enablers == []
    assert a.forced["data"].stale_reads == set()  # the deassign captures, it does not read


def test_real_forced_reg_keeps_its_type():
    a = analyze(FIX / "vz_real.v", "VZREAL", GLBL)
    x = a.forced["rv"]
    assert (x.type, x.dims) == ("real", "")
    assert a.triggers == ["S"]
    v = analyze(FIX / "vz_loopwait.v", "VZLOOPWAIT", GLBL).forced
    assert (v["r"].type, v["cnt"].type) == ("reg", "integer")


def test_never_written_variable_is_a_constant():
    a = analyze(FIX / "vz_constvar.v", "VZCONST", GLBL)
    assert a.triggers == ["S"]
    assert a.notes == ["VZCONST.never: never written; treated as constant"]


def test_undriven_net_is_still_refused():
    with pytest.raises(TransformError, match="cannot resolve the driver of en"):
        analyze(FIX / "vz_bad_undriven.v", "VZUNDRIVEN", GLBL)


def test_same_file_helper_module():
    a = analyze(FIX / "vz_helper.v", "VZHELPER", GLBL)
    assert a.forced == {} and set(a.submodules) == {"VZHELPER_CORE"}
    sub = a.submodules["VZHELPER_CORE"]
    assert sub.model == "VZHELPER_CORE" and sub.text[sub.endmodule :].startswith("endmodule")
    assert sub.forced["q"].triggers == {"PWR", "RST"} and sub.forced["q"].enablers == {"C"}
    assert (a.triggers, a.enablers) == (["PWR", "RST"], ["C"])


def test_read_after_assign_is_substituted_not_refused():
    a = analyze(FIX / "vz_rao.v", "VZRAO", GLBL)
    x = a.forced["r"]
    ((ovr, _),) = x.overrides
    ((read,),) = [[r for r in x.stale_reads]]
    assert read.active == ovr and a.text[read.span.start - 4 : read.span.end] == "x = r"


def test_non_ansi_output_reg_port():
    a = analyze(FIX / "vz_portreg.v", "VZPORTREG", GLBL)
    x = a.forced["Q"]
    assert x.is_port and x.dims == "[1:0] " and x.type == "reg"
    assert a.text[x.reg_keyword.start : x.reg_keyword.end] == "reg"
    assert a.text[x.decl_name.start : x.decl_end] == "Q;"
    assert a.triggers == ["S"]


def test_deassign_of_a_never_assigned_reg_is_a_noop():
    a = analyze(FIX / "vz_noopdeassign.v", "VZNOOP", GLBL)
    assert a.forced == {}
    ((d,),) = [a.noop_deassigns]
    assert a.text[d.start : d.end] == "deassign q;"
    assert a.notes == ["VZNOOP.q: deassigned but never assigned; deassign is a no-op"]


def test_helper_generate_branches_are_enumerated_through_the_model_parameter(tmp_path):
    f = tmp_path / "vz_helpgen.v"
    f.write_text("""// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module VZHG_CORE (Q, C, D, R);
  parameter MODE = "A";
  output Q;
  input C, D, R;
  reg q;
  assign Q = q;
  generate
    case (MODE)
      "B": begin : g_b
        always @(R) if (R) assign q = 1'b0; else deassign q;
      end
      default: begin : g_a
        always @(R) if (R) assign q = 1'b1; else deassign q;
      end
    endcase
  endgenerate
  always @(posedge C) q <= D;
endmodule
module VZHG (output Q, input C, input D, input R);
  parameter MODE = "A";
  VZHG_CORE #(.MODE(MODE)) u (.Q(Q), .C(C), .D(D), .R(R));
endmodule
""")
    assert generate_configs(f, "VZHG") == [{}, {"MODE": '"B"'}]
    a = analyze(f, "VZHG", GLBL)
    assert len(a.submodules["VZHG_CORE"].forced["q"].overrides) == 2
    assert a.triggers == ["R"]


def test_hierarchical_write_defeats_never_written(tmp_path):
    # even without the writer being analysed (a module not instantiated here), a dotted
    # name ending in the variable anywhere in the file means it may be written
    src = (FIX / "vz_bad_hier.v").read_text().replace("  VZHIER_HLP h (.i(S));\n", "")
    (tmp_path / "vz_hier2.v").write_text(src)
    with pytest.raises(TransformError, match="cannot resolve the driver of en"):
        analyze(tmp_path / "vz_hier2.v", "VZHIER", GLBL)


def test_procedural_assign_to_hierarchical_reference_is_refused(tmp_path):
    src = (FIX / "vz_single.v").read_text().replace("assign q = 1'b0;", "assign VZSINGLE.q = 1'b0;")
    (tmp_path / "vz_hassign.v").write_text(src)
    with pytest.raises(TransformError, match="hierarchical reference"):
        analyze(tmp_path / "vz_hassign.v", "VZSINGLE", GLBL)


def test_deassign_only_configuration_contributes_no_sensitivity(tmp_path):
    f = tmp_path / "vz_donly.v"
    f.write_text("""// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module VZDONLY (output Q, input C, input D, input A, input B);
  parameter [0:0] P = 1'b0;
  reg r;
  assign Q = r;
  generate if (P) begin : g1
    always @(A) if (A) assign r = 1'b0; else deassign r;
  end else begin : g0
    always @(B) deassign r;
  end endgenerate
  always @(posedge C) r <= D;
endmodule
""")
    x = analyze(f, "VZDONLY", GLBL).forced["r"]
    assert x.sensitivity == {"A"} and x.triggers == {"A"} and len(x.deassigns) == 2
