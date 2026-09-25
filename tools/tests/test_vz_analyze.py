# SPDX-License-Identifier: Apache-2.0
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
        ("vz_bad_rao.v", "VZRAO", "read after its procedural assign"),
        ("vz_bad_ansi.v", "VZANSI", "ANSI output reg"),
        ("vz_bad_macro.v", "VZMACRO", "macro expansion"),
        ("vz_bad_undriven.v", "VZUNDRIVEN", "cannot resolve the driver of en"),
        ("vz_bad_blackbox.v", "VZBLACKBOX", "driven by an instance output"),
        ("vz_bad_genparam.v", "VZBADGEN", "cannot enumerate generate configurations"),
        ("vz_bad_nestgen.v", "VZNESTGEN", "nested generate conditions"),
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
    with pytest.raises(TransformError, match="generate branch at line 12 mentions forced reg r"):
        analyze(FIX / "vz_generate.v", "VZGEN", GLBL, {"IS_C_INVERTED": ["1'b0"]})


def test_procedural_assign_in_another_module_is_refused(tmp_path):
    src = (
        (FIX / "vz_sub.v")
        .read_text()
        .replace(
            "assign o = ~i;",
            "reg r; assign o = r;\n  always @(i) if (i) assign r = 1'b0; else deassign r;",
        )
    )
    (tmp_path / "vz_sub2.v").write_text(src)
    with pytest.raises(TransformError, match="is in module VZSUB_INV, not VZSUB"):
        analyze(tmp_path / "vz_sub2.v", "VZSUB", GLBL)


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
    "CFGLUT5": "data is read after its procedural assign",
    "SRL16E": "data is read after its procedural assign",
    "SRLC16E": "data is read after its procedural assign",
    "SRLC32E": "data is read after its procedural assign",
    "FIFO18E1": "is in module FF18_INTERNAL_VLOG, not FIFO18E1",
    "FIFO36E1": "is in module FF36_INTERNAL_VLOG, not FIFO36E1",
    "ISERDESE1": "is in module bscntrl_iserdese1_vlog, not ISERDESE1",
    "OSERDESE1": "is in module plg_oserdese1_vlog, not OSERDESE1",
    "MMCME2_ADV": "clkfbout_frac_ht_rl: forced variable of type `real`",
    "MMCME3_ADV": "clkfbout_frac_ht_rl: forced variable of type `real`",
    "MMCME4_ADV": "clkfbout_frac_ht_rl: forced variable of type `real`",
    "PLLE2_ADV": "cannot resolve the driver of clk0_div_fint_odd",
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
}
PILOT = ("FDRE", "FDSE", "FDCE", "FDPE")


def _forced_models(ms):
    out = []
    for d in ms.search:
        for f in sorted(d.glob("*.v")):
            if re.search(rb"\bdeassign\b", f.read_bytes()) and has_procedural_assign(f):
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
    assert a.forced and a.triggers
    if f.stem in EXPECT_TRIGGERS:
        assert (a.triggers, a.enablers) == EXPECT_TRIGGERS[f.stem]


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
