# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.formats.xvec import Event, XvecError, decode_value, dumps, encode_value, loads

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
