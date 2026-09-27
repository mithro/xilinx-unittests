# SPDX-License-Identifier: Apache-2.0
from xut.hw import proto, selftest


def test_passthrough_expected_is_the_pattern_list():
    exp = selftest.expected_samples(selftest.PASS_SLOT)
    assert exp[0] == "0000000000000001" and exp[15] == "1000000000000000"
    assert exp[16] == "1111111111111110" and exp[-2:] == ["0000000000000000", "1111111111111111"]


def test_counter_counts_wraps_holds_and_clears():
    exp = dict(zip(selftest.counter_program().labels, selftest.expected_samples(1), strict=True))
    assert exp["c0"] == "00000000" and exp["c1"] == "00000001" and exp["c255"] == "11111111"
    assert exp["c256"] == "00000000" and exp["c257"] == "00000001"
    assert exp["hold"] == exp["c260"] == format(260 % 256, "08b")
    assert exp["clear"] == "00000000"


def test_check_names_the_first_difference():
    good = proto.RunReply(0, 0, 1, tuple(selftest.expected_samples(0)), 0, 0)
    assert selftest.check(0, good) is None
    bad = proto.RunReply(0, 0, 1, ("0" * 16, *good.samples[1:]), 0, 0)
    assert "p0" in selftest.check(0, bad)
    assert "status" in selftest.check(0, proto.RunReply(0, 0, 1, (), 3, 0))
