# SPDX-License-Identifier: Apache-2.0
import zlib

from xut.hw import image, proto
from xut.hw.image import ImageBuilder
from xut.hw.interp import EmuSlot, Harness, margin_violations, run_program
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
