# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.formats.xtr import Mismatch, Trace, XtrError, compare, concat, diff, dumps, loads

EXP = """\
# xut-trace 2  runner=python flow=rtl model=golden seed=17 kind=expected prim=FDRE cfg=a
S0  Q=0  | Q=doc:375
S1  Q=-  | Q=inferred:doc_silent_on_GSR_vs_CLR
S2  Q=1 DO=0000_1111  | Q=doc:375 DO=doc:375
"""


def _act(q0="0", q1="1", q2="1", do="00001111"):
    t = Trace({"runner": "iverilog", "flow": "rtl", "model": "unisim-2025.2", "seed": "17"})
    t.add("S0", {"Q": q0})
    t.add("S1", {"Q": q1})
    t.add("S2", {"Q": q2, "DO": do})
    return t


def test_parse_expected_with_prov_and_grouping():
    t = loads(EXP)
    assert t.kind == "expected"
    assert t.samples["S2"] == {"Q": "1", "DO": "00001111"}
    assert t.prov["S1"]["Q"] == "inferred:doc_silent_on_GSR_vs_CLR"
    assert loads(dumps(t)).samples == t.samples


def test_dumps_groups_by_four():
    assert "DO=0000_1111" in dumps(_act())
    assert "Q=1" in dumps(_act())


def test_dont_care_masks_and_match():
    assert compare(loads(EXP), _act()) == []


def test_x_where_defined_fails():
    m = compare(loads(EXP), _act(q2="x"))
    assert m == [Mismatch("S2", "Q", 0, "1", "x", "doc:375")]


def test_bit_index_is_lsb_zero():
    m = compare(loads(EXP), _act(do="00011111"))
    assert [(x.port, x.bit) for x in m] == [("DO", 4)]


def test_missing_and_extra_samples():
    a = _act()
    del a.samples["S0"]
    a.add("S9", {"Q": "0"})
    kinds = sorted(x.kind for x in compare(loads(EXP), a))
    assert kinds == ["extra-sample", "missing-sample"]
    assert "sample-order" not in kinds  # the surviving common labels (S1, S2) are still in order


def test_sample_order_detected():
    exp = loads(EXP)
    a = Trace({"runner": "iverilog", "flow": "rtl", "model": "unisim-2025.2", "seed": "17"})
    a.add("S2", {"Q": "1", "DO": "00001111"})
    a.add("S0", {"Q": "0"})
    a.add("S1", {"Q": "1"})
    assert compare(exp, a) == [Mismatch("S0", "*", -1, "0", "1", None, "sample-order")]


def test_diff_sample_order():
    a = _act()
    b = Trace({"runner": "verilator", "flow": "rtl", "model": "unisim-2025.2", "seed": "1"})
    b.add("S1", {"Q": "1"})
    b.add("S0", {"Q": "0"})
    b.add("S2", {"Q": "1", "DO": "00001111"})
    order = [x for x in diff(a, b) if x.kind == "sample-order"]
    assert order == [Mismatch("S0", "*", -1, "0", "1", None, "sample-order")]


def test_duplicate_label_error_has_line_number():
    text = "# xut-trace 2  runner=x flow=rtl model=m seed=0\nS0  Q=0\nS0  Q=1\n"
    with pytest.raises(XtrError, match=r"^line 3: duplicate label 'S0'$"):
        loads(text)


def test_port_width_vs_missing_port():
    exp = loads(EXP)
    a = _act(do="0001111")  # 7 bits, not 8: a width mismatch, not an absence
    widths = [x for x in compare(exp, a) if x.port == "DO"]
    assert widths == [Mismatch("S2", "DO", -1, "00001111", "0001111", "doc:375", "port-width")]

    b = _act()
    del b.samples["S2"]["DO"]
    missing = [x for x in compare(exp, b) if x.port == "DO"]
    assert missing == [Mismatch("S2", "DO", -1, "00001111", "missing", "doc:375", "missing-port")]


def test_diff_port_width_vs_missing_port():
    a = _act()
    b = _act(do="0001111")
    widths = [x for x in diff(a, b) if x.port == "DO"]
    assert widths == [Mismatch("S2", "DO", -1, "00001111", "0001111", None, "port-width")]

    c = _act()
    del c.samples["S2"]["DO"]
    missing = [x for x in diff(a, c) if x.port == "DO"]
    assert missing == [Mismatch("S2", "DO", -1, "00001111", "missing", None, "missing-port")]


def test_diff_respects_x_observability():
    a, b = _act(q2="x"), _act(q2="1")
    assert diff(a, b) != []  # both 4-state: x vs 1 differs
    assert diff(a, b, b_x=False) == []  # b is 2-state: cannot observe x
    assert diff(_act(q2="0"), b, b_x=False) != []


def test_actual_trace_rejects_dont_care():
    with pytest.raises(XtrError, match="'-'"):
        loads("# xut-trace 2  runner=x flow=rtl model=m seed=0\nS0  Q=-\n")


def test_concat_prefixes_labels():
    t = concat(
        [("cfgA", _act()), ("cfgB", _act())],
        {"runner": "iverilog", "flow": "rtl", "model": "m", "seed": "1"},
    )
    assert list(t.samples)[:2] == ["cfgA/S0", "cfgA/S1"] and "cfgB/S2" in t.samples


# --- A1: one name grammar; the writer never produces a file that reads back differently


def _t(**hdr):
    return Trace({"runner": "x", "flow": "rtl", "model": "m", "seed": "0", **hdr})


def test_error_types_share_a_format_base():
    from xut.errors import XutError
    from xut.formats.common import FormatError
    from xut.formats.xvec import XvecError

    assert issubclass(XtrError, FormatError) and issubclass(XvecError, FormatError)
    assert issubclass(FormatError, XutError) and issubclass(FormatError, ValueError)
    e = XtrError("bad", 7)
    assert str(e) == "line 7: bad" and e.line == 7


@pytest.mark.parametrize("label", ["a|b=c/S0", "a b", "S#0", "", "S0\n"])
def test_add_rejects_unrepresentable_labels(label):
    with pytest.raises(XtrError, match="label"):
        _t().add(label, {"Q": "0"})


@pytest.mark.parametrize("port", ["Q#", "1Q", "a|b", "Q=", ""])
def test_add_rejects_bad_port_names(port):
    with pytest.raises(XtrError, match="port"):
        _t().add("S0", {port: "0"})


@pytest.mark.parametrize("bits", ["1#", "", "1_0", "12", "1 0"])
def test_add_rejects_bad_bits(bits):
    with pytest.raises(XtrError, match="bits"):
        _t().add("S0", {"Q": bits})


def test_add_rejects_dont_care_in_actual_trace():
    with pytest.raises(XtrError, match="'-'"):
        _t().add("S0", {"Q": "-"})
    _t(kind="expected").add("S0", {"Q": "-"})


def test_add_rejects_provenance_for_unknown_port():
    with pytest.raises(XtrError, match="provenance"):
        _t(kind="expected").add("S0", {"Q": "0"}, {"R": "doc:1"})


@pytest.mark.parametrize(
    "hdr",
    [{"model": "a b"}, {"model": ""}, {"bad key": "1"}, {"kind": "golden"}, {"model": "a\nb"}],
)
def test_dumps_rejects_unrepresentable_header(hdr):
    t = _t()
    t.header.update(hdr)
    with pytest.raises(XtrError, match="header"):
        dumps(t)


def test_dumps_revalidates_samples_mutated_in_place():
    t = _t()
    t.add("S0", {"Q": "0"})
    t.samples["S0"]["Q"] = "1#"
    with pytest.raises(XtrError, match="bits"):
        dumps(t)


def test_concat_refuses_a_cfg_outside_the_grammar():
    part = _t()
    part.add("S0", {"Q": "1"})
    with pytest.raises(XtrError, match="configuration"):
        concat([("a|b=c", part)], {"runner": "x", "flow": "rtl", "model": "m", "seed": "0"})
    with pytest.raises(XtrError, match="configuration"):
        concat([("a/b", part)], {"runner": "x", "flow": "rtl", "model": "m", "seed": "0"})


def test_round_trip_is_exact():
    t = _t(kind="expected", prim="FDRE", cfg="a.b-c")
    t.add("cfg/S0.x-1", {"Q": "-", "DO": "01xz0101z"}, {"Q": "inferred:silent", "DO": "doc:9"})
    t.add("S1", {})
    back = loads(dumps(t))
    assert (back.header, back.samples, back.prov) == (t.header, t.samples, t.prov)


def test_loads_rejects_junk_header_tokens():
    with pytest.raises(XtrError, match="header"):
        loads("# xut-trace 2  runner=x junk\n")


def test_diff_names_a_portless_sample_present():
    a, b = _t(), _t()
    a.add("S0", {})
    (m,) = diff(a, b)
    assert (m.expected, m.actual, m.kind) == ("present", "missing", "missing-sample")
