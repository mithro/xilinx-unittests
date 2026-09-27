# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.hw import image
from xut.hw.image import HwImageError, ImageBuilder


def test_chunks_lsb_first():
    bits = "1" + "0" * 15 + "0000000000000011"  # 32 bits: bit 31 and bits 1:0
    assert image.chunks(bits) == [0x0003, 0x8000]
    assert image.chunks("101") == [0b101]


def test_word_encoding_round_trips():
    assert image.decode(image.w_set(3, 0xBEEF)) == (image.OP_SET, 3, 0xBEEF)
    assert image.decode(image.w_edge(7, 1)) == (image.OP_EDGE, 7, 1)
    assert image.decode(image.w_wait(1000)) == (image.OP_WAIT, 1000, 0)
    assert image.decode(image.W_SAMPLE) == (image.OP_SAMPLE, 0, 0)
    assert image.decode(image.W_END) == (image.OP_END, 0, 0)


def test_set_bits_writes_only_changed_chunks_then_commits():
    b = ImageBuilder(20, 1, 1, "0" * 20)
    b.set_bits("0" * 20)  # no change: no words
    b.set_bits("1" + "0" * 19)  # bit 19 = chunk 1, bit 3
    p = b.end()
    assert p.words == (image.w_set(1, 0x8), image.w_commit(), image.W_END)


def test_edges_samples_and_labels():
    b = ImageBuilder(1, 2, 1, "0")
    b.edge(1, 1)
    b.sample("a")
    b.edge(1, 0)
    b.sample("b")
    p = b.end()
    assert p.labels == ("a", "b")
    assert p.words == (
        image.w_edge(1, 1),
        image.W_SAMPLE,
        image.w_edge(1, 0),
        image.W_SAMPLE,
        image.W_END,
    )


@pytest.mark.parametrize(
    "call,match",
    [
        (lambda b: b.edge(2, 1), "clock 2"),
        (lambda b: b.set_bits("01"), "1 char"),
        (lambda b: b.set_bits("x"), "0/1"),
        (lambda b: b.wait(image.MAX_WAIT + 1), "WAIT"),
    ],
)
def test_builder_refuses(call, match):
    b = ImageBuilder(1, 2, 1, "0")
    with pytest.raises(HwImageError, match=match):
        call(b)


def test_capacity():
    b = ImageBuilder(1, 1, 1, "0")
    for _ in range(10):
        b.sample(f"s{_}")
    with pytest.raises(HwImageError, match="11 words"):
        b.end(maxwords=10)


def test_opcode_literal_values_match_the_brief():
    """The op table (spec §7.1) is a cross-module hardware contract: Task 3's harness
    RTL hardcodes the same values independently of this module. Pin them literally, not
    via decode(w_x(...)) round trips (those only prove encode and decode agree with
    each other, not with the brief's table)."""
    assert (
        image.OP_SET,
        image.OP_COMMIT,
        image.OP_EDGE,
        image.OP_WAIT,
        image.OP_SAMPLE,
        image.OP_END,
    ) == (0x1, 0x2, 0x3, 0x4, 0x5, 0xF)
    assert (image.CHUNK, image.MAX_CHUNKS, image.MAX_CLOCKS) == (16, 4096, 4096)
    assert image.MAX_WAIT == 2**28 - 1
    assert (image.MAXWORDS, image.MARGIN) == (8192, 16)


def test_golden_image_is_exact_ints_from_the_brief():
    """One small program's words, computed by hand from the brief's bit layout (op in
    [31:28]; SET [27:16] chunk, [15:0] data; EDGE [12] level, [11:0] clock i) rather
    than by calling w_set/w_edge/decode: a swapped opcode or a reordered field would
    still round-trip through the encoder/decoder pair, but not past these literals."""
    b = ImageBuilder(20, 2, 1, "0" * 20)
    b.set_bits("1" + "0" * 19)  # bit 19: chunk 1 (bits 31:16), offset 3 -> data 0x0008
    b.edge(1, 1)
    b.sample("a")
    b.edge(1, 0)
    b.sample("b")
    p = b.end()
    assert p.words == (
        0x1001_0008,  # SET   op=1 chunk=1        data=0x0008
        0x2000_0000,  # COMMIT op=2
        0x3000_1001,  # EDGE  op=3 level=1 (bit12) clock=1
        0x5000_0000,  # SAMPLE op=5
        0x3000_0001,  # EDGE  op=3 level=0        clock=1
        0x5000_0000,  # SAMPLE op=5
        0xF000_0000,  # END   op=0xF
    )
