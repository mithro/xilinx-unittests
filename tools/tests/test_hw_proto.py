# SPDX-License-Identifier: Apache-2.0
import struct
import zlib
from pathlib import Path

import pytest

from xut.hw import proto
from xut.hw.proto import ProtoError

VH = Path(__file__).resolve().parents[1] / "xut/hdl/hw/xut_hw_msgs.vh"


def test_render_is_fixed_width_lower_hex():
    got = proto.render("id", build=0xDEADBEEF, slots=3, maxwords=8192, margin=16)
    assert got == b"# xut-hw 1 id build=deadbeef slots=03 maxwords=2000 margin=10\n"
    assert proto.render("sample", sidx=10, bits="0101") == b"S 000a 0101\n"


def test_render_refuses_what_the_rtl_cannot_print():
    with pytest.raises(ProtoError, match="does not fit"):
        proto.render("load", slot=256, words=1, crc=0, status=0)
    with pytest.raises(ProtoError, match="0/1"):
        proto.render("sample", sidx=0, bits="01x")


@pytest.mark.parametrize("name", list(proto.MESSAGES))
def test_parse_round_trips_every_message(name):
    values = {f: (1 if f != "bits" else "10") for f in proto.FIELDS}
    fields = set(proto.PATTERNS[name].groupindex)
    values = {k: v for k, v in values.items() if k in fields}
    assert proto.parse(name, proto.render(name, **values)) == values


def test_load_frame_layout_and_crc():
    f = proto.load_frame(2, [0x12345678, 0xF0000000])
    assert f[:1] == b"L"
    body = f[1:-4]
    assert body == struct.pack("<BHII", 2, 2, 0x12345678, 0xF0000000)
    assert f[-4:] == struct.pack("<I", zlib.crc32(body))


@pytest.mark.parametrize("slot,words", [(256, [0]), (-1, [0]), (0, [])])
def test_load_frame_refuses(slot, words):
    with pytest.raises(ProtoError):
        proto.load_frame(slot, words)


def _run_block(samples, status=0, slot=2, crc_delta=0):
    body = proto.render("run", build=0xABCD0123, slot=slot, words=5)
    body += b"".join(proto.render("sample", sidx=i, bits=b) for i, b in enumerate(samples))
    end = proto.render(
        "end", slot=slot, samples=len(samples), status=status, crc=zlib.crc32(body) ^ crc_delta
    )
    return body + end


def test_parse_run_ok():
    r = proto.parse_run(_run_block(["1", "0"]))
    assert r == proto.RunReply(0xABCD0123, 2, 5, ("1", "0"), 0, r.crc)


def test_parse_run_crc_mismatch_is_a_proto_error():
    with pytest.raises(ProtoError, match="CRC"):
        proto.parse_run(_run_block(["1"], crc_delta=1))


def test_parse_run_refuses_truncation_reordering_and_err_lines():
    good = _run_block(["1", "0"])
    with pytest.raises(ProtoError, match="truncated"):
        proto.parse_run(good[:-1])
    swapped = good.replace(b"S 0000 1\nS 0001 0\n", b"S 0001 0\nS 0000 1\n")
    with pytest.raises(ProtoError, match="sample"):
        proto.parse_run(swapped)
    with pytest.raises(ProtoError):
        proto.parse_run(proto.render("err", cmd=0x5A, status=7))


def test_rom_expands_back_to_the_templates():
    data, start = proto.rom()
    assert len(data) <= 512  # the printer's 9-bit ROM address
    tok = {t: n for n, (t, _) in proto.FIELDS.items()}
    for name, tpl in proto.MESSAGES.items():
        a, text = start[name], ""
        while data[a]:
            text += f"{{{tok[data[a]]}}}" if data[a] & 0x80 else chr(data[a])
            a += 1
        assert text == tpl


def test_committed_rom_is_current():
    assert VH.read_text() == proto.render_rom_vh(), "run: uv run xut hw gen-rtl"
