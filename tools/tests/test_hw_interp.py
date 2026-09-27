# SPDX-License-Identifier: Apache-2.0
import zlib

import pytest

from xut.hw import image, proto
from xut.hw.image import ImageBuilder
from xut.hw.interp import EmuError, EmuSlot, Harness, margin_violations, run_program
from xut.hw.selftest import PassthroughSim


class Recorder:
    def __init__(self):
        self.log = []

    def reset(self, t0):
        self.v = t0

    def drive(self, in_bits, clk_bits):
        self.log.append((in_bits, clk_bits))
        self.v = in_bits

    def out_bits(self):
        return self.v[-1:]


def _prog():
    b = ImageBuilder(2, 1, 1, "00")
    b.set_bits("01")
    b.edge(0, 1)
    b.sample("a")
    b.edge(0, 0)
    b.wait(5)
    b.sample("b")
    return b.end()


def test_run_program_drives_one_change_at_a_time_and_keeps_margins():
    p, r = _prog(), Recorder()
    r.reset(p.t0)
    out = run_program(p.words, p.nin, p.nclk, r, p.t0, margin=16)
    assert out.status == 0 and out.samples == ["1", "1"]
    assert r.log == [("01", "0"), ("01", "1"), ("01", "0")]
    assert margin_violations(out.events, 16) == []
    # SET, COMMIT(+17), EDGE(+17), SAMPLE, EDGE(+17), WAIT 5(+6), SAMPLE, END: 2 cycles/word
    assert out.cycles == 2 * 8 + 3 * 17 + 6


def test_margin_violations_catch_a_short_gap():
    from xut.hw.interp import CycleEvent

    ev = [CycleEvent(10, "commit", "1"), CycleEvent(20, "sample", "1")]
    assert margin_violations(ev, 16) == [
        "sample at cycle 20 is 10 cycle(s) after the commit at cycle 10"
    ]


def test_running_off_the_end_and_unknown_ops_are_badop():
    r = Recorder()
    r.reset("0")
    assert run_program([image.W_SAMPLE], 1, 0, r, "0").status == proto.STATUS_CODE["badop"]
    assert run_program([0x7 << 28], 1, 0, r, "0").status == proto.STATUS_CODE["badop"]


def test_edge_on_a_missing_clock_changes_nothing_but_still_waits():
    r = Recorder()
    r.reset("0")
    out = run_program([image.w_edge(3, 1), image.W_END], 1, 1, r, "0", margin=4)
    assert r.log == [] and out.cycles == 2 + 5 + 2


def _harness():
    return Harness(0xABCD0001, [EmuSlot(16, 16, 0, "0" * 16, PassthroughSim())], maxwords=64)


def test_identify():
    assert _harness().feed(b"I") == proto.render(
        "id", build=0xABCD0001, slots=1, maxwords=64, margin=16
    )


def test_load_run_and_used():
    h = _harness()
    b = ImageBuilder(16, 0, 16, "0" * 16)
    b.set_bits("0000000000000101")
    b.sample("s")
    p = b.end()
    load = proto.parse_load(h.feed(proto.load_frame(0, p.words)))
    assert load.status == 0 and load.words == len(p.words)
    run = proto.parse_run(h.feed(b"R"))
    assert run.samples == ("0000000000000101",) and run.status == 0
    again = proto.parse_run(h.feed(b"R"))
    assert again.status == proto.STATUS_CODE["used"] and again.samples == ()


def test_error_paths():
    h = _harness()
    assert proto.parse_run(h.feed(b"R")).status == proto.STATUS_CODE["noload"]
    bad = bytearray(proto.load_frame(0, [image.W_END]))
    bad[-1] ^= 1
    assert proto.parse_load(h.feed(bytes(bad))).status == proto.STATUS_CODE["badcrc"]
    assert proto.parse_load(h.feed(proto.load_frame(3, [image.W_END]))).status == 4
    assert proto.parse_load(h.feed(proto.load_frame(0, [image.W_END] * 65))).status == 6
    assert h.feed(b"Z") == proto.render("err", cmd=0x5A, status=7)


def test_bytes_may_arrive_in_pieces():
    h, frame = _harness(), proto.load_frame(0, [image.W_END])
    assert h.feed(frame[:3]) == b""
    assert proto.parse_load(h.feed(frame[3:])).status == 0


def test_load_reply_crc_is_the_computed_one():
    h = _harness()
    frame = proto.load_frame(0, [image.W_END])
    assert proto.parse_load(h.feed(frame)).crc == zlib.crc32(frame[1:-4])


def _passthrough(nin, words, t0=None):
    r = PassthroughSim()
    t0 = t0 or "0" * nin
    r.reset(t0)
    return run_program(words, nin, 0, r, t0)


def test_multi_chunk_in_vec_round_trips():
    """nin=40 is three chunks (the top one partial): every random vector comes back."""
    import random

    rng = random.Random(7)
    vecs = [format(rng.getrandbits(40), "040b") for _ in range(50)]
    b = ImageBuilder(40, 0, 40, "0" * 40)
    for v in vecs:
        b.set_bits(v)
        b.sample("s")
    p = b.end()
    out = _passthrough(40, p.words)
    assert out.status == 0 and out.samples == vecs


def test_set_to_chunk_1_and_partial_top_chunk_truncation():
    """nin=20: chunk 1 holds in_vec[19:16]; COMMIT keeps only its low 4 bits."""
    words = [image.w_set(1, 0xFFFF), image.w_commit(), image.W_SAMPLE, image.W_END]
    assert _passthrough(20, words).samples == ["1111" + "0" * 16]


def test_set_beyond_the_slots_chunks_has_no_effect():
    """The RTL's in_nxt is wider than the slot, which takes only its own width: a SET to a
    chunk the slot does not have is dropped, never wrapped into a chunk it does have."""
    t0 = "1010" + "0" * 16
    words = [image.w_set(2, 0xFFFF), image.w_set(5, 0x1234), image.w_commit()]
    out = _passthrough(20, [*words, image.W_SAMPLE, image.W_END], t0)
    assert out.status == 0 and out.samples == [t0]


def test_a_sample_wider_or_narrower_than_nout_is_refused():
    h = Harness(1, [EmuSlot(16, 8, 0, "0" * 16, PassthroughSim())], maxwords=64)
    h.feed(proto.load_frame(0, [image.W_SAMPLE, image.W_END]))
    with pytest.raises(EmuError, match=r"width\(nout\)=8"):
        h.feed(b"R")
