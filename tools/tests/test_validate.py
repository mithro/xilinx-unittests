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
    errors = validate(_v("t=121000 edge clk0 f\n"), fdce_map).errors
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


def test_gsr_is_hw_renderable(fdce_map):
    r = validate(_v("t=121000 glbl GSR=1\nt=123000 glbl GSR=0\nt=125000 sample S0\n"), fdce_map)
    assert r.errors == [] and r.hw_renderable


def test_x_at_initialisation_is_sim_only(fdce_map):
    r = validate(_v("t=0 set in[2]=0bx\nt=121000 sample S0\n"), fdce_map)
    assert r.errors == [] and r.hw_reasons == ["t=0: x/z stimulus"]


def test_pad_class_is_sim_only():
    m = build_map(spec_from_catalog(load_entry("7series", "FDCE", repo_root()), "c", {}))
    m.bits = [dataclasses.replace(b, cls="pad") if b.port == "D" else b for b in m.bits]
    r = validate(_v("t=121000 set in[2]=1\nt=122000 sample S0\n"), m)
    assert r.errors == [] and any("pad harness" in x for x in r.hw_reasons)


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
    body = "t=121000 edge clk0 r\nt=123000 set in[1]=1\n"
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
    assert r.output == "hw_renderable: no\n  reason: t=121000: x/z stimulus\n"

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
    errors = validate(_v("t=121000 set in[2:1]=0x3\n"), fdce_map).errors
    assert errors == [
        "t=121000: set in[2:1] changes 1 async/gate bit(s) and 1 other bit(s) in one line: "
        "split the async/gate and data changes, and each async/gate bit, into separate "
        "event times (spec §5.1)"
    ]
    assert not any("simultaneous" in e for e in errors)


def test_mixed_line_is_accepted_inside_a_simultaneous_group(fdce_map):
    r = validate(
        _v("t=121000 simultaneous set in[2:1]=0x3\nt=121000 simultaneous edge clk0 r\n"),
        fdce_map,
    )
    assert r.errors == [] and not r.hw_renderable


def test_header_async_sep_below_minimum(fdce_map):
    v = loads(HDR.replace("seed=0", "seed=0 async_sep_ps=500"))
    assert any("below the minimum 1000" in e for e in validate(v, fdce_map).errors)
