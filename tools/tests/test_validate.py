# SPDX-License-Identifier: Apache-2.0
import dataclasses

import pytest
from click.testing import CliRunner

from xut.catalog.model import load_entry
from xut.cli import main
from xut.formats.xvec import Event, Vec, XvecError, dumps, loads
from xut.paths import repo_root
from xut.validate import mark, validate
from xut.wrap import build_map, spec_from_catalog

HDR = (
    "# xut-vec 2  prim=FDCE cfg=c nin=3 nout=1 nclk=1 settle_ps=120000 seed=0\n"
    "clock clk0 period=10000 phase=0 duty=50 mode=stepped\n"
)
# FDCE catalog order Q, C, CE, CLR, D -> in: CE=0, CLR=1 (async), D=2


@pytest.fixture(scope="module")
def fdce_map():
    return build_map(spec_from_catalog(load_entry("7series", "FDCE", repo_root()), "c", {}))


def _v(body):
    return loads(HDR + body)


def _raw(*events):
    """A Vec built in memory, bypassing the parser's co-timing rule (Ruling S6), so the
    validator's own checks for the same condition are exercised."""
    base = loads(HDR)
    return Vec(base.header, base.clocks, list(events))


def test_clean_file(fdce_map):
    r = validate(
        _v(
            "t=120000 set in[2]=1\nt=121000 edge clk0 r\nt=122000 sample S0\n"
            "t=126000 edge clk0 f\nt=130000 set in[1]=1\nt=131000 sample S1\n"
        ),
        fdce_map,
    )
    assert r.errors == [] and r.hw_renderable and r.ok


@pytest.mark.parametrize(
    "body,msg",
    [
        ("t=121000 set in[1]=1\nt=121000 set in[2]=1\n", "must be alone"),
        ("t=121000 set in[2:1]=0x3\n", "separate event times"),
        ("t=121000 set in[2]=1\nt=121500 sample S0\n", "after the last change"),
        ("t=121000 edge clk0 r\nt=121500 set in[1]=1\n", "from a clock edge"),
        ("t=121000 set in[1]=1\nt=121500 edge clk0 r\n", "from a clock edge"),
        ("t=121000 edge clk0 f\n", "alternate"),
        ("t=121000 edge clk0 r\nt=122000 edge clk0 r\n", "alternate"),
    ],
)
def test_rule_violations(fdce_map, body, msg):
    assert any(msg in e for e in validate(_v(body), fdce_map).errors)


@pytest.mark.parametrize(
    "events,msg",
    [
        (
            (Event(121000, "edge", "clk0", value="r"), Event(121000, "set", "in", 2, 2, "1")),
            "must be alone",
        ),
        ((Event(121000, "set", "in", 2, 2, "1"), Event(121000, "sample", "S0")), "shares its time"),
        (
            (Event(121000, "glbl", "GSR", value="1"), Event(121000, "set", "in", 2, 2, "1")),
            "must be alone",
        ),
    ],
)
def test_rule_violations_the_parser_already_refuses(fdce_map, events, msg):
    # Ruling S6: the .xvec parser refuses these unmarked co-timed groups, but validate
    # also sees in-memory Vecs (the builder's output) and must catch them itself.
    with pytest.raises(XvecError, match="co-timed"):
        loads(dumps(_raw(*events)))
    assert any(msg in e for e in validate(_raw(*events), fdce_map).errors)


def test_errors_name_the_time(fdce_map):
    errors = validate(_v("t=121000 edge clk0 f\nt=123000 sample S0\n"), fdce_map).errors
    assert errors and all(e.startswith("t=121000: ") for e in errors)


def test_disjoint_data_sets_may_share_a_time(fdce_map):
    r = validate(_v("t=121000 set in[0]=1\nt=121000 set in[2]=1\nt=122000 sample S0\n"), fdce_map)
    assert r.errors == [] and r.hw_renderable


def test_simultaneous_allowed_but_not_hw(fdce_map):
    r = validate(
        _v(
            "t=121000 simultaneous edge clk0 r\nt=121000 simultaneous set in[1]=1\n"
            "t=123000 sample S0\n"
        ),
        fdce_map,
    )
    assert r.errors == [] and not r.hw_renderable
    assert any("simultaneous" in x for x in r.hw_reasons)


def test_x_and_glbl_make_sim_only(fdce_map):
    r = validate(_v("t=121000 set in[2]=0bx\nt=123000 glbl GTS=1\nt=125000 sample S0\n"), fdce_map)
    assert r.errors == []
    assert sorted(r.hw_reasons) == [
        "t=121000: x/z stimulus",
        "t=123000: glbl GTS is sim-only (spec §5.2)",
    ]


def test_x_at_initialisation_is_sim_only(fdce_map):
    r = validate(_v("t=0 set in[2]=0bx\nt=121000 sample S0\n"), fdce_map)
    assert r.errors == [] and r.hw_reasons == ["t=0: x/z stimulus"]


def test_pad_class_is_sim_only():
    m = build_map(spec_from_catalog(load_entry("7series", "FDCE", repo_root()), "c", {}))
    m.bits = [dataclasses.replace(b, cls="pad") if b.port == "D" else b for b in m.bits]
    r = validate(_v("t=121000 set in[2]=1\nt=122000 sample S0\n"), m)
    assert r.errors == [] and r.hw_reasons == [
        "pad-class or inout port(s) D need the pad harness (spec §7.3)"
    ]


def test_set_on_clock_class_bit_is_an_error():
    m = build_map(spec_from_catalog(load_entry("7series", "FDCE", repo_root()), "c", {}))
    m.bits = [dataclasses.replace(b, cls="clock") if b.port == "D" else b for b in m.bits]
    assert any("clock-class" in e for e in validate(_v("t=121000 set in[2]=1\n"), m).errors)


def test_header_mismatch(fdce_map):
    v = loads(HDR.replace("nin=3", "nin=4").replace("prim=FDCE", "prim=FDRE"))
    errors = validate(v, fdce_map).errors
    assert any("nin=4" in e for e in errors) and any("prim=FDRE" in e for e in errors)


def test_settle_too_short(fdce_map):
    v = loads(HDR.replace("settle_ps=120000", "settle_ps=50000"))
    assert any("settle_ps" in e for e in validate(v, fdce_map).errors)


def test_header_async_sep_is_used(fdce_map):
    body = "t=121000 edge clk0 r\nt=123000 set in[1]=1\nt=125000 sample S0\n"
    assert validate(_v(body), fdce_map).errors == []
    v = loads(HDR.replace("seed=0", "seed=0 async_sep_ps=3000") + body)
    assert any("async_sep_ps=3000" in e for e in validate(v, fdce_map).errors)


def test_free_clock_edges_count_for_async_separation(fdce_map):
    v = loads(
        HDR.replace("mode=stepped", "mode=free")
        + "t=120000 clock_start clk0\nt=130200 set in[1]=1\nt=135000 sample S0\n"
    )
    errors = validate(v, fdce_map).errors
    assert any("from a clock edge" in e for e in errors)
    assert any("t=135000: a sample shares its time" in e for e in errors)  # 135000 is a free edge


def test_clock_start_is_not_a_second_change_at_its_first_edge(fdce_map):
    v = loads(
        HDR.replace("mode=stepped", "mode=free")
        + "t=120000 clock_start clk0\nt=126000 sample S0\nt=127000 clock_stop clk0\n"
    )
    assert validate(v, fdce_map).errors == []


def test_explicit_edge_on_free_clock(fdce_map):
    v = loads(HDR.replace("mode=stepped", "mode=free") + "t=121000 edge clk0 r\n")
    assert any("free-running" in e for e in validate(v, fdce_map).errors)


def test_free_clock_stop_must_be_in_low_phase(fdce_map):
    base = HDR.replace("mode=stepped", "mode=free") + "t=120000 clock_start clk0\n"
    high = validate(loads(base + "t=122000 clock_stop clk0\n"), fdce_map).errors
    low = validate(loads(base + "t=127000 clock_stop clk0\n"), fdce_map).errors
    assert any("low phase" in e for e in high)
    assert not any("low phase" in e for e in low)


def test_free_clock_restart_waits_for_low_phase(fdce_map):
    base = HDR.replace("mode=stepped", "mode=free") + "t=120000 clock_start clk0\n"
    early = base + "t=127000 clock_stop clk0\nt=128000 clock_start clk0\n"
    assert any(
        "before its previous low phase" in e for e in validate(loads(early), fdce_map).errors
    )


def test_free_clock_edges_definition(fdce_map):
    from xut.formats.xvec import free_clock_edges

    v = loads(
        HDR.replace("mode=stepped", "mode=free")
        + "t=120000 clock_start clk0\nt=137000 clock_stop clk0\nt=150000 end\n"
    )
    edges = [(e.t, e.value) for e in free_clock_edges(v)]
    assert edges == [(120000, "r"), (125000, "f"), (130000, "r"), (135000, "f")]
    # golden (Task 6) and the stimulus compiler (Task 7) are pinned to this same
    # definition by test_golden.py and test_stimcompile.py::test_free_clock_words


def test_mark(fdce_map):
    v = _v("t=121000 set in[2]=0bx\nt=123000 glbl GTS=1\nt=125000 sample S0\n")
    mark(v, validate(v, fdce_map))
    assert v.hw_renderable is False
    assert v.hw_reason == "t=121000: x/z stimulus; t=123000: glbl GTS is sim-only (spec §5.2)"
    assert loads(dumps(v)).hw_reason == v.hw_reason


def _write_map(tmp_path, m):
    p = tmp_path / "map.json"
    p.write_text(m.to_json())
    return p


def test_cli_vec_check(tmp_path, fdce_map):
    mp = _write_map(tmp_path, fdce_map)
    good = tmp_path / "good.xvec"
    good.write_text(HDR + "t=121000 set in[2]=0bx\nt=123000 sample S0\n")
    r = CliRunner().invoke(main, ["vec", "check", str(good), "--map", str(mp)])
    assert r.exit_code == 0, r.output
    assert r.output == "hw_renderable: no\n  reason: t=121000: x/z stimulus\nx_inputs: yes\n"

    bad = tmp_path / "bad.xvec"
    bad.write_text(HDR + "t=121000 edge clk0 f\n")
    r = CliRunner().invoke(main, ["vec", "check", str(bad), "--map", str(mp)])
    assert r.exit_code == 1 and "error: t=121000:" in r.output


def test_cli_vec_check_syntax_error_is_clean(tmp_path, fdce_map):
    mp = _write_map(tmp_path, fdce_map)
    bad = tmp_path / "bad.xvec"
    bad.write_text(HDR + "t=121000 bogus\n")
    r = CliRunner().invoke(main, ["vec", "check", str(bad), "--map", str(mp)])
    assert r.exit_code == 1 and "Error:" in r.output and "line 3" in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_lone_mixed_async_data_line_says_split(fdce_map):
    errors = validate(_v("t=121000 set in[2:1]=0x3\nt=123000 sample S0\n"), fdce_map).errors
    assert errors == [
        "t=121000: set in[2:1] changes 1 async/gate bit(s) and 1 other bit(s) in one line: "
        "split the async/gate and data changes, and each async/gate bit, into separate "
        "event times (spec §5.1)"
    ]
    assert not any("simultaneous" in e for e in errors)


def test_mixed_line_is_accepted_inside_a_simultaneous_group(fdce_map):
    r = validate(
        _v(
            "t=121000 simultaneous set in[2:1]=0x3\nt=121000 simultaneous edge clk0 r\n"
            "t=123000 sample S0\n"
        ),
        fdce_map,
    )
    assert r.errors == [] and not r.hw_renderable


def test_header_async_sep_below_minimum(fdce_map):
    v = loads(HDR.replace("seed=0", "seed=0 async_sep_ps=500"))
    assert any("below the minimum 1000" in e for e in validate(v, fdce_map).errors)


# --- Ruling S8-prime: hw_renderable is order-renderable on stepped clocks only.

FREE = HDR.replace("mode=stepped", "mode=free") + "t=120000 clock_start clk0\n"
FREE_REASON = "free-running clocks need real-time rendering (step 3): clk0"


def test_close_spacing_on_stepped_clocks_stays_hw_renderable(fdce_map):
    # 1 ns spacing everywhere: the stepped harness re-times events, only order matters.
    r = validate(
        _v(
            "t=120000 set in[2]=1\nt=121000 edge clk0 r\nt=122000 set in[1]=1\n"
            "t=123000 set in[0]=1\nt=124000 edge clk0 f\nt=125000 sample S0\n"
        ),
        fdce_map,
    )
    assert r.errors == [] and r.hw_renderable


@pytest.mark.parametrize(
    "body",
    [
        "t=127500 set in[2]=1\nt=129000 sample S0\n",  # clear of every free edge
        "t=125500 set in[2]=1\nt=127000 sample S0\n",  # 500 ps from a free edge
        "t=126000 sample S0\n",  # no input change at all
    ],
)
def test_any_free_clock_is_hw_no(fdce_map, body):
    """B1 (Ruling S8-prime): the stepped harness re-times events, so it would change how
    many free-clock edges fall between two events: any mode=free clock is hw no."""
    r = validate(loads(FREE + body), fdce_map)
    assert r.errors == []
    assert r.hw_reasons == [FREE_REASON]


def test_free_clock_declared_but_never_started_is_hw_no(fdce_map):
    free = HDR.replace("phase=0 duty=50 mode=stepped", "phase=2500 duty=50 mode=free")
    r = validate(loads(free + "t=121000 sample S0\n"), fdce_map)
    assert r.errors == [] and r.hw_reasons == [FREE_REASON]


def test_gsr_near_free_clock_edge_is_still_a_sim_error(fdce_map):
    r = validate(loads(FREE + "t=125500 glbl GSR=1\nt=127000 sample S0\n"), fdce_map)
    assert any("GSR change 500 ps from a clock edge" in e for e in r.errors)
    assert not r.hw_renderable


@pytest.mark.parametrize("before", [True, False])
def test_gsr_is_async_for_stepped_edge_separation(fdce_map, before):
    body = (
        "t=121000 glbl GSR=1\nt=121500 edge clk0 r\n"
        if before
        else "t=121000 edge clk0 r\nt=121500 glbl GSR=1\n"
    ) + "t=130000 sample S0\n"
    errors = validate(_v(body), fdce_map).errors
    assert errors == [
        "t=121%s: GSR change 500 ps from a clock edge (< async_sep_ps=1000)"
        % ("000" if before else "500")
    ]


# --- B2: every inter-event gap >= max(async_sep_ps, the primitive's min_event_gap_ps)


def test_sub_gap_data_events_are_hw_no(fdce_map):
    r = validate(_v("t=121000 set in[2]=1\nt=121400 set in[0]=1\nt=123000 sample S0\n"), fdce_map)
    assert r.errors == []
    assert r.hw_reasons == [
        "t=121400: 400 ps after the previous event at t=121000 (< min event gap 1000 ps; "
        "stepped rendering preserves order only, Ruling S8-prime)"
    ]


def test_event_gap_uses_the_recorded_async_sep(fdce_map):
    body = "t=121000 set in[2]=1\nt=123000 set in[0]=1\nt=126000 sample S0\n"
    assert validate(_v(body), fdce_map).hw_renderable
    v = loads(HDR.replace("seed=0", "seed=0 async_sep_ps=2500") + body)
    r = validate(v, fdce_map)
    assert r.errors == [] and any("< min event gap 2500 ps" in x for x in r.hw_reasons)


def test_event_gap_uses_the_primitive_min_event_gap(fdce_map):
    m = dataclasses.replace(fdce_map, min_event_gap_ps=5000)
    body = "t=121000 set in[2]=1\nt=124000 set in[0]=1\nt=130000 sample S0\n"
    assert validate(_v(body), fdce_map).hw_renderable
    r = validate(_v(body), m)
    assert r.errors == []
    assert r.hw_reasons == [
        "t=124000: 3000 ps after the previous event at t=121000 (< min event gap 5000 ps; "
        "stepped rendering preserves order only, Ruling S8-prime)"
    ]


def test_initialisation_is_not_an_event_gap(fdce_map):
    r = validate(_v("t=0 set in[2]=1\nt=120000 set in[0]=1\nt=121000 sample S0\n"), fdce_map)
    assert r.errors == [] and r.hw_renderable


# --- B3: pad outputs and inout ports need the pad harness


def _map_of(prim):
    return build_map(spec_from_catalog(load_entry("7series", prim, repo_root()), "c", {}))


@pytest.mark.parametrize("prim", ["OBUF", "IOBUF"])
def test_pad_output_or_inout_makes_file_hw_no(prim):
    m = _map_of(prim)
    hdr = (
        f"# xut-vec 2  prim={prim} cfg=c nin={m.nin} nout={m.nout} nclk=0 settle_ps=120000 seed=0\n"
    )
    r = validate(loads(hdr + "t=121000 sample S0\n"), m)
    assert r.errors == []
    assert len(r.hw_reasons) == 1 and "pad harness (spec §7.3)" in r.hw_reasons[0]


# --- B4: GSR on hardware needs the GSR-immune harness


def test_gsr_makes_file_hw_no(fdce_map):
    r = validate(_v("t=121000 glbl GSR=1\nt=123000 glbl GSR=0\nt=125000 sample S0\n"), fdce_map)
    assert r.errors == []
    assert r.hw_reasons == [
        "t=121000: glbl GSR on hardware needs the GSR-immune harness (spec §7.2; step 3)",
        "t=123000: glbl GSR on hardware needs the GSR-immune harness (spec §7.2; step 3)",
    ]


# --- B5: x_inputs flags stimuli 2-state runners must skip


@pytest.mark.parametrize(
    "body,x",
    [
        ("t=121000 set in[2]=1\nt=122000 sample S0\n", False),
        ("t=121000 set in[2]=0bx\nt=122000 sample S0\n", True),
        ("t=0 set in[2:0]=0b0z1\nt=121000 sample S0\n", True),
    ],
)
def test_x_inputs_flag(fdce_map, body, x):
    assert validate(_v(body), fdce_map).x_inputs is x


def test_cli_vec_check_prints_x_inputs(tmp_path, fdce_map):
    mp = _write_map(tmp_path, fdce_map)
    f = tmp_path / "x.xvec"
    f.write_text(HDR + "t=121000 set in[2]=0bx\nt=123000 sample S0\n")
    r = CliRunner().invoke(main, ["vec", "check", str(f), "--map", str(mp)])
    assert r.exit_code == 0 and "x_inputs: yes" in r.output.splitlines()


# --- B6: settle covers glbl's GSR and GTS/GRESTORE pulses, from named constants


def test_settle_bound_is_max_of_roc_and_gres_end_plus_margin():
    from xut.validate import (
        GRES_START_PS,
        GRES_WIDTH_PS,
        MIN_SETTLE_PS,
        ROC_WIDTH_PS,
        SETTLE_MARGIN_PS,
    )

    assert max(ROC_WIDTH_PS, GRES_START_PS + GRES_WIDTH_PS) + SETTLE_MARGIN_PS == MIN_SETTLE_PS


def test_settle_below_bound_is_an_error(fdce_map):
    from xut.validate import MIN_SETTLE_PS

    ok = loads(
        HDR.replace("settle_ps=120000", f"settle_ps={MIN_SETTLE_PS}") + "t=130000 sample S0\n"
    )
    bad = loads(HDR.replace("settle_ps=120000", f"settle_ps={MIN_SETTLE_PS - 1}"))
    assert validate(ok, fdce_map).errors == []
    assert any("settle_ps" in e for e in validate(bad, fdce_map).errors)


def _glbl_params(path):
    import re

    text = path.read_text()
    assert re.search(r"`timescale\s+1\s*ps\s*/\s*1\s*ps", text), path
    return {
        k: int(re.search(rf"parameter\s+{k}\s*=\s*(\d+)\s*;", text).group(1))
        for k in ("ROC_WIDTH", "GRES_START", "GRES_WIDTH")
    }


def _check_glbl(path):
    from xut.validate import GRES_START_PS, GRES_WIDTH_PS, ROC_WIDTH_PS

    assert _glbl_params(path) == {
        "ROC_WIDTH": ROC_WIDTH_PS,
        "GRES_START": GRES_START_PS,
        "GRES_WIDTH": GRES_WIDTH_PS,
    }


def test_glbl_constants_match_submodule_glbl():
    from xut.paths import submodule_src

    glbl = submodule_src() / "glbl.v"
    if not glbl.is_file():
        pytest.skip("XilinxUnisimLibrary submodule not initialised")
    _check_glbl(glbl)


@pytest.mark.vivado
def test_glbl_constants_match_vivado_glbl():
    from xut.paths import VIVADO_SRC

    _check_glbl(VIVADO_SRC / "glbl.v")


def test_in_memory_parser_illegal_cotiming_is_an_error(fdce_map):
    v = _raw(
        Event(121000, "set", "in", 0, 0, "1", simultaneous=True),
        Event(121000, "set", "in", 2, 2, "1"),
        Event(122000, "sample", "S0"),
    )
    r = validate(v, fdce_map)
    assert any(e.startswith("structure: t=121000: mixed 'simultaneous'") for e in r.errors)
    assert "event(s) #2" in r.errors[0]
    assert not r.hw_renderable
    with pytest.raises(ValueError, match="invalid stimulus"):
        mark(v, r)


def test_in_memory_time_order_is_checked(fdce_map):
    v = _raw(Event(122000, "sample", "S0"), Event(121000, "set", "in", 2, 2, "1"))
    assert any("time goes backwards" in e for e in validate(v, fdce_map).errors)


# --- A2: in-memory Vecs are held to the parser's per-event rules


@pytest.mark.parametrize(
    "event,msg",
    [
        (Event(121000, "set", "in", 9, 9, "1"), "out of range"),
        (Event(121000, "sample", "bad label"), "bad sample label"),
        (Event(5000, "sample", "S0"), "settle_ps"),
        (Event(121000, "edge", "clk3", value="r"), "undeclared clock"),
        (Event(121000, "clock_start", "clk0"), "mode=free"),
    ],
)
def test_in_memory_parser_illegal_event_is_an_error_not_a_crash(fdce_map, event, msg):
    v = _raw(Event(120000, "set", "in", 2, 2, "1"), event, Event(130000, "sample", "S9"))
    r = validate(v, fdce_map)
    assert any(e.startswith("structure: event #2: ") and msg in e for e in r.errors), r.errors
    assert not r.hw_renderable


def test_in_memory_bad_clock_does_not_hang(fdce_map):
    from xut.formats.xvec import Clock

    base = loads(HDR)
    v = Vec(base.header, [Clock("clk0", 0, 0, 0, 50, "free")], [Event(130000, "sample", "S0")])
    assert any("period" in e for e in validate(v, fdce_map).errors)


# --- A4: mark() raises a XutError; vec check never prints a bare "hw no" for invalid files


def test_mark_refusal_is_a_xut_error(fdce_map):
    from xut.errors import XutError
    from xut.validate import ValidationError

    v = _v("t=121000 edge clk0 f\n")
    with pytest.raises(ValidationError, match="invalid stimulus") as ei:
        mark(v, validate(v, fdce_map))
    assert isinstance(ei.value, XutError) and isinstance(ei.value, ValueError)


def test_cli_vec_check_invalid_file_has_no_hw_verdict(tmp_path, fdce_map):
    mp = _write_map(tmp_path, fdce_map)
    bad = tmp_path / "bad.xvec"
    bad.write_text(HDR + "t=121000 edge clk0 f\nt=123000 sample S0\n")
    r = CliRunner().invoke(main, ["vec", "check", str(bad), "--map", str(mp)])
    assert r.exit_code == 1
    lines = r.output.splitlines()
    assert lines[0].startswith("error: t=121000:")
    assert "hw_renderable: n/a (invalid)" in lines
    assert "hw_renderable: no" not in r.output


# --- A5: the header's cfg and attr.* must match the wrapper map


def test_cfg_and_attrs_are_compared_with_the_map():
    m = build_map(
        spec_from_catalog(load_entry("7series", "FDCE", repo_root()), "c", {"INIT": "1'b1"})
    )
    good = loads(HDR.replace("seed=0", "seed=0 attr.INIT=1'b1") + "t=121000 sample S0\n")
    assert validate(good, m).errors == []
    errors = validate(loads(HDR.replace("cfg=c", "cfg=d")), m).errors
    assert any("cfg=d" in e for e in errors)
    errors = validate(loads(HDR.replace("seed=0", "seed=0 attr.INIT=1'b0")), m).errors
    assert any("attr.INIT" in e for e in errors)
    errors = validate(loads(HDR.replace("seed=0", "seed=0 attr.IS_C_INVERTED=1'b1")), m).errors
    assert any("attr.IS_C_INVERTED" in e for e in errors)


# --- ruling S15: zero evidence is never a pass ------------------------------------------


def test_a_stimulus_without_samples_is_an_error(fdce_map):
    """A non-reject stimulus that never samples would replay to an empty expected trace
    and "pass" on every runner while checking nothing (PR B gate (b) #1)."""
    r = validate(_v("t=120000 set in[2]=1\nt=121000 edge clk0 r\nt=126000 edge clk0 f\n"), fdce_map)
    assert any("no samples" in e for e in r.errors) and not r.hw_renderable


def test_a_reject_stimulus_needs_no_samples(fdce_map):
    v = loads(
        HDR.replace("seed=0", "seed=0 expect=reject illegal=INIT attr.INIT=1'bx")
        + "t=121000 edge clk0 r\n"
    )
    assert not any("no samples" in e for e in validate(v, fdce_map).errors)


# --- the implicit GSR release at ROC_WIDTH is an async change (PR B gate (b) #5) --------


def test_a_free_clock_edge_at_the_gsr_release_is_an_error(fdce_map):
    """A free clock running from t=0 has an edge exactly at ROC_WIDTH (100 ns), where it
    races glbl's GSR release: the language does not order the two."""
    v = loads(HDR.replace("mode=stepped", "mode=free") + "t=121000 sample S0\n")
    errors = validate(v, fdce_map).errors
    assert any("t=100000" in e and "GSR release" in e for e in errors), errors


def test_a_free_clock_clear_of_the_gsr_release_is_fine(fdce_map):
    v = loads(
        HDR.replace("phase=0 duty=50 mode=stepped", "phase=2500 duty=50 mode=free")
        + "t=123500 sample S0\n"
    )
    assert not any("GSR release" in e for e in validate(v, fdce_map).errors)


def test_an_explicit_event_near_the_gsr_release_is_an_error(fdce_map):
    """settle_ps may sit within a larger async_sep_ps of ROC_WIDTH: an event there
    races the release too."""
    v = loads(
        HDR.replace("settle_ps=120000", "settle_ps=101000").replace(
            "seed=0", "seed=0 async_sep_ps=5000"
        )
        + "t=101000 set in[2]=1\nt=110000 sample S0\n"
    )
    errors = validate(v, fdce_map).errors
    assert any("t=101000" in e and "GSR release" in e for e in errors), errors


# --- ruling S13b: a reject configuration names its illegal attribute(s) ----------------

REJ = HDR.replace("seed=0", "seed=0 expect=reject attr.INIT=1'bx")


@pytest.mark.parametrize(
    ("extra", "msg"),
    [
        ("", "must name its illegal attribute"),
        (" illegal=SRVAL", "illegal=SRVAL is not an attribute"),
    ],
)
def test_reject_needs_a_declared_illegal_attribute(fdce_map, extra, msg):
    m = dataclasses.replace(fdce_map, attrs={"INIT": "1'bx"})
    v = loads(REJ.replace("expect=reject", "expect=reject" + extra) + "t=121000 edge clk0 r\n")
    assert any(msg in e for e in validate(v, m).errors)
    v = loads(REJ.replace("expect=reject", "expect=reject illegal=INIT") + "t=121000 edge clk0 r\n")
    assert v.illegal == ["INIT"] and validate(v, m).errors == []


def test_illegal_without_reject_is_an_error(fdce_map):
    v = loads(HDR.replace("seed=0", "seed=0 illegal=INIT") + "t=121000 sample S0\n")
    assert any("only meaningful with expect=reject" in e for e in validate(v, fdce_map).errors)
