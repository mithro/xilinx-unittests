# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.formats.xvec import (
    Event,
    Vec,
    XvecError,
    decode_value,
    dumps,
    encode_value,
    free_clock_edges,
    free_runs,
    loads,
)

SPEC_EXAMPLE = """\
# xut-vec 2  prim=FDCE cfg=init1 nin=4 nout=1 nclk=1 settle_ps=120000 seed=17
clock  clk0  period=10000 phase=0 duty=50 mode=stepped   # or mode=free
t=120000  set   in[3:0]=0x1          # data
t=121000  edge  clk0 r
t=125000  set   in[2]=1              # async: alone in its event
t=126000  sample S1
"""


def test_spec_example_parses():
    v = loads(SPEC_EXAMPLE)
    assert (v.prim, v.cfg, v.nin, v.nout, v.nclk, v.settle_ps, v.seed) == (
        "FDCE",
        "init1",
        4,
        1,
        1,
        120000,
        17,
    )
    assert v.clocks[0].mode == "stepped" and v.clocks[0].period == 10000
    assert v.events[0] == Event(120000, "set", "in", 0, 3, "0001")
    assert v.events[1] == Event(121000, "edge", "clk0", value="r")
    assert v.events[2] == Event(125000, "set", "in", 2, 2, "1")
    assert v.events[3] == Event(126000, "sample", "S1")


def test_roundtrip_is_canonical():
    v = loads(SPEC_EXAMPLE)
    assert loads(dumps(v)) == v
    assert dumps(loads(dumps(v))) == dumps(v)


def test_attrs_expect_and_hw_line():
    text = (
        "# xut-vec 2  prim=FDRE cfg=a nin=3 nout=1 nclk=1 settle_ps=120000 seed=1 "
        "attr.INIT=1'b1 expect=reject\n"
        'hw_renderable no reason="t=130000: simultaneous events"\n'
        "clock clk0 period=10000 phase=0 duty=50 mode=stepped\n"
        "t=0 set in[2]=1\n"
        "t=130000 end\n"
    )
    v = loads(text)
    assert v.attrs == {"INIT": "1'b1"} and v.expect == "reject"
    assert v.hw_renderable is False and v.hw_reason == "t=130000: simultaneous events"
    assert loads(dumps(v)) == v


@pytest.mark.parametrize(
    "text,width,bits",
    [
        ("0x1", 4, "0001"),
        ("5", 3, "101"),
        ("0b1x0z", 4, "1x0z"),
        ("0bx", 1, "x"),
        ("0x00f", 4, "1111"),
        ("0", 2, "00"),
    ],
)
def test_decode_value(text, width, bits):
    assert decode_value(text, width) == bits


@pytest.mark.parametrize(
    "text,width",
    [
        ("0x1f", 4),
        ("0b10", 1),
        ("0xg", 4),
        ("abc", 4),
        ("0bx0", 1),
        ("0x-1", 4),
        ("0x+1", 4),
        ("0x1_0", 8),
        ("-1", 4),
    ],
)
def test_decode_value_rejects(text, width):
    with pytest.raises(XvecError):
        decode_value(text, width)


@pytest.mark.parametrize("bits,text", [("1", "1"), ("0001", "0x1"), ("1x", "0b1x"), ("000", "0x0")])
def test_encode_value(bits, text):
    assert encode_value(bits) == text
    assert decode_value(text, len(bits)) == bits


@pytest.mark.parametrize(
    "text,width",
    [
        ("0x1f", 4),  # hex: 0x1f = 0b11111, a non-zero bit above the 4-bit field
        ("0b101", 2),  # bin: leading '1' above a 2-bit field
        ("0bx0", 1),  # bin: an 'x' above a 1-bit field is still a fit error
        ("0bz1", 1),  # bin: a 'z' above a 1-bit field is still a fit error
    ],
)
def test_decode_value_strict_width_rejects(text, width):
    with pytest.raises(XvecError, match=f"does not fit in {width} bit"):
        decode_value(text, width)


@pytest.mark.parametrize(
    "text,width,bits",
    [
        ("0x01", 4, "0001"),  # hex: leading zero nibble is fine
        ("0b001", 2, "01"),  # bin: leading zero bit is fine
        ("0b0x0", 2, "x0"),  # bin: leading zero ahead of the truncation point is fine
    ],
)
def test_decode_value_leading_zeros_fit(text, width, bits):
    assert decode_value(text, width) == bits


def test_decode_value_field_name_in_message():
    with pytest.raises(XvecError, match=r"in\[3:0\]: value '0x1f' does not fit in 4 bit"):
        decode_value("0x1f", 4, field="in[3:0]")


H = (
    "# xut-vec 2  prim=P cfg=c nin=4 nout=1 nclk=1 settle_ps=100 seed=0\n"
    "clock clk0 period=10 phase=0 duty=50 mode=stepped\n"
)


@pytest.mark.parametrize(
    "body,msg",
    [
        ("t=100 set in[4]=1\n", "out of range"),
        ("t=200 sample A\nt=100 sample B\n", "backwards"),
        ("t=100 edge clk1 r\n", "undeclared clock"),
        ("t=100 sample A\nt=200 sample A\n", "duplicate label"),
        ("t=50 sample A\n", "precede settle_ps"),
        ("t=100 simultaneous sample A\n", "simultaneous"),
        ("t=100 end\nt=200 sample A\n", "'end' must be the last"),
        ("t=100 frob x\n", "unknown op"),
        ("bogus\n", "unrecognised line"),
        ("t=100 set in[1:2]=0\n", "msb < lsb"),
    ],
)
def test_errors(body, msg):
    with pytest.raises(XvecError, match=msg):
        loads(H + body)


def test_missing_header_key():
    with pytest.raises(XvecError, match="lacks seed"):
        loads("# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=0 settle_ps=0\n")


def test_wrong_version():
    with pytest.raises(XvecError, match="version 1"):
        loads("# xut-vec 1  prim=P\n")


def test_set_value_overflow_names_field():
    with pytest.raises(XvecError, match=r"in\[3:0\]: value '0x1f' does not fit in 4 bit"):
        loads(H + "t=100 set in[3:0]=0x1f\n")


# --- free_runs / free_clock_edges: the single shared definition of free-running clock
# --- edges, used later by validate, golden replay and the testbench compiler.


def test_free_clock_edges_no_free_clocks():
    """A stepped-only vector has no free clocks: both functions return empty."""
    text = (
        "# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=1 settle_ps=0 seed=0\n"
        "clock clk0 period=100 phase=0 duty=50 mode=stepped\n"
        "t=100 edge clk0 r\n"
    )
    v = loads(text)
    assert free_runs(v) == []
    assert free_clock_edges(v) == []


def test_free_clock_edges_no_clocks_at_all():
    """A vector with nclk=0 and no clocks declared: both functions return empty."""
    v = loads("# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=0 settle_ps=0 seed=0\nt=0 sample A\n")
    assert free_runs(v) == []
    assert free_clock_edges(v) == []


def test_free_clock_edges_duty_and_phase():
    """Non-50% duty and a nonzero phase: first rise at phase, fall at phase+high."""
    text = (
        "# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=1 settle_ps=0 seed=0\n"
        "clock clk0 period=100 phase=30 duty=25 mode=free\n"
        "t=230 sample A\n"
    )
    v = loads(text)
    assert free_clock_edges(v) == [
        Event(30, "edge", "clk0", value="r"),
        Event(55, "edge", "clk0", value="f"),
        Event(130, "edge", "clk0", value="r"),
        Event(155, "edge", "clk0", value="f"),
        Event(230, "edge", "clk0", value="r"),
    ]


def test_free_runs_and_edges_with_clock_start_stop():
    """A clock_start/clock_stop window: the stop (in a low phase) ends the run with
    no trailing falling edge and no edges at or after it."""
    text = (
        "# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=1 settle_ps=0 seed=0\n"
        "clock clk0 period=100 phase=0 duty=50 mode=free\n"
        "t=10 clock_start clk0\n"
        "t=175 clock_stop clk0\n"
    )
    v = loads(text)
    assert free_runs(v) == [(v.clock("clk0"), 10, 175)]
    assert free_clock_edges(v) == [
        Event(10, "edge", "clk0", value="r"),
        Event(60, "edge", "clk0", value="f"),
        Event(110, "edge", "clk0", value="r"),
        Event(160, "edge", "clk0", value="f"),
    ]


def test_free_clock_edges_multiple_clocks_merged_sorted():
    """Two free clocks with different period/phase: edges are merged in time order,
    ties broken by declaration order (clk0 before clk1)."""
    text = (
        "# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=2 settle_ps=0 seed=0\n"
        "clock clk0 period=100 phase=0 duty=50 mode=free\n"
        "clock clk1 period=60 phase=10 duty=50 mode=free\n"
        "t=130 sample A\n"
    )
    v = loads(text)
    assert free_clock_edges(v) == [
        Event(0, "edge", "clk0", value="r"),
        Event(10, "edge", "clk1", value="r"),
        Event(40, "edge", "clk1", value="f"),
        Event(50, "edge", "clk0", value="f"),
        Event(70, "edge", "clk1", value="r"),
        Event(100, "edge", "clk0", value="r"),
        Event(100, "edge", "clk1", value="f"),
        Event(130, "edge", "clk1", value="r"),
    ]


def test_free_clock_edge_exactly_at_sample_time():
    """An edge computed exactly at a sample's time is still included (the vector
    itself never forbids this; class-rule separation is xut.validate's job)."""
    text = (
        "# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=1 settle_ps=0 seed=0\n"
        "clock clk0 period=50 phase=0 duty=50 mode=free\n"
        "t=100 sample A\n"
    )
    v = loads(text)
    assert v.events[-1].t == 100
    assert Event(100, "edge", "clk0", value="r") in free_clock_edges(v)


# --- quote-aware comment stripping and a writer that never silently mangles data (I1) ---


def test_hw_reason_hash_is_data_trailing_comment_is_stripped():
    text = (
        H
        + 'hw_renderable no reason="issue #5: bad"  # a real trailing comment\n'
        + "t=100 sample A\n"
    )
    v = loads(text)
    assert v.hw_renderable is False
    assert v.hw_reason == "issue #5: bad"
    assert loads(dumps(v)) == v
    assert '"issue #5: bad"' in dumps(v)


def test_attr_value_with_hash_roundtrips():
    text = (
        "# xut-vec 2  prim=P cfg=c nin=1 nout=1 nclk=0 settle_ps=0 seed=0 "
        'attr.NOTE="release #5"\n'
        "t=0 sample A\n"
    )
    v = loads(text)
    assert v.attrs == {"NOTE": "release #5"}
    assert loads(dumps(v)) == v
    assert 'attr.NOTE="release #5"' in dumps(v)


def test_hw_reason_with_quote_round_trips():
    """S34.3 reverses I1 narrowly: a literal quote is escaped, not refused."""
    v = loads(H + "t=100 sample A\n")
    v.hw_renderable = False
    v.hw_reason = 'has a "quote" in it'
    assert loads(dumps(v)) == v
    assert loads(dumps(v)).hw_reason == 'has a "quote" in it'


def test_dumps_raises_on_unrepresentable_newline_in_header_value():
    v = loads(H + "t=100 sample A\n")
    v.header["attr.NOTE"] = "line one\nline two"
    with pytest.raises(XvecError, match="cannot be represented"):
        dumps(v)


@pytest.mark.parametrize("ctrl", ["\r", "\x00", "\x07", "\x1f", "\x7f"])
def test_dumps_raises_on_other_control_chars_in_header_value(ctrl):
    """Not just newline: any control character the parser cannot represent in this
    line-oriented format is refused, never silently mangled (S34.3 narrows I1, it
    does not remove it)."""
    v = loads(H + "t=100 sample A\n")
    v.header["attr.NOTE"] = f"a{ctrl}b"
    with pytest.raises(XvecError, match="cannot be represented"):
        dumps(v)


@pytest.mark.parametrize("ctrl", ["\n", "\x00", "\x1f", "\x7f"])
def test_dumps_raises_on_control_char_in_hw_reason(ctrl):
    v = loads(H + "t=100 sample A\n")
    v.hw_renderable = False
    v.hw_reason = f"a{ctrl}b"
    with pytest.raises(XvecError, match="cannot be represented"):
        dumps(v)


# --- S34.3: the writer escapes '"' and '\' in a header attr.* value exactly as the
# --- parser accepts them, rather than refusing a quoted string (reverses I1 narrowly).
# --- Required before the bufg/io units, whose attributes include strings such as
# --- IOSTANDARD="LVCMOS33".


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        "has spaces",
        'has a "quote" inside',
        "has a \\backslash",
        "a=b",
        "release #5",
        "trailing backslash\\",
        "",
        '"LVCMOS33"',  # a rendered Verilog string literal (spec §5.1/§5.3, S34.3)
        'mix "of" \\stuff\\ and spaces = # too',
        '\\"',  # backslash immediately followed by a quote: an escaping-order trap
        '""',  # two adjacent quotes
        "\\\\",  # two literal backslashes
    ],
)
def test_attr_value_round_trips(value):
    v = _mem(Event(1000, "sample", "A"), header={**BASE, "attr.NOTE": value})
    text = dumps(v)
    assert loads(text) == v
    assert v.attrs == {"NOTE": value}


def test_attr_value_with_only_backslash_is_quoted():
    """The trigger for quoting a header value (``_quote``) includes a bare backslash,
    matching the module docstring and spec §5.3: a value containing only ``\\`` is
    not left as a literal, unescaped bare token (code-quality review must-fix on
    PR #8)."""
    v = _mem(Event(1000, "sample", "A"), header={**BASE, "attr.NOTE": "a\\b"})
    text = dumps(v)
    assert 'attr.NOTE="a\\\\b"' in text
    assert loads(text) == v


def test_attr_value_iostandard_round_trips():
    """The concrete case S34.3 names: a string attribute's rendered Verilog literal,
    quotes included, such as IOSTANDARD="LVCMOS33"."""
    v = _mem(Event(1000, "sample", "A"), header={**BASE, "attr.IOSTANDARD": '"LVCMOS33"'})
    text = dumps(v)
    assert loads(text) == v
    assert v.attrs == {"IOSTANDARD": '"LVCMOS33"'}


def test_attr_value_as_rendered_by_wrap_render_attr_round_trips():
    """The exact literal the wrapper/stimulus pipeline puts in the header: attrs flow
    from ``xut.wrap.render_attr`` (a string kind is rendered with surrounding quotes,
    Verilog-literal style) into ``VecBuilder.build``'s ``attr.<NAME>`` header keys
    (``tools/xut/stimgen.py``), unchanged."""
    from xut.wrap import render_attr

    lit = render_attr({"kind": "string", "name": "IOSTANDARD"}, "LVCMOS33")
    assert lit == '"LVCMOS33"'
    v = _mem(Event(1000, "sample", "A"), header={**BASE, "attr.IOSTANDARD": lit})
    text = dumps(v)
    assert loads(text) == v
    assert v.attrs["IOSTANDARD"] == lit


# --- co-timed events (I2): disjoint 'set' ranges commute without 'simultaneous';
# --- any other co-timed combination needs 'simultaneous' on every event at that t.


def test_cotimed_disjoint_sets_allowed_without_simultaneous():
    v = loads(H + "t=100 set in[3:2]=0b10\nt=100 set in[1:0]=0b01\n")
    assert v.events == [
        Event(100, "set", "in", 2, 3, "10"),
        Event(100, "set", "in", 0, 1, "01"),
    ]
    assert loads(dumps(v)) == v


def test_cotimed_overlapping_sets_rejected():
    with pytest.raises(XvecError, match="overlapping"):
        loads(H + "t=100 set in[3:0]=1\nt=100 set in[2:1]=1\n")


def test_cotimed_set_and_nonset_requires_simultaneous_on_all():
    with pytest.raises(XvecError, match="co-timed events require 'simultaneous'"):
        loads(H + "t=100 set in[0]=1\nt=100 sample A\n")


def test_cotimed_set_and_nonset_ok_when_all_marked():
    v = loads(H + "t=100 simultaneous set in[0]=1\nt=100 simultaneous sample A\n")
    assert v.events[0].simultaneous and v.events[1].simultaneous
    assert loads(dumps(v)) == v


def test_cotimed_two_nonsets_require_simultaneous_on_all():
    with pytest.raises(XvecError, match="co-timed events require 'simultaneous'"):
        loads(H + "t=100 edge clk0 r\nt=100 sample A\n")


def test_cotimed_two_nonsets_ok_when_all_marked():
    v = loads(H + "t=100 simultaneous edge clk0 r\nt=100 simultaneous sample A\n")
    assert loads(dumps(v)) == v


def test_cotimed_mixed_marking_rejected():
    with pytest.raises(XvecError, match="unmarked at line"):
        loads(H + "t=100 simultaneous edge clk0 r\nt=100 sample A\n")


@pytest.mark.parametrize(
    "body",
    [
        "t=100 simultaneous set in[3:2]=0b10\nt=100 set in[1:0]=0b01\n",
        "t=100 set in[3:2]=0b10\nt=100 simultaneous set in[1:0]=0b01\n",
        "t=100 simultaneous set in[3]=1\nt=100 simultaneous set in[2]=1\nt=100 set in[0]=1\n",
    ],
)
def test_cotimed_disjoint_sets_mixed_marking_rejected(body):
    with pytest.raises(XvecError, match="mixed 'simultaneous' marking"):
        loads(H + body)


def test_cotimed_disjoint_sets_all_marked_ok():
    v = loads(H + "t=100 simultaneous set in[3:2]=0b10\nt=100 simultaneous set in[1:0]=0b01\n")
    assert all(e.simultaneous for e in v.events) and loads(dumps(v)) == v


# --- Vec int properties raise XvecError, not a bare ValueError, on a non-numeric
# --- header value (Vec can be built directly, bypassing loads()'s own validation).


def test_vec_int_property_raises_xvec_error_on_non_numeric_header():
    v = Vec(
        header={
            "prim": "P",
            "cfg": "c",
            "nin": "abc",
            "nout": "1",
            "nclk": "0",
            "settle_ps": "0",
            "seed": "0",
        }
    )
    with pytest.raises(XvecError, match="not an integer"):
        _ = v.nin


# --- A2: an in-memory Vec is held to every rule the parser applies (check_structure)

from xut.formats.xvec import Clock, check_structure  # noqa: E402

BASE = {
    "prim": "P",
    "cfg": "c",
    "nin": "3",
    "nout": "1",
    "nclk": "1",
    "settle_ps": "1000",
    "seed": "0",
}
CLK = [Clock("clk0", 0, 100, 0, 50, "stepped")]


def _mem(*events, header=None, clocks=None):
    return Vec(dict(header or BASE), list(CLK if clocks is None else clocks), list(events))


@pytest.mark.parametrize(
    "events,msg",
    [
        ((Event(1000, "sample", "bad label"),), "bad sample label"),
        ((Event(1000, "sample", "A"), Event(1100, "sample", "A")), "duplicate label"),
        ((Event(500, "sample", "A"),), "settle_ps"),
        ((Event(1000, "set", "in", 9, 9, "1"),), "out of range"),
        ((Event(1000, "set", "in", 2, 1, "1"),), "msb < lsb"),
        ((Event(1000, "set", "in", 0, 1, "1"),), "2 bit"),
        ((Event(1000, "set", "in", 0, 0, "q"),), "01xz"),
        ((Event(1000, "set", "out", 0, 0, "1"),), "target"),
        ((Event(1000, "edge", "clk1", value="r"),), "undeclared clock"),
        ((Event(1000, "edge", "clk0", value="x"),), "r or f"),
        ((Event(1000, "glbl", "FOO", value="1"),), "glbl"),
        ((Event(1000, "glbl", "GSR", value="2"),), "glbl"),
        ((Event(1000, "clock_start", "clk0"),), "mode=free"),
        ((Event(1000, "end", "x"),), "'end'"),
        ((Event(1000, "bogus"),), "unknown op"),
        ((Event(-1, "set", "in", 0, 0, "1"),), "negative"),
    ],
)
def test_check_structure_applies_the_parser_per_event_rules(events, msg):
    with pytest.raises(XvecError, match=msg) as ei:
        check_structure(_mem(*events))
    assert "event #" in str(ei.value)


@pytest.mark.parametrize(
    "header,clocks,msg",
    [
        ({k: v for k, v in BASE.items() if k != "seed"}, None, "lacks seed"),
        ({**BASE, "nin": "x"}, None, "non-negative integer"),
        ({**BASE, "bad key": "1"}, None, "header key"),
        (BASE, [Clock("clk0", 1, 100, 0, 50, "stepped")], "index"),
        (BASE, [Clock("clk5", 5, 100, 0, 50, "stepped")], "index"),
        (BASE, [Clock("clk0", 0, 0, 0, 50, "stepped")], "period"),
        (BASE, [Clock("clk0", 0, 100, 0, 100, "stepped")], "duty"),
        (BASE, [Clock("clk0", 0, 100, 0, 50, "fast")], "mode"),
        (BASE, [Clock("clk0", 0, 100, -1, 50, "stepped")], "phase"),
        (BASE, CLK * 2, "declared twice"),
    ],
)
def test_check_structure_checks_header_and_clocks(header, clocks, msg):
    with pytest.raises(XvecError, match=msg):
        check_structure(_mem(Event(1000, "sample", "A"), header=header, clocks=clocks))


def test_check_structure_accepts_what_parses():
    v = _mem(
        Event(0, "set", "in", 0, 2, "01x"),
        Event(1000, "edge", "clk0", value="r"),
        Event(1100, "sample", "A.b/c-1"),
        Event(1200, "end"),
    )
    check_structure(v)
    assert loads(dumps(v)) == v


def test_dumps_refuses_unrepresentable_names():
    with pytest.raises(XvecError, match="header key"):
        dumps(_mem(header={**BASE, "bad key": "1"}))
    with pytest.raises(XvecError, match="label"):
        dumps(_mem(Event(1000, "sample", "a b")))


def test_header_value_with_space_and_hash_round_trips():
    v = _mem(Event(1000, "sample", "A"), header={**BASE, "attr.NOTE": "a b #1"})
    assert loads(dumps(v)) == v
