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
